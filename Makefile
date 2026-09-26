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

.PHONY: up down test lint ingest seed probe eval eval-rag load

# Compose đọc .env; chưa có .env thì dùng .env.example (giá trị mẫu, chỉ cho máy dev).
ENV_FILE := $(if $(wildcard .env),.env,.env.example)
COMPOSE := docker compose --env-file $(ENV_FILE)
HEALTH_URL := http://127.0.0.1:8000/api/health
# Mock chỉ nghe trong mạng compose (không bind ra máy) → kiểm /health từ bên trong container.
MOCK_HEALTH := python -c "import httpx; httpx.get('http://127.0.0.1:8100/health').raise_for_status()"

# Dựng compose; chạy migration (role app_migrate); nạp seed mock; kiểm /health của mock, worker healthy
# (heartbeat, tối đa 60 giây — quá hạn in 30 dòng log worker, exit 1) và /api/health.
up:
	@if [ "$(ENV_FILE)" = ".env.example" ]; then \
	  echo "CẢNH BÁO: không có .env — dùng giá trị mẫu của .env.example (chỉ cho máy dev)." >&2; fi
	$(COMPOSE) build backend
	$(COMPOSE) build mock
	$(COMPOSE) up -d --wait postgres qdrant
	$(COMPOSE) run --rm --no-deps backend alembic upgrade head
	$(COMPOSE) up -d backend worker mock
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

# ruff, mypy, import-linter, gitleaks (cổng T01 mục 4).
lint:
	uv run ruff check .
	uv run mypy backend/app
	uv run mypy --cache-dir .mypy_cache/mock_services mock_services/app  # cache riêng: cùng tên package `app`
	PYTHONPATH=backend uv run lint-imports
	@command -v gitleaks >/dev/null || { echo "Thiếu gitleaks — cài: brew install gitleaks" >&2; exit 1; }
	gitleaks detect --no-banner --redact

# Pipeline RAG (P3): in kb_version và số đoạn truncated (phải = 0).
ingest:
	@echo "TODO (Phase 3): chưa có pipeline RAG (P3)." >&2; exit 1

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
