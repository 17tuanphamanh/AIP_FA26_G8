# PROGRESS

*Theo `docs/spec/CLAUDE.md` mục 4: phase đang mở, task xong, cổng nào xanh, câu hỏi mở.
Mọi đường dẫn dưới đây tính từ `docs/spec/`.*

## Trạng thái

| Mục | Giá trị |
|---|---|
| Chế độ xây | **Code trước, gắn API sau** (`build/decisions.md` mục 4): Phase 1–7 dùng `ScriptedLLM`, không gọi LLM thật |
| Phase đang mở | **Phase 2 (P1, B01, B20)** — chặng 2a **đã duyệt**, đã commit; chặng 2b theo 4 bước: **2b-1 đã commit `6c43153`, CI xanh (run `36240526098`)**; **2b-2 đã commit `b68e800`, CI xanh (run `36243253945`)**; **2b-3 (dịch vụ ticket + route sự kiện + nối `create_app`): code + unit + lint xanh, đã commit `dcc5ddc`, CI xanh (run `36270415646`)**; **2b-4 (stack thật + cổng 2): code + unit + lint + mutation 11/11, `make test` xanh (1643 + mock 86, sau lần rà `after_event`), `make gate2` đủ 10 kịch bản 0 FAIL trên máy dev, Tuấn Anh đã đọc bảng threads; **cổng 2 CHƯA đạt — chờ một thành viên khác chạy `make gate2 S=all` trên máy họ và dán kết quả** — chưa commit**. Phase 1 đã đóng |
| Cổng xanh | Phase 0; T01; **Cổng Phase 1 — tự động xanh** (26/09/2026): `make lint`, `make test` (backend 1215 + mock 86), `make up` + `/api/health` 200 có `mock`, `make seed`, đăng nhập user demo. Còn mục **thủ công** của cổng 1 (`huong-dan` 5.1): người xác nhận gọi tay 12 tool (bảng ở `mock_services/README.md`) — mở Phase 2 trước khi mục này xong hay không là **người quyết** |
| Cập nhật | 28/09/2026 — Phase 3 chặng 3a đã commit `00e72b0` (CI xanh); **chặng 3b (RAG ingest): code + unit + lint + mutation 10/10 + `make test` xanh (1847 + mock 86 + ml 61), chưa commit** — mục "Phase 3 — chặng 3b" |

## Phase 0 — đã xong (25/09/2026)

- D-01…D-33: **đã chốt theo đặc tả** (`build/decisions.md` mục 3).
- Q1–Q14: nhóm tự quyết, chỉ báo cáo GVHD, không có vòng hỏi (`build/decisions.md` mục 2).
- N3, N4, N5 đã chốt. N1 (chọn model) và N2 (VRAM) **chỉ chặn mốc G**, không chặn code.
- Bảng 20 luật R01–R20: `build/decisions.md` mục 1.1 (luật VPN thiết bị chưa đăng ký = **R17**, tài liệu cũ ghi R22).

## Việc đã làm (chuẩn bị repo, trước Phase 1)

- Gỡ agent thử nghiệm cũ; dựng cây thư mục theo `build/01-kien-truc-project.md` mục 3
  ngay tại gốc repo (chỉ `__init__.py` + README 1 dòng, **chưa có logic nghiệp vụ**).
- `pyproject.toml` (Python 3.12, uv) + `uv.lock`; `Makefile` theo 01 mục 7.1 — `test`,
  `lint` chạy được, các lệnh khác in TODO.
- `backend/tests/unit/test_smoke.py` — test giữ chỗ; **đã xoá** ở Phase 1b khi có test thật.

**Cổng T01 (01 mục 8) — xanh cả 5 mục** (26/09/2026, Phase 1a):

| Mục | Kết quả | Kiểm bằng |
|---|---|---|
| 1. `make up` dựng postgres, mock, backend; `/api/health` 200 | Xanh | `make up` → `{"status":"ok","checks":{"db":"ok","qdrant":"ok"}}`; chạy lại lần 2 trên volume cũ vẫn OK; `make down` sạch, giữ volume |
| 2. `make lint` xanh gồm hợp đồng import | Xanh | ruff, mypy, 5 hợp đồng import-linter; hợp đồng 6 là test AST trong `make test` |
| 3. Test chữ ký `policy_engine.evaluate` | Xanh | `test_policy_engine_signature.py` |
| 4. `.env` trong `.gitignore`; gitleaks sạch | Xanh | `gitleaks detect` trong `make lint`: 21 commit, không có leak |
| 5. backend và worker chung image | Xanh | `docker inspect`: cùng image id `sha256:083acb13…` |

`make test` = 908 passed (874 unit + 34 integration trên testcontainers Postgres 16), 26/09/2026.

## Phase 1 — đã đóng (26/09/2026)

| Việc | Trạng thái |
|---|---|
| docker-compose (postgres 16, qdrant, backend, worker, mock) + `make up/down` | **Xong** 25/09/2026 (Phase 1a) — backend và worker chung image `servicedesk-backend`; mock mới có `/health` |
| DB 22 bảng + 3 role Postgres + trigger append-only (Alembic, P7) | **Xong** 25/09/2026 (Phase 1a) — migration `0001` chạy bằng `app_migrate`; bảng nguồn từng cột ở `backend/app/db/README.md`; 34 test integration (testcontainers) |
| `backend/app/core`, `domain` (14 trạng thái, `is_allowed`, E0–E9, Action, hash) | **Xong** 25/09/2026 (Phase 1b) — `build_action` làm cùng B11 (câu hỏi 9) |
| `mock_services` + `seed.json` + `make seed` + registry/tool (P5) | **Xong** 26/09/2026 (Phase 1c chặng 1, đã duyệt, commit `2257060`) |
| Auth (P6) | **Xong** 26/09/2026 (Phase 1c chặng 2) — `make test` + `make up` + đăng nhập demo xanh; chưa commit |
| `.importlinter` 5 hợp đồng + hợp đồng 6 bằng test AST (01 mục 4.3) | **Xong** 25/09/2026 (Phase 1b) — `make lint` + `test_side_effects_ast.py`, `test_write_adapters_listed.py`; đã thử phá từng hợp đồng, đều bắt được |
| `.env.example` theo 01 mục 5.1 (bỏ biến agent cũ; biến LLM để trống tới mốc G) | **Xong** 25/09/2026 (Phase 1a) |

## Phase 1c — chặng 1: mock + registry/tool + Makefile/CI (26/09/2026, chờ duyệt)

Kế hoạch đã duyệt chia 2 chặng: chặng 1 = mock (P5 mục 7) + `backend/app/tools/` (P5 mục 4–6.1)
+ Makefile/CI; chặng 2 = auth (P6), MFA, migration 0002 — chỉ làm sau khi người duyệt chặng 1.

**Đã làm:**
- `mock_services/`: AD (argon2id, hash giả cho user không tồn tại), VPN, phần mềm, file server; 13
  endpoint ghi (8 tool + 5 hoàn tác) chỉ nhận token `svc_executor`; `/_admin/faults` (error/timeout/
  latency, theo tiền tố path, giới hạn số lần), `/_admin/reset`; `seed.json` 16 người (đủ 4
  `employment_status`, 4 nhóm AD, ca D-15, D-20, TC06), mốc thời gian tương đối; `python -m app.seed
  validate|reset|hash`. Mật khẩu demo + bảng mong đợi 12 tool: `mock_services/README.md`.
- `backend/app/tools/`: `specs.py` (ToolSpec, 12 tool đọc + `ad_get_user` + 13 tool ghi, `TOOL_MAP`,
  `validate_specs` chạy lúc import), `retry.py` (`call_with_retry`), `breaker.py`, `registry.py`
  (`ToolResult` theo P5 6.1), `adapters/` (`*_read` token svc_agent, `*_write` token svc_executor),
  `wiring.py` (`build_read_registry`).
- `config/policy.json` (chỉ khối `constants`; `rules` thêm ở Phase 3) và `config/slots.yaml`
  (`tool_arg_slots`), nạp + kiểm schema trong `settings.py`. `Clock.sleep` (FakeClock tua giờ).
- `/api/health` kiểm thêm `mock`. Compose: mock nhận 3 token; **worker không nhận `SVC_EXECUTOR_TOKEN`**.
  `.env.example` thêm `SVC_AGENT_TOKEN`, `SVC_WORKER_TOKEN`. Phụ thuộc: `pyyaml`, `types-pyyaml` (dev).
- Makefile: `test` chạy thêm `pytest mock_services/tests -o pythonpath=mock_services`; `lint` thêm mypy
  cho mock (cache riêng); `seed` = validate + reset; `up` chờ mock `/health` rồi `make seed`.
  → giải quyết câu hỏi mở 3 (ba package `app`) cho mock; ml_service làm tương tự ở P4.
- `.github/workflows/ci.yml`: `uv sync --locked` → `make lint` (có gitleaks 8.30.1) → `make test` đầy đủ.

**Kết quả kiểm (26/09/2026, trong sandbox Claude Code):**

| Lệnh | Kết quả |
|---|---|
| `make lint` | **Xanh** — ruff, mypy backend + mock, 5 hợp đồng import-linter, gitleaks detect 24 commit không leak; `gitleaks dir` trên file mới/sửa: không leak (kể cả hash argon2 trong seed) |
| unit backend | **963 passed** (961 + 2 test breaker trung tính, sau khi sửa theo P5 1.4) |
| test mock | **86 passed** |
| integration (34, testcontainers) | **Xanh** — người chạy `make test` ngoài sandbox (sandbox chặn socket Docker) |
| e2e `test_tools_vs_mock.py` (24) | **Xanh** — cùng lần chạy trên (sandbox chặn bind cổng local) |
| `make test` đầy đủ | **Xanh** (người chạy ngoài sandbox, sau khi sửa breaker theo P5 1.4): backend 1021 passed (963 unit + 34 integration + 24 e2e) + mock 86 passed |
| `make up` + `/api/health` | Chưa chạy ở chặng 1 (làm ở bước kiểm cuối Phase 1c) |
| CI GitHub | **Xanh** — run `36189412156` (workflow `ci`, push `dev-tuananh`, commit `de243b6`, 1m1s, 26/09/2026): `make lint` + `make test` đầy đủ trên ubuntu |

**Quyết định khi hiện thực** — người đã duyệt cả 5 điểm (26/09/2026); điểm 1–4 đã vào P5 mục 6.1, 7 (bản 1.4):
- `registry.call` theo P5 6.1. Sơ đồ P5 mục 2 vẫn ghi "mở ─► ExternalSystemError ngay" — mục 6.1 [Chốt] thắng.
- **Tool ghi 404/409** = thực thi thất bại → `error` (B17 → E7), không raise, **không tính vào breaker**.
  Bản đầu gọi `record_success()` (xoá chuỗi lỗi liên tiếp) — lệch chữ "không tính"; đã sửa thành
  `record_neutral()`: giữ nguyên chuỗi lỗi, riêng lượt thử half-open thì coi là thành công (hệ thống
  đã trả lời, không để kẹt half-open). Có 2 test mới (4 lỗi + 409 + 1 lỗi → mở; 409 ở lượt thử → đóng).
- Breaker đếm lỗi theo **lần gọi registry sau retry**, không theo từng HTTP attempt.
  Lỗi hợp đồng không tính là lỗi hạ tầng; exception lạ thì tính (để half-open không kẹt).
- `check_device_registered` không có `device_id` → tra mọi máy của người đó (thêm endpoint mock
  `GET /vpn/devices?owner_id=`) — để TC06 tự suy `device_id`. `check_installed_list`,
  `check_catalog_entry`, `check_license_available`, `check_resource_sensitivity` **bắt buộc** slot
  tương ứng; thiếu slot = lỗi hợp đồng (raise → E9) → B6 (Phase 3) **phải lọc** tool theo slot đã có
  trước khi gọi (P5 6.1 bản 1.4).
- **Hook pre-commit** (`.githooks/pre-commit`): đổi file trong `mock_services/` (kể cả `seed.json`) →
  chạy thêm `pytest mock_services/tests -o pythonpath=mock_services -q`; luật cũ (`.py`, `config/prompts/`,
  `config/policy.json` → unit backend) giữ nguyên. Đã thử: sửa giả `mock_services/app/main.py` cho đỏ 1
  test → hook chạy test mock, in "Test mock đỏ", thoát 1; hoàn tác → hook chạy cả 2 bộ, thoát 0.
  Hook chỉ thấy file đã stage hoặc file tracked đang sửa — file mới chưa `git add` không kích hoạt
  (commit thì phải stage nên vẫn bị bắt).
- Tên trường input trùng tên slot, trừ `target_user` → `user_id` (`models.SLOT_TO_FIELD`).
- Mock: khoá tài khoản email/ERP không chặn `/ad/authenticate`; trạng thái disabled/terminated do
  backend quyết (P6 mục 4 bước 5).

**Câu hỏi mở cho Phase 2:**
- ~~Worker không có `SVC_EXECUTOR_TOKEN`, nhưng `runner.recover()` (P1 mục 7) chạy trong worker có thể
  đi tới B17~~ — **đã chốt + hiện thực ở Phase 2a**: recover ở worker không chạy B17, chuyển E7 "thực thi
  bị gián đoạn" (mục Phase 2a, quyết định 4).

## Phase 1c — chặng 2: auth (P6) — kế hoạch đã duyệt (26/09/2026; đã làm — kết quả ở mục ngay dưới)

Làm sau khi chặng 1 được duyệt (đã commit `2257060`). Lệch phase so với P6 mục 10 (middleware ở
Phase 2, MFA/CSRF ở Phase 7, `can_decide_approval` ở Phase 4): làm sớm theo task. **Không làm:** B1
node, graph, route tickets/approvals thật, LLM.

**Quyết định đã chốt:**
1. **IDOR (D-02):** `can_*` là hàm thuần trong `auth/`; test HTTP qua **router chỉ có trong
   `backend/tests/`**, không thêm route sản phẩm (route thật gắn ở Phase 2/4, dùng lại các hàm này).
   Đọc ticket của người khác mà không có quyền → **404, không 403** (không lộ ticket tồn tại). Test cả
   hai phía: ticket có thật của người khác và id không tồn tại cho **cùng** phản hồi 404 (status + body).
2. **MFA:** bắt buộc với `manager`, chỉ đăng ký qua CLI vận hành
   `python -m app.auth.mfa enroll|reset <username> --by <operator> --reason <text>`.
   - Enroll và reset đều ghi `security_events` (`mfa_enrolled` / `mfa_reset`); `detail` chỉ có `by`,
     `reason` — **không** secret, không URI otpauth (có test canary). Hai loại này **không** nằm trong
     view `auth_failures`.
   - `reset`: xoá secret cũ, sinh secret mới, tăng `token_version` (phiên cũ chết). Secret/URI chỉ in
     ra stdout, không log.
   - Manager chưa enroll mà đăng nhập → 401 (fail-closed) + `mfa_failed` (`detail.reason=not_enrolled`).
   - **Migration 0002** (không sửa 0001) nới CHECK `security_events.event_type`; thêm 2 giá trị vào
     `SECURITY_EVENT_TYPES` (`db/models.py`). Test upgrade/downgrade; downgrade dừng với thông báo rõ
     nếu đã có dòng thuộc 2 loại này (bảng append-only, không xoá được). P7 2.3 đã được người cập nhật.
3. **Refresh giữ chặt:** trình lại token đã xoay → thu hồi cả họ (`reuse_detected`) + ghi
   `refresh_reuse_detected`. Test ca **2 request refresh đồng thời cùng token** (2 tab) → request thứ
   hai bị coi là reuse; đây là hành vi đã biết, frontend xử lý ở Phase 7.
4. **Worker không có `SVC_EXECUTOR_TOKEN`** (đã hiện thực ở chặng 1, `docker-compose.yml`): chỉ container
   backend giữ credential ghi (D-03). Chặng 2 không đổi điều này. Hệ quả còn mở cho Phase 2:
   `runner.recover()` chạy trong worker mà đi tới B17 thì sẽ ra E7 (xem mục chặng 1 "Câu hỏi mở cho Phase 2").

**Thiết kế (từ kế hoạch Phase 1c):**
- **Phụ thuộc module (01 mục 4.2: auth → domain, core, db):** `auth` không import `tools`/`audit`. Port
  `Protocol` ở `auth/ports.py`: `IdentityProvider`, `SecurityEventSink`, `AdUser`. Adapter AD
  (`tools/adapters/ad_read.py`) và writer (`audit/security_events.py`) khớp port theo cấu trúc;
  `main.create_app` nối lại.
- **Tham số (một nguồn):** `MAX_AUTH_FAILURES`, `AUTH_FAILURE_WINDOW_MINUTES` ở `config/policy.json`
  (đã có). `Settings` (env, có mặc định): `ACCESS_TTL` 15 phút, `REFRESH_TTL` 8 giờ, `LOCKOUT_MINUTES`
  15, giới hạn theo dải IP 20 lần/10 phút, xác nhận lại 10 phút, cache thu hồi 30 giây.
- **Role từ nhóm AD:** `IT-L1`→l1, `IT-Manager`→manager, `IT-L2`→l2, chỉ `IT-Users`→employee; thuộc hơn
  1 nhóm đặc quyền → 401 (fail-closed) [Suy luận]. Role đổi giữa 2 lần đăng nhập → `role_changed`.
- **Refresh xoay vòng:** mỗi lần refresh tạo dòng `sessions` mới cùng `token_family_id`, dòng cũ
  `revoke_reason='rotated'`; hạn tuyệt đối 8 giờ tính từ lúc đăng nhập (không trượt).
- **Xác nhận lại** (admin revoke): thời điểm đăng nhập = `min(created_at)` của họ token; JWT giữ đúng
  7 claim của P6 (`sub, role, sid, tv, iat, exp, jti`), không thêm `auth_time`.
- **Khoá do dò mật khẩu:** auth ghi `security_events(account_locked)`; dòng `alerts` báo Trưởng BP do
  M9 sinh (P9 luật 3) → Phase 7.
- **`manager_id` có FK:** đồng bộ user thì upsert người quản lý trước (`idp.get_user`, sâu tối đa 5 cấp,
  chặn vòng).
- **Chống dò username:** vẫn đếm lỗi theo `username_attempted` khi user không tồn tại, trả cùng 401;
  mock AD verify hash giả (đã có ở chặng 1).
- Thiếu `JWT_SIGNING_KEY` → route auth trả 503; app vẫn khởi động, `/api/health` vẫn chạy.

**Việc làm (phần C của kế hoạch):**
- `auth/permissions.py`: `PERMS` đúng P6 5.1.
- `auth/ports.py`: `IdentityProvider`, `SecurityEventSink`, `AdUser`.
- `auth/tokens.py`: JWT HS256, 7 claim, khoá ≥ 32 byte, chặn `alg=none`; refresh 256 bit, DB chỉ lưu
  SHA-256; CSRF double-submit (cookie `csrf` + header `X-CSRF-Token` ở `/api/auth/refresh`).
- `auth/mfa.py`: AES-GCM (`MFA_ENC_KEY`), TOTP (pyotp, thời gian lấy từ clock) + CLI như quyết định 2.
- `db/alembic/versions/0002_security_events_mfa_types.py`.
- `auth/service.py`: `login` (8 bước P6 mục 4, thông báo lỗi chung), `refresh`, `logout`, `logout_all`,
  `revoke_user`, `validate_access` (phiên chưa thu hồi, `tv` khớp, status không disabled/terminated;
  cache 30 giây).
- `auth/deps.py`: `current_principal` (Bearer), `require(perm)`; từ chối → `permission_denied` kèm route,
  perm, không kèm dữ liệu.
- `auth/authz.py`: `can_read_ticket` (không quyền → 404), `can_decide_approval` (có quyền, là người được
  giao, phiếu pending, chưa quá hạn, không rơi vào 3 xung đột B15), `can_override`,
  `can_close_escalation`, `can_read_audit`, `scope_tool_target` (D-16).
- `domain/context.py`: `RequesterContext.from_ad(user, now)`.
- `api/auth.py`: `login`, `refresh`, `logout`, `logout-all`, `me`, `POST /api/admin/users/{id}/revoke`
  (manager + xác nhận lại); cookie refresh `HttpOnly; Secure; SameSite=Strict; Path=/api/auth`.
- `audit/security_events.py`: chỉ INSERT, `occurred_at` lấy từ clock.
- `core/logging.py`: filter che chuỗi dạng JWT, `password=…`, cookie refresh.
- `main.create_app` nhận `idp`, `clock`, `sink` để test tiêm vào.

**Test (định nghĩa "xong" của chặng 2):**

| Nguồn | Test |
|---|---|
| P6 test 1 | Quét route (`iter_route_contexts`): mọi route có `require()`, trừ `/api/auth/login`, `/api/auth/refresh`, `/api/health` |
| P6 test 2 | 40 test ma trận (10 chức năng × 4 vai trò, NGU-CANH 2.2) + 2 luật cứng (`policy:edit` ∉ l1, `approval:decide` ∉ l2) |
| P6 test 3 | TC30 qua router trong test: A đọc ticket của B → 404 (giống hệt id không tồn tại); L1-X duyệt phiếu của L1-Y → 403; L2 duyệt → 403 |
| P6 test 4–7, 10 | Thu hồi ≤ 30 giây (FakeClock); terminated → mọi phiên chết; refresh dùng lại → cả họ bị thu hồi; **2 refresh đồng thời → cái thứ hai là reuse**; TC25 khoá 15 phút + `account_locked`; TC24 đúng 1 `login_failed`, không khoá; MFA; CSRF; `role_changed`; canary (không mật khẩu/token trong log và `security_events`) |
| P6 test 8 | Đã có (`test_db_constraints.py`) |
| P6 test 9 | Đã có (chặng 1: test mock + e2e) |
| P7 2.3 / MFA | Migration 0002 upgrade/downgrade; `auth_failures` không đếm 2 loại mới; CLI enroll/reset ghi sự kiện, `detail` không có secret/URI; manager chưa enroll → 401 + `mfa_failed(not_enrolled)` |
| B01 unit | `from_ad`: `tenure_days` đúng; model frozen |
| Cổng 1 | "Ghi audit thiếu trường bắt buộc bị từ chối" — kiểm lại test cũ, thiếu thì thêm |

Khoá JWT, `MFA_ENC_KEY`, token dịch vụ trong test sinh ngẫu nhiên trong fixture; không đọc `.env`.

**Chuyển phase (không phải mốc G — không cần LLM):** P6 test 11 mạo danh qua B1 + M5 (Phase 2/3; chặng 2
chỉ test đăng nhập bỏ qua `role` trong body); test integration B01 (Phase 2); dòng `alerts` khi khoá
(Phase 7, M9); header/CORS/giới hạn kích thước request (Caddy, Phase 7); OWASP ZAP (Phase 7).

**Kiểm cuối Phase 1c (sau chặng 2):** `make lint`, `make test` xanh; `make up` + `/api/health` 200 (có
`mock`), `make seed` OK; thử đăng nhập user demo (cần `.env` có `JWT_SIGNING_KEY`, `SVC_AGENT_TOKEN` —
người tự thêm); đóng Phase 1 trong PROGRESS; mục "người xác nhận gọi tay 12 tool" (bảng ở README mock)
vẫn cần người khác làm.

