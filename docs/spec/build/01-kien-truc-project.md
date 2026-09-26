# 01 — Kiến trúc project và cấu trúc code

*Thuộc bộ `build/`. Trả lời ba câu: hệ thống chia thành những process nào, code sắp xếp theo cấu trúc nào, và các module được phép phụ thuộc nhau ra sao.*

> **Cập nhật v1.3 (25/09/2026):** `domain/states.py` dùng `is_allowed()` (D-29); thêm module `notify/` và bảng `child_notices` → 22 bảng (D-31).
>
> **Cập nhật v1.2 (25/09/2026):** thêm `graph/effects.py` (D-18), `runner.py` có `recover()` và khóa phiên trên lock pool riêng (D-19), DB tăng lên 21 bảng (`side_effects`), thêm hợp đồng import-linter số 6.

---

## 1. Chọn kiểu kiến trúc: modular monolith, không microservices

### 1.1. Kết luận

**Modular monolith cho phần nghiệp vụ + 3 service phụ trợ tách riêng vì lý do kỹ thuật cụ thể.** **[Đề xuất D-13]**

- **Một codebase backend Python duy nhất** (`backend/`) chứa toàn bộ nghiệp vụ M1–M7, M9. Nó chạy thành hai tiến trình từ cùng một image: `backend` (API + graph runner) và `worker` (quét hạn chờ).
- **Tách riêng** chỉ những thứ có lý do tách: `mock` (giả lập hệ thống ngoài — bản chất là "hệ thống khác"), `ml-service` (model nặng, cần nạp đúng 1 lần), `frontend` (bản build tĩnh).
- Bên trong monolith, mỗi module có ranh giới rõ (giao diện công khai, cấm import chéo phần nội bộ), để **có thể tách sau này** nếu cần.

### 1.2. Vì sao không microservices

| Tiêu chí | Microservices | Modular monolith | Hệ quả cho đồ án |
|---|---|---|---|
| Giao dịch | Mỗi service một DB; ghi state + audit cần saga/outbox | Một Postgres, một transaction | `goto()` phải đổi trạng thái **và** ghi audit trong cùng transaction **[Chốt mục 6]**. Tách service sẽ phá bất biến này |
| Checkpoint LangGraph | Graph phải nằm trong một process đọc được checkpoint | Tự nhiên | LangGraph chạy trong một process; tách node ra service khác chỉ thêm lời gọi mạng |
| Độ trễ | Thêm 1 lần gọi mạng ở mỗi ranh giới | Gọi hàm | Lượt đầu đã 10–15 giây vì LLM **[Chốt 14.2]**, không nên cộng thêm |
| Nhân lực | Mỗi service cần CI, deploy, health, version API | Một pipeline | Nhóm 4 người, 10 tuần, TV4 cần việc ngoài đường găng |
| Debug và tái lập thực nghiệm | Trace phân tán, nhiều log | Một trace, một log JSON | RQ1 cần chạy lại ra cùng số **[Chốt Phase 10]** |
| Chịu tải | Scale từng phần | Scale cả khối | Tải mục tiêu 110 ticket/giờ, năng lực ~1.400 lượt/giờ **[Chốt 14.3]** — không cần scale từng phần |

**Câu trả lời khi hội đồng hỏi "sao không microservices":** hệ thống có một bất biến quan trọng — đổi trạng thái ticket và ghi audit phải nguyên tử. Microservices buộc phải dùng giao dịch phân tán cho đúng bất biến này, trong khi tải thực tế chỉ bằng vài phần trăm năng lực một máy. Ranh giới module được giữ bằng quy tắc import và test, nên tách service sau này vẫn khả thi.

**Giới hạn cần nói thẳng [Suy luận, v1.2]:** transaction chung chỉ bảo vệ *state + audit*. Tác dụng phụ ngoài DB (gửi thông báo, tạo phiếu duyệt, tạo ticket con) vẫn có thể lặp khi node chạy lại sau crash. Vì vậy mọi tác dụng phụ trong node đi qua `graph/effects.py` với khóa idempotency ghi vào bảng `side_effects` **[Đề xuất D-18]**.

### 1.3. Ba service tách riêng và lý do

