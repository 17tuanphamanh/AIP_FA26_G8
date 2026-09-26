# PROGRESS

*Theo `docs/spec/CLAUDE.md` mục 4: phase đang mở, task xong, cổng nào xanh, câu hỏi mở.
Mọi đường dẫn dưới đây tính từ `docs/spec/`.*

## Trạng thái

| Mục | Giá trị |
|---|---|
| Chế độ xây | **Code trước, gắn API sau** (`build/decisions.md` mục 4): Phase 1–7 dùng `ScriptedLLM`, không gọi LLM thật |
| Phase đang mở | **Phase 2 (P1, B01, B20)** — chặng 2a (runtime) **đã duyệt** (26/09/2026), đã commit; chặng 2b: kế hoạch đã duyệt, làm theo 4 bước 2b-1 → 2b-4, **2b-1 (B1 thật) xong, chờ duyệt**. Phase 1 đã đóng |
| Cổng xanh | Phase 0; T01; **Cổng Phase 1 — tự động xanh** (26/09/2026): `make lint`, `make test` (backend 1215 + mock 86), `make up` + `/api/health` 200 có `mock`, `make seed`, đăng nhập user demo. Còn mục **thủ công** của cổng 1 (`huong-dan` 5.1): người xác nhận gọi tay 12 tool (bảng ở `mock_services/README.md`) — mở Phase 2 trước khi mục này xong hay không là **người quyết** |
| Cập nhật | 26/09/2026 |

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