## Phase 1c — chặng 2: kết quả (26/09/2026)

**Đã làm** (theo kế hoạch trên, không commit):
- `backend/app/auth/`: `permissions.py` (PERMS P6 5.1, `ADMIN_REVOKE_ROLES`), `models.py`, `ports.py`
  (`IdentityProvider`, `SecurityEventSink`, `AdUser`, **`AuthStore`**), `tokens.py`, `mfa.py` (+ CLI),
  `store.py` (`SqlAuthStore`), `service.py` (login 8 bước, refresh, logout, logout-all, revoke,
  `validate_access`), `deps.py` (`current_principal`, `require`), `authz.py` (`can_*`, `scope_tool_target`).
- `domain/context.py`: `role_from_groups`, `RequesterContext.from_ad`. `audit/security_events.py`
  (`SecurityEventWriter`, `check_event`). `api/auth.py` (6 route). `core/logging.py` (`redact`,
  `RedactSecretsFilter`). `tools/adapters/ad_read.py`: `AdIdentityProvider`. `main.create_app` nối tất cả,
  nhận `idp`/`store`/`sink`/`clock` để test tiêm vào. `settings.py`: 7 tham số auth (env, có mặc định).
- Migration `0002_security_events_mfa_types.py`; `SECURITY_EVENT_TYPES` + `AUTH_FAILURE_TYPES` ở `db/models.py`.
- `.env.example`: mục "Xác thực (P6)" (tham số tùy chọn + lệnh enroll MFA).
- Test mới — unit: `test_auth_{permissions,tokens,mfa,login,sessions,idor,route_scan,store_memory,redaction}.py`,
  `test_authz.py`, `test_domain_context.py`, `test_ad_identity_provider.py`; bộ hợp đồng chung
  `auth_store_contract.py`; bản giả `tests/fakes/auth.py`; helper `auth_helpers.py`. Integration:
  `test_auth_store_sql.py` (cùng bộ hợp đồng trên Postgres), `test_migration_0002.py`, `test_mfa_cli.py`,
  `test_auth_http_sql.py` (luồng đầy đủ trên Postgres, gồm 2 refresh đồng thời thật), thêm 4 test Cổng 1
  "ghi audit thiếu trường bắt buộc bị từ chối" vào `test_db_constraints.py` (trước đó **chưa có**).
  `tests/integration/pg.py`: `fresh_database()` — DB trống riêng cho test ghi `mfa_*`. E2E: thêm
  `test_identity_provider_against_mock_ad` vào `test_tools_vs_mock.py`.

**Kết quả kiểm (26/09/2026, trong sandbox Claude Code):**

| Lệnh | Kết quả |
|---|---|
| `make lint` | **Xanh** — ruff, mypy `backend/app` (67 file), mypy mock, 5 hợp đồng import-linter, gitleaks detect 28 commit không leak; `gitleaks dir` trên `backend/app`, `backend/tests`, `mock_services`: không leak (bản đầu có 1 chuỗi JWT giả trong test → đã đổi sang sinh lúc chạy) |
| unit backend | **1137 passed** (963 cũ + 174 mới, gồm test hồi quy cookie và test chuẩn hoá UTC) |
| test mock | **86 passed** |
| integration (53 test, testcontainers) | **Xanh** — `make test` lần 2 (người chạy ngoài sandbox, 26/09/2026); gồm bộ hợp đồng AuthStore trên Postgres (có test UTC), migration 0002, CLI MFA, luồng auth đầy đủ trên Postgres |
| e2e (25 test) | **Xanh** — cùng lần chạy trên (gồm `AdIdentityProvider` với mock AD thật) |
| `make test` đầy đủ | **Xanh** (lần 2, sau sửa bug cookie/UTC): backend **1215 passed** (1137 unit + 53 integration + 25 e2e) + mock **86 passed** |
| `make up` + `/api/health` | **Xanh** (người chạy, 26/09/2026): build image mới (có `pyjwt`, `pyotp`, `cryptography`); `alembic upgrade head` chạy `0001 -> 0002` trên volume cũ; mock `/health` ok; `make seed` 16 người, 7 thiết bị; `/api/health` = `{"status":"ok","checks":{"db":"ok","qdrant":"ok","mock":"ok"}}` |
| Đăng nhập user demo trên stack thật | **Xanh** (người chạy `curl`, 26/09/2026): `POST /api/auth/login` `an.nv` → có `access_token` (JWT HS256, payload `sub=nv001`, `role=employee`) — backend gọi mock AD thật (argon2id) bằng `SVC_AGENT_TOKEN`, ký bằng `JWT_SIGNING_KEY` của `.env` |

**`make test` lần 1 (người chạy ngoài sandbox, 26/09/2026): 3 failed, 1206 passed** — 2 nguyên nhân:
- **Bug thật trong code:** mốc thời gian đọc từ Postgres mang tzinfo `ZoneInfo("Etc/UTC")`, không phải
  `timezone.utc`; `Response.set_cookie(expires=…)` của Starlette từ chối → `/api/auth/refresh` trả 500 trên DB
  thật. Unit không bắt được vì store in-memory giữ UTC của FakeClock — đúng lý do cần test SQL. Sửa: chuẩn
  hoá `astimezone(UTC)` trong `api/auth._set_cookies`; thêm unit hồi quy `test_cookie_expiry_accepts_postgres_timezone`
  (đã kiểm: bỏ fix → test đỏ).
- **Bug của test:** `test_migration_0002` đọc `alembic_version` bằng `app_rw` — role này (đúng thiết kế) không
  có quyền trên bảng đó; đổi sang `app_migrate`. Kèm sửa cảnh báo pytest (fixture scope class viết dạng
  method → fixture module). Sau sửa: `make lint` xanh, unit **1133 passed** — chờ người chạy lại `make test`.

**Bổ sung theo yêu cầu người (26/09/2026, sau `make test` lần 1):** `SqlAuthStore` chuẩn hoá MỌI datetime trả
về thành `tzinfo=timezone.utc` (`store._utc`; DB trả naive → `ValueError`); bản giả in-memory làm y hệt khi
đọc. Bộ hợp đồng thêm `test_every_returned_datetime_is_timezone_utc`: đầu vào cố ý mang múi giờ
`Asia/Ho_Chi_Minh`, soi mọi đường trả về (`get_user`, `get_user_by_username`, `upsert_user`, `get_session`,
`get_session_by_refresh_hash`, sau `rotate`/`revoke`, `login_started_at`) — `assert_utc` duyệt mọi trường
datetime của dataclass nên trường mới cũng bị soi. Thêm `test_auth_store_sql_mapping.py` (unit, không cần
Postgres) kiểm ánh xạ dòng của `SqlAuthStore` với giá trị `ZoneInfo("Etc/UTC")` như psycopg trả. Bản sửa ở
`_set_cookies` giữ nguyên làm lớp thứ hai. Mutation: bỏ chuẩn hoá ở bản giả → test hợp đồng đỏ; bỏ ở
`SqlAuthStore._utc` → 3 test ánh xạ đỏ. `make lint` xanh, unit **1137 passed**, mock 86 passed; phần hợp đồng
trên Postgres chạy trong `make test` (chưa chạy lại).

**Mutation check (sửa hỏng code rồi chạy test, sau đó khôi phục):** bỏ khoá cửa sổ trượt; rotate không
nguyên tử; `require` bỏ kiểm perm; bỏ filter che log; bỏ che ở formatter; bỏ kiểm `iat`; cache thu hồi
không hết hạn; bỏ kiểm `tv`; bỏ kiểm role claim; bỏ phát hiện reuse; hạn refresh trượt → **đều có test
đỏ**. Lần đầu có 4 đột biến sống (`require` bỏ kiểm perm, bỏ filter, bỏ formatter, bỏ `tv`/role) vì lớp
khác che hộ → đã thêm test riêng cho từng lớp. Test quét route bản đầu **không tìm thấy route nào** (FastAPI
0.141 bọc router thành `_IncludedRouter`) — nó chỉ không đỏ oan nhờ có assert "danh sách route không rỗng";
đã chuyển sang `fastapi.routing.iter_route_contexts`.

**Quyết định khi hiện thực — người đã duyệt 26/09/2026** (đánh số theo kế hoạch Plan Mode):
1. Port `AuthStore` + bản in-memory; một bộ test hợp đồng chạy trên cả in-memory (unit) và Postgres (integration).
2. Bảng nhóm AD → role ở `domain/context.py`; >1 nhóm đặc quyền hoặc không nhóm nào đã biết → từ chối
   (login 401 + `permission_denied(reason=role_unmappable)`; `from_ad` → `DomainError`).
3. `authenticate` gọi thẳng `/ad/authenticate` 1 lần, không retry, không qua ToolRegistry (không phải tool
   P5; mật khẩu không vào input/span registry). `get_user` qua registry `ad_get_user`, `caller_step="B1"`.
4. `require()` = chỉ cần đăng nhập; admin revoke = `require(roles=ADMIN_REVOKE_ROLES, recent_login=True)`,
   hằng ở `permissions.py`, có test; không thêm permission mới.
5. Username chưa có dòng `users` → khoá theo cửa sổ trượt (≥ 5 lỗi/10 phút); phản hồi **giống hệt** user thật
   bị khoá (status + body + không set-cookie) — có test.
6. Giới hạn dải IP đếm lượt thất bại (`auth_failures` theo `ip_prefix`), 429 không ghi sự kiện.
7. Mỗi lần thử khi đang khoá ghi `account_locked`, `detail.reason` = `threshold` | `still_locked`.
8. Role đổi khi đăng nhập → `role_changed` + tăng `token_version` + thu hồi phiên (`admin`).
9. Cookie `refresh` HttpOnly/Secure/Strict/`Path=/api/auth`; `csrf` không HttpOnly, `Path=/`.
10. `exp`/`iat` kiểm theo clock tiêm vào; pyjwt vẫn kiểm chữ ký, thuật toán (chỉ HS256), claim bắt buộc;
    test: exp quá hạn, iat tương lai, `alg=none`, HS512 cùng khoá, sai khoá, sửa payload, claim thừa/thiếu → 401.
11. Test ghi `mfa_*` chạy trên DB riêng (`fresh_database`).
12. Người quản lý không có trong AD / không ánh xạ được role / quá 5 cấp / vòng → `manager_id = NULL`.

Chi tiết nhỏ khác (không đổi đặc tả): thiếu OTP khi cần MFA → 401 `mfa_required`, **không** ghi `mfa_failed`
(bước 1 của form 2 bước); OTP sai → `mfa_failed(invalid_otp)` và tính vào ngưỡng khoá (view `auth_failures`
đếm cả `mfa_failed`); manager chưa enroll → 401 `mfa_not_enrolled` + `mfa_failed(not_enrolled)`. Tài khoản
disabled/terminated → 401 chung + `login_failed(reason=account_inactive)` + thu hồi mọi phiên
(`user_disabled`). CLI MFA là điểm nối riêng nên import `audit`/`store` muộn trong `_run` (giống `main`).
`security_events.detail` bị chặn nếu tên khoá có phần `password|token|secret|otp|uri|key|cookie|csrf|…`
hoặc giá trị trông như JWT. Refresh không tính là đăng nhập lại (xác nhận lại dùng `min(created_at)` của họ).

**Ràng buộc chuyển cho phase sau (người yêu cầu ghi, 26/09/2026):**
- **Phase 7 (Caddy):** sau proxy, `request.client.host` là IP của Caddy → chỉ tin `X-Forwarded-For` khi request
  đến từ Caddy (danh sách proxy tin cậy); nếu không, giới hạn dải IP sẽ gộp mọi người vào một dải.
- **Phase 7 (M9, P9 luật 3):** cảnh báo khoá tài khoản chỉ sinh khi `account_locked.detail.reason = "threshold"`,
  không sinh cho `still_locked` (tránh spam mỗi lần thử khi đang khoá).
- **Phase 3–4 (M5/B15):** `users.manager_id = NULL` / `RequesterContext.manager_id is None` nghĩa là **"không
  biết"**, không phải "không có sếp" → không được khớp luật `allow` (R09, xung đột `boss_of_approver` ở B15);
  phải đi phê duyệt (giảm False Negative).

**Đóng Phase 1 (26/09/2026):** mọi mục tự động của cổng xanh (bảng trên). Còn mở:
- Thủ công (thuộc cổng 1): người gọi tay 12 tool với seed, đối chiếu `mock_services/README.md` — có chặn Phase 2 hay không do người quyết.
  **→ Người quyết (26/09/2026): không chặn Phase 2; đây là mục duy nhất còn lại của Phase 1.**
- ~~Chưa commit chặng 2~~ — đã commit `62b0d0e`.
- **CI GitHub xanh:** run `36195560365` (commit `62b0d0e`, 26/09/2026) — Phase 1 đóng, chỉ còn mục "người khác gọi tay 12 tool".
- P6 mục 11: D-01 (TC24/TC25 viết lại) cần nhóm xác nhận và báo GVHD.

## Phase 2 — chặng 2a: runtime LangGraph (P1) — 26/09/2026, đã duyệt

Kế hoạch Plan Mode đã duyệt (chia 2 chặng; 2b = B1 thật, B20 thật, dịch vụ ticket tối thiểu — chỉ làm
sau khi người duyệt 2a). Không LLM, không đọc `.env`, **không commit**.

**Đã làm:**
- `backend/app/graph/`: `context.py` (RunContext qua contextvar — `turn_id` ở đây là nguồn khoá
  idempotent), `goto.py`, `effects.py`, `boundary.py`, `tracing.py`, `routing.py` (`ROUTES`, `WAIT_NODES`),
  `builder.py` (`build_graph`, `fake_nodes`), `checkpoint.py` (serde có allowlist kiểu Pydantic,
  `open_postgres_saver`), `lock.py` (`PgTicketLock`), `runner.py`, `late_event.py` (`deliver_event`,
  `wake_parent`, `LateEvent` 409), `worker_jobs.py`, `ports.py`, `fakes.py` (phụ thuộc của node giả),
  `wiring.py`; `nodes/` 16 node **giả** (bảng dưới).
- `audit/writer.py` (`AuditWriter`, `check_audit_row`); `db/runtime.py` (store SQL `side_effects`, `turns`,
  `spans`, `wait_deadlines` + đọc hạn `approvals`, `current_tx()`).
- Migration `0003_langgraph_checkpoint`: `PostgresSaver.setup()` trên kết nối autocommit riêng dưới
  `app_migrate` (setup có `CREATE INDEX CONCURRENTLY`), `GRANT` CRUD 4 bảng checkpoint cho `app_rw`;
  downgrade DROP 4 bảng. `alembic/env.py` bỏ qua bảng checkpoint khi so metadata.
- `domain/ticket_state.py`: thêm `escalation_note`, `escalation_reason_detail` (D-27), `aggregate_status`
  (D-30) — **đã kiểm: LangGraph 1.2 bỏ IM LẶNG key không khai báo trong state**, thiếu thì ghi chú E9 mất.
- `core/hashing.py`: `sha256_key`. `settings.py`: `graph_recursion_limit` 60, `checkpoint_pool_size`,
  4 tham số worker (quét hạn 15 giây, quét lượt dở 60 giây, lượt mở quá 120 giây, batch 200).
- `worker.py`: APScheduler chạy 2 job + recover một lần lúc khởi động; runner `can_execute=False`.

**Node (tên theo mã giả các file nhánh; bước con nằm trong node như đặc tả):** `b01_identity` (B1),
`b02_screen` (B2), `b03_classify` (B3–B5), `b06_diagnose` (B6–B7), `b08_retrieve` (B8–B9), `b10_route`
(B10), `b11_slots` + `clarify_wait` (B11), `b12_assess` (B12–B14), `b15_prepare_approval` (B15),
`approval_wait` (B16), `b17_execute` (B17–B18), `confirm_wait` (B19), `parent_wait` + `parent_reply_wait`
(B5 cha, D-31), `b20_audit` (B20, giả: chỉ kết thúc thread). Kết quả của node giả chọn qua `FakeScenario`
(mặc định: đường vui dừng ở chờ duyệt); việc trước khi chờ nằm ở node đứng trước, qua `effects.once`.

**Quyết định khi hiện thực (trong phạm vi kế hoạch đã duyệt):**
1. `goto` là `async` (ghi DB). Cấm 4 đầy đủ: sang `S_RESOLVED` thì `AuditSink.record` kiểm dòng audit
   (khoá idempotent) tồn tại **trong cùng transaction** với INSERT; không có → `IllegalTransition(F4)`.
2. Boundary: exception ở node khi trạng thái đã kết thúc/đã escalate (chỉ xảy ra ở `b20_audit`) — không còn
   chuyển hợp lệ → ghi audit `unhandled_exception` + kết thúc thread (không ném, worker không sập).
3. `GraphRecursionError` → runner bẻ luồng `S_ESCALATED` E9 (`step="runner"`, `event="recursion_limit"`)
   qua `goto` + `aupdate_state`, rồi chạy B20.
4. **Worker không có SVC_EXECUTOR_TOKEN (đã chốt):** recover mà bước kế tiếp là `b17_execute` → không thực
   thi, `goto` E7 (`event="execution_interrupted"`, `escalation_reason_detail="execution_interrupted"`,
   ghi chú "Thực thi bị gián đoạn — cần L2 kiểm tra…") rồi B20. Runner của backend (`can_execute=True`)
   vẫn chạy lại B17 như P1 mục 7 (B17 thật tự chặn bằng `transaction_log begun` — Phase 3).
5. Đã kiểm với LangGraph 1.2: giá trị `Command(resume=…)` được ghi vào checkpoint trước khi node chạy →
   process chết giữa lượt resume thì `recover` = `ainvoke(None)` chạy lại node chờ với đúng giá trị đó.
6. Recover giữ `turn_id` và chỉ đóng dòng `turns` cũ — `turn_id` là khoá chính nên
   `turns.event_type='recover'` không được dùng.
7. `late_event`: `step` = bước của trạng thái chờ mà sự kiện nhắm tới (B11/B16/B19), `turn_id` NULL, không
   khoá idempotent, `detail = {expected_status, actual_status, event_kind, source}`, **`source` = `user` |
   `worker`** (bổ sung của người khi duyệt). Sai loại sự kiện → `InvalidEvent` (API → 422, 2b).
8. Worker quét hạn: đọc hạn không khoá → `deliver_event(timeout, source="worker")` → đánh dấu `fired_at`
   (cả khi 409); ticket bận → để chu kỳ sau. Hạn duyệt: sau 409 đặt `approvals.status='timeout'` để không bắn
   lại. `deadlines.set` thay (đánh dấu đã bắn) hạn cũ chưa bắn của cùng ticket + kind — không để hạn vòng hỏi
   trước cắt ngang vòng sau.
9. Thứ tự bọc: `traced(with_error_boundary(fn))` — span ghi cả `interrupted`; boundary đánh dấu span `error`
   + traceback ≤ 4 KB khi nuốt exception.

**Hoãn (người đã duyệt 26/09/2026):**
- TC34–36, ticket cha 3 con, TC32/"con E1 tức thì" (P1 mục 11) → **Phase 5** cùng B05 (`child_notices`,
  `compose_digest`, `aggregate_children`, `finalize_once`). 2a chỉ có node cha giả + `wake_parent` + routing.
- Test tải 8 graph × LLM chậm 10 giây + `pg_stat_activity` (P1 mục 11) → `backend/tests/load/`, ngoài `make test`.
- Nhắc duyệt 50%/80% → Phase 4 (cần `notify_approver` thật).

**Ghi nhận cho phase sau (người yêu cầu ghi, 26/09/2026):**
- **2b:** tin trả lời người dùng nằm trong `conversation`/checkpoint — **không thêm bảng**.
- **Phase 4 cần bảng `notifications`** (P10 "Phải có": `GET /api/me/notifications`; P1 5.3 và B15 cũng nhắc)
  — không có trong 22 bảng P7 → thêm bằng **migration mới + cập nhật P7, chốt trước Phase 4**.
- Nâng `langgraph-checkpoint-postgres`: số migration checkpoint đổi → test đỏ "cần migration Alembic mới"
  (unit so `KNOWN_CHECKPOINT_MIGRATIONS` của 0003; integration so số dòng `checkpoint_migrations`).
- **Phase 3 (B06, B11):** node thật thay node giả phải giữ `goto(state, S_X, next_node="…")` với hằng
  (test tĩnh AST suy trạng thái vào từ các goto khác).

**Test mới:**

| File | Nội dung |
|---|---|
| `unit/test_graph_goto.py` | 14×14 cặp × (thường/cha): goto ⇔ bảng chuyển, bị chặn thì không ghi audit; 5 chuyển cấm có ca riêng + F4 (audit không ghi được → chặn; chạy lại có dòng cũ → qua); FORBIDDEN thắng bảng; `B11/user_replied` + `B11/action_built` → 2 dòng; khoá theo turn/loop_seq; cờ D-20; cột audit từ `risk` |
| `unit/test_graph_effects.py` | `once` chạy lại → 1 lần, ref cũ; `sub`/loop/turn khác → lần mới; fn lỗi không ghi, thử lại được; kind lạ |
| `unit/test_graph_static.py` | AST: đích ⊆ ROUTES; trạng thái vào suy từ goto → mọi cặp qua `is_allowed` (chỉ D-20 cần cờ); mọi node tới `b20_audit`, không node mồ côi; 16 node đều `traced` ngoài `boundary` |
| `unit/test_graph_runtime.py` | cổng 2 (dừng → restart → resume, cả 3 trạng thái chờ); sự kiện muộn 6 cặp chờ × chờ + sau khi đóng → 409, state không đổi, 1 dòng `late_event`; duyệt sau hết hạn → 409, không thực thi; đếm thông báo; **process chết sau `approval_create` → worker recover → 1 phiếu, 1 thông báo, giữ turn_id**; worker recover trước B17 → E7, không thực thi (đối chứng backend chạy lại); TC29 + 10 ticket song song; lỗi B1/B2/B20; boundary không nuốt `GraphInterrupt`; recursion → E9; span; 2 sự kiện đồng thời → 1 lần chạy; `wake_parent`; vòng cha giả |
| `unit/test_graph_worker.py` | hạn clarify → E4 (bắn 1 lần), duyệt → E6 + phiếu `timeout`, confirm → tự đóng 48h; timeout sau khi ticket đã đi tiếp → `late_event source=worker`; hạn vòng mới thay hạn cũ; mục lỗi không chặn mục khác; ticket bận → chu kỳ sau |
| `unit/test_checkpoint_schema.py` | số migration checkpoint của bản cài == 0003; 3 danh sách bảng checkpoint khớp; serde không cảnh báo kiểu chưa đăng ký |
| `integration/test_graph_pg.py` (12) | `checkpoint_migrations` == thư viện; `app_rw` không tạo được bảng, CRUD được bảng checkpoint; cổng 2 trên `AsyncPostgresSaver` qua 3 lần mở lại runtime + mỗi ticket 1 thread; sự kiện muộn 3 trạng thái chờ; **giết process thật** (`subprocess` + `os._exit` sau `approval_create`) → recover; worker không thực thi B17; TC29 + 10 song song (span error có traceback); 2 "process" giao sự kiện đồng thời với `pg_advisory_lock` thật; `lock_timeout` → `TicketBusy`; worker quét `wait_deadlines`/`approvals` thật |
| `integration/test_migration.py` | tách 22 bảng nghiệp vụ với 4 bảng checkpoint; so metadata bỏ qua bảng checkpoint; **mới** 0003 hạ/nâng lại + grant `app_rw` |
| `integration/test_migration_0002.py` | nâng tới `0002` thay vì `head` (head nay là 0003) |