| Service | Lý do tách | Giao tiếp |
|---|---|---|
| `mock` | Giả lập AD/VPN/phần mềm/file — ngoài đời là hệ thống của bên khác. Tách để adapter gọi qua HTTP thật, test được lỗi mạng, timeout, 5xx **[Chốt]** | HTTP (httpx), cổng 8100 |
| `ml-service` | bge-m3 + bge-reranker-v2-m3 + model phân loại injection ≈ 3–4 GB RAM. Nếu nằm trong backend thì mỗi worker uvicorn nạp một bản **[Đề xuất D-09]** | HTTP nội bộ, cổng 8200 |
| `frontend` | Bản build tĩnh do Caddy phục vụ **[Chốt 13.2]** | HTTPS qua Caddy |

`worker` **không** phải service riêng về code: cùng image với `backend`, khác lệnh khởi động (`python -m app.worker`).

---

## 2. Sơ đồ process (Docker Compose)

```
                          Internet (443)
                               │
                        ┌──────▼──────┐
                        │   caddy     │  reverse proxy + HTTPS
                        └──┬───────┬──┘
              /  (tĩnh)    │       │  /api/*
                 ┌─────────▼─┐   ┌─▼──────────────────────────────┐
                 │ frontend  │   │ backend  (uvicorn × 2–4)       │
                 │ (build)   │   │  API · AuthN/Z · privacy guard │
                 └───────────┘   │  graph runner (LangGraph)      │
                                 │  M1–M7, M9 read APIs           │
                                 └─┬───────┬──────┬───────┬──────┘
                                   │       │      │       │
            ┌──────────────────────┘       │      │       └───────────────┐
            │                              │      │                       │
     ┌──────▼──────┐   ┌─────────────┐  ┌──▼──────▼──┐  ┌──────────┐  ┌───▼────────┐
     │  postgres   │◄──┤   worker    │  │ ml-service │  │  qdrant  │  │   mock     │
     │ tickets,    │   │ APScheduler │  │ embed      │  │ kb_*     │  │ AD, VPN,   │
     │ audit,      │   │ (cùng image │  │ rerank     │  │ collections│ │ software,  │
     │ checkpoint, │   │  backend)   │  │ classify   │  └──────────┘  │ file       │
     │ trace,      │   └─────────────┘  │ count_tokens│               └────────────┘
     │ side_effects│                    └────────────┘
     └─────────────┘
                                   ┌────────────────────────┐
                                   │ LLM: API cloud  hoặc   │  (ngoài compose, hoặc
                                   │ ollama / vLLM (tùy chọn)│   service `ollama` khi có GPU)
                                   └────────────────────────┘
```

Backend giữ **hai pool kết nối** tới Postgres: pool chính (transaction nghiệp vụ, checkpoint) và **lock pool** nhỏ chỉ để giữ `pg_advisory_lock` cấp phiên theo ticket **[Đề xuất D-19]**.

| Process | Image | Cổng | Mạng | Phase bật |
|---|---|---|---|---|
| `postgres` | postgres:16 | 5432 | nội bộ | 1 |
| `qdrant` | qdrant/qdrant | 6333 | nội bộ | 3 |
| `mock` | `mock` (FastAPI) | 8100 | nội bộ | 1 |
| `ml-service` | `ml` (FastAPI + torch CPU) | 8200 | nội bộ | 3 |
| `backend` | `backend` | 8000 | nội bộ, sau Caddy | 1 |
| `worker` | `backend` | — | nội bộ | 2 |
| `frontend` | `frontend` (build tĩnh) | — | sau Caddy | 7 |
| `caddy` | caddy:2 | 443 | **duy nhất mở ra ngoài** | 7 |
| `ollama` | ollama/ollama | 11434 | nội bộ | Tùy chọn (mức phần cứng 1) |

Chỉ Caddy mở cổng ra Internet. Postgres, Qdrant, mock, ml-service và `/api/eval/*` chỉ nghe trong mạng Docker nội bộ **[Chốt 13.2]**.

---

## 3. Cây thư mục repo

