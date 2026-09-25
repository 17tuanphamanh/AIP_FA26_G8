# Lệnh theo docs/spec/build/01-kien-truc-project.md mục 7.1.
# Lệnh chưa có hạ tầng thì in TODO và thoát mã 1 — để không ai tưởng nó đã chạy.
# Lệnh chạy được một phần (lint) thì chạy phần đã có và in TODO cho phần còn thiếu.

STRATEGY ?= hybrid
SPLIT ?= dev

.PHONY: up down test lint ingest seed probe eval eval-rag load

# Dựng compose; chạy migration; seed mock; kiểm /api/health.
up:
	@echo "TODO (Phase 1): chưa có docker-compose.yml, migration, seed mock." >&2; exit 1

down:
	@echo "TODO (Phase 1): chưa có docker-compose.yml." >&2; exit 1

# unit + integration + e2e với ScriptedLLM, testcontainers. Không gồm probe/ và load/.
test:
	uv run pytest backend/tests/unit backend/tests/integration backend/tests/e2e

# ruff, mypy, import-linter.
lint:
	uv run ruff check .
	uv run mypy backend/app
	@echo "TODO (Phase 1): import-linter — chưa có .importlinter (6 hợp đồng ở 01 mục 4.3)." >&2

# Pipeline RAG (P3): in kb_version và số đoạn truncated (phải = 0).
ingest:
	@echo "TODO (Phase 3): chưa có pipeline RAG (P3)." >&2; exit 1

seed:
	@echo "TODO (Phase 1): chưa có mock_services/seed.json (P5)." >&2; exit 1

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