**Kết quả kiểm (26/09/2026, trong sandbox Claude Code):**

| Lệnh | Kết quả |
|---|---|
| `make lint` | **Xanh** — ruff, mypy `backend/app` (101 file), mypy mock, 5 hợp đồng import-linter, gitleaks 29 commit không leak; `gitleaks dir` trên thư mục mới: không leak |
| unit backend | **1221 passed** (1137 cũ + 84 mới) |
| test mock | **86 passed** |
| integration (13 mới + sửa `test_migration*`) | **Xanh** — người chạy `make test` ngoài sandbox (26/09/2026): 66 integration (53 cũ + 12 `test_graph_pg.py` + 1 test 0003), gồm test giết process thật |
| `make test` đầy đủ | **Xanh** (người chạy, 26/09/2026): backend **1312 passed** (1221 unit + 66 integration + 25 e2e) + mock **86 passed** |
| `make up` | **Xanh** (người chạy, 26/09/2026): build lại image backend; `alembic upgrade head` chạy `0002 -> 0003` trên volume cũ; `make seed` 16 người, 7 thiết bị; `/api/health` = `{"status":"ok","checks":{"db":"ok","qdrant":"ok","mock":"ok"}}`. `docker compose ps worker` = `Up 6 minutes` — qua nhiều chu kỳ quét 15 giây và 60 giây (worker dựng runtime + pool checkpoint bằng `app_rw` không sập). Log 30 dòng cuối: `scan_deadlines` mỗi 15 giây, `scan_stale_turns` mỗi 60 giây đều `executed successfully` (~5–35 ms), không có dòng ERROR/traceback. DB chưa có ticket nào nên lượt quét không giao sự kiện nào — đường giao timeout/recover thật đã phủ ở `test_graph_pg.py` |
| Mutation check | Sửa hỏng rồi khôi phục 11 chỗ, **đều có test đỏ**: bỏ re-raise `GraphInterrupt`, bỏ kiểm cấm 4, bỏ `check_transition`, bỏ `once` (gọi thẳng), worker recover chạy B17, resume không cập nhật `turn_id`, bỏ guard trạng thái chờ, `source` luôn `user`, span `interrupted` sai, worker không đánh dấu `fired_at`, hạn cũ không bị thay. (Lần chạy đầu cho kết quả sai do `.pyc` cũ cùng kích thước + cùng giây mtime — đã xoá `__pycache__`, chạy lại với `PYTHONDONTWRITEBYTECODE=1`.) |

**Bổ sung trước khi commit 2a (người yêu cầu khi duyệt, 26/09/2026):**
1. `core/logging.py`: `QUIET_LOGGERS` — logger `apscheduler` hạ xuống WARNING (trước đó ~10 dòng INFO/phút ở
   worker). Log `app.*` vẫn INFO; lỗi job vẫn hiện (job tự `log.exception`).
2. **Heartbeat worker — file, không bảng** (không thêm bảng ngoài P7): `app/heartbeat.py`. Worker ghi thời
   điểm vào `WORKER_HEARTBEAT_PATH` (mặc định `/tmp/servicedesk-worker.heartbeat`) mỗi
   `WORKER_HEARTBEAT_SECONDS` (10 giây) bằng CHÍNH APScheduler chạy job quét, và một lần lúc khởi động; ghi
   nguyên tử (file tạm + rename). `python -m app.heartbeat`: thiếu file / hỏng / cũ hơn
   `WORKER_HEARTBEAT_MAX_AGE` (60 giây) → thoát 1. Settings chặn nhịp > MAX_AGE/3.
   `docker-compose.yml` worker: healthcheck gọi lệnh đó (interval 5s, timeout 5s, retries 1, start_period 20s).
   `Makefile up`: sau `make seed` chờ worker `healthy` tối đa 60 giây; quá hạn in trạng thái + 30 dòng log
   worker, `exit 1`. `worker.py` tách `schedule_jobs` để test không cần DB.
   *Giới hạn đã biết:* heartbeat chứng minh event loop + scheduler còn chạy, không chứng minh từng lượt quét
   thành công (job lỗi vẫn được bắt và log, không làm heartbeat ngừng).
3. Test `unit/test_worker_heartbeat.py` (12): ngưỡng 60 giây, file thiếu/hỏng/thiếu múi giờ, ghi nguyên tử,
   biên nhịp/MAX_AGE, `schedule_jobs` có job heartbeat, **APScheduler thật nhịp 0,05 giây làm mới file**,
   healthcheck compose + vòng chờ trong `make up` (đọc file cấu hình), mức log apscheduler.
   **Mutation — 6/6 đỏ:** tắt job heartbeat (2 test đỏ); job không ghi file; bỏ ngưỡng 60 giây; healthcheck
   không đọc heartbeat; `make up` không in log worker; không hạ log apscheduler.

**Kết quả kiểm cuối 2a:**

| Lệnh | Kết quả |
|---|---|
| `make lint` | **Xanh** (sandbox) — ruff, mypy 102 file, mypy mock, 5 hợp đồng, gitleaks không leak |
| unit backend | **1233 passed** (sandbox; 1221 + 12 heartbeat) |
| `make test` | **Xanh** (người chạy, trước phần heartbeat): 1312 + mock 86. Sau heartbeat chỉ đổi 1 dòng import ở `test_migration.py` — integration chưa chạy lại, CI sẽ chạy |
| `make up` | **Xanh** (người chạy, 26/09/2026, sau phần heartbeat): `worker: healthy`, rồi `/api/health` ok (db, qdrant, mock) |
| CI GitHub | **Xanh** — run `36226646863` (commit `9b310d4`, push `dev-tuananh`, 26/09/2026): `make lint` + `make test` đầy đủ trên ubuntu, gồm integration sau lần đổi import và test giết process |

## Phase 2 — chặng 2b: kế hoạch đã duyệt (26/09/2026)

Làm 4 bước; mỗi bước: `make lint` + unit, người chạy `! make test` nếu cần Docker, dừng chờ duyệt, commit
riêng (tiếng Việt không dấu). 2b-1 = B1 thật + cảnh báo dò mật khẩu; 2b-2 = B20 thật + hàng đợi L2; 2b-3 =
dịch vụ ticket + route sự kiện + nối `create_app`; 2b-4 = stack thật (timeout/recover) + cổng 2.

**Quyết định của người (trả lời Q1–Q7, 26/09/2026):**
1. **Q1 cảnh báo dò mật khẩu:** một hàm ghi idempotent (`audit/alerts.py`), gọi từ auth lúc khoá và từ B1;
   khoá chống trùng PHẢI có người dùng → migration 0004 thêm `alerts.subject`, khoá `(rule_id, subject,
   window_start)` (gộp cảnh báo 2 người = False Negative an ninh). Cảnh báo E0/E7/E9 ở B20 bước 6 → M9 Phase 7
   (P9 luật 2, 4).
2. **Q2 privacy guard (2b-3):** port `PrivacyGuard`; `NotRedactingGuard` chỉ nạp khi `APP_ENV ∈ {dev, test}`,
   env khác → app từ chối khởi động. Có test.
3. **Q3 route duyệt (2b-3):** làm; quyết định duyệt đi qua `deliver_event` (mong đợi `S_PENDING_APPROVAL`; quá
   hạn / duyệt lần 2 → 409 + `late_event`). `FAKE_APPROVER_ID` cùng luật fail-closed như Q2.
4. **Q4:** mọi E5 là deny case (`is_deny_case`).
5. **Q5:** 2b kiểm 6/8 `close_reason`. "Ghi một lần" hiểu **theo từng cột**; L2 đóng = `UPDATE tickets SET
   close_reason = … WHERE close_reason IS NULL AND final_state = 'S_ESCALATED'` (Phase 7) — sinh
   `resolved_after_escalation`, `resolved_after_deny_review`.
6. **Q6 lỗi ở B20 (2b-2):** boundary ở B20 ghi audit `unhandled_exception` rồi ném tiếp → lượt không đóng →
   worker recover chạy lại B20 (chỉ ghi phần thiếu). **Giới hạn:** thất bại 3 lần cho cùng một lượt → worker
   ngừng thử, ghi audit `finalize_failed_permanent` kèm chi tiết. **Phase 7 (M9): thêm luật cảnh báo cho event
   `finalize_failed_permanent`.** Test: bug cố định → đúng 3 lần thử, 1 dòng, rồi dừng.
7. **Q7:** đồng ý mặc định (`total_turns` = số dòng `turns`; `total_duration` = `closed_at − created_at`;
   `auto_closed`; AD 404 → `S_BLOCKED invalid_credentials`; non-owner đọc được → 403, không đọc được → 404),
   trừ:
   - Role không ánh xạ được → **`S_ESCALATED` E2, `reason_detail=role_unmappable`** (lỗi cấu hình, không phải
     lỗi người dùng; không bao giờ mặc định employee).
   - `resolution_path`: đối chiếu CHECK trong P7 trước khi code (2b-2).
   - `TicketBusy`: đang giữ khoá → 503 + `Retry-After`; lượt trước đã xong, trạng thái không còn chờ → 409.
     Test điều khiển thứ tự bằng Event, không dựa vào sleep.
   - **Lệch mã giả B20 (ghi theo yêu cầu):** `wake_parent` gọi **sau khi nhả khoá** của ticket con (runner),
     không gọi trong B20 — gọi trong B20 có thể deadlock (con giữ khoá con chờ khoá cha, cha chuyển sự kiện
     xuống con). **Việc Phase 5:** worker đối soát ticket cha đang ở `parent_wait` khi mọi con đã có
     `final_state` (trường hợp mất tín hiệu wake).

**Đặc tả — ĐÃ ĐỒNG BỘ (người sửa `docs/spec`, 26/09/2026; Claude đối chiếu với code 2b-1: khớp):** `decisions.md` mục 4.1 (2b-Q1…2b-Q7), P7 bản 1.6 (mục 2.12, tiêu chí 10), P9 bản 1.3 (bảng `subject` 14 luật), B01 bản 1.2 (mục 5.1), B20 bản 1.4 (mục 5.1). Việc đã yêu cầu:
- P7: thêm mục 2.12 (migration 0004: `alerts.subject VARCHAR(64) NOT NULL DEFAULT ''`, bỏ UNIQUE
  `(rule_id, window_start)`, thêm UNIQUE `(rule_id, subject, window_start)`) + nhật ký bản 1.6.
- P9 mục 6: khoá chống trùng thành `(rule_id, subject, window_start)`; ghi `subject` cho từng luật (luật theo
  người → user_id, theo ticket → ticket_id, tổng hợp → '').

## Phase 2 — 2b-1: B1 thật + cảnh báo dò mật khẩu (26/09/2026, `make test` xanh, chờ duyệt commit)

**Đã làm:**
- `graph/nodes/b01_identity.py` — B1 thật theo B01 mục 5: phiên → `ad_get_user` qua ToolRegistry thật
  (`caller_step="B1"`, retry + breaker) → khoá → disabled/terminated → role → `RequesterContext.from_ad`.
  AD lỗi/breaker mở → E2 `identity_unverifiable` (không E9); AD 404 → `invalid_credentials` (`user_not_found`);
  role không ánh xạ được → E2 `role_unmappable` (Q7). B1 không đọc `redacted_request`, không import `app.llm`.
- `db/identity.py` — `SqlIdentityReads`: `active_session`, `locked_until` (chuẩn hoá UTC).
- `domain/alerts.py` — `AlertDraft`, `bruteforce_alert` (rule `password_bruteforce`, `subject` = user_id; username
  chưa có dòng `users` → `username:<tên>`, dài quá 64 ký tự thì băm — không cắt cụt để khỏi gộp), severity
  `critical`. `window_start` = thời điểm bắt đầu khoá: auth lấy lúc khoá, B1 lấy `locked_until − LOCKOUT` →
  cùng khoá. **Đánh đổi đã chấp nhận:** đổi `LOCKOUT_MINUTES` giữa một đợt khoá thì B1 tính ra khoá khác
  auth → thêm một cảnh báo thừa (False Positive, chấp nhận; không bao giờ mất cảnh báo).
- `audit/alerts.py` — `AlertWriter.raise_once` (`ON CONFLICT (rule_id, subject, window_start) DO NOTHING`),
  `check_alert` (chặn `detail` có khoá nhạy cảm/giá trị giống JWT — tách `check_detail` dùng chung với
  `security_events`).
- Migration `0004_alerts_subject.py` + `models.Alert.subject`; downgrade dừng rõ ràng nếu đã có hai dòng cùng
  `(rule_id, window_start)` khác `subject`. **Cột `subject` KHÔNG có DEFAULT** (người yêu cầu, 26/09/2026):
  DEFAULT '' chỉ dùng lúc ADD COLUMN để điền dòng cũ rồi `DROP DEFAULT` ngay — INSERT quên `subject` phải lỗi
  (M9 Phase 7 viết SQL cho 14 luật; quên subject = gộp cảnh báo = False Negative). Luật tổng hợp truyền
  `SYSTEM_SUBJECT = ""` (hằng ở `domain/alerts.py`) tường minh.
- Auth: port `AlertSink` (`auth/ports.py`); `AuthService._check_threshold` ghi cảnh báo khi khoá (`threshold`),
  không ghi khi `still_locked`. `main.create_app(alerts=…)` để test tiêm.
- `graph/ports.py` thêm `IdentityReads`, `ToolCaller`, `AlertSink`; `NodeDeps` thêm `identity`, `directory`,
  `alerts`, `lockout`; `graph/wiring.open_runtime` dựng registry đọc (hoặc nhận `directory` để dùng chung
  breaker), thiếu `SVC_AGENT_TOKEN` → `UnconfiguredDirectory` (B1 → E2, runtime vẫn lên).

**Quyết định khi hiện thực:**
- **Phiên = họ token — người đã duyệt (26/09/2026):** mỗi lần refresh tạo dòng `sessions` mới và thu hồi dòng cũ (`rotated`);
  ticket giữ `session_id` lúc tạo. Nếu B1 chỉ xét đúng dòng đó, một lần refresh bình thường làm ticket bị
  chặn `invalid_credentials`. B1 coi phiên còn hiệu lực ⇔ **họ token còn ít nhất một dòng chưa thu hồi, chưa hết
  hạn**. Logout, logout-all, admin revoke, reuse, user bị vô hiệu hoá đều thu hồi dòng đang sống → hết hiệu lực.
- Thứ tự kiểm theo đúng B01 mục 5: khoá dò mật khẩu **trước** disabled — người vừa bị khoá vừa bị vô hiệu hoá
  vẫn được báo là sự cố an ninh (có test).

**Test mới / sửa:**

| File | Nội dung |
|---|---|
| `unit/test_b01_identity.py` (24) | phiên hợp lệ → `S_SCREENING` + ngữ cảnh đúng AD, `tenure_days`, frozen; nhóm IT-L1 → l1; mạo danh "tôi là quản trị viên" → employee (P6 test 11 phần B1); AST: B1 không đọc `redacted_request`, không import llm; phiên không có/None/thu hồi/hết hạn → `invalid_credentials`, không gọi AD, không cảnh báo; xoay vòng refresh vẫn hợp lệ, logout thì hết; AD timeout → E2 (3 lần gọi, backoff 1s 2s), không E9; breaker mở → E2 không gọi AD; AD 404; disabled/terminated; role không ánh xạ được (3 dạng nhóm) → E2 `role_unmappable`; khoá → `repeated_auth_failure` + đúng 1 cảnh báo cho 2 ticket; **khoá lần 2 sau khi hết khoá → cảnh báo thứ 2**; khoá kiểm trước disabled; khoá hết hạn không chặn; **TC25** (auth khoá → ticket → vẫn 1 cảnh báo, nguồn `login`); **TC24** (sai 1 lần → đúng → ticket qua B1, 0 cảnh báo) |
| `unit/test_alerts.py` (7) | khoá login == khoá B1; subject user/username/băm dài; `check_alert` từ chối 5 dạng sai |
| `unit/test_auth_login.py` | TC24: 0 cảnh báo; TC25: 1 cảnh báo đúng khoá, `still_locked` không thêm, đợt khoá thứ 2 → cảnh báo thứ 2; **2 người khoá cùng thời điểm → 2 cảnh báo (Q1)**; username không tồn tại → subject `username:…` |
| `unit/test_graph_runtime.py` | "lỗi ở B1 → E9" đổi sang lỗi từ phụ thuộc của B1 thật (scenario không còn chọn kết quả B1) |
| `integration/test_b01_pg.py` (10) | `SqlIdentityReads` theo họ token + hết hạn; `locked_until` UTC; `AlertWriter` idempotent theo subject; **INSERT thiếu `subject` → IntegrityError**, luật tổng hợp dùng `SYSTEM_SUBJECT`; migration 0004 downgrade dừng khi trùng, hạ/nâng sạch; B1 trên runtime Postgres: hợp lệ (đọc lại checkpoint), phiên bị thu hồi (audit ghi `block_reason`/`close_reason`), khoá → 1 dòng `alerts` cho 2 ticket, **khoá lần 2 sau khi hết khoá → 2 dòng**, AD tắt → E2 |
| `integration/test_auth_http_sql.py` | TC25 trên SQL: đúng 1 dòng `alerts` `(password_bruteforce, nv001, lúc khoá, critical)` |
| `integration/graph_pg.py`, `test_graph_pg.py`, `_crash_after_approval.py` | seed phiên thật `sess-graph` (B1 thật đọc `sessions`), submit bằng phiên đó thay cho `session_id=None` |
| `e2e/test_b01_vs_mock.py` (4) | mock AD thật: nv001 → ngữ cảnh đúng seed, l1_01 → l1; nv004/nv006 (disabled/terminated) → chặn; `/_admin/faults` trên `/ad` → E2 không E9 |
| `e2e/conftest.py`, `e2e/mock_server.py` | tách fixture `mock_server`/`reset` khỏi `test_tools_vs_mock.py` để dùng chung (không đổi nội dung test cũ) |

**Kết quả kiểm (26/09/2026, trong sandbox Claude Code):**

| Lệnh | Kết quả |
|---|---|
| `make lint` | **Xanh** — ruff, mypy 106 file, mypy mock, 5 hợp đồng import-linter, gitleaks detect 30 commit không leak; `gitleaks dir backend/app backend/tests`: không leak |
| unit backend | **1266 passed** (1233 cũ + 33 mới) |
| `make test` đầy đủ | **Xanh** (người chạy ngoài sandbox, 26/09/2026, code sạch sau khi hoàn nguyên mutation): backend **1371 passed** (1266 unit + 76 integration [66 cũ + 10 `test_b01_pg`] + 29 e2e [25 cũ + 4 `test_b01_vs_mock`]) + mock **86 passed** — gồm migration 0004 (model khớp migration, `subject` không DEFAULT), `test_graph_pg` với phiên thật, `test_tools_vs_mock` sau khi tách fixture |
| Mutation | Sửa hỏng rồi khôi phục 11 chỗ, **đều có test đỏ**: bỏ kiểm phiên; AD lỗi ném ra (E9); AD 404 coi như hợp lệ; đảo thứ tự khoá/disabled; `lock_start = now`; bỏ cảnh báo ở B1; role không ánh xạ được → đi tiếp; khoá `>=`; bỏ `frozen`; auth bỏ cảnh báo khi khoá; subject không có người dùng. Mutation SQL của `SqlIdentityReads` (người chạy từng lệnh `pytest test_b01_pg.py -k …` ngoài sandbox, 26/09/2026) — **3/3 đỏ, đúng lý do**: (a) bỏ `live.revoked_at IS NULL` → `follows_token_family` đỏ ở assert "logout xong phải None" + `revoked_session_blocks` đỏ (ticket không bị chặn); (b) bỏ `expires_at > now` → chỉ đỏ ở assert phiên `short` hết hạn (các assert thu hồi vẫn qua); (c) join theo `user_id` → cả 2 test đỏ (mượn phiên `sess-graph` của họ khác). Đã hoàn nguyên, kiểm lại truy vấn khớp bản gốc. Chạy pytest trực tiếp phải kèm env của Makefile (`DOCKER_HOST` colima, `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`) — thiếu thì Ryuk lỗi mount socket ở setup |

**Chuyển sang bước sau:** TC24/TC25 qua HTTP (đăng nhập → `POST /api/tickets`) ở 2b-3 khi có route ticket;
điểm log 8 cho ticket bị chặn ở B1 ở 2b-2 (B20 thật).

**Commit + CI:** `6c43153` (35 file, gồm 5 file `docs/spec` người cập nhật) — CI GitHub **xanh**, run
`36240526098` (26/09/2026, người theo dõi).

## Phase 2 — 2b-2: B20 thật + hàng đợi L2 (26/09/2026, commit `b68e800`, CI xanh run `36243253945`)

**Quyết định của người cho 2b-2 (26/09/2026):**
- **Q-A `resolution_path`:** B20 suy ra ở MỘT chỗ (`audit/final.resolution_path`): cha → NULL; `S_ESCALATED` →
  escalated; `S_REJECTED` → rejected; `S_BLOCKED` → NULL; `S_RESOLVED` → deflected (`need_type=info`) /
  approved (`approval_result=approved`) / auto. Kèm: **`goto()` và boundary kiểm key trả về ⊆ `TicketState`**
  (`domain.ticket_state.check_state_keys`, key lạ → `UnknownStateKey` → E9) — chặn loại lỗi LangGraph bỏ im
  lặng. **Việc spec (người sửa):** mã giả B10/B17 bỏ tự đặt `resolution_path` (không có trong `TicketState`).
- **Q-B đếm lần phục hồi:** KHÔNG dùng span (process bị giết không kịp ghi span → đếm 0 → thử vô hạn). Migration
  **0005** `turns.recover_attempts SMALLINT NOT NULL DEFAULT 0`; runner tăng bằng `UPDATE … RETURNING` **trước**
  khi chạy lại (dưới khoá ticket). Vượt 3: kẹt ở B20 → audit `finalize_failed_permanent` + đóng lượt; kẹt ở node
  khác → E9 `recover_exhausted` qua B20. Nghĩa "3": tối đa **3 lần worker chạy lại** (cộng lượt gốc = 4 lần chạy
  node), lần quét thứ 4 ngừng thử.
- **Q-C (lệch thứ tự mã giả B20, ghi theo yêu cầu):** `finalize_once` chạy **trước**, trả dòng `tickets` đang
  có; điểm log 8 ghi **từ chính dòng đó** → audit và `tickets` luôn giống hệt dù B20 chạy lại sau vài phút (mã
  giả ghi audit trước → hai nguồn lệch `total_duration`).