```
servicedesk-agent/
├── Makefile                      # make up | down | test | lint | ingest | seed | eval
├── docker-compose.yml            # dev
├── docker-compose.prod.yml       # staging/bảo vệ: + caddy, frontend build, không bind cổng nội bộ
├── .env.example                  # KHÔNG commit .env
├── pyproject.toml / uv.lock      # pin phiên bản (T01)
├── .importlinter                 # hợp đồng phụ thuộc giữa module (mục 4)
├── config/
│   ├── policy.json               # 20 luật + ngưỡng + hằng số [Chốt]
│   ├── llm.yaml                  # provider, vai trò fast/strong, fallback, giá
│   ├── injection_patterns.json   # regex B2 tầng 1
│   ├── privacy_patterns.json     # mẫu bí mật + PII tiếng Việt
│   ├── slots.yaml                # REQUIRED_SLOTS theo intent [Chốt B11]
│   ├── action_metadata.yaml      # ACTION_METADATA → reversible, data_sensitivity [Chốt 3.1]
│   ├── vi_abbrev.yaml            # từ viết tắt tiếng Việt cho truy hồi [Đề xuất v1.2, P3]
│   └── prompts/                  # b02_injection_judge.yaml, b03_classify.yaml, ...
├── backend/
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py               # tạo FastAPI app, gắn router, middleware
│   │   ├── settings.py           # pydantic-settings đọc env + config/
│   │   ├── worker.py             # entrypoint worker (APScheduler)
│   │   ├── core/                 # dùng chung, KHÔNG phụ thuộc module nghiệp vụ
│   │   │   ├── ids.py            # ticket_id, turn_id, trace_id
│   │   │   ├── clock.py          # Clock / FakeClock
│   │   │   ├── errors.py         # DomainError, ExternalSystemError, LLMSchemaError
│   │   │   ├── hashing.py        # hash_action (JSON sắp khóa + SHA-256)
│   │   │   └── logging.py        # log JSON có ticket_id, trace_id
│   │   ├── domain/               # kiểu dữ liệu thuần, không I/O
│   │   │   ├── states.py         # 14 S_*, is_allowed() = bảng 2.1 + 3 quy tắc (D-29), 6 chuyển bị cấm
│   │   │   ├── exit_codes.py     # E0–E9, block_reason, close_reason
│   │   │   ├── action.py         # Action, build_action
│   │   │   ├── ticket_state.py   # TicketState (TypedDict, có children, turn_id, reasoning_loops)
│   │   │   └── context.py        # RequesterContext
│   │   ├── db/
│   │   │   ├── models.py         # SQLAlchemy 2.0 (22 bảng — thêm side_effects v1.2, child_notices v1.3)
│   │   │   ├── session.py        # engine, pool chính + lock pool, role app_rw
│   │   │   └── alembic/
│   │   ├── auth/                 # P6 — AuthN/AuthZ
│   │   ├── guard/                # B2 — normalize, privacy, patterns, injection
│   │   ├── llm/                  # P2 — LLM gateway
│   │   ├── rag/                  # P3 — ingest (chunk theo token), retriever (fallback D-23), expand (D-24)
│   │   ├── tools/                # P5 — registry (ToolSpec.arg_slots), call_with_retry, breaker, adapters
│   │   ├── risk/                 # M5 — policy_engine, estimator, calibrator, decision_math
│   │   ├── approval/             # M6 — chọn người duyệt, xung đột lợi ích, SLA
│   │   ├── executor/             # B17 — Executor, TransactionLog
│   │   ├── audit/                # M7 — audit writer, security_events writer
│   │   ├── notify/               # notify_user — điểm gửi tin duy nhất; ticket con → child_notices (D-31)
│   │   ├── graph/                # P1 — M4
│   │   │   ├── builder.py
│   │   │   ├── routing.py
│   │   │   ├── boundary.py       # with_error_boundary (E9)
│   │   │   ├── tracing.py        # traced()
│   │   │   ├── goto.py
│   │   │   ├── effects.py        # effects.once — tác dụng phụ idempotent (D-18)
│   │   │   ├── runner.py         # submit / resume / recover; khóa phiên theo ticket (D-19)
│   │   │   ├── late_event.py     # on_late_event, wake_parent (D-17)
│   │   │   └── nodes/            # b01_identity.py … b20_audit.py (1 file/nhánh)
│   │   ├── monitor/              # M9 — chỉ đọc (role app_monitor) — P9
│   │   ├── eval/                 # M8 — chỉ bật khi EVAL_MODE=true — P8
│   │   └── api/                  # router mỏng: auth, tickets, approvals, overrides,
│   │                             #   escalations, policy, kb, dashboard, health, eval
│   └── tests/
│       ├── unit/  integration/  e2e/  probe/  load/
│       ├── fakes/                # ScriptedLLM, FakeClock, FakeMlService
│       └── conftest.py           # testcontainers Postgres + Qdrant
├── ml_service/                   # P4
│   ├── Dockerfile
│   └── app/  (main.py, embed.py, rerank.py, classify.py, intent.py, tokens.py)   # intent.py: /classify_intent (D-32)
├── ml_models/                    # intent-clf/<ver>/, injection-clf/<ver>/ — ONNX + thresholds.json + model_card.md (P11); tải vào volume models/
├── training/                     # P11 — KHÔNG nằm trong image; common/, intent/, injection/, data/
├── mock_services/                # P5
│   ├── Dockerfile
│   ├── seed.json                 # [Chốt] người dùng, thiết bị, license, thư mục...
│   └── app/  (ad.py, vpn.py, software.py, fileserver.py, admin_faults.py)
├── frontend/                     # React + Vite + TS + Tailwind + TanStack Query — P10
├── kb/                           # tài liệu KB .md có front matter
├── eval/                         # kịch bản, nhãn, SPLIT.md, kết quả thực nghiệm
└── docs/                         # servicedesk-agent-docs + build/ (bộ này)
```

