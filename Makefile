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

.PHONY: up down test test-ml lint ingest tokenizer seed probe eval eval-rag load gate2 gate3 vpn-smoke models ml-bench \
	rerank-bench verify verify-status audit-check

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
# Phase 4 P4 (Việc treo 13): commit của image backend cho `lineage.commit_sha` — CHỈ khi file tracked không đổi (file untracked
# như PLAN-*.md không tính, không thì máy dev không bao giờ "sạch"); cây bẩn → rỗng → lineage NULL.
GIT_SHA := $(shell test -z "$$(git status --porcelain --untracked-files=no 2>/dev/null)" && git rev-parse HEAD 2>/dev/null)
BUILD_BACKEND := $(COMPOSE) build --build-arg GIT_SHA=$(GIT_SHA) backend

# Dựng compose; chạy migration (role app_migrate); nạp seed mock; kiểm /health của mock, worker healthy
# (heartbeat, tối đa 60 giây — quá hạn in 30 dòng log worker, exit 1) và /api/health.
# ml-service (3a): kiểm model đã tải TRƯỚC khi build (thiếu → "chạy make models"); backend và worker chờ
# ml-service healthy (depends_on) — nạp model lần đầu mất tới vài phút; lỗi thì in log ml-service.
up:
	@if [ "$(ENV_FILE)" = ".env.example" ]; then \
	  echo "CẢNH BÁO: không có .env — dùng giá trị mẫu của .env.example (chỉ cho máy dev)." >&2; fi
	@PYTHONPATH=ml_service uv run python -m app.lock $(MODELS_DIR) || { \
	  echo "Thiếu model cho ml-service — chạy: make models" >&2; exit 1; }
	$(BUILD_BACKEND)
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
	# Phase 4 P5: test cũng soát kiểu. --explicit-package-bases + MYPYPATH=backend: gốc gói như pytest (`tests.*`, `app.*`) —
	# thiếu thì mypy dừng vì 2 `conftest.py` (integration, e2e) trùng tên module. Cache riêng (khác gốc gói với backend/app).
	MYPYPATH=backend uv run mypy --explicit-package-bases --cache-dir .mypy_cache/tests backend/tests
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
	$(BUILD_BACKEND)
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

# Cổng 3 trên stack compose thật (phase3 11.6; backend/tests/stack/README.md). Node THẬT: .env KHÔNG đặt FAKE_SCENARIO,
# LLM_BACKEND=scripted (preset config/scripted/tc*.yaml), có SVC_EXECUTOR_TOKEN (B15 thật chọn người duyệt theo
# config/approvers.yaml — không cần FAKE_APPROVER_ID, biến đó chỉ cho gate2); KB fixture:
# make ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated. Route tính theo giờ lúc chạy (in đầu bảng).
# tc28 tự `compose stop qdrant` rồi `start` lại. Ví dụ: make gate3 S=preflight | make gate3 S=tc02 | make gate3 S=all
gate3:
	COMPOSE="$(COMPOSE)" PYTHONPATH=backend uv run python -m tests.stack.gate3 $(S)

# Phase 4 (mục 4.4, Q-4-I/Q-4-T): MỘT lệnh cho mọi DỪNG — lint → test → up → cổng theo G (chuỗi chữ số: 0 = chỉ lint+test,
# 2 = gate2, 3 = gate3; 4d thêm 4) → LUÔN trả backend+worker về cấu hình .env. gate2/gate3 cần FAKE_SCENARIO ngược nhau →
# script tạo lại backend+worker bằng biến shell, không đọc/sửa .env. BENCH=1 thêm bench checkpoint (P6). Kết quả:
# .verify/summary.txt (agent đọc) + .verify/run-*.log. Lệnh >120 s bị đẩy nền là bình thường — báo agent "xong".
G ?= 3
BENCH ?= 0
# KHÔNG viết biến MAKE của make trong dòng lệnh dưới: GNU make coi dòng có nó là gọi đệ quy và CHẠY THẬT cả khi `make -n`.
verify:
	G="$(G)" BENCH="$(BENCH)" COMPOSE="$(COMPOSE)" MAKE_BIN=make bash scripts/verify.sh

verify-status:
	@cat .verify/summary.txt 2>/dev/null || echo "chưa có .verify/summary.txt — chạy: make verify"

# Phase 4 4d (P5, PLAN-4d TQ-5/6): kiểm 8 điểm log + quét bí mật trên audit_logs — CHỈ ĐỌC, chạy TRONG container backend (DSN của
# compose: app_monitor nếu có, không thì app_rw READ ONLY; máy không đọc .env). In nhãn role, không in DSN/giá trị. Cần `make up` (image
# mới có app/audit/check.py). Quét thêm log: `$(COMPOSE) logs --no-color backend worker | $(COMPOSE) exec -T backend python -m
# app.audit.check --log - …`. Ví dụ: make audit-check ARGS="--since 2026-10-01T10:00:00+07:00" | make audit-check ARGS="<ticket_id>"
audit-check:
	$(COMPOSE) exec -T backend python -m app.audit.check $(ARGS)

# Smoke luồng VPN (phase3 11.9): tc02, tc04, tc05, tc06 với LLM_BACKEND hiện hành + số liệu llm_calls. Với real: TỪ CHỐI
# khi spend.cap_usd (config container backend đang nạp) > 1 hoặc model chưa có pricing — README "Chạy smoke LLM thật".
vpn-smoke:
	COMPOSE="$(COMPOSE)" PYTHONPATH=backend uv run python -m tests.stack.vpn_smoke

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

# Đo tốc độ + độ lệch int8 của reranker TRONG TIẾN TRÌNH, không qua HTTP (Q-3a-16) — chọn cấu hình rag_rerank_k
# / threads / int8. Nạp model bằng lock thật (`make models` trước) — DỪNG service đang chạy trước khi đo (torch
# tranh CPU với service thật sẽ làm số đo sai): `docker compose stop backend worker ml-service` rồi `make up`
# lại sau khi đo xong. Ví dụ: make rerank-bench KB_DIR=backend/tests/fixtures/kb ARGS="--k 10,20 --threads 3,4 --int8"
rerank-bench:
	$(COMPOSE) build ml-service
	$(COMPOSE) run --rm --no-deps -v "$(abspath $(KB_DIR)):/kb:ro" ml-service \
	  python -m app.rerank_bench --kb /kb $(ARGS)

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

# Đo Recall@5/FG/MRR truy hồi trên bản KB ĐANG CHẠY (alias kb_current, Q-3c-15) — không ingest lại. Cần `make up`
# và đã `make ingest` trước. `--sweep` thêm bảng 13 ngưỡng (chỉ quan sát, KHÔNG chọn ngưỡng — D-22); `--csv` in
# CSV thay bảng người đọc. Ablation 4 cấu hình truy hồi (D-25, Phase 5) là việc KHÁC, làm sau, có thể dùng lại
# CLI này với tham số khác — không nhầm với việc này.
# Ví dụ: make eval-rag KB_DIR=backend/tests/fixtures/kb ARGS=--sweep
eval-rag:
	$(COMPOSE) run --rm --no-deps -v "$(abspath $(KB_DIR)):/srv/kb:ro" backend \
	  python -m app.rag.eval_cli --kb-dir /srv/kb $(ARGS)

# Locust theo 5 kịch bản huong-dan mục 14.4.
load:
	@echo "TODO (Phase 8): chưa có kịch bản locust." >&2; exit 1