- **Q-D:** route **`GET /api/escalations/queue`** (P9 mục 7); `handoff_note.request` **chỉ** từ `redacted_request`
  (cắt 500 ký tự); `closed_at` đặt ở B20 cho mọi trạng thái cuối; ticket `S_BLOCKED` không có tin ở B20.

**Đã làm:**
- `graph/nodes/b20_audit.py` — B20 thật: `finalize_once` → điểm log 8 (event `closed`, khoá theo lượt) → nếu có
  `exit_code` (cha không bao giờ có): `effects.once("escalation_create")` + `effects.once("notify_user")`, tin
  vào `conversation` của checkpoint (không thêm bảng).
- `audit/final.py` (`summarize_final`, `resolution_path`), `domain/final.py` (`FinalSummary` — `db` không import
  `audit`), `audit/handoff.py` (`HandoffNote` 4 phần, `build_handoff`, `is_deny_case` = mọi E5).
- `config/escalation_templates.yaml` + `settings.get_escalation_templates` (đủ E0–E9, không rỗng, không khoá lạ):
  tin người dùng theo B20 7.1, `next_for_l2`, `deny_warning`.
- `db/tickets.py` (`created_at`, `count_turns`, `finalize_once` — ghi `WHERE final_state IS NULL` rồi đọc lại
  trong cùng transaction), `db/escalations.py` (`create` = `INSERT … SELECT rank FROM exit_code_priority` trong
  transaction của `effects.once`; `list_open` lọc `is_parent=false`, `closed_at IS NULL`, sắp `priority,
  created_at, escalation_id`).
- Migration `0005_turns_recover_attempts.py` + `models.Turn.recover_attempts`; `SqlTurnStore.bump_recover_attempts`.
- `graph/boundary.py`: lỗi ở trạng thái kết thúc → audit `unhandled_exception` **khoá theo lượt** rồi ném tiếp
  (2a kết thúc thread → ticket không `final_state`). `graph/runner.py`: `recover` tăng bộ đếm trước, `_give_up`,
  `after_turn`/`wake_parent` **sau khi nhả khoá** (2b-Q7); `late_event.deliver_event` gọi `after_turn` sau khi nhả
  khoá; `late_event.wake_parent` chuyển sang `Runner.wake_parent`. `settings.max_recover_attempts = 3`.
- `api/escalations.py` — `GET /api/escalations/queue` (`escalation:handle`, `limit` 1..200, mặc định 50);
  `main.create_app(escalations=…)`.
- Node giả: B3 thêm `low_confidence` (E1 `intent_low_confidence`, D-27); B12 thêm `high_risk` (E5 do LLM, không
  luật deny — để kiểm "mọi E5 là deny case").
- `tests/unit/test_side_effects_ast.py`: thêm `escalations.create` vào danh sách phải qua `effects.once`.

**Test mới / sửa:**

| File | Nội dung |
|---|---|
| `unit/test_b20_audit.py` (26) | E0–E9 do node giả sinh: 1 escalation, rank từ seed 0001 (đọc thẳng migration — không chép), handoff 4 phần không rỗng, 1 tin đúng mẫu vào `conversation`, điểm log 8 == `tickets`; E0 không lộ lý do; E1 `intent_low_confidence` vs `out_of_scope`; mọi E5 (deny + LLM rủi ro cao) là deny case + cảnh báo; `request` chỉ từ `redacted_request`, cắt 500; 8 ca `close_reason`/`resolution_path` (6/8 giá trị); cha → không escalation, NULL; `total_turns`, `total_duration`; **chạy lại ở 3 khe hở** (chết trước điểm log 8 / giữa lúc gửi tin / trước checkpoint) → 1 escalation, 1 tin, 1 điểm log 8, audit = `tickets` |
| `unit/test_recover_limit.py` (4) | bug cố định ở B20 → 3 lần worker, lần 4 dừng: 1 `finalize_failed_permanent`, lượt đóng, `recover_attempts=4`, sau đó không đụng tới; **process bị giết ở B20, không có span lỗi → vẫn dừng**; lỗi tạm thời → xong, không bỏ cuộc; kẹt ở B15 (chết mãi) → E9 `recover_exhausted` qua B20, vẫn 1 phiếu duyệt |
| `unit/test_state_keys.py` (3) | `need_type`, `approval_result` có trong `TicketState`, `resolution_path` không; goto key lạ → lỗi, không ghi audit; node trả key gõ sai → E9 |
| `unit/test_final_handoff.py` (18) | bảng `resolution_path` (9 ca) + trạng thái không kết thúc → lỗi; `summarize_final`; handoff từ state đầy đủ/tối thiểu; chỉ E5 là deny; file mẫu đủ mã; schema từ chối thiếu mã / chuỗi rỗng / khoá lạ |
| `unit/test_escalations_api.py` (7) | l1, l2 đọc được, sắp đúng, bỏ cha; employee, manager → 403 + `permission_denied`; `limit` 0/201/x → 422; `limit` áp dụng |
| `unit/test_graph_runtime.py` | điểm log 8 ở cuối chuỗi event; E4 có thêm tin escalation; lỗi B20 → ném tiếp, lượt mở; **con kết thúc → đánh thức cha khi không còn giữ khoá con**; lỗi đánh thức chỉ log |
| `integration/test_b20_pg.py` (17) | seed `exit_code_priority` == B20 4.1; E0–E9 trên Postgres (1 dòng, rank, JSONB 4 khoá, điểm log 8 == `tickets`, `side_effects` B20); chạy lại sau khi chết giữa lúc gửi tin (5 phút sau) → không trùng, thời lượng audit = tickets; **chết giữa `finalize_once` và điểm log 8 → audit lấy dòng DB**; `finalize_once` không đè; hàng đợi sắp đúng + bỏ cha; giới hạn phục hồi với `turns.recover_attempts` thật (bug + SIGKILL) |
| `integration/test_graph_pg.py` | chuỗi event kết thúc bằng `closed` |

**Kết quả kiểm (26/09/2026, sandbox):**

| Lệnh | Kết quả |
|---|---|
| `make lint` | **Xanh** — ruff, mypy 113 file, mypy mock, 5 hợp đồng, gitleaks detect không leak; `gitleaks dir backend/app backend/tests config`: không leak |
| unit backend | **1326 passed** (1266 + 60 mới) |
| Mutation logic | **14/14 đỏ**: escalation không qua `effects.once`; điểm log 8 từ summary thay vì dòng đã lưu; bỏ `done_so_far`; E0 nói lý do; boundary nuốt lỗi B20 như 2a; giới hạn `>=`; không đóng lượt sau `finalize_failed_permanent`; **tăng bộ đếm SAU khi recover** (đọc trước, tăng sau — lần viết đầu của đột biến này sai, gây lỗi thu thập test, đã viết lại đúng nghĩa); goto bỏ kiểm key; boundary bỏ kiểm key; `resolution_path` cha không NULL; `wake_parent` trong khoá; tin không vào `conversation`; `is_deny_case` chỉ khi luật deny |
| Mutation SQL | **7/7 đỏ đúng lý do** (người chạy từng lệnh `pytest test_b20_pg.py -k …` ngoài sandbox, 26/09/2026): (1) `finalize_once` bỏ `WHERE final_state IS NULL` → `finalize_once_never_overwrites` + `rerun_no_duplicates` đỏ `(0, 300)`; (2) `finalize_once` trả `summary` thay dòng đọc lại → `finalize_once_never_overwrites` + **`crash_between_finalize_and_point8`** đỏ `(300, 0)`; (3) priority hằng 6 → `each_exit_code` đỏ đúng 6 mã có hạng ≠ 6 (E0, E2, E5, E6, E7, E9) + `queue_sorted`; (4) bỏ lọc cha → `queue_sorted` (thêm E7 của cha); (5a) bỏ ORDER BY → `queue_sorted`; (5b) ORDER BY `priority, escalation_id` → `queue_sorted` đúng vị trí 3 (`E9` trước `E2`); (6) `bump_recover_attempts` không tăng → `recover_limit[bug]` (`calls` 6 ≠ 4) + `[killed]` (đỏ — output bị cắt, chưa thấy dòng lỗi cụ thể). Đã hoàn nguyên cả 7, kiểm không còn chú thích `MUTATION` |
| `make test` đầy đủ | **Xanh** (người chạy ngoài sandbox, 26/09/2026, code sạch sau khi hoàn nguyên 7 mutation SQL): backend **1448 passed** (1326 unit + 93 integration [76 cũ + 17 `test_b20_pg`] + 29 e2e) + mock **86 passed** — gồm migration 0005 (model khớp migration), `test_graph_pg` với B20 thật, `test_b01_pg`, e2e |

**Bài học từ mutation SQL (người yêu cầu kiểm, 26/09/2026) — ba test đã sửa/thêm vì đột biến lẽ ra phải bị bắt:**
1. **Test xanh oan vì lệch đồng hồ:** `test_b20_rerun_…` bản đầu xanh dưới đột biến (1). Dòng `tickets` tạo bằng `now()` thật
   của Postgres, còn FakeClock ở 08:00 → `max(0, NOW − created_at)` luôn kẹp về 0 ở cả lần ghi đầu lẫn lần đè. Sửa:
   `create_ticket(created_at=NOW)` tường minh (`graph_pg.py`) → thời lượng có nghĩa (0 vs 300).
2. **Thiếu ca cốt lõi của Q-C trên SQL:** thêm `test_crash_between_finalize_and_point8_audit_uses_stored_row`
   (`finalize_once` thật commit rồi chết trước điểm log 8; recover 5 phút sau → audit phải lấy dòng DB, 0 chứ không 300).
3. **Hoà hạng phân định bằng id thay vì `created_at`:** hàng đợi chèn mọi dòng cùng `created_at` → bỏ `created_at` khỏi
   ORDER BY vẫn xanh. Sửa: E9 chèn trước nhưng `created_at` muộn hơn E2 → đúng phải ra E2 trước E9.
Kèm: chạy pytest trực tiếp phải `cd` về gốc repo (`!` chạy ở thư mục hiện tại của phiên); `FailingTickets` ném bản exception
mới mỗi lần (ném lại cùng đối tượng → traceback cộng dồn qua các lần thử — chỉ ảnh hưởng log của test).

**Commit + CI:** `b68e800` — CI GitHub **xanh**, run `36243253945` (26/09/2026, người theo dõi, đã đối chiếu `headSha`).


## Phase 2 — 2b-3: dịch vụ ticket + route sự kiện + nối `create_app` (26–27/09/2026, commit `dcc5ddc`, CI xanh run `36270415646`)

Kế hoạch Plan Mode đã duyệt (kèm chốt a–h và Q1–Q5 của người, 26/09/2026). Không LLM, không đọc `.env`,
**không commit**.

**Quyết định của người cho 2b-3:**
- **Q1:** sự kiện (messages/confirm/decision) trả **202**: request lấy khoá ticket + kiểm guard (409/422 trả
  ngay), rồi **giao khoá cho task nền** chạy lượt resume. try/finally + cờ "đã giao": chưa giao thì request nhả;
  task nền nhả trong `finally`; task bị huỷ trước khi kịp chạy → `on_cancel` nhả.
- **Q2 (lệch B15 mục 10):** bấm duyệt muộn **KHÔNG đổi `approvals.status`** — chỉ audit `late_event` (B16,
  `source=user`, `approval_id`, `clicked_by`, `reason=expired|already_decided`). Lý do: đổi `pending→late_ignored`
  trước chu kỳ quét 15 giây làm worker không bao giờ bắn timeout → ticket kẹt `S_PENDING_APPROVAL`.
- **Q3:** compose `APP_ENV: ${APP_ENV:?…}`; `.env.example` có `APP_ENV=dev`. Người tự thêm vào `.env`.
- **Q4:** không seed DB app; `FAKE_APPROVER_ID` chưa có dòng `users` → B15 giả vấp FK → E9 (có test).
  **2b-4: `gate2.py` phải tự đăng nhập l1 trước.** Phase 4 (chọn người duyệt theo lịch trực) gặp lại vấn đề này.
- **Q5:** 413 đứng TRƯỚC kiểm quyền, đếm **byte đọc thật** (chunked không Content-Length vẫn bị chặn).
- Chốt a–h: thứ tự kiểm messages/confirm = 413 → quyền → 404 (không có / không đọc được, cùng body) → 403 (không
  phải chủ) → 409 (ticket con) → 422 (body) → guard → `start_event`; bị từ chối chỉ ghi `permission_denied`
  (404 id giả: không ghi gì); GET `status` = `tickets.final_state` nếu đã đóng, còn mở thì từ checkpoint;
  `waiting_for` chỉ từ checkpoint; checkpoint lỗi → 503; response model `TicketView`; route duyệt không ghi quyết
  định (B16 ghi), so hạn bằng Clock của app (bằng hạn = muộn), `approver_id` chỉ từ token; `view_started_at` tuỳ
  chọn, chỉ log; worker recover lượt mở + snapshot rỗng → chạy state đầu từ dòng `tickets` cùng `turn_id`; task nền
  giữ tham chiếu + `done_callback` log exception.

**Đã làm:**
- `api/tickets.py` (`POST /api/tickets` 202, `GET /api/tickets/{id}`, `POST …/messages`, `POST …/confirm`),
  `api/approvals.py` (`POST /api/approvals/{id}/decision`), `api/desk.py` (phụ thuộc chung; runtime lỗi → 503;
  `parse_body` để 422 đứng sau kiểm quyền), `api/background.py` (`BackgroundRuns`), `api/errors.py` (LateEvent 409,
  TicketBusy 503 + `Retry-After`, InvalidEvent 422, TicketNotFound 404), `api/limits.py` (`BodyLimitMiddleware`).
- `guard/privacy.py` (`PrivacyGuard`, `RedactionResult` B02 mục 4, `NotRedactingGuard`); `approval/store.py`
  (`SqlApprovals`: `create` trong `current_tx()`, `close` chỉ từ `pending`, `lock_row` FOR UPDATE, `get`).
- `db/tickets.py`: `NewTicket`, `TicketRow`, `create` (ticket + lượt `submit` MỘT transaction, `created_at` từ
  Clock của app), `get`. `graph/ports.py`: `TicketReader`, `TicketRepo`, `ApprovalRepo`.
- `graph/runner.py`: `run_new` (không chạy khi lượt đã đóng hoặc thread đã có state), recover snapshot rỗng →
  state đầu từ dòng `tickets`; port `tickets`. `graph/late_event.py`: tách `_guard`, thêm `start_event` (giao
  khoá), `record_late`. `auth/authz.py`: `may_decide_as` (phần "ai" → 403); `can_decide_approval` giữ nghĩa P6.
- `graph/wiring.py`: `Runtime` mang `tickets`, `approvals`; `SqlApprovals` thay `UnavailableApprovals` ở CẢ
  backend lẫn worker; `fake_approver()` kiểm `APP_ENV` trước khi đụng DB. Node giả B15 dùng `FAKE_APPROVER_ID`
  (thiếu → ném → E9); B16 giả ghi `decided_by`, `note` từ sự kiện.
- `main.create_app(runtime=, guard=)`: guard giả / `FAKE_APPROVER_ID` sai môi trường → `RuntimeError` ngay trong
  `create_app`; lifespan một `AsyncExitStack`; runtime mở lỗi → `runtime_status="down"`, route ticket/duyệt 503;
  tắt app: chờ `BACKGROUND_SHUTDOWN_SECONDS` rồi huỷ lượt nền (worker phục hồi). `/api/health` thêm `"runtime"`.
- `settings.py`: `app_env` (không mặc định), `fake_approver_id`, `max_request_body_bytes`, `background_shutdown_seconds`,
  `require_dev_fakes`. `conftest.py` gốc đặt `APP_ENV=test`. `docker-compose.yml`, `.env.example` (mục "Môi trường").
- `FakeScenario.plan_all`/`on_all` (id ticket do API sinh, test không biết trước).

**Sửa thêm ngoài phạm vi (phát hiện khi chạy test, 26/09/2026 16:09 UTC):** 8 test auth (refresh, CSRF) **đỏ trên
chính HEAD `b68e800`** — đã kiểm bằng worktree tạm ở `$TMPDIR`. Nguyên nhân: `EPOCH` của `tests/fakes/auth.py` là
26/09/2026 08:00 UTC, cookie refresh hết hạn EPOCH + 8 giờ = 16:00 UTC, mà cookie jar của httpx bỏ cookie theo
**giờ thật**. CI run `36243253945` xanh vì chạy trước 16:00. Sửa: `EPOCH = 2099-09-26 08:00 UTC` (app vẫn kiểm
JWT/phiên/khoá theo FakeClock; store SQL ghi mọi mốc thời gian từ clock, không dùng `now()`). Integration auth
chưa chạy lại với mốc mới.

**Lỗi tìm ra khi viết test:** `BackgroundRuns.drain` quay vô hạn — `gather` trên task đã xong trả về mà không
nhường vòng lặp nên `done_callback` chưa kịp bỏ task khỏi tập; sửa bằng `sleep(0)` sau mỗi vòng.

**Bổ sung sau duyệt sandbox (người yêu cầu, 27/09/2026):**
1. **Cạn lượt phục hồi mà thread chưa từng có checkpoint** — bản đầu chỉ đóng lượt + log (ticket không
   `final_state` = biến mất khỏi mọi hàng đợi, trái 2b-Q6). Nay `Runner._give_up_before_checkpoint`: dựng state đầu
   từ dòng `tickets`, `goto` sang `S_ESCALATED` E9 `recover_exhausted` (audit `detail.no_checkpoint=true`), ghi cả
   state lẫn cập nhật vào checkpoint (`aupdate_state(as_node=b01_identity)`) rồi chạy B20 — cùng đường E9
   `recover_exhausted` có sẵn. `_divert`/`_divert_bound` nhận `values` thay cho snapshot (+ cờ `seed`).
   **Sửa nhận định cũ:** "chết ở B1 cả 4 lần" KHÔNG rơi vào khe này — LangGraph ghi checkpoint input trước khi
   chạy B1, nên ca đó đi đường `_give_up` có sẵn (đã có test chứng minh). Khe thật hẹp hơn: chết sau commit
   `tickets.create`, trước checkpoint input, cả 4 lần.
2. **Test cho lỗi `drain`** (`gather` trên toàn task đã xong trả về ngay, không nhường vòng lặp → quay vô hạn):
   dựng đúng trạng thái "xong mà callback chưa chạy" bằng `eager_task_factory`, chạy trong thread daemon + `join`
   2 giây (vòng quay không nhường nên `wait_for` không cắt được) → hỏng thì đỏ, không treo.
3. **EPOCH 2099 giữ nguyên**; message commit sau này có dòng riêng:
   `- test: doi EPOCH auth sang 2099, sua bom hen gio tu 1c`.

**Test mới:**

| File | Nội dung |
|---|---|
| `unit/test_tickets_api.py` (36) | tạo 202 + chạy nền; `requester_role/dept/session`; guard che trước khi lưu; `created_at` = FakeClock, thời lượng 300 giây (`tickets` + điểm log 8); body sai 422 không ghi gì; 401; `TicketView` đúng tập key; TC30 404 cùng body; `waiting_for` 3 trạng thái; `status` theo `final_state` khi lệch checkpoint; checkpoint lỗi 503; thứ tự (a): người lạ → ticket con 404, chủ → con 409 trước body/guard, l1 không phải chủ 403 (`reason=not_owner`), 404 id giả không ghi gì, bị từ chối không gọi guard, 422 sau kiểm; sự kiện muộn 3 ca → đúng 1 `late_event`, state không đổi; bận → 503 `Retry-After: 3` rồi 409; request bị huỷ khi đang giữ khoá → khoá nhả NGAY; task huỷ trước khi chạy → `on_cancel` nhả; huỷ giữa lượt → không E9, lượt mở; task nền lỗi → log; TC24, TC25 qua HTTP |
| `unit/test_approvals_api.py` (16) | phiếu `pending` tới khi graph chạy; từ chối ghi note (đã che) + `decided_by`; `approver_id` chỉ từ token (body có → 422); từ chối thiếu note (3 dạng) → 422, 0 resume; l1 khác / L2 / employee / người gửi → 403; 404; đã quyết → 409 `already_decided`; bấm muộn trước chu kỳ quét → 409 `expired`, phiếu vẫn `pending`, worker → E6 + `timeout`, 0 lần thực thi; biên hạn (`==` → 409, `−1 µs` → 202); so bằng Clock của app; 2 request đồng thời (request sau đứng ở khoá) → 1 resume, 409, đúng 1 `late_event` |
| `unit/test_runner_intake.py` (7) | `run_new` dựng state từ dòng `tickets`; chết trước checkpoint đầu → worker recover, cùng `turn_id`, 1 phiếu; `run_new` tới sau khi thread có state → không chạy lại; lượt đã đóng; `create` nguyên tử; **chết ở B1 × 4** → E9 `recover_exhausted`, 1 escalation, 1 lượt, `recover_attempts=4`, 1 tin; **chết trước checkpoint đầu × 4** → như trên + `no_checkpoint`, B1 chưa từng chạy |
| `unit/test_background_runs.py` (1) | `drain` trả về khi task đã xong mà `done_callback` chưa chạy (eager task, thread + join 2 giây) |
| `unit/test_app_env.py` (14) | None/staging/prod + guard giả → `RuntimeError`; + `FAKE_APPROVER_ID` → lỗi; dev/test lên; worker (`open_runtime`) cùng luật, chặn trước khi đụng DB; runtime lỗi → health 200 `"down"`, route ticket/duyệt/GET 503; runtime lên → `"up"` |
| `unit/test_body_limit.py` (6) | 64 KB + 1 → 413 ở 4 route POST, trước 401, 0 dòng ghi; chunked (không Content-Length) → 413; đúng 64 KB → qua giới hạn |
| `unit/test_privacy_guard.py` (2) | sau tạo ticket + trả lời có `SECRET`: không có trong mọi store giả + mọi blob checkpoint; đối chứng: guard không che → quét thấy |
| `unit/test_auth_route_scan.py` (+1) | 5 route mới có trong danh sách quét, đúng permission |
| `integration/test_tickets_http_pg.py` (11) | cổng 2 qua HTTP (đóng app, mở app mới cùng DB) + thời lượng 300 giây; sự kiện muộn 3 trạng thái chờ; bấm muộn trước chu kỳ quét (S5); IDOR + mỗi người đọc đúng ticket mình; quét `information_schema` mọi cột text/varchar/jsonb/bytea mọi bảng + checkpoint không có `SECRET` (đối chứng: thấy chuỗi không bí mật ở `tickets` và checkpoint); Q4 E9; **giết process thật giữa commit INSERT và submit** → worker xong, 1 thread, 1 `turn_id`; cạn lượt phục hồi (chết ở B1 × 4 / chết trước checkpoint đầu × 4, mỗi lần một runtime mới) → `tickets` E9, đúng 1 dòng `escalations` E9 `recover_exhausted`, 1 lượt `recover_attempts=4` |
| `integration/test_approval_store_pg.py` (8) | `create` ghi ticket + lượt theo Clock, `get` UTC; `create` nguyên tử; `close` chỉ từ `pending`; CHECK note; `lock_row` chặn UPDATE khác (`LockNotAvailable`); id sai/không có → None; UTC; **chết giữa INSERT phiếu và commit `side_effects` → cả hai mất, phục hồi đúng 1 phiếu** |
| Sửa | `test_graph_runtime.py`, `test_graph_pg.py`: sự kiện `rejected` kèm `note` (bản giả cũ tự điền "(node giả)"; nay note phải đi từ sự kiện); `test_health.py`, `auth_helpers.py`: tiêm `no_runtime`; `graph_pg.py`: `SqlApprovals` thật (`RecordingApprovals`), `pg_runtime_factory` |