**Quy tắc "một nhánh = một file node":** `graph/nodes/b06_diagnose.py` chỉ chứa hàm node và import dịch vụ từ `tools/`. Logic nặng nằm trong module nghiệp vụ, node chỉ điều phối. Nhờ vậy test được dịch vụ mà không cần dựng graph, và coding agent sửa một nhánh không đụng nhánh khác.

---

## 4. Kiến trúc bên trong mỗi module và quy tắc phụ thuộc

### 4.1. Ba lớp trong một module (kiểu hexagonal rút gọn)

```
module/
├── __init__.py      # GIAO DIỆN CÔNG KHAI: chỉ export những gì module khác được dùng
├── service.py       # nghiệp vụ, không biết HTTP hay SQL cụ thể
├── models.py        # Pydantic schema vào/ra
├── ports.py         # Protocol cho phụ thuộc bên ngoài (ví dụ IdentityProvider)
└── adapters/        # hiện thực ports: httpx, SQLAlchemy, qdrant-client...
```

**Vì sao:** test nghiệp vụ bằng adapter giả, và đổi mock sang hệ thống thật chỉ cần viết adapter mới **[Chốt 17.3]**.

### 4.2. Đồ thị phụ thuộc cho phép

```
api ──► auth, guard(privacy), graph.runner, approval, audit(read), monitor, risk(policy CRUD), rag(kb admin)   # guard: D-07, B02 §2
graph ──► guard, llm, rag, tools, risk, approval, executor, audit, domain, core
risk ──► llm, domain, core            (KHÔNG import guard, rag.raw, api)
executor ──► tools(write adapters), risk.policy_engine, domain, core
monitor ──► db (role app_monitor) , domain, core   (KHÔNG import graph, executor, tools)
llm, rag, tools, guard, auth, audit ──► domain, core, db
domain ──► core
core ──► (không gì)
```

### 4.3. Hợp đồng kiểm tra tự động (`.importlinter`)

| Hợp đồng | Chặn điều gì | Vì sao |
|---|---|---|
| `risk` không được import `guard`, `api`, hoặc đọc `raw_request` | M5 đọc câu người dùng | Bất biến chống injection **[Chốt 6.2]** |
| `monitor` không được import `graph`, `executor`, `tools`, `graph.goto` | M9 ghi ngược | Ranh giới chỉ-đọc **[Chốt 17.9.1]** |
| Chỉ `executor` được import `tools.adapters.*_write` | Tool ghi bị gọi ngoài B17 | Điểm ghi duy nhất **[Chốt]**. Import-linter không nhận wildcard một phần tên → liệt kê từng module `{ad,vpn,software,fileserver}_write`; kèm test: mọi file `tools/adapters/*_write.py` phải có tên trong `.importlinter` |
| `domain`, `core` không import module nghiệp vụ | Vòng phụ thuộc | Giữ lớp lõi thuần |
| `graph.nodes.*` không import lẫn nhau | Nhánh gọi thẳng nhánh khác | Mọi chuyển trạng thái đi qua `goto()` và routing |
| *(không dùng import-linter)* `graph.nodes.*` không **gọi thẳng** `approvals.create`, `approvals.notify_approver`, `notify_user`, `deadlines.set`, `tickets.create_child`, `runner.submit` — chỉ truyền vào `effects.once` | Tác dụng phụ lặp khi node chạy lại | Idempotency sau crash **[D-18]**. Import-linter không phân biệt được "import để truyền vào `once`" với "gọi thẳng", nên kiểm bằng **test AST** (P1 mục 5.3) **[Chốt 25/09/2026]** |

