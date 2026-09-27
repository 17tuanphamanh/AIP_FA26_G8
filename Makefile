# Lệnh theo docs/spec/build/01-kien-truc-project.md mục 7.1.
# Lệnh chưa có hạ tầng thì in TODO và thoát mã 1 — để không ai tưởng nó đã chạy.
# Lệnh chạy được một phần (lint) thì chạy phần đã có và in TODO cho phần còn thiếu.

STRATEGY ?= hybrid
SPLIT ?= dev

# Docker qua colima: nếu socket colima tồn tại thì dùng nó (không sửa ~/.zshrc).
# Không có (Docker Desktop, Linux) thì để nguyên DOCKER_HOST của máy.
COLIMA_SOCK := $(HOME)/.colima/default/docker.sock
ifneq ($(wildcard $(COLIMA_SOCK)),)
export DOCKER_HOST := unix://$(COLIMA_SOCK)
# Ryuk của testcontainers mount socket BÊN TRONG VM colima, không phải socket trên macOS.
export TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE := /var/run/docker.sock
endif

# ~/.docker/config.json của máy từng cài Docker Desktop có "credsStore": "desktop"; dùng colima
# mà helper không nằm trong PATH thì mọi lệnh pull đều lỗi. Thêm thư mục bin của Docker.app.
DOCKER_DESKTOP_BIN := /Applications/Docker.app/Contents/Resources/bin
ifneq ($(wildcard $(DOCKER_DESKTOP_BIN)/docker-credential-desktop),)
export PATH := $(DOCKER_DESKTOP_BIN):$(PATH)
endif

.PHONY: up down test test-ml lint ingest tokenizer seed probe eval eval-rag load gate2 models ml-bench

# Compose đọc .env; chưa có .env thì dùng .env.example (giá trị mẫu, chỉ cho máy dev).
ENV_FILE := $(if $(wildcard .env),.env,.env.example)
COMPOSE := docker compose --env-file $(ENV_FILE)
HEALTH_URL := http://127.0.0.1:8000/api/health
# Mock chỉ nghe trong mạng compose (không bind ra máy) → kiểm /health từ bên trong container.
MOCK_HEALTH := python -c "import httpx; httpx.get('http://127.0.0.1:8100/health').raise_for_status()"
# Thư mục model của ml-service trên máy (compose mount read-only). Biến make/shell, KHÔNG đặt trong .env
# (export cho compose — một giá trị cho cả kiểm, tải và mount). Đổi: make models up MODELS_DIR=/đường/dẫn
MODELS_DIR ?= ./models
export MODELS_DIR

# Dựng compose; chạy migration (role app_migrate); nạp seed mock; kiểm /health của mock, worker healthy
# (heartbeat, tối đa 60 giây — quá hạn in 30 dòng log worker, exit 1) và /api/health.
# ml-service (3a): kiểm model đã tải TRƯỚC khi build (thiếu → "chạy make models"); backend và worker chờ
# ml-service healthy (depends_on) — nạp model lần đầu mất tới vài phút; lỗi thì in log ml-service.
up:
	@if [ "$(ENV_FILE)" = ".env.example" ]; then \
	  echo "CẢNH BÁO: không có .env — dùng giá trị mẫu của .env.example (chỉ cho máy dev)." >&2; fi
	@PYTHONPATH=ml_service uv run python -m app.lock $(MODELS_DIR) || { \
	  echo "Thiếu model cho ml-service — chạy: make models" >&2; exit 1; }
	$(COMPOSE) build backend
	$(COMPOSE) build mock
	$(COMPOSE) build ml-service
	$(COMPOSE) up -d --wait postgres qdrant
	$(COMPOSE) run --rm --no-deps backend alembic upgrade head
	$(COMPOSE) up -d ml-service backend worker mock || { \
	  echo "ml-service/backend/worker không lên — 50 dòng log ml-service:" >&2; \
	  $(COMPOSE) logs --tail 50 ml-service >&2; exit 1; }
	@for i in $$(seq 1 60); do \
	  if $(COMPOSE) exec -T mock $(MOCK_HEALTH) >/dev/null 2>&1; then echo "mock /health: ok"; break; fi; \
	  if [ $$i = 60 ]; then echo "mock /health chưa OK sau 60 giây" >&2; $(COMPOSE) logs --tail 50 mock >&2; exit 1; fi; \
	  sleep 1; done
	$(MAKE) seed
	@for i in $$(seq 1 60); do \
	  st=$$(docker inspect -f '{{.State.Health.Status}}' $$($(COMPOSE) ps -q worker) 2>/dev/null); \
	  if [ "$$st" = "healthy" ]; then echo "worker: healthy"; break; fi; \
	  if [ $$i = 60 ]; then echo "worker chưa healthy sau 60 giây (trạng thái: $${st:-không chạy})" >&2; \
	    $(COMPOSE) logs --tail 30 worker >&2; exit 1; fi; \
	  sleep 1; done
	@for i in $$(seq 1 60); do \
	  if curl -fsS $(HEALTH_URL) >/dev/null 2>&1; then \
	    echo "/api/health: $$(curl -s $(HEALTH_URL))"; exit 0; fi; \
	  sleep 1; done; \
	echo "/api/health chưa OK sau 60 giây: $$(curl -s $(HEALTH_URL))" >&2; \
	$(COMPOSE) logs --tail 50 backend >&2; exit 1