**Kết quả kiểm (26/09/2026, sandbox):**

| Lệnh | Kết quả |
|---|---|
| `make lint` (từng bước) | **Xanh** — ruff, mypy `backend/app` 121 file, mypy mock 11 file, 5 hợp đồng import-linter, `gitleaks detect` không leak; `gitleaks dir backend/app backend/tests config .env.example docker-compose.yml conftest.py`: không leak (bản đầu bắt `SECRET = "SECRET-…"` ở `tests/fakes/desk.py` → đổi sang ghép lúc chạy) |
| unit backend | **1409 passed** (1326 cũ + 83 mới) — lần chạy sau bổ sung 27/09/2026 |
| `docker compose config` (bản sao ở `$TMPDIR`) | có `APP_ENV` → `dev`; bỏ `APP_ENV` → dừng "required variable APP_ENV is missing a value" |
| Mutation logic L1–L28 | **28/28 đỏ đúng test dự đoán** (chạy lại cả bộ sau bổ sung 27/09/2026). **L27** bỏ nhánh E9 trước checkpoint → `final_state` None (`test_killed_before_first_checkpoint_every_time_goes_e9`); **L28** bỏ `sleep(0)` trong `drain` → "drain treo quá 2.0 giây" (`test_drain_returns_when_done_callback_pending`). Lần chạy đầu 2 đột biến SỐNG → đã sửa test: **L25** xanh oan vì generator của khoá bị GC tự nhả khi task chết (test giờ kiểm khoá nhả NGAY, không nhường vòng lặp); **L17** xanh oan vì request thứ hai ra 409 ở `lock_row` (phiếu đã quyết) chứ không chờ khoá (test giờ đợi request thứ hai đứng ở khoá ticket rồi mới thả lượt đầu). L24 thực hiện là "bỏ log trong `done_callback`" (bỏ hẳn callback thì `drain` treo) |
| `make test` lần 1 (người chạy, 27/09/2026) | **2 failed, 1548 passed** — cả hai là lỗi TEST (không nằm trong danh sách S nên trước đó chỉ chạy lẻ/chưa chạy): (1) `test_late_click_before_scan_pg` `delivered 2 == 1` — DB dùng chung cả module, phiếu pending của `test_late_events_pg` cũng quá hạn khi tua clock → đổi sang `delivered >= 1 and failed == 0`, vẫn kiểm đúng phiếu/ticket của test (S5 bắt ở assert "vẫn pending" TRƯỚC bước quét, không bị nới); (2) quét guard `relation "collations" does not exist` — Postgres tính `has_table_privilege(quote_ident(table_name))` trên cả dòng của `information_schema` trước khi lọc schema → dùng tên đủ schema `format('%I.%I', …)` |
| `make test` lần 2 (người chạy, 27/09/2026) | **Xanh** — backend **1550 passed** (1409 unit + 112 integration [93 cũ + 19 mới] + 29 e2e) + mock **86 passed**; gồm integration auth với `EPOCH` 2099, giết process thật giữa commit INSERT và submit, quét guard toàn DB |
| Mutation SQL S1–S8 | **8/8 đỏ đúng lý do** (người chạy từng lệnh ngoài sandbox, 27/09/2026; script tự khôi phục + so nội dung, sau cùng không còn dấu đột biến): **S1** tách 2 tx → `assert 1 == 0` (dòng `tk-a2` còn lại); **S2** bỏ `created_at=:at` → `test_full_flow_restart_duration_300s_pg` (`created_at = EPOCH` False) + `test_create_writes_ticket_and_turn_with_app_clock`; **S3** bỏ `FOR UPDATE` → `DID NOT RAISE OperationalError`; **S4** `close` bỏ điều kiện `pending` → phiếu `approved` bị đè `status='timeout'`; **S5** `mark_late` đổi status → `'late_ignored' == 'pending'`; **S6** `tickets.get` bỏ `WHERE` → rò IDOR thật (binh đọc ticket của an ra 200; kèm B15 vấp UNIQUE vì `run_new` dựng state từ nhầm dòng); **S7** bỏ `current_tx()` → `assert 1 == 0` (phiếu mồ côi sau khi chết); **S8** recover snapshot rỗng đóng lượt → `None == 'S_ESCALATED'` |

**Đặc tả — ĐÃ ĐỒNG BỘ** (người sửa `docs/spec`, 27/09/2026; Claude đối chiếu với code 2b-3: khớp nội dung):
`decisions.md` mục 4.1 (2b-3-Q1…Q5, QA…QD), P1 bản 1.5 (mục 7, 10), B15-B16 bản 1.4 (mục 4, 5.1, 10), 01 bản 1.5
(mục 4.2). Lệch CHỮ còn lại (đề xuất, không đổi code): (1) "recover gọi `run_new`" — code gọi `_run_initial`
(cùng cách dựng state), vì `run_new` tự lấy khoá ticket mà recover đang giữ (khoá không tái nhập); (2) B15 5.1 đặt
`mark_late` và 422 trước "nhả hàng" — code nhả hàng ngay sau khi xác định 404/403/muộn rồi mới ghi `late_event`,
parse body, 422; (3) route gọi `start_event` (bản API của `deliver_event`), không phải `deliver_event`; B15 5.1
chưa nhắc `note` cũng qua privacy guard.

Người đã sửa cả 3 chỗ lệch chữ (27/09/2026) — Claude đối chiếu lại: decisions 2b-3-QC + P1 mục 7/10 "recover
chạy state đầu từ dòng `tickets`, không gọi `run_new`" = `_run_initial`; B15 5.1 "xác định muộn → nhả hàng → mark_late
+ 409 → 422 → note qua guard → `start_event`" = code; 2b-3-QA `start_event` (route) / `deliver_event` (worker) = code.

**Bổ sung trước commit (người yêu cầu, 27/09/2026):** test quét guard trên Postgres assert danh sách quét có ≥ 22 bảng
(và chứa `tickets`, `audit_logs`, `turns`, `side_effects`, 3 bảng checkpoint) — không xanh oan khi danh sách rỗng /
lọc sai schema. Sandbox không tới được Docker nên chưa chạy lúc commit; **đã chạy và xanh trên CI** (run `36270415646`,
`make test` đầy đủ). Kiểm tĩnh trước đó: 22/22 bảng P7 có cột text/jsonb và `app_rw`
có SELECT trên cả 22 (`RW_CRUD_TABLES` ∪ `APPEND_ONLY` của 0001) + 3 bảng checkpoint có cột text/bytea → **ước tính
25** (`checkpoint_migrations` chỉ có cột `v INTEGER` nên không vào danh sách quét; bản trước ghi "dự kiến 26" là sai;
chưa đo). Người chốt (2b-4 Q6): giữ assert `≥ 22` + tập con bắt buộc, không siết `== 25`.

**Spec cần sửa (người sửa `docs/spec`) — đã xử lý ở trên:**
- B15-B16 mục 10: "Bấm duyệt sau khi hết hạn → 409, phiếu `late_ignored`" → phiếu giữ trạng thái thật, dấu vết ở
  audit `late_event` (Q2). Mã giả handler mục 5: `can_decide_approval` (gồm `pending` + hạn) đứng trước → TC27 ra
  403 — tách "ai" (403) với "khi nào" (409).
- B15-B16 mục 4 `DecisionIn.view_started_at` bắt buộc → tuỳ chọn, chỉ log; `view_duration` tính phía server từ
  `first_viewed_at` (chốt f).
- 01 mục 4.2: đồ thị phụ thuộc thiếu `api → guard` (B02 mục 2 + D-07 đặt privacy guard ở API).

## Phase 2 — 2b-4: chứng minh cổng 2 trên stack compose thật (27/09/2026, chưa commit)

Kế hoạch Plan Mode đã duyệt (chốt Q1–Q8 + 4 vá của người, 27/09/2026). Không LLM, không đọc `.env`, **không commit**.

**Kiểm đầu 2b-4:** run `36270415646` đã ghi ở trên (vào commit đầu 2b-4). Assert "≥ 22 bảng" của test quét guard
**đã có** trong commit `dcc5ddc` (`backend/tests/integration/test_tickets_http_pg.py:288-292`) và chạy ở run đó.

**Quyết định của người (27/09/2026):**
- **Q1:** chọn kịch bản theo ticket bằng thẻ `[fake:<preset>]` trong câu yêu cầu; chỉ đọc thẻ khi `FAKE_SCENARIO`
  đặt (dev/test), đọc từ `redacted_request`; node thật B1/B20 không đọc thẻ.
- **Q2:** `FAKE_NODE_DELAY` = số giây; điểm dừng do preset quyết (`kill_b06`: đầu `b06_diagnose`; `kill_b15`:
  sau `approval_create`).
- **Q3:** hết hạn = dời `deadline` bằng psql trong script (không thêm setting rút ngắn SLA).
- **Q4:** script tự chạy lệnh compose, in lệnh trước khi chạy, có chốt an toàn.
- **Q5:** duyệt `approved` trên stack ra **E7** (B17 giả + `RefusingExecutor`) là đúng tới Phase 3; script in
  "E7 do RefusingExecutor (dung toi Phase 3)".
- **Q6:** giữ assert quét guard `≥ 22` + tập con; sửa "dự kiến 26" → "ước tính 25" (đã sửa ở mục 2b-3).
- **Q7:** thêm `make gate2` — người đã thêm vào bảng lệnh `build/01-kien-truc-project.md` §7.1 (27/09/2026).
- **Q8:** không chạy TC24/TC25 trên stack — **đã phủ ở 2b-3** (`test_tickets_api.py` qua HTTP, `test_auth_http_sql.py`
  trên SQL, `test_b01_pg.py`).
- **Vá 1:** chốt an toàn gate2 chạy trước mọi việc: `compose exec -T backend printenv APP_ENV` ≠ `dev` → dừng (exit 2);
  URL chỉ `http://127.0.0.1:<cổng>`; cấm `down -v` / `--volumes` / `volume rm|prune` (kiểm chuỗi lệnh ở một điểm).
- **Vá 2:** kịch bản kill poll `pg_locks` (khoá advisory của ĐÚNG ticket) tới 0 trong ≤ 10 giây; quá hạn mới FAIL,
  in số khoá còn.
- **Vá 3:** **cổng 2 chỉ đạt khi một thành viên khác chạy `make gate2 S=all` trên máy họ** (ưu tiên máy gaming —
  kiêm ghi N2: GPU + VRAM) và dán kết quả vào đây.
- **Vá 4:** mật khẩu demo đọc `GATE2_PASSWORD`, mặc định là hằng import được (không chép chuỗi vào script).
  **Lệch nhỏ so với chốt:** `mock_services` không có hằng Python nào (mật khẩu chỉ ở README + hash trong
  `seed.json`), và `mock_services/app` trùng tên package `app` với backend nên không import chéo được → tách hằng
  có sẵn `DEMO_PASSWORD` của `tests/fakes/auth.py` sang `tests/fakes/demo.py` (không import gì; `auth.py` import lại
  từ đó) — vẫn một nguồn duy nhất, script không chép chuỗi. Người muốn nguồn nằm trong `mock_services` thì báo.
- Nhỏ: `restart-all` so số ticket trước/sau; mỗi dòng PASS/FAIL kèm ticket_id.

**Đã làm:**
- `graph/fakes.py`: `StackScenario` (cùng giao diện `FakeScenario`; preset theo thẻ trong `redacted_request`, không
  thẻ → preset `FAKE_SCENARIO`; thẻ lạ → `ValueError` → E9; kết quả đánh chỉ số theo `clarification_turns` của
  STATE — backend, worker, trước/sau restart chọn như nhau), `STACK_PRESETS` (`approval`, `clarify`, `confirm`,
  `raise`, `kill_b06`, `kill_b15`), `PAUSABLE_NODES` (node giả b02…b17, không node thật/node chờ) + hook
  `after_approval_create`; `FakeScenario.pause` (bản test không dừng).
- `graph/builder.fake_nodes`: bọc node trong `PAUSABLE_NODES` bằng `scenario.pause` (bên trong boundary — thẻ lạ ở
  điểm dừng cũng ra E9; `functools.wraps` giữ tên, test tĩnh traced/boundary không đổi).
- `settings.py`: `fake_scenario`, `fake_node_delay` (≥ 0, phải < `WORKER_STALE_TURN_SECONDS/2`).
  `graph/wiring.fake_scenario(settings)`: fail-closed (`require_dev_fakes`) cho cả hai biến, trước khi đụng DB;
  delay mà không có scenario → từ chối; gọi ở `main.create_app` và `open_runtime` (worker).
- `docker-compose.yml`: anchor chung backend + worker thêm `FAKE_SCENARIO`, `FAKE_NODE_DELAY`. `.env.example`: mẫu
  `FAKE_SCENARIO=approval`, `FAKE_NODE_DELAY=40` + giải thích. **Người tự thêm 2 biến vào `.env`.**
- `Makefile`: `make gate2 S=<kịch bản>` (dùng `COMPOSE` của Makefile — colima + `--env-file`).
- `backend/tests/stack/gate2.py` + `README.md`: 10 kịch bản (`preflight`, `restart`, `restart-all`, `late`, `expire`,
  `late-click`, `kill`, `kill-b15`, `tc29`, `threads`; `all` = trừ `restart-all`), cách đọc kết quả ở README.
  psql chạy trong container postgres bằng biến của container (script không đọc `.env`). Kiểm trên tập rỗng = FAIL;
  "không có X" cần đối chứng "có Y" cùng ticket.

**Test mới:**

| File | Nội dung |
|---|---|
| `unit/test_stack_scenario.py` (31) | kết quả mỗi preset ⊆ nhánh thật của node (đọc AST node); điểm dừng không gồm b01/b20/node chờ; AST: B1/B20 không đọc thẻ/scenario; preset mặc định lạ → lỗi; thẻ chọn preset (5 trạng thái chờ) + `raise` → E9; không thẻ → mặc định; thẻ lạ → E9 (không về mặc định); không đặt FAKE_SCENARIO → thẻ bị bỏ qua; **hỏi → restart với StackScenario MỚI → trả lời → chờ duyệt, B11 `asked` 1 lần**; delay chỉ ở điểm preset (sleep tiêm, không ngủ thật); `kill_b15` ngủ khi đã có đúng 1 phiếu; delay 0 không ngủ; compose truyền 2 biến cho backend VÀ worker |
| `unit/test_app_env.py` (+16) | FAKE_SCENARIO / FAKE_NODE_DELAY / cả hai với APP_ENV None/staging/prod → `RuntimeError` ở `create_app`; worker (`open_runtime`) chặn trước DB; dev/test lên; preset lạ → `ValueError`; delay không scenario → từ chối; delay ≥ stale/2, âm → `ValidationError` |
| `unit/test_gate2.py` (42 → 45: +2 `after_event`, +1 tĩnh "đọc sau 202 luôn chờ lượt") | **chốt 1**: APP_ENV prod/staging/test/rỗng → exit 2, chỉ đúng 1 lệnh (`printenv`) đã chạy; printenv lỗi → dừng; **chốt 2**: 7 URL không phải `http://127.0.0.1` → dừng trước mọi lệnh; **chốt 3**: 7 dạng xoá volume bị từ chối, lệnh thường (kể cả `psql -v`) qua; `Shell` từ chối trước khi chạy, in lệnh trước khi chạy; `rows` rỗng → FAIL; `absent` cần đối chứng; dòng PASS/FAIL kèm ticket_id; tổng kết không có kiểm nào ≠ xanh; mật khẩu `GATE2_PASSWORD` → hằng; ticket_id lạ không vào SQL; psql chạy trong container postgres |
| `integration/test_stack_scenario_pg.py` (1) | `Settings(FAKE_SCENARIO)` → `open_runtime` thật trên Postgres: `[fake:clarify]` → hỏi → đóng runtime, mở runtime mới → trả lời → chờ duyệt; 1 `asked`, 1 phiếu |

**Kết quả kiểm (27/09/2026, sandbox):**