Thêm một test bổ sung: `inspect.signature(policy_engine.evaluate)` chỉ có tham số `action`, `ctx` **[Chốt]**.

---

## 5. Cấu hình

### 5.1. Nguyên tắc

| Loại | Ở đâu | Ai sửa | Ví dụ |
|---|---|---|---|
| Bí mật | `.env` (quyền 600) / GitHub Secrets | Vận hành | `LLM_API_KEY`, `JWT_SIGNING_KEY`, `PG_PASSWORD`, `MFA_ENC_KEY`, `SVC_EXECUTOR_TOKEN` |
| Hạ tầng | `.env` | Vận hành | `DATABASE_URL`, `QDRANT_URL`, `ML_SERVICE_URL`, `MOCK_URL`, `LOCK_POOL_SIZE`, `TICKET_LOCK_TIMEOUT` |
| Chính sách nghiệp vụ | `config/policy.json` → nạp vào `policy_versions` | Trưởng BP qua UI | 20 luật, ngưỡng, SLA, giới hạn vòng lặp **[Chốt]** |
| Hành vi AI | `config/llm.yaml`, `config/prompts/*` | Dev qua PR | model, timeout, prompt version |
| Cờ thực nghiệm | env | Người chạy thực nghiệm | `EVAL_MODE`, `ENABLE_PROACTIVE_DIAGNOSIS`, `STRATEGY`, `LLM_CACHE_MODE`, `REDIAGNOSE_ON_NEW_SLOT` (mặc định `false`, D-20) |

### 5.2. Hằng số trong `policy.json` [Chốt]

`MAX_LOOPS=5`, `MAX_CLARIFICATION_TURNS=3`, `TOOL_RETRY=2`, `BACKOFF_BASE_SECONDS=1`, `MAX_AUTH_FAILURES=5` (cửa sổ 10 phút), `SLA_MINUTES=30`, `THRESHOLD_LOW=0.25`, `THRESHOLD_HIGH=0.75` (sẽ thay bằng ngưỡng chọn trên tập calibration), `RETRIEVAL_THRESHOLD=0.6` (giá trị khởi điểm; chọn lại trên tập dev theo quy trình D-22), `CLARIFY_TIMEOUT=24h`, `CONFIRM_TIMEOUT=48h`.

### 5.3. Nạp cấu hình

`settings.py` dùng `pydantic-settings`. Khi khởi động: validate `policy.json` bằng schema Pydantic (sai → không khởi động), nạp bản `policy_versions.is_current=TRUE` vào bộ nhớ. Khi Trưởng BP lưu policy mới: validate → ghi `policy_versions` + `policy_rules` trong một transaction → phát tín hiệu reload (NOTIFY Postgres) để mọi worker nạp lại.

---

## 6. Công nghệ và phiên bản

Pin toàn bộ ở T01 bằng `uv lock`. Bảng dưới là danh sách thư viện, không phải phiên bản bắt buộc.