# Dừng và xoá container; GIỮ volume dữ liệu (xoá hẳn: docker compose down -v).
down:
	$(COMPOSE) down

# unit + integration + e2e với ScriptedLLM, testcontainers. Không gồm probe/ và load/.
# backend và mock_services đều là package `app` → chạy pytest riêng, mỗi lần một PYTHONPATH.
# e2e dựng mock bằng uvicorn trên cổng local: sandbox Claude Code cần sandbox.network.allowLocalBinding.
test:
	uv run pytest backend/tests/unit backend/tests/integration backend/tests/e2e
	uv run pytest mock_services/tests -o pythonpath=mock_services
	uv run pytest ml_service/tests -o pythonpath=ml_service -m "not ml_real"

# Test ml-service với model/tokenizer THẬT (a3, a4, a5, a6, a16 — thiết kế Phase 3 mục 4.8). Cài nhóm uv
# `ml` (torch…) vào .venv; cần `make models` trước — thiếu model thì FAIL, không skip. Không vào CI.
test-ml:
	uv run --group ml pytest ml_service/tests -o pythonpath=ml_service -m ml_real

# ruff, mypy, import-linter, gitleaks (cổng T01 mục 4).
lint:
	uv run ruff check .
	uv run mypy backend/app
	uv run mypy --cache-dir .mypy_cache/mock_services mock_services/app  # cache riêng: cùng tên package `app`
	uv run mypy --cache-dir .mypy_cache/ml_service ml_service/app
	PYTHONPATH=backend uv run lint-imports
	@command -v gitleaks >/dev/null || { echo "Thiếu gitleaks — cài: brew install gitleaks" >&2; exit 1; }
	gitleaks detect --no-banner --redact

# Pipeline RAG (P3, thiết kế Phase 3 mục 5.8): image backend KHÔNG có kb/ → mount read-only. Cần `make up`
# (postgres, qdrant, ml-service chạy). In kb_version và số đoạn truncated (phải = 0).
# Ví dụ: make ingest ARGS=--dry-run | make ingest KB_DIR=backend/tests/fixtures/kb
KB_DIR ?= kb
ingest:
	$(COMPOSE) build backend
	$(COMPOSE) run --rm --no-deps -v "$(abspath $(KB_DIR)):/srv/kb:ro" backend \
	  python -m app.rag.ingest.cli --kb-dir /srv/kb $(ARGS)

# Chỉ tokenizer bge-m3 (tokenizer.json, tokenizer_config.json, special_tokens_map.json) đúng revision trong
# ml_service/models.lock.json — cho test chunker thật (marker tokenizer_real). Có rồi thì bỏ qua. Cần mạng lần đầu.
TOKENIZER_DIR ?= ./models/_tokenizer
tokenizer:
	uv run --with huggingface_hub python scripts/download_models.py --tokenizer-only $(TOKENIZER_DIR)

# Cổng 2 trên stack compose thật (2b-4) — backend/tests/stack/README.md. Cần `make up` trước và
# FAKE_SCENARIO, FAKE_NODE_DELAY trong .env. Script tự chạy lệnh compose (in lệnh trước khi chạy), dừng
# nếu APP_ENV của container backend khác dev. Ví dụ: make gate2 S=preflight | make gate2 S=all
S ?= preflight
gate2:
	COMPOSE="$(COMPOSE)" PYTHONPATH=backend uv run python -m tests.stack.gate2 $(S)

# Tải model của ml-service về $(MODELS_DIR), ghim revision HF ở ml_service/models.lock.json (lần đầu ghi
# SHA — commit file lock; các lần sau tải đúng SHA đã ghim, lock lệch → dừng). Cần mạng tới huggingface.co,
# ~4–5 GB. Chỉ cần huggingface_hub — không cài torch.
models:
	uv run --with huggingface_hub python scripts/download_models.py $(MODELS_DIR)

# Đo ml-service đang chạy (cần `make up`): embed 1 câu × 50, rerank 20 và 32 đoạn × 20 → p50/p95 + RSS.
# Chạy trong container (cổng 8200 không bind ra máy), rồi in RAM mọi container.
ml-bench:
	$(COMPOSE) exec -T ml-service python -m app.bench
	docker stats --no-stream

# Kiểm schema mock_services/seed.json rồi nạp lại vào mock đang chạy (/_admin/reset — đồng thời tắt
# mọi lỗi đang bơm). Cần `make up` trước.
seed:
	PYTHONPATH=mock_services uv run python -m app.seed validate
	$(COMPOSE) exec -T mock python -m app.seed reset

# Probe với LLM thật (intent, injection, phân phối p) — TỐN TIỀN, không nằm trong make test.
probe:
	@echo "TODO (Phase 3): chưa có probe; chưa chốt provider LLM (N1)." >&2; exit 1

# Harness M8, chỉ khi EVAL_MODE=true. Ví dụ: make eval STRATEGY=hybrid SPLIT=test
eval:
	@echo "TODO (Phase 8): chưa có harness M8 (P8). STRATEGY=$(STRATEGY) SPLIT=$(SPLIT)" >&2; exit 1

# Ablation 4 cấu hình truy hồi (D-25) trên tập dev.
eval-rag:
	@echo "TODO (Phase 5): chưa có ablation RAG (D-25)." >&2; exit 1

# Locust theo 5 kịch bản huong-dan mục 14.4.
load:
	@echo "TODO (Phase 8): chưa có kịch bản locust." >&2; exit 1