| Lệnh | Kết quả |
|---|---|
| `make lint` | **Xanh** — ruff, mypy `backend/app` 121 file, mypy mock 11 file, 5 hợp đồng import-linter, `gitleaks detect` 33 commit không leak |
| `gitleaks dir` (`backend/app backend/tests config .env.example docker-compose.yml Makefile`) | không leak |
| unit backend | **1498 passed** (1409 + 89 mới) |
| Mutation M1–M9 | **9/9 đỏ đúng test dự đoán** (script tự khôi phục, so md5 + `git diff --stat` sau cùng khớp): M1 bỏ `require_dev_fakes` FAKE_SCENARIO → `test_prod_refuses_fake_scenario[FAKE_SCENARIO-*]` + `test_worker_runtime_refuses_fake_scenario`; M2 `create_app` không gọi `fake_scenario` → 6 ca prod + `delay_without_scenario`; M3 chỉ số theo bộ nhớ process → `test_clarify_sequence_survives_restart`; M4 thẻ lạ về mặc định → `test_unknown_tag_goes_e9_not_default`; M5 delay mọi điểm → `test_delay_only_at_preset_pause_point` (5 ca) + `kill_b15_pauses…`; M6 compose chỉ backend → `test_compose_passes_fake_vars_to_service[worker]`; M7 kiểm rỗng cho qua → `test_rows_empty_is_fail`; M8 bỏ validator delay → `test_delay_must_stay_below_half_stale_turn`; **M9 gate2 bỏ kiểm APP_ENV → `test_stops_before_anything_when_backend_not_dev` (4 ca)** |
| `make test` đầy đủ (người chạy, 27/09/2026) | **Xanh** — backend **1640 passed** (1498 unit + 113 integration [112 cũ + 1 `test_stack_scenario_pg`] + 29 e2e) + mock **86 passed** |
| `make up` (người chạy, 27/09/2026, `.env` đã có `FAKE_SCENARIO`, `FAKE_NODE_DELAY`) | **Xanh** — build lại image backend; `alembic upgrade head` chạy `0003 -> 0004 -> 0005` trên volume cũ (stack dev chưa từng nâng từ 2b-1/2b-2); `make seed` 16 người, 7 thiết bị; `worker: healthy`; `/api/health` = `{"status":"ok","checks":{"db":"ok","qdrant":"ok","mock":"ok"},"failed":[],"runtime":"up"}` |
| `make gate2 S=preflight` (người chạy, 27/09/2026, run `37ee2db4`) | **5 PASS, 0 FAIL** — chốt APP_ENV qua (`printenv` = dev); health `ok` + `runtime: up`; worker `healthy`; đăng nhập ha.lt rồi an.nv; ticket `6bb7146d-276a-49f0-a6d9-d210f6287dd4` `[fake:clarify]` → `S_CLARIFYING` (thẻ có hiệu lực trên stack) |
| `make gate2 S=restart` lần 1 (người chạy, run `241a2e7e`) | **14 PASS, 1 FAIL**. PASS: 3 ticket dừng đúng 3 trạng thái chờ; `restart backend`; duyệt → 202 → **E7 do RefusingExecutor** (audit `… B15 queued → B16 approved → B17 execution_failed → B20 closed`), phiếu `approved`/`l1_01`; confirm → `resolved_user_confirmed`; mỗi ticket có checkpoint (14/13/10). **FAIL** ticket `08ba0c88-…` "clarify → chờ duyệt": thấy `S_CLARIFYING`. **Chẩn đoán — lỗi SCRIPT, ĐÃ XÁC NHẬN** (người đọc audit ticket `08ba0c88-…`: `… B11 asked → B11 user_replied → B11 action_built → B13/B14 risk_decided → B15 queued`, đúng 1 `asked` — hệ thống đã tới chờ duyệt, không hỏi lại): trả lời trả 202 rồi lượt chạy NỀN; script dùng `settled()` — mà ticket ngay sau 202 vẫn đang ở trạng thái chờ CŨ nên `settled` trả về ngay. Kiểm "B11 asked 1 lần" cũng đo quá sớm nên PASS của nó chưa có nghĩa. **Sửa:** `Ctx.after_event` chờ có lượt mới (> số lượt trước sự kiện) và mọi lượt đã đóng rồi mới đọc trạng thái (đúng cả khi lượt mới dừng lại ở cùng trạng thái chờ — ca "hỏi lại" mà kiểm này nhắm bắt). Unit +2 (`test_after_event_*`), **M10** (bỏ bước chờ) → cả 2 đỏ; unit 1500 passed |
| `make gate2 S=restart` lần 2 (người chạy, run `6b8b4cf9`, script đã sửa) | **15 PASS, 0 FAIL** — **cổng 2 dòng 1 trên stack thật**: 3 ticket dừng ở 3 trạng thái chờ → `restart backend` → approval `3c083b2b-…`: duyệt 202 → E7 do RefusingExecutor, audit `B15 queued → B16 approved → B17 execution_failed → B20 closed`, phiếu `approved`/`l1_01`; clarify `16e5baba-…`: trả lời 202 → (chờ lượt nền đóng) → `S_PENDING_APPROVAL`, `B11 asked` đúng 1 lần; confirm `fc824308-…` → `resolved_user_confirmed`; checkpoint 14/13/10 |
| `make gate2 S=late` (người chạy, run `4fd4cd89`) | **15 PASS, 0 FAIL** — **cổng 2 dòng 3 trên stack**: 3 trạng thái chờ × sự kiện sai loại → 409, trạng thái giữ nguyên, đúng 1 `late_event` mỗi ticket, `source=user`; `step` = bước của trạng thái chờ mà sự kiện NHẮM tới (2a quyết định 7): message vào chờ duyệt → `B11` (`expected=S_CLARIFYING`, `actual=S_PENDING_APPROVAL`); confirm vào chờ trả lời → `B19`; message vào chờ xác nhận → `B11` |
| `make gate2 S=expire` (người chạy, run `1eca2b45`) | **15 PASS, 0 FAIL** — dời hạn về quá khứ bằng psql (mỗi ticket đúng 1 dòng) → worker thật (đồng hồ thật, quét 15 giây) bắn hạn cả 3 trong ≤ 45 giây: chờ duyệt → E6 + phiếu `timeout` + escalation E6, **0 dòng audit B17** (đối chứng `B16 approval_timeout` có) — bất biến "hết hạn không tự thực thi" trên stack; chờ trả lời → E4 + escalation E4; chờ xác nhận → `S_RESOLVED` `resolved_auto_timeout_48h`; `wait_deadlines.fired_at` đã đặt |
| `make gate2 S=late-click` (người chạy, run `aaa48265`) | **10 PASS, 0 FAIL** — 2b-3-Q2 trên stack: `stop worker` → ticket `52b1df7c-…` chờ duyệt, phiếu 7 → dời hạn → l1 bấm duyệt → 409, phiếu **vẫn `pending`**, `late_event` (`expired`, approval 7, `l1_01`, `user`) → `start worker` → E6 + phiếu `timeout`, 0 dòng B17 (đối chứng B16 `approval_timeout` có) → bấm lại → 409, `late_event` thứ hai `already_decided` |
| `make gate2 S=kill` (người chạy, run `43187920`) | **8 PASS, 0 FAIL** — ticket `ced3bfb5-…` `[fake:kill_b06]` ngủ ở b06 (lượt mở) → `kill -s SIGKILL backend` → lượt vẫn mở → `up -d backend` → worker phục hồi → `S_PENDING_APPROVAL`; **cùng `turn_id` `def23064-…`, `recover_attempts=1`, 1 lượt đã đóng**; 1 phiếu; `side_effects` `approval_create`/`notify_approver` = 1/1; không `(step, event)` nào trùng. **Hạn chế của lần chạy này:** dòng "khoá advisory nhả ≤ 10 giây" (thấy 0) **không có đối chứng** — chưa chứng minh truy vấn `pg_locks` (classid/objid từ `hashtext`) tìm thấy được khoá khi đang giữ; trái chính quy ước "không có X cần đối chứng có Y" của script. **Sửa:** thêm kiểm "khoá đang giữ trước kill = 1"; `kill-b15` (cùng hàm `_kill`) sẽ chạy đối chứng này, chạy lại `kill` sau |
| `make gate2 S=kill-b15` (người chạy, run `b4aae64a`, có đối chứng khoá) | **9 PASS, 0 FAIL** — D-18 trên stack: ticket `2c69eb03-…` `[fake:kill_b15]` ngủ SAU `approval_create`, TRƯỚC `notify_approver` → **đối chứng: khoá advisory của ticket đang giữ = 1** (truy vấn `pg_locks` tìm đúng khoá) → SIGKILL backend → khoá nhả (0) ≤ 10 giây → lượt vẫn mở → `up -d backend` → worker phục hồi → `S_PENDING_APPROVAL`; cùng `turn_id` `c8a9b929-…`, `recover_attempts=1`; **đúng 1 phiếu**, `approval_create`/`notify_approver` = 1/1; audit không trùng |
| `make gate2 S=kill` lần 2 (người chạy, run `2949de7e`, có đối chứng khoá) | **9 PASS, 0 FAIL** — ticket `2703a100-…` ngủ ở b06; **đối chứng khoá đang giữ = 1** → SIGKILL → khoá 0 ≤ 10 giây → lượt vẫn mở → worker phục hồi → `S_PENDING_APPROVAL`; cùng `turn_id` `4dcc7d6c-…`, `recover_attempts=1`; 1 phiếu; `approval_create`/`notify_approver` 1/1; audit không trùng. Thay cho hạn chế của lần 1 |
| `make gate2 S=tc29` (người chạy, run `37786dd7`) | **9 PASS, 0 FAIL** — **cổng 2 dòng 4 (E9) trên stack**: ticket `8716fc55-…` `[fake:raise]` → `ValueError` ở `b06_diagnose` → `S_ESCALATED` E9; audit `unhandled_exception` (step `b06_diagnose`) có `exception`, `traceback`, `escalation_note`; span `error` có traceback (khung `builder.py` = lớp dừng `_pausable`, đúng thứ tự boundary → pause → node); 5 ticket song song tới `S_PENDING_APPROVAL`; worker vẫn `healthy` |
| `make gate2 S=threads` (người chạy, run `476e38c7`) | **2 PASS, 0 FAIL** — bảng 23 ticket gate2 (= 1 preflight + 3 restart lần 1 + 3 restart lần 2 + 3 late + 3 expire + 1 late-click + 1 kill lần 1 + 1 kill-b15 + 1 kill lần 2 + 6 tc29 — khớp số ticket các kịch bản đã tạo), mỗi ticket 7–14 checkpoint trên thread riêng; 0 thread không có dòng `tickets`. **Nói rõ giới hạn:** cột `threads` luôn ≤ 1 do truy vấn lọc `thread_id = ticket_id` — "mỗi ticket một luồng" đúng theo cách dựng (`Runner.config`: `thread_id = ticket_id`), phần có nội dung kiểm là "mọi ticket có checkpoint" + "không thread lạ". Mục thủ công của cổng 2 ("đọc bảng checkpoint") — xem dòng xác nhận của người ở tổng kết dưới |
| `make gate2 S=restart-all` (người chạy, run `14fe67f5`) | **16 PASS, 0 FAIL** — 3 ticket ở 3 trạng thái chờ → `down` (không `-v`) + `make up` (cả backend lẫn worker, image dựng lại) → chốt APP_ENV chạy lại → **số ticket trước/sau = 26/26** (23 ticket gate2 cũ + 3 mới) → cùng 3 kết quả như `restart` (E7 do RefusingExecutor, clarify → chờ duyệt với 1 `asked`, confirm → `resolved_user_confirmed`), checkpoint 14/13/10 |
| `make gate2 S=threads` lần 2 (người chạy, run `b8c98bed`, sau `restart-all`) | **2 PASS, 0 FAIL** — bảng 26 ticket gate2 (23 cũ + 3 của `restart-all`), mỗi ticket 1 thread, 7–14 checkpoint; 0 thread lạ |
| Sau 2 lần sửa script (`after_event`, đối chứng khoá) | `make lint` xanh, unit **1500 passed**, `gitleaks dir backend/tests/stack backend/tests/unit/test_gate2.py` không leak |
| Rà trước commit (người yêu cầu): mọi chỗ đọc trạng thái sau request 202 | Đổi sang `after_event` **7 chỗ**: sau tạo ticket ở `preflight`, `_three_waits` (dùng bởi restart/restart-all/late/expire), `late_click`, `tc29` (ticket lỗi + 5 ticket song song); sau quyết định duyệt và sau xác nhận ở `restart` (trước là `closed`); chờ phục hồi ở `_kill` (trước là `settled` — nay chờ lượt duy nhất cùng `turn_id` đóng). Bỏ hẳn `settled`; `closed` chỉ còn cho việc do WORKER làm (`expire`, `late_click` sau `start worker`). Test tĩnh `test_reads_after_202_always_wait_for_turn` (AST); **M11** (ticket lỗi của `tc29` quay lại `closed`) → đỏ. `make lint` xanh, unit **1501 passed**; **`make test` đầy đủ (người chạy, 27/09/2026) xanh: backend 1643 passed (1501 unit + 113 integration + 29 e2e) + mock 86 passed**. Các lần chạy `make gate2` ở trên dùng bản TRƯỚC lần rà này (7 chỗ cũ vẫn cho kết quả đúng vì chờ `final_state`/trạng thái chờ của ticket mới — không đọc được trạng thái cũ — nhưng không bảo đảm được như `after_event`) |

**Tổng kết `make gate2` trên máy dev (27/09/2026):** đủ 10 kịch bản, lần chạy cuối của mỗi kịch bản đều 0 FAIL. Hai FAIL
giữa chừng đều là lỗi SCRIPT, không phải lỗi hệ thống, đã sửa + có unit/mutation: (1) đọc trạng thái ngay sau 202
(`restart` lần 1 — audit xác nhận hệ thống đúng); (2) dòng "khoá nhả" thiếu đối chứng (`kill` lần 1 — chạy lại có đối chứng).
**Cổng 2 CHƯA đạt — chờ một thành viên khác chạy `make gate2 S=all` trên máy họ và dán kết quả** (vá 3; ưu tiên máy
gaming, kiêm ghi N2). **Tuấn Anh đã đọc bảng threads** (27/09/2026, bảng 26 ticket của run `b8c98bed`): mỗi ticket một
`thread_id` trùng `ticket_id`, số thread = số ticket, không thread lạ, mọi ticket có checkpoint — mục thủ công của cổng 2 xong. Spec đã đồng bộ (người cập nhật, 27/09/2026): `build/01-kien-truc-project.md` §7.1 thêm `make gate2`
(Q7), `build/decisions.md` 4.1 quyết định 2b-4.

**Còn lại của 2b-4:** cổng 2 chờ thành viên khác chạy `make gate2 S=all` (vá 3).

**Commit + CI:** `2a9f3ee` (19 file, gồm 2 file `docs/spec` người cập nhật) — CI GitHub **xanh**, run `36274714302`
(workflow `ci`, push `dev-tuananh`, 1m27s, 27/09/2026; người theo dõi, đã đối chiếu `headSha` = `2a9f3ee711db…`).
Cổng 2 vẫn **CHƯA đạt** — chờ thành viên khác chạy `make gate2 S=all` (vá 3).

## Phase 3 — chặng 3a: ml-service (27/09/2026, đang làm, chưa commit)

Thiết kế: `build/phase3-thiet-ke-chi-tiet.md` mục 4 (bản 1.1). Spec Phase 3 đã nằm trong commit `ce2429f` (local,
chưa push) — không còn file spec nào chờ stage. Kế hoạch Plan đã duyệt kèm chốt Q-3a-1…15 của người (27/09/2026).

**Quyết định của người (Q-3a):**
1. Torch lấy từ index `pytorch-cpu` trên linux (`[tool.uv.sources]` marker `sys_platform == 'linux'`); Mac giữ PyPI.
2. `MlResult.attempts` = số lần gọi LỖI (cùng nghĩa `ToolResult.attempts`, `call_with_retry`): 500,500,200 → 2; hết
   lượt → **3**. **Spec cần sửa:** a10 (ghi `attempts=2`) và mục 4.5 ("số lần thử lại").
3. `httpx.TransportError` khác timeout/connect (vd. `RemoteProtocolError` khi ml-service bị OOMKilled giữa request)
   → `error="connect"`, có retry — xử lý trong `MlClient`, **không sửa** `tools/retry.py`. **Lỗ tương tự ở tool đọc**
   (`call_with_retry` để lọt `ReadError`/`RemoteProtocolError` → E9 thay vì E2): quyết ở 3f.
4. `NodeDeps.ml` bắt buộc, không mặc định (FakeMlService nằm ở `tests/`).
5. `ML_SERVICE_TOKEN` backend: `Settings.ml_service_token` tuỳ chọn; `open_runtime` từ chối trước khi đụng DB;
   `create_app` từ chối khi dùng runtime mặc định; `conftest.py` gốc đặt token ngẫu nhiên.
6. `FakeMlService` = `httpx.MockTransport` sau `MlClient` thật; băm `blake2b` (không `mmh3` ở 3a).
7. Test sinh đôi a3f/a4f/a6f dùng tokenizer giả (thêm ĐÚNG 2 token đặc biệt), gọi code thật `tokens.py`/`rerank.py`.
8. Backend **và worker** `depends_on: ml-service: service_healthy`.
9. Image ml theo spec (`--group ml`) — đo kích thước, ghi ở đây.
10. Giữ `onnxruntime` trong nhóm ml. 11. `make tokenizer` để 3b.
12. Client: `attempts` cộng dồn qua lô, dừng ở lô lỗi đầu; chia lô thêm theo byte; một văn bản đơn vượt giới hạn
    byte → `MlContractError` thông điệp rõ; `MlResult.model_version` từ `X-Model-Version`; span = dòng log.
13. `/classify`, `/classify_intent` Phase 3: token → body (422) → 503 `model_missing`, kể cả khi có thư mục.
14. **Không** commit lock với revision null: người chạy `make models` trước commit 3a; test tĩnh: `models.lock.json`
    phải có revision 40 hex.
15. Spec cần sửa (Claude chat): xem cuối mục.

**Sửa thêm của người:** compose không truyền biến int rỗng (`ML_THREADS`, `ML_MAX_CONCURRENCY`) + test tĩnh;
`ML_MAX_CONCURRENCY` mặc định 1; `make ml-bench` đo rerank 20 và 32 đoạn, timeout rerank tạm 10 s (chỉnh theo số đo
≥ 2 × p95 lô 32); `make models` dùng `uv run --with huggingface_hub` (không kéo torch); `make test-ml` thiếu model →
FAIL; ml_real assert đoạn không liên quan có điểm < 0,5 (bắt sigmoid hai lần).

**Nhật ký bước (1→11 của plan):**
- **B1 xong** — `uv remove --group ml FlagEmbedding`, `uv add --group ml sentence-transformers`, index `pytorch-cpu`
  cho linux. Kiểm xanh: `uv lock --check`; `uv.lock` 0 dòng `flagembedding`, 0 gói `nvidia-*` (trước: 15); torch
  linux = `2.14.0+cpu` (aarch64 + x86_64), mac = `2.14.0` PyPI; `uv sync --locked` (nhóm dev) OK. `uv lock` cần
  host `download-r2.pytorch.org` (đã khai báo cho lệnh đó).
- **B2 xong** (+ `scripts/download_models.py` của B7 làm sớm vì test ml cần) — `ml_service/app/` (settings, lock,
  models, tokens, embed, rerank, classify, intent, auth, limits, loader, main, bench), `ml_service/tests/` (conftest
  tokenizer giả +2 token đặc biệt, security, endpoints, lock, download_models, real_models = ml_real). pyproject:
  marker `ml_real`, override mypy cho torch/sentence_transformers/transformers/huggingface_hub. Kiểm:
  `pytest ml_service/tests -o pythonpath=ml_service -m "not ml_real"` **56 passed, 1 failed** — failed là
  `test_repo_lock_pins_40_hex_revisions` (chưa có `ml_service/models.lock.json`; đỏ tới khi người chạy `make models`,
  đúng Q-3a-14); mypy `ml_service/app` 15 file xanh; ruff xanh.
- **B3 xong** — `backend/app/ml/` (`models`, `ports`: `MlPort`, `MlResult`, `MlContractError`; `client`: `MlClient`
  dùng `call_with_retry`, chia lô theo số + byte), `backend/tests/fakes/fake_ml.py` (MockTransport, blake2b),
  `unit/test_ml_client.py` (a9–a13 + TransportError, 429, 404, schema, byte, hằng khớp `ml_service/app/schemas.py`,
  log không văn bản), `unit/test_fake_ml.py` (a14). Kiểm: 29 passed; `mypy backend/app` 125 file xanh; ruff xanh.
- **B4 xong** — `Settings.ml_service_token` + `require_ml_token()`; `NodeDeps.ml: MlPort` bắt buộc; `wiring.open_runtime`
  từ chối thiếu token trước DB rồi dựng `MlClient` (client HTTP đóng khi thoát); `create_app` từ chối khi dùng runtime
  thật mà thiếu token; `_default_checks` thêm `"ml"` (GET `/health`, không token); `conftest.py` gốc đặt
  `ML_SERVICE_TOKEN` ngẫu nhiên; `tests/fakes/graph.py` (`GraphHarness.ml`), `integration/graph_pg.py` truyền
  `FakeMlService`. Test: `test_health` (+2, đổi tên test tập check), `test_app_env` (+6). Kiểm: unit **1538 passed**
  (1501 + 37); `--collect-only` integration + e2e 142 test (113 + 29) thu thập được; mypy, ruff xanh.
- **B5 xong** — `.importlinter`: `app.ml` vào nguồn hợp đồng 3 và vào cấm của hợp đồng 4; hợp đồng mới **6
  `ml-only-core`** (ml cấm import mọi module nghiệp vụ + `app.tools`, `ignore_imports = app.ml.client -> app.tools.retry`).
  Kiểm: `lint-imports` 6 kept; thử phá (ml/ports import `tools.registry`; domain/action import `ml.ports`) → đúng 2 hợp
  đồng BROKEN (6 và 4), hoàn nguyên, không còn dấu `MUTATION`, `git diff` 2 file trống; `test_write_adapters_listed` xanh.
- **B6 xong** — `ml_service/Dockerfile` (khuôn mock, `uv sync --frozen --no-dev --group ml --no-install-project`,
  `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HOME=/tmp/hf`, không copy `models/`, 1 worker); compose: service
  `ml-service` (không `ports`, `${MODELS_DIR:-./models}:/models:ro`, healthcheck start_period 180s, env chỉ
  `ML_SERVICE_TOKEN` `:?` + `MODELS_DIR`), `x-backend-env` thêm `ML_SERVICE_TOKEN` `:?`, backend + worker
  `depends_on ml-service: service_healthy`; `.env.example` `ML_SERVICE_TOKEN=` trống; `.gitignore` `/models/`; Makefile:
  `models`, `test-ml`, `ml-bench`, dòng pytest thứ 3 trong `test`, mypy ml_service trong `lint`, `up` kiểm model trước
  (`python -m app.lock`) + build ml-service + in log ml-service khi không lên. `ml_service/README.md`.
  **Lệch nhỏ so với 3.5:** `MODELS_DIR` là biến make/shell (Makefile `export`), KHÔNG đặt trong `.env` — env shell
  đè `.env` khi compose nội suy, để trong `.env` thì `make up` kiểm một chỗ mà mount chỗ khác.
  Test tĩnh mới `unit/test_ml_deploy.py` (10). Kiểm: `docker compose config` (bản sao `.env.example` có token giả ở
  `$TMPDIR`) OK — ml-service không ports, volume `read_only`, backend/worker `service_healthy`; thiếu token → dừng
  "required variable ML_SERVICE_TOKEN is missing a value"; `python -m app.lock ./models` khi chưa có model → exit 1
  "chạy `make models`"; test tĩnh + `test_stack_scenario` + `test_worker_heartbeat` xanh.
- **B7 xong (làm cùng B2)** — `scripts/download_models.py` (`uv run --with huggingface_hub`): chưa có lock → SHA hiện tại
  của từng repo, tải, ghi lock; có lock → tải đúng SHA, lock lệch repo/revision → exit 1; bỏ `onnx/*`, `*.onnx`,
  `colbert_linear.pt`, `sparse_linear.pt`, `imgs/*`, và `pytorch_model.bin` khi repo có `model.safetensors`. Thư mục
  `models/<repo>@<sha>` khớp `ml_service/app/lock.py`. **`ml_service/models.lock.json` CHƯA có** — người tạo bằng
  `make models` (Q-3a-14); tới lúc đó `test_repo_lock_pins_40_hex_revisions` đỏ.
- **B8 xong** — `make lint` **xanh**: ruff; mypy backend 125 file, mock 11, ml_service 15; `lint-imports` 6 kept;
  `gitleaks detect` 35 commit không leak. Unit backend **1548 passed** (1501 + 47); mock **86 passed**; ml
  **56 passed, 1 failed** (chỉ `test_repo_lock_pins_40_hex_revisions` — chờ lock), 5 deselected (`ml_real`).
  `gitleaks dir` trên `ml_service`, `backend/app/ml`, `fake_ml.py`, `test_ml_client.py`, `test_ml_deploy.py`,
  `scripts`, compose, `.env.example`, Makefile, `conftest.py`, pyproject: không leak.
- **B9 xong (phần sandbox)** — mutation logic **13/13 đỏ đúng test dự đoán** (script áp → chạy → khôi phục → so md5;
  sau cùng `git diff --stat` khớp, `grep MUTATION` trống): M-3a-1 bỏ kiểm token → 11 đỏ (`test_missing_token_401` ×5,
  `test_wrong_token_401` ×5, header); **M-3a-2** truncated luôn False → `test_a4f`; **M-3a-3** đếm không token đặc biệt →
  `test_a3f` + `test_a4f`; **M-3a-4** retry cả model_missing → `test_a11` ×2 + fake; **M-3a-5** nuốt 5xx → `test_a10` + 7;
  **M-3a-6** không cắt câu truy vấn → `test_a6f`; M7 bỏ nhánh TransportError → 3; M8 không chia lô theo byte → 1; M9 bỏ
  sigmoid → `test_a5`; M10 bỏ giới hạn body → 2; M11 health bỏ `ml` → 2; M12 worker không kiểm token → 2; M13 bỏ handler
  422 (vọng lại input) → `test_logs_never_contain_text`. Lần chạy đầu 2 đột biến viết SAI (không phải test yếu): M-3a-2
  chèn comment giữa dòng làm hỏng lời gọi (đỏ vì lỗi setup, không vì assert); M13 regex không khớp nên không áp gì
  ("SỐNG") — sửa script, thêm chặn "đột biến không áp được", chạy lại cả bộ. Script (người yêu cầu đưa vào repo):
  **`scripts/mutation/mutate_3a.py`** — đường dẫn tương đối theo vị trí file, không đọc `.env`; chạy lại từ chỗ mới:
  13/13 đỏ, md5 khớp, ruff xanh. Chế độ `--real` (M-3a-2/3/6, M9 + **M14** bỏ `activation_fn=Identity` =
  sigmoid hai lần — chỉ model thật bắt được) chờ người chạy sau `make models`.