| Nhóm | Thư viện | Dùng cho |
|---|---|---|
| Ngôn ngữ | Python 3.12 | Backend, ml-service, mock |
| API | FastAPI, uvicorn, pydantic v2, pydantic-settings | Mọi service Python **[Chốt]** |
| Điều phối | langgraph 1.x, langgraph-checkpoint-postgres | M4 **[Chốt]** |
| DB | PostgreSQL 16, SQLAlchemy 2.0, Alembic, psycopg 3 | **[Chốt]** |
| HTTP | httpx, respx (test) | Tool, mock, ml-service **[Chốt]** |
| Lịch | APScheduler | Worker **[Chốt]** |
| LLM | openai (SDK, base_url), Ollama/vLLM tùy chọn | P2 **[Đề xuất D-12]** |
| Vector | qdrant-client | P3 **[Chốt]** |
| Model | FlagEmbedding hoặc sentence-transformers, transformers, torch CPU, onnxruntime (tùy chọn) | ml-service |
| Tiếng Việt | pyvi (hoặc underthesea) | Tách từ cho BM25 **[Đề xuất D-10]** |
| Riêng tư | presidio-analyzer, presidio-anonymizer, unidecode | B2 **[Đề xuất D-06]** |
| Bảo mật | PyJWT, argon2-cffi (mock), pyotp (MFA), cryptography | P6 |
| Hiệu chỉnh | scikit-learn, numpy, scipy (Clopper–Pearson) | M5, M8 **[Chốt]** |
| Đánh giá truy hồi | tự viết Recall@k / MRR / nDCG@k (numpy) | Ablation RAG D-25 |
| Test | pytest, pytest-asyncio, respx, testcontainers, hypothesis (tùy chọn), locust | **[Chốt]** |
| Chất lượng | ruff, mypy, import-linter | CI |
| Frontend | React, Vite, TypeScript, Tailwind, TanStack Query | **[Chốt]** |
| Hạ tầng | Docker Compose, Caddy, GitHub Actions, GHCR | **[Chốt]** |

---

## 7. Makefile và CI/CD

### 7.1. Lệnh

| Lệnh | Làm gì |
|---|---|
| `make up` | Dựng compose; chạy migration; seed mock; kiểm `/api/health` |
| `make test` | unit + integration + e2e với ScriptedLLM, testcontainers |
| `make lint` | ruff, mypy, import-linter |
| `make ingest` | Chạy pipeline RAG (P3), in `kb_version` và số đoạn `truncated` (phải = 0) |
| `make probe` | Probe với LLM thật (intent, injection, phân phối p) |
| `make eval STRATEGY=hybrid SPLIT=test` | Harness M8 (chỉ khi `EVAL_MODE=true`) |
| `make eval-rag` | Ablation 4 cấu hình truy hồi (D-25) trên tập dev |
| `make load` | Locust theo 5 kịch bản mục 14.4 |

### 7.2. Pipeline [Chốt 13.3, chi tiết hóa]

1. **PR:** `make lint` + `make test`. Đỏ thì không merge. Thêm bước quét bí mật (gitleaks) **[Đề xuất]**.
2. **Merge vào main:** build 4 image (`backend`, `ml`, `mock`, `frontend`), tag = mã commit, đẩy GHCR.
3. **Staging:** SSH → `docker compose pull` → migration → `up -d` → smoke (`/api/health` + TC01 với ScriptedLLM). Smoke đỏ → quay về tag trước.
4. **Migration an toàn:** chỉ thêm bảng/cột trong một đợt; xóa cột ở đợt sau.

---

## 8. Tiêu chí đạt của cấu trúc project (cổng T01)

1. `make up` dựng đủ process của Phase 1 (postgres, mock, backend), `/api/health` trả 200.
2. `make lint` xanh, bao gồm 5 hợp đồng import-linter ở mục 4.3 (với module rỗng); hợp đồng thứ 6 là test AST trong `make test`.
3. Test chữ ký `policy_engine.evaluate(action, ctx)` xanh.
4. `.env` nằm trong `.gitignore`; gitleaks không báo gì trên toàn repo.
5. Image `backend` và `worker` là một; chỉ khác lệnh khởi động.

---

## Lịch sử thay đổi

| Phiên bản | Ngày | Thay đổi |
|---|---|---|
| v1.2 | 25/09/2026 | `graph/effects.py` (D-18); `runner.recover`, lock pool (D-19); `late_event.wake_parent` (D-17); DB 21 bảng; hợp đồng import-linter số 6; cờ `REDIAGNOSE_ON_NEW_SLOT` (D-20); `vi_abbrev.yaml`, `ml_service/tokens.py` (D-21); `make eval-rag` (D-25) |
| v1.3 | 25/09/2026 | `is_allowed()` (D-29); `notify/` + `child_notices`, 22 bảng (D-31) |
| v1.4 | 25/09/2026 | Thêm `training/`, `ml_models/`, `ml_service/app/intent.py` (D-32, D-33, P11) |
| v1.5 | 26/09/2026 | Mục 4.2: `api` được phụ thuộc `guard` (privacy guard chạy ở API trước khi lưu — D-07, B02 §2; chốt khi hiện thực 2b-3). `APP_ENV` bắt buộc trong `.env` (compose `${APP_ENV:?…}`), không mặc định |