- **B10 đang chờ người** (Docker/mạng, chạy bằng `!`; `ML_SERVICE_TOKEN` đã có trong `.env` — người xác nhận):
  `colima list` → `make models`
  → `make test-ml` → `uv run python scripts/mutation/mutate_3a.py --real` → `make up` → a15 (ps, `/api/health` 200, stop ml-service → 503 có `ml`, start) →
  `make ml-bench` + `docker stats` (3-Q39: tổng > 7 GB → tăng RAM colima, sửa README) → kích thước image ml (Q-3a-9)
  → `make test` trên code sạch. Kết quả dán vào đây (B10), rồi B11.
  - `colima list` (người chạy, 27/09/2026): aarch64, 4 CPU, **8 GiB**, đĩa **20 GiB** — RAM đo sau `make up`; đĩa VM có
    thể chật khi thêm image ml (model nằm trên máy, mount vào, không tốn đĩa VM).
  - `make models` (người chạy, 27/09/2026): xong, exit 0, ~9 phút. Lock: `BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181`,
    `BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`; mỗi thư mục 2,1 GB (bge-m3 chỉ có
    `pytorch_model.bin`, không có safetensors; ONNX/colbert/sparse đã bỏ). `models/` bị gitignore; lock untracked, chờ
    commit. Sau đó (sandbox): `python -m app.lock ./models` → đủ model; test ml **57 passed** (test lock 40 hex đã xanh).
  - `make test-ml` (Claude chạy trong sandbox, không cần Docker, 27/09/2026): **5 passed** trong 57 giây (a3, a4, a5 thật
    có assert đoạn không liên quan < 0,5, a6, a16) — bge-m3 dạng `pytorch_model.bin` nạp được với transformers 5.17 +
    torch 2.14 (mac).
  - `scripts/mutation/mutate_3a.py --real` (sandbox): **5/5 đỏ đúng test dự đoán** — M-3a-2 → `test_a4`, M-3a-3 → `test_a3`,
    M-3a-6 → `test_a6`, M9 bỏ sigmoid → `test_a5_real`, **M14 sigmoid hai lần** (bỏ `activation_fn=Identity`) →
    `test_a5_real`; md5 khớp, `git diff --stat` khớp, không còn dấu `MUTATION`.
  - `make up` (người chạy, 27/09/2026): **xanh**, exit 0. Image `servicedesk-ml:dev` build: `torch==2.14.0+cpu`,
    sentence-transformers 6.1.0, transformers 5.17.0, onnxruntime 1.30.0, **0 gói nvidia** (Q-3a-1 hiệu lực), 132 gói;
    alembic không có migration mới; ml-service `Healthy` rồi backend + worker mới start (depends_on); mock ok; seed 16
    người, 7 thiết bị; `worker: healthy`; `/api/health` =
    `{"status":"ok","checks":{"db":"ok","qdrant":"ok","mock":"ok","ml":"ok"},"failed":[],"runtime":"up"}`.
  - **a15 phần "tắt ml-service"** (người chạy, 27/09/2026): `compose stop ml-service` → `/api/health` **503**
    `{"status":"degraded","checks":{…,"ml":"error: ConnectError"},"failed":["ml"],"runtime":"up"}` — đúng 3-Q9.
    `compose start ml-service` → `/api/health` **200**, `"ml":"ok"` (backend tự hồi phục, không cần restart). **a15 đạt.**
  - `make ml-bench` (người chạy, 27/09/2026; exit 2 chỉ do gõ thừa đối số `—` sau target — phần đo đã chạy hết). Colima
    4 CPU / 8 GiB, `ML_THREADS` mặc định 3, `ML_MAX_CONCURRENCY` 1. Đoạn đo = 278 token, cặp (query, đoạn) = 296 token
    (đếm bằng tokenizer reranker thật):

    | Đo | n | p50 | p95 | Mục tiêu P4 §9 |
    |---|---|---|---|---|
    | embed 1 câu | 50 | 118,6 ms | **228,1 ms** | < 300 ms — **đạt** |
    | rerank 20 đoạn | 20 | 15 105 ms | **15 626 ms** | < 2 s — **KHÔNG đạt** (gấp ~8 lần) |
    | rerank 32 đoạn | 20 | 24 482 ms | **33 213 ms** | — |

    ≈ 0,75 s mỗi cặp ~300 token (bge-reranker-v2-m3 fp32, CPU, 3 luồng). RAM: RSS ml-service **3 615 MB** (`docker stats`
    3,474 GiB); tổng các container servicedesk ≈ 3,8 GiB (+ `voca_pg16_dev` của dự án khác 46 MiB) trên 7,737 GiB →
    **< 7 GB, KHÔNG cần tăng RAM colima** (3-Q39), README giữ nguyên.
  - **Kích thước image ml (Q-3a-9, người chạy 27/09/2026):** `servicedesk-ml:dev` = **2,6 GB** (`--group ml`, gồm cả deps
    chính của project — presidio/spacy, langgraph… — và torch CPU; không có model). Chấp nhận theo chốt Q-3a-9; nếu đĩa VM
    colima 20 GiB chật thì cách giảm là `--only-group ml` + khai báo fastapi/uvicorn/pydantic-settings/httpx vào nhóm ml
    (chưa làm; 3e gỡ presidio cũng giảm một phần).
  - **Số đo tóm tắt:** embed 1 câu p95 **228 ms**; rerank 20 đoạn p95 **15,6 s**; rerank 32 đoạn p95 **33,2 s**; RSS
    ml-service **3,6 GB** (colima 4 CPU / 8 GiB, `ML_THREADS` 3, cặp 296 token, 27/09/2026).
  - **Q-3a-16 — ĐÃ CHỐT (người, 27/09/2026):** 3a **giữ timeout rerank 10 s**; cấu hình quyết ở **3c** khi có độ dài đoạn
    KB thật, theo thứ tự thử: `RAG_RERANK_K=10` → `ML_THREADS=4` → int8 (phải đo độ lệch điểm). Lý do không theo luật
    "≥ 2 × p95 lô 32" (≥ 66 s): 3 lần thử × 66 + 3 s backoff ≈ 200 s > `WORKER_STALE_TURN_SECONDS` = 120 → worker recover
    lượt còn đang chạy; biên an toàn: 3·T + 3 < 60 → T ≤ 19 s. Hệ quả đã biết: với số đo hiện tại, rerank 20 đoạn
    ~300 token sẽ timeout → B8 ra E2 — phải xử lý ở 3c trước khi B8 thật chạy.
    **Khoá trần (thêm ở 3a):** `unit/test_ml_timeouts.py` (7) — mọi phương thức của `MlPort` có timeout; với mọi
    endpoint: (TOOL_RETRY + 1) × `TIMEOUT_S[ep]` + tổng backoff < `worker_stale_turn_seconds` mặc định / 2, đọc hằng thật
    (`client.TIMEOUT_S`, `policy.json`, `Settings.model_fields`); đối chứng công thức 10 s → 33 s. Biên tính cho MỘT
    request (lượt graph: embed 1 câu, rerank ≤ 20 ≤ 32 đoạn = 1 lô). **Mutation M15** timeout rerank 30 s →
    `test_worst_case_call_under_half_stale_turn[rerank]` **đỏ** (93 s ≥ 60 s), đã hoàn nguyên (md5 khớp). Script thêm
    `--only <tiền tố>`. Unit backend sau khi thêm: **1555 passed** (1548 + 7).
  - **`make test` đầy đủ (người chạy, 27/09/2026, code sạch sau mọi mutation): XANH** — backend **1697 passed** (1555 unit +
    113 integration + 29 e2e, gồm `graph_pg` với `FakeMlService`, `test_stack_scenario_pg` qua `open_runtime` có
    `MlClient` thật), mock **86 passed**, ml **57 passed** (5 `ml_real` deselected; `make test-ml` 5 passed riêng).
- **B10 xong.** **B11 xong** — PROGRESS cập nhật (mục này). **Chặng 3a: code + unit + lint + mutation (13 + 5 thật + M15)
  + `make test` + stack xanh; CHƯA commit** — chờ người bảo. Khi commit phải có `ml_service/models.lock.json`
  (untracked) và `scripts/` (download_models.py, mutation/mutate_3a.py); KHÔNG có `models/`.
- **Commit + CI:** `00e72b0` (56 file, gồm 4 file `docs/spec` Claude chat sửa: phase3 v1.2, P4 v1.3, 01 v1.7, decisions) —
  push `dev-tuananh` (kèm `ce2429f`); CI GitHub **xanh**, run `36328742986` (workflow `ci`, 27/09/2026; người theo dõi).
  **Chặng 3a đóng.** Việc mở chuyển sang 3c: Q-3a-16 (cấu hình rerank). Chặng kế tiếp theo thứ tự: 3b (RAG ingest).

**Spec cần sửa (Claude chat sửa `docs/spec`; Claude Code không sửa — Q-3a-15):**
**→ ĐÃ SỬA** (Claude chat, 27/09/2026): `phase3-thiet-ke-chi-tiet.md` v1.2 (mục 4.12 mới; a4/a6/a10, 4.5, 4.6, 3.5, 4.11),
P4 v1.3, `01` v1.7, `decisions.md` 4.1. **Claude Code đối chiếu với code: khớp nội dung.** Lệch CHỮ còn lại (code đúng
chốt, không sửa code): (1) bảng 4.8 dòng a3 vẫn ghi "unit (ml, tokenizer thật)", a16 "probe" — 4.12 (Q-3a-7) xếp cả hai là
`ml_real`, code theo 4.12; (2) 4.12 Q-3a-5 ghi "`create_app` từ chối" — code từ chối khi dùng runtime THẬT (không tiêm
`runtime=`), đúng chốt Q-3a-5; test tiêm runtime giả không cần token; (3) "≤ 200 KB/request" = `MAX_REQUEST_BYTES =
200 * 1024` (KiB); (4) P4 §3 dòng Torch còn `set_num_threads(N_CPU)` — code dùng `ML_THREADS` (vCPU − 1, P4 §6).
Các mục dưới giữ để truy vết.
1. `phase3-thiet-ke-chi-tiet.md` mục 4.8 a10 + mục 4.5: `attempts` hết lượt = **3** (số lần gọi lỗi, cùng nghĩa
   `ToolResult.attempts`), không phải 2 / "số lần thử lại" (Q-3a-2).
2. Mục 4.8: nhãn a4 ("model giả nhỏ"), a6 ("unit") → ml_real như mục 4.7; thêm a3f/a4f/a6f (tokenizer giả, make test)
   và a5 ml_real "đoạn không liên quan < 0,5" (Q-3a-7).
3. Mục 4.6: FakeMlService băm `blake2b` (không `mmh3` ở 3a); là `httpx.MockTransport` sau `MlClient` thật (Q-3a-6).
4. Mục 3.5: `MODELS_DIR` là biến make/shell (Makefile export), không đặt trong `.env`; `ML_THREADS`/`ML_MAX_CONCURRENCY`
   không truyền qua compose, mặc định ở `ml_service/app/settings.py` (`ML_MAX_CONCURRENCY` = 1, P4 §6 ghi 4).
5. Mục 4.7: `make models` dùng `uv run --with huggingface_hub` (không `--group ml`); `make tokenizer` để 3b (Q-3a-11);
   worker cũng `depends_on ml-service healthy` (Q-3a-8).
6. Mục 4.10/4.4: lock không bao giờ có revision null — lock trong repo phải 40 hex (Q-3a-14).
7. **P4 §9 "rerank 20 đoạn p95 < 2 giây" chỉ đúng với GPU** — CPU 4 vCPU đo 15,6 s (cặp ~300 token); mục 4.11 của thiết
   kế Phase 3 cũng vậy. P4 §3 vẫn ghi FlagEmbedding (3-Q19 đè lên).
8. `01-kien-truc-project.md`: §3 cây thư mục thêm `backend/app/ml/`, `scripts/`; §4.2 đồ thị thêm `ml ──► core
   (+ tools.retry)` và `rag, guard, graph ──► ml`; §4.3 thêm hợp đồng `ml-only-core` (nay 6 hợp đồng import-linter).
9. Mục 4.5: timeout phải thoả trần (lần thử × timeout + backoff < stale/2 — `test_ml_timeouts.py`); rerank 10 s tạm,
   quyết ở 3c (Q-3a-16).
10. Lỗ ở tool đọc: `call_with_retry` để lọt `httpx.ReadError`/`RemoteProtocolError` → E9 thay vì E2 — quyết ở 3f (Q-3a-3).

## Phase 3 — chặng 3b: RAG ingest (27/09/2026, đang làm, chưa commit)

Kế hoạch đã duyệt: `PLAN-3b.md` ở gốc repo (KHÔNG commit). Thiết kế: `build/phase3-thiet-ke-chi-tiet.md` mục 5
(bản 1.2); khi lệch, `PLAN-3b.md` thắng (đã gồm chốt Q-3b), trừ bất biến và mục [Chốt] của spec.

**Quyết định của người (Q-3b, 27/09/2026):**

| Mã | Chốt |
|---|---|
| Q-3b-1 | Ingest gọi `embed` theo nhóm `INGEST_EMBED_GROUP = 1` (cả đoạn KB lẫn câu hỏi bộ kiểm tra); không sửa `MlClient`/`TIMEOUT_S`; bước 7 in thời gian embed (tổng, p50, max) |
| Q-3b-2 | `content_sha256` = sha256(canonical_json(front matter, MỌI trường) + "\n" + thân đã normalize); tài liệu disabled vẫn so ở bước 4, upsert `kb_documents` với `kb_version = NULL`; `doc_count` chỉ đếm enabled |
| Q-3b-3 | Bước 10 đạt → ghi báo cáo cổng + `chunk_count` vào metadata collection trước khi đổi alias; ghi bù đọc số từ đó |
| Q-3b-4 | Cổng (c) đánh giá lại cả bản cũ (đích alias) bằng bộ kiểm tra hiện tại, cùng retriever |
| Q-3b-5 | Index duy nhất dạng cột `ux_kb_versions_current ON kb_versions (is_current) WHERE is_current` |
| Q-3b-6 | `rag/filters.py` tạo ngay ở 3b (`allowed_sensitivity`, `base_filter`) |
| Q-3b-7 | Payload Qdrant có thêm `owner` |
| Q-3b-8 | `pipeline_sha` trong metadata collection; alias đúng `kb_<v>` mà `pipeline_sha` lệch → mã 1 "cấu hình ingest đã đổi" |
| Q-3b-9 | `tokenize_vi`: giữ mã (`CODE_RE`) TRƯỚC rồi mới mở viết tắt |
| Q-3b-10 | `FakeMlService` giữ `blake2b`; `mmh3` chỉ ở `rag/bm25.py` |
| Q-3b-11 | `uv add --dev tokenizers`; `LocalTokenizerCounter` chỉ cho test (marker `tokenizer_real`, `make tokenizer`); CLI không có tuỳ chọn chọn bộ đếm |
| Q-3b-12 | Mã thoát 0/1/2 (1 = lỗi trước đổi alias; 2 = lỗi bước 12–14); `--allow-unevaluated` + `APP_ENV ∉ {dev,test}` → 1 ở bước 0 |
| Q-3b-13 | Luật loader bổ sung (`###` trước `##`, `####`, tiền tố doc_id ↔ request_type, `supersedes`, ngày tương lai theo UTC+7, KB không có tài liệu enabled, fact không có nhóm bắt, bộ kiểm tra thiếu câu âm tính) |
| Q-3b-14 | Fixture `KB-VPN-003` sắp lại thành 6 bước trải 3 mục H2; `KB-VPN-001` chép nguyên văn bản mẫu |
| Q-3b-15 | Khoá advisory Postgres chặn 2 lượt ingest đồng thời; `kb_version` quay lại → upsert `kb_versions` giữ `created_at` cũ; bước 14 xếp theo `created_at` |
| Q-3b-16 | `.importlinter` hợp đồng 7 `rag-lower-layer` |
| Q-3b-17 | Test spy cho `switch_alias` (1 lời gọi, 2 thao tác); M-3b-5 vẫn kiểm bằng review |

**Ghi chú cho 3c:**
- `retrieve` phải so `pipeline_sha` của collection đã ghim với cấu hình hiện tại (`kbversion.pipeline_sha`); lệch →
  E2 `rag_system_error`, không truy hồi tiếp (Q-3b-8).
- Cổng kiểm của 3b là **dense-only** (`DenseOnlyRetriever`), cosine ≠ thang điểm rerank mà `RETRIEVAL_THRESHOLD` dành
  cho → `make ingest` với model thật ở 3b **có thể đỏ cổng kiểm — dự kiến**; KB thật chỉ nạp được sau 3c (thay bằng
  adapter quanh `retrieve()`).

**Spec cần sửa (3b) — Claude Code không sửa `docs/spec/`:**
1. 5.2: thiếu `rag/ingest/config.py` (P3 §7 có), `db/kb.py`, `rag/filters.py` (kéo từ 3c, Q-3b-6).
2. 5.4: regex SSTP ví dụ (`…cổng\s*(?:TCP\s*)?…`) khác `kb-mau/kb-facts.md` (`…TCP\s*(\d{2,5})`) — code theo bản mẫu.
3. 5.7: danh sách payload thiếu `owner` (3-Q40 ghi giữ) — Q-3b-7.
4. 5.8 bước 12: ghi `kb_versions` **trước** `kb_documents` (FK không hoãn) và tắt `is_current` cũ trước khi bật mới
   (index duy nhất); bước 3½ khoá advisory; bước 5 thêm nhánh `pipeline_sha` (Q-3b-8) và ghi bù lấy số từ metadata
   collection (Q-3b-3).
5. 5.8 bước 10 (c): so bằng cách đánh giá lại bản cũ (Q-3b-4).
6. 5.9: KB-VPN-003 "6 bước trải 3 mục H2" khác bản mẫu `kb-mau/KB-VPN-003.md` (2 mục) — fixture sắp lại (Q-3b-14).
7. 5.10: index `((true))` → dạng cột `(is_current) WHERE is_current` (Q-3b-5); "mmh3 dùng bởi FakeMlService" là sai —
   FakeMl dùng blake2b (Q-3b-10; 4.12 dòng Q-3a-6 "mmh3 để 3b" cũng cần sửa).
8. 3.5: `RAG_KEEP_OLD_COLLECTIONS` là mặc định trong settings, không truyền qua compose.
9. P8 §4.2 ghi `eval/kb-facts.md`; hướng dẫn soạn KB và thiết kế 3b dùng `kb/kb-facts.md` (câu hỏi mở số 5).
10. `01-kien-truc-project.md` §4.3: thêm hợp đồng 7 `rag-lower-layer` (nay 7 hợp đồng import-linter).
11. 5.5: thêm luật loader Q-3b-13 (`###` trước `##`, `####`, tiền tố doc_id ↔ request_type, `supersedes`, UTC+7).

**Nhật ký (S0–S17 của `PLAN-3b.md` mục 11):**
- **S0 xong** — mục này.
- **S1 xong** — `uv add mmh3` (chính, 5.3.0) + `uv add --dev tokenizers` (0.23.2): mạng PyPI đi được trong sandbox nên
  Claude chạy luôn (không phải nhờ người); marker `tokenizer_real` trong pyproject. Kiểm: `uv lock --check` xanh,
  `uv run --locked python -c "import mmh3, tokenizers, pyvi"` ok.
- **S2 xong** — `core/textnorm.py` (`normalize`, `fold_diacritics`, chỉ stdlib) + `unit/test_textnorm.py` (b20, 7 test).
  Kiểm: 7 passed; mypy `backend/app` xanh. (Ghi chú: công cụ Write của Claude đổi `\uXXXX` thành ký tự thật — đã
  sửa về dạng escape trong mã nguồn và test.)
- **S3 xong (phần sandbox)** — migration `0006_kb_content_hash.py`, model `KbVersion` (`chunk_count`, `eval_status`,
  CHECK `ck_kb_versions_eval_status`, index `ux_kb_versions_current`), `KbDocument.content_sha256`,
  `KB_EVAL_STATUSES`; `unit/test_db_models.py` +1 (b30); `integration/test_migration_0006.py` (3 test, b36). Kiểm:
  test_db_models 8 passed; collect-only 3 test; ruff, mypy xanh. **Chạy thật (Docker) → người** (lệnh 3 mục 12).
- **Hai chỗ plan im lặng — người chốt (27/09/2026):** (1) `--dry-run` chạy bước 4 và 5 **chỉ đọc**: (i) `pipeline_sha`
  lệch → 1, (ii) "KB không đổi" → 0, (iii) KHÔNG ghi bù, in "sẽ ghi bù khi chạy thật" rồi đi tiếp bước 6; không
  lấy khoá, không ghi gì (cần DB + Qdrant). (2) Lỗi không gắn dòng (thư mục lạ, KB không có tài liệu enabled, thiếu
  `kb-facts.md`) in `{rel_path}: {message}` — bỏ phần dòng.
- **S4 xong** — `rag/models.py` (`FrontMatter`, `IngestIssue`, `IngestError`, `IngestMlError`, `Doc`, `Block`, `Chunk`,
  `ChunkPayload`, `IngestReport`), `rag/ingest/config.py`, `frontmatter.py`, `loader.py`; helper test
  `tests/fakes/kb.py` (`FIXTURE_KB`, `KB_TEST_NOW`, `copy_kb`, `write_doc` — file helper nhỏ ngoài danh sách plan).
  `unit/test_rag_frontmatter.py` 30 test (b1 8 ca + ngày theo giờ VN + nhiều file + YAML/fence; b2 6; b21 3; b22 8).
  Phần b1 "`run_ingest` trả 1" viết ở S12 (khi có pipeline). Kiểm: 30 passed; ruff, mypy xanh.
- **S5 xong** — `facts_check.py` (`load_facts`, `check_docs`, `check_facts`; lỗi schema trỏ dòng của fact qua
  `yaml.compose`); fixture `backend/tests/fixtures/kb/kb-facts.md` chép nguyên văn bản mẫu (test so byte).
  `unit/test_rag_facts.py` 10 test (b3). Kiểm: 10 passed; ruff, mypy xanh.
- **S6 xong** — `rag/token_counter.py` (`TokenCounter`, `MlTokenCounter`, `LocalTokenizerCounter` import muộn),
  `tests/fakes/token_counter.py` (`WordCounter`), `tests/fakes/tokenizer.py` (`bge_m3_tokenizer_path`,
  `require_bge_tokenizer`); `unit/test_rag_token_counter.py` (b29 + đếm thật `tokenizer_real`, 5 test). **Fixture KB**
  `backend/tests/fixtures/kb/`: `kb-facts.md` + `KB-VPN-001` chép nguyên văn bản mẫu; 002 (disabled, 2 H2), 003
  (sắp lại 5 H2: mục bước 185/185/161 token), 004 (mục H2 3 đoạn: p1+p2 = **344**, p1+p2+p3 = **412** token thật),
  005, 007 (restricted); `eval/retrieval_set.yaml` 8 P + 6 N. Fixture: 6 tài liệu, 0 lỗi loader, 0 lỗi kb-facts.
  Số đo bằng tokenizer bge-m3 thật (`models/BAAI/bge-m3@5617a9f…/tokenizer.json`, 27/09/2026). Kiểm: 5 passed.
- **S7 xong** — `rag/ingest/chunker.py` (`chunk_doc`: làm sạch HTML giữ số dòng, chia mục `##`/`###`, khối + khối danh
  sách, gom tham lam bằng đếm lô MỌI tiền tố, tách mục danh sách / câu, gộp đoạn nhỏ cùng H2, `text`, `chunk_id`;
  `Block.atomic` đánh dấu câu đã tách). Chỗ plan không nói, chọn theo văn bản gốc: mục danh sách tách ra nối lại bằng
  đúng cách xuống dòng gốc ("\n" hoặc "\n\n"), câu nối bằng " " hoặc "\n" như gốc. `unit/test_rag_chunker.py` 15 test
  (b4 ×2 `tokenizer_real` **PASSED, không skip**; b5 ×6; b6; b7; tách câu/danh sách; HTML/"Tổng quan"; text > 480).
  Số đo tokenizer thật ghi ở comment đầu file test. Giả lập cổng với FakeMl trên fixture (script tạm, không vào repo):
  Recall@5 = 8/8, max cosine câu âm tính 0,282 < 0,6; tắt KB-VPN-004 → chỉ P006 trượt.
- **S8 xong** — `config/vi_abbrev.yaml` (12 mục), `config/vi_stopwords.txt` (40 từ, không có "không"/số), `rag/bm25.py`
  (`load_lexicon` lru_cache, `tokenize_vi` giữ mã trước viết tắt, pyvi nạp muộn, `to_sparse` mmh3 cộng dồn va chạm);
  pyproject thêm override mypy `pyvi.*` (pyvi không có stub). `unit/test_rag_bm25.py` (b8 8 ca gồm `negation`,
  `ma-truoc-viet-tat`; b9; băm thật) + `test_config_files.py` +2 (b26, gồm `test_stopwords_exclude_negation`).
  Kiểm: 21 passed; ruff, mypy xanh.
- **S9 xong** — `rag/ingest/kbversion.py` (`kb_version`, `canonical_front_matter`, `content_sha256`, `pipeline_sha` —
  gồm sha 2 file config, trần chia đoạn, `CODE_RE`, cách băm, bản pyvi). `unit/test_rag_kbversion.py` 6 test (b10 gồm
  `test_b10_order_independent`). Kiểm: 6 passed; ruff, mypy xanh.
- **S10 xong (phần sandbox)** — `rag/filters.py` (`allowed_sensitivity`, `base_filter`), `rag/vector_store.py`
  (`VectorIndex`, `QdrantIndex`, `VectorStoreError` bọc lỗi Qdrant; `switch_alias` một lệnh), `integration/qdrant.py`
  (`QDRANT_IMAGE` = `qdrant/qdrant:v1.19.1`, `wipe_kb`), `integration/conftest.py` fixture `qdrant_url` (session,
  `QdrantContainer`) + `clean_qdrant`. `unit/test_rag_filters.py` (b25, 11) + `unit/test_rag_vector_store_spy.py` (b27,
  2). Kiểm: 13 passed; ruff, mypy xanh; integration thu thập được.
- **S11 xong** — `rag/ingest/gate.py` (`RetrievalSet`/`EvalItem` `extra="forbid"`, `load_retrieval_set`,
  `DenseOnlyRetriever` — embed nhóm 1, `base_filter(role)`, prefetch 20, bỏ trùng doc; `metrics` thuần; `decide`
  nhánh a/b/c). `unit/test_rag_gate.py` 24 test (b23 8 ca; b24 chỉ số tay + biên 0,80 / 0,05 / tụt đúng 0,05 và
  0,05 + 0,001). Kiểm: 24 passed; ruff, mypy xanh.
- **S12 xong (phần sandbox)** — `db/kb.py` (`KbRepo`: `doc_rows`, `current`, `version_row`, `known_users`,
  `created_order`, `write_version` một transaction đúng thứ tự tắt current → upsert version → upsert docs, `try_lock`/
  `release` khoá advisory; `DocRow`, `KbVersionRow` đặt ở db — db không import rag), `Settings.rag_keep_old_collections`
  (mặc định 2), `rag/ingest/pipeline.py` (14 bước, mã 0/1/2, dry-run theo chốt), `cli.py` (`main(argv, deps_factory)`;
  luôn `MlTokenCounter`), `rag/__init__.py` export `run_ingest`. Exception không lường trước được gắn note
  "ingest: lỗi ở bước N"; CLI in "lỗi ở bước N" và trả 1 — **riêng N ≥ 12 trả 2** (plan chỉ nói "trước bước 11 → 1";
  sau bước 11 alias đã đổi nên áp Q-3b-12). `unit/test_rag_frontmatter.py` +2 (b1 `run_ingest` → 1; bước 0).
  `integration/test_rag_ingest_pg.py` 15 test (b11–b19, b31–b35, CLI). **Phát hiện khi viết test:** tắt KB-VPN-004
  mà không tăng version bị bước 4 chặn (đúng Q-3b-2) → b17/b35 tắt 004 bằng `version: 2, enabled: false`; b35 bật lại
  bằng file v1 gốc (kb_version quay lại đúng bản đầu). Tự kiểm trong sandbox bằng Qdrant/DB giả trong bộ nhớ (script
  tạm, không vào repo): mọi kịch bản b11–b19, b31–b35 ra đúng mã/kết quả; b17 Recall 1,000 → 0,875 (đổi −0,125).
  Kiểm: ruff, mypy xanh; collect-only 15 test. **Chạy thật (Docker) → người** (lệnh 4).
- **S13 xong** — Makefile: `ingest` (build backend, `run --rm --no-deps`, mount `$(abspath $(KB_DIR)):/srv/kb:ro`),
  `tokenizer`, `KB_DIR`, `TOKENIZER_DIR`, `.PHONY`; `scripts/download_models.py --tokenizer-only DIR`
  (`tokenizer_target`, `tokenizer_only`; thiếu lock → 1, đã có → bỏ qua không mạng); CI: cache `models/_tokenizer` +
  `make tokenizer` trước `make test`; `.env.example` dòng chú thích `RAG_KEEP_OLD_COLLECTIONS`; `kb/README.md`;
  `kb/eval/.gitkeep`. Test: `unit/test_ingest_deploy.py` 6 (b28), `ml_service/tests/test_download_models.py` +4.
  Kiểm: b28 6 passed; ml `-k download` 13 passed; `make -n ingest tokenizer` in đúng lệnh. `make tokenizer` thật
  (mạng huggingface) chưa chạy — máy dev dùng `models/BAAI/bge-m3@…` có sẵn (lệnh 2 mục 12, tuỳ chọn).
- **S14 xong** — `.importlinter` hợp đồng 7 `rag-lower-layer` (comment đầu file "7 hợp đồng"). Kiểm: `lint-imports`
  **7 kept**; thử chèn `import app.graph.goto` vào `rag/bm25.py` → đúng hợp đồng 7 BROKEN (`app.rag.bm25 ->
  app.graph.goto`), hoàn nguyên, md5 khớp, không còn dấu `MUTATION`. `make lint` xanh (ruff; mypy backend 143 file,
  mock 11, ml_service 15; 7 kept; gitleaks 36 commit không leak); `gitleaks dir` trên từng thư mục/file mới: không leak.
- **S15 xong (phần sandbox)** — `scripts/mutation/mutate_3b.py` (khuôn `mutate_3a.py`; nhiều test dự đoán mỗi đột biến;
  so md5 + `git diff --stat` trước/sau; `--integration`, `--only`). Chạy phần unit (28/09/2026): **5/5 đỏ đúng test dự
  đoán** — M-3b-1 → `test_b10_order_independent`; **M-3b-3** → `test_b4_fixture_chunks_within_limits_real_tokenizer` đỏ
  ĐÚNG ở `assert c.content_tokens <= 380` (412, đoạn KB-VPN-004, text 431 ≤ 480 — không phải IngestError); M-3b-4 →
  `test_b9_to_sparse_merges_collisions`; M-3b-5 (spy) → `test_switch_alias_single_atomic_call[True-kinds0]` ở
  `len(alias_calls) == 1` (2); M-3b-7 → `test_b8_tokenize_vi[negation]` + `test_stopwords_exclude_negation`. md5 khớp,
  `git diff --stat` khớp, `grep MUTATION` trống. **Review M-3b-5:** `grep -rn "update_collection_aliases\|delete_alias\|
  create_alias" backend/app` → một lời gọi `update_collection_aliases` (`rag/vector_store.py:134`), không lời gọi
  `delete_alias()`/`create_alias()` nào (dòng 131–132 là tham số `delete_alias=`/`create_alias=` của model Operation).
  Phần `--integration` (M-3b-2, M-3b-6, S1–S3) chờ người (lệnh 5).
- **S16 xong** — toàn bộ unit backend **1687 passed, 0 skipped** (trước 3b: 1555; +132, gồm b4 `tokenizer_real` chạy
  thật với `models/BAAI/bge-m3@5617a9f…`); ml_service `not ml_real` **61 passed** (57 + 4); `make lint` xanh (xem S14).
  Test chưa chạy (cần Docker — người): `integration/test_migration_0006.py` (3), `integration/test_rag_ingest_pg.py`
  (15), `test_migration.py` (so model ↔ migration 0006), mutation `--integration`, `make ingest` thật.
- **S17 (soát lại trong phiên, model Opus)** — đọc lại `pipeline.py` bước 4–5, 11–14 và `chunker.py`: không phát hiện
  lỗi cần sửa. Đã kiểm có chủ đích: khoá advisory nhả trong `finally` cả khi exception; dry-run không lấy khoá, không
  ghi bù; bước 8 chỉ drop `kb_<v>` khi nó không phải đích alias (bước 5 đã thoát trước); bước 12 lỗi DB → mã 2 kèm
  hướng dẫn ghi bù, lỗi không lường trước nổi lên kèm note bước (b18); bước 14 không bao giờ drop đích alias, bản
  không có dòng DB bị xoá trước. Ghi chú hiệu năng (không sửa, đúng plan): gom tham lam đếm MỌI tiền tố của một mục —
  mục rất dài (hàng trăm câu) sẽ gửi nhiều văn bản dài tới `/count_tokens`; KB theo hướng dẫn (mục 80–250 từ) không
  chạm tới.
- **Việc chờ người (mục 12 `PLAN-3b.md`):** lệnh 3, 4, 5 (integration + mutation SQL), 6 `make up` (image có `mmh3`,
  áp 0006), 7–8 `make ingest` với fixture (ghi số đoạn, thời gian embed, Recall/FG — cổng dense-only với model thật
  đỏ là dự kiến), 9 `make test`; sau đó người bảo mới commit (không commit `PLAN-3b.md`).
- **Lệnh 3 (người chạy, 28/09/2026):** `test_migration.py` + `test_migration_0006.py` — **8 passed** (5 + 3; gồm
  `test_models_match_migration` với 0006, `test_0006_eval_status_check`, `test_0006_single_current`, `test_0006_down_up`).
- **Lệnh 4 lần 1 (người chạy, 28/09/2026): ĐỎ** — 2 passed (b11, b12 — ingest đầu tiên chạy trọn trên Qdrant + PG
  thật), 13 ERROR ở setup: helper test `integration/qdrant.py::wipe_kb` gọi `QdrantClient.delete_alias` — qdrant-client
  1.19 KHÔNG có hàm này (`AttributeError`); b12 để lại alias nên mọi test sau hỏng lúc dọn. Lỗi của helper test, không
  phải pipeline (Claude đã kiểm API của `AsyncQdrantClient` cho `QdrantIndex` nhưng không kiểm hàm dùng trong helper).
  Sửa: xoá alias bằng `update_collection_aliases([DeleteAliasOperation])`; đã kiểm mọi hàm Qdrant helper/test gọi đều
  tồn tại. Chờ người chạy lại lệnh 4.
- **Lệnh 4 lần 2 (người chạy, 28/09/2026): XANH** — `test_rag_ingest_pg.py` **15 passed** (14,7 s): b11–b19, b31–b35,
  CLI, trên Qdrant v1.19.1 + Postgres 16 thật, FakeMlService.
- **Lệnh 5 (người chạy, 28/09/2026): mutation `--integration` 5/5 ĐỎ đúng dự đoán**, md5 + `git diff --stat` khớp —
  M-3b-2 → `test_b11_same_version_changed_content_stops`; M-3b-6 → `test_b15_no_eval_no_flag_keeps_alias`; **S1** (bỏ
  index) → `test_0006_single_current` + `test_models_match_migration` (kèm 3 test hạ/nâng migration đỏ vì downgrade
  `drop_index` một index không tồn tại — hệ quả dự kiến); **S2** → `test_models_match_migration`; **S3** →
  `test_0006_eval_status_check`. Tổng mutation 3b: unit 5/5 + integration 5/5; M-3b-5 thêm review (S15).
- **Lệnh 9 `make test` (người chạy, 28/09/2026): XANH** — backend **1847 passed** (1687 unit + 131 integration [113 cũ +
  3 migration 0006 + 15 ingest] + 29 e2e), mock **86 passed**, ml **61 passed** (5 `ml_real` deselected). **Chặng 3b:
  code + unit + lint + mutation (10/10 + review M-3b-5) + `make test` xanh; CHƯA commit** — chờ người bảo. Chưa chạy
  (tuỳ chọn, mục 12): `make up`, `make ingest` với fixture (số đoạn/thời gian embed/Recall thật), `make tokenizer`.
- **Đối chiếu spec `phase3-thiet-ke-chi-tiet.md` v1.4 mục 5.14 (Claude chat sửa, 28/09/2026) với code: khớp nội dung.**
  Lệch CHỮ còn lại (code đúng chốt/plan, không sửa code):
  1. Q-3b-8: `pipeline_sha` trong code còn gồm tên cách băm BM25 (`HASH_NAME = "mmh3-u32-mod2^31"`, PLAN-3b 4.6) — 5.14
     không liệt kê.
  2. Q-3b-12: mã 0 còn gồm "ghi bù xong" (PLAN-3b 7 bước 5); CLI gặp exception không lường trước ở bước ≥ 12 trả **2**
     (áp Q-3b-12 vì alias đã đổi) — 5.14 không nói ca exception.
  3. Q-3b-16 (và `01-kien-truc-project.md` §4.3 v1.8): ghi "`rag` chỉ import … `tools.retry`", nhưng hợp đồng 7 trong
     `.importlinter` (theo PLAN-3b 4.10) CẤM `app.tools` với `rag`, chỉ bỏ qua đường gián tiếp `app.ml.client ->
     app.tools.retry`; `rag` import thẳng `tools.retry` sẽ BROKEN — 3c thêm dòng ignore `rag.retriever -> tools.retry`
     khi cần. Ngoài ra `rag` import `app.settings` (không bị cấm, spec không liệt kê).
- **Việc đầu 3c:** `make up` + `make ingest KB_DIR=backend/tests/fixtures/kb` (`--dry-run` rồi chạy thật), ghi số đoạn,
  thời gian embed, Recall/FG.

## Dồn về mốc G (cần LLM thật — làm sau Phase 7, trước Phase 8)

*Mỗi phase ghi thêm vào đây phần cổng cần LLM thật mà chưa chạy.*

| Phase | Việc | Nguồn |
|---|---|---|
| — | Chọn model fast/strong bằng probe, điền `pricing` (N1) | P2 mục 12–13 |
| — | Ghi GPU + VRAM 3 máy gaming (N2) | `build/decisions.md` mục 1.3 |
| 3 | Demo 4 ca VPN với LLM thật (+ chạy thử 1 lần bằng model rẻ ngay khi xong cổng code Phase 3) | `huong-dan` 5.1, `decisions.md` mục 4 |
| 5 | Cổng 5 thủ công | `huong-dan` 5.1 |
| 6 | Probe phân phối p | `huong-dan` 5.1 |

---

## Câu hỏi mở / điểm lệch

1. ~~Bảng `decisions.md` mục 2 hỏng~~ — **đã sửa** (25/09/2026).
2. ~~CSV trong `eval/reports/`~~ — **đã thêm** `!eval/reports/**/*.csv` (25/09/2026).
3. Ba package cùng tên `app` (backend, ml_service, mock_services): hướng xử lý là
   `make test`/`make lint` gọi pytest và mypy **riêng từng service**, mỗi lần một
   `PYTHONPATH`; không đổi tên package. Làm khi tới P4/P5.
4. ~~`data/` cũ~~ — **đã gỡ** (25/09/2026). Luật `data/*` trong `.gitignore` giữ lại, vô hại.
5. P8 mục 4.2 ghi `eval/kb-facts.md` "tạo ở Phase 0" — chưa tạo; làm cùng luồng nội dung KB.
6. Nhóm `ml` trong `pyproject.toml` lấy `torch` từ PyPI; Dockerfile ml-service cần index
   CPU của PyTorch để không kéo bản CUDA — xử lý khi làm P4.
7. ~~Hook chặn nhầm~~ — **đã sửa** (25/09/2026): `.claude/hooks/pre-commit-test.sh` tự lọc
   lệnh có `git commit` từ stdin; `.githooks/pre-commit` dùng `uv run --locked`.
8. ~~Mâu thuẫn cấm số 5 ↔ D-29~~ — **đã giải quyết** (25/09/2026): người nới đặc tả (NGU-CANH IV 2.2,
   B02 mục 7, P1 5.1.1) thành `S_SCREENING` → ngoài {`S_CLASSIFYING`, `S_BLOCKED`, `S_ESCALATED`};
   `S_SCREENING → S_SCREENING` vẫn cấm. Có test ở `backend/tests/unit/test_states.py`. Ghi chép gốc:
   chuyển cấm số 5
   (`NGU-CANH-DAY-DU.md` IV 2.2 **[Chốt]**: `S_SCREENING` → bất kỳ đâu ngoài `S_CLASSIFYING`/`S_BLOCKED`)
   đụng D-29 quy tắc 2 (P1 5.1.1: mọi trạng thái chưa kết thúc → `S_ESCALATED`, ghi rõ "E2/E9 ở
   `S_NEW` **và `S_SCREENING`**"). Cả P1 5.1.1 lẫn 00-README đều ghi "`FORBIDDEN` luôn thắng" → hiểu
   theo chữ thì E9/E2 ở B2 vẫn ném `IllegalTransition`, ticket kẹt ở `S_SCREENING` — đúng lỗi L-13 mà
   D-29 sinh ra để sửa, và làm đỏ test P1 mục 11 "lỗi giả ở B2 → `S_ESCALATED` E9". B02 mục 7 (dòng
   163) cũng ghi "(cần nới cho dòng E2 ở trên khi chốt)" nhưng chưa ai nới. Quy tắc 1 (`S_SCREENING` →
   `S_SCREENING`) cũng va với chuyển cấm này theo chữ, nhưng hiện chưa node nào dùng.
9. ~~`build_action` chưa có~~ — **đã chốt** (25/09/2026): làm cùng B11 ở Phase 3 (cần
   `config/action_metadata.yaml` + `REQUIRED_SLOTS`); `domain/action.py` hiện chỉ có `Action`.
10. ~~Hợp đồng 6 va với `effects.once(…, approvals.create, …)`~~ — **đã giải quyết** (25/09/2026):
    01 mục 4.3 + P1 mục 5.3 bỏ hợp đồng 6 khỏi import-linter, thay bằng test AST
    `backend/tests/unit/test_side_effects_ast.py` (quét `graph/nodes/**`, tham chiếu tới
    `SIDE_EFFECT_FUNCS` ngoài vị trí `fn` của `effects.once` → đỏ; có mẫu node giả chứng minh bắt được).
    `tickets` = `backend/app/db/tickets.py` (chưa tạo). B15 đổi sang `approvals.notify_approver`.
11. ~~Wildcard `*_write`~~ — **đã giải quyết** (25/09/2026): 01 mục 4.3 chốt liệt kê tường minh
    `{ad,vpn,software,fileserver}_write`; `backend/tests/unit/test_write_adapters_listed.py` đỏ nếu có
    `tools/adapters/*_write.py` chưa khai báo trong `.importlinter`.
12. ~~Cách hiện thực cấm 2/3/4~~ — **đã chốt** (25/09/2026, P1 mục 5.1.1): cấm 2 chặn mọi
    `approval_result != "approved"`; cấm 3 chặn cả khi thiếu `action_plan_hash`; cấm 4 ở domain chỉ
    kiểm `step`/`event`, phần audit cùng transaction thuộc `goto()` Phase 2. `approval_result` đã có
    trong P1 `TicketState`. Cấm 1 giữ đúng chữ (`risk` rỗng không bị cấm 1 chặn).
13. ~~Thiếu DDL 17 bảng gốc~~ — **đã giải quyết** (25/09/2026, Phase 1a): không còn `schema.sql`; dựng
    lại từ `claude/thiet-ke-database.md`, NGU-CANH III mục 9, IV mục 3 và 9, `huong-dan` 17.1 và
    17.9, các file B/P, rồi áp P7. Người đã duyệt bảng "bảng → cột → nguồn" (lưu ở
    `backend/app/db/README.md`). Quyết định kèm theo:
    - **A1:** cột `tickets.redacted_request` thay cho `raw_request` (D-07: ticket chỉ lưu bản đã che).
    - **A2:** `tickets` = 20 cột có nguồn + `is_parent` = 21; không thêm cột thứ 21 không có nguồn
      mà `thiet-ke-database.md` nhắc tới.
    - **A3:** CHECK `transaction_log.status` gồm `begun` (B17 mục 8 — phát hiện thực thi bị gián đoạn).
    - **A4:** `docker/postgres/init-roles.sh` (superuser, chạy lúc khởi tạo container) tạo 3 role có
      mật khẩu lấy từ env và cho `app_migrate` làm owner schema. Alembic chạy bằng `app_migrate`
      (không superuser). Downgrade không đụng role. Conftest testcontainers chạy cùng script này.
    - Điều chỉnh: `audit_logs` thêm `raw_prob` (CHECK 0..1) và `p_method` (CHECK
      {self_report, sampling_k5}); `thresholds`, `all_matched`, `layer`, `model_probs` nằm trong
      `detail` JSONB. Thêm index `audit_logs(step, created_at)`, `escalations(closed_at, exit_code)`,
      `llm_calls(created_at)` (P9 mục 4).
14. Phase 1a — ghi chú không chặn:
    - Bảng checkpoint LangGraph (`checkpointer.setup()`) chưa tạo — làm ở Phase 2 (P1).
    - Repository `backend/app/db/tickets.py` (`create_child`, `finalize_once`…) chưa có — làm khi có
      B05/B20.
    - Thêm trigger chặn TRUNCATE trên `audit_logs` và `security_events` [Đề xuất] — P6 chỉ ghi
      UPDATE/DELETE, nhưng TRUNCATE bỏ qua trigger FOR EACH ROW.
    - `exit_code_priority` seed theo B20 4.1 — thứ tự vẫn là [Suy luận, cần chốt].
    - Postgres dev bind `127.0.0.1:55432`, không dùng 5432 (máy dev đang có Postgres khác ở 5432).
    - `gitleaks detect` trong `make lint` chỉ quét lịch sử commit; file chưa commit chỉ được quét
      khi đã commit (trong Phase 1a đã quét tay các file mới bằng `gitleaks dir`, không thấy gì).
      **Đã bổ sung** (26/09/2026): `.githooks/pre-commit` chạy `gitleaks git --pre-commit --staged
      --redact` trước pytest, với mọi commit; thiếu gitleaks thì chặn. Đã thử stage file chứa token
      giả dạng `ghp_…` → hook chặn (rule `github-pat`).
    - Test không chạm `.env` (26/09/2026): pytest tự `stat` từng mục ở thư mục gốc khi thu thập
      test → sandbox chặn đọc `.env` làm hỏng cả phiên test (và hook pre-commit). `conftest.py` gốc
      đặt `collect_ignore_glob = [".env*"]` và `APP_ENV_FILE=""`; `Settings` đọc file env theo
      `APP_ENV_FILE` (mặc định `.env`, rỗng = tắt). Kiểm: trong sandbox unit 876 passed; bỏ conftest
      (`--noconftest`) thì lỗi `PermissionError … .env` quay lại.
    - Lỗi gặp khi dựng image (đã sửa): SQLAlchemy 2.1 không tự kéo `greenlet` → backend chết khi
      import `sqlalchemy.ext.asyncio`. Test trên máy vẫn xanh vì `greenlet` có sẵn qua nhóm dev
      (locust). Đã đổi phụ thuộc thành `sqlalchemy[asyncio]` (`uv add`). **Bài học:** test chạy
      với nhóm dev không phát hiện được phụ thuộc thiếu ở image `--no-dev`; `make up` mới bắt được.
    - Mạng trong VM colima chập chờn (timeout tới ghcr.io, tải `spacy`) → Dockerfile đặt
      `UV_HTTP_TIMEOUT=300`, cache mount cho uv, build backend rồi mới build mock.
    - Máy dev: colima (4 CPU, 8 GB) + gitleaks cài bằng brew. Makefile tự nhận socket colima và thêm
      `docker-credential-desktop` vào PATH (xem README "Dựng môi trường").
