# B10 — Biên bản kiểm tra thủ công cổng 1 và cổng 3

> Khung biên bản soạn từ code ở `a1078ff`. Lần chạy ngày 24/10/2026 trên code `bc7eaae` (lý do: xem dòng Commit).
> Quân thực hiện; dùng Claude Code hỗ trợ chạy lệnh và soạn bản nháp, Quân kiểm tra và chịu trách nhiệm kết quả (đã khai với
> Tuấn Anh). Output thô ở `reports/b10_run.log` (lưu cục bộ, không đưa lên repo).
> Lệnh tương ứng in sẵn trong `reports/b10_checklist.ps1` (lưu cục bộ, không đưa lên repo). Checklist viết cho `.env` + `a1078ff`, nên lần chạy này có điều chỉnh,
> ghi ở bảng tiến độ.

## 1. Thông tin chung

| Mục | Giá trị |
|---|---|
| Ngày kiểm tra | 24/10/2026, 00:40–01:20 (giờ VN) |
| Người thực hiện | Quân |
| Commit | **`bc7eaae`** (22/10, "Merge PR #61 (g1-duong)"), chạy từ worktree tách rời. Lý do: volume `servicedesk_pgdata` của B8 đã ở migration 0010, còn nhánh làm việc `d2-kichban-quan` @ `a1078ff` (15/10) chỉ có tới 0009 (xem mục 2 ở bảng tiến độ). Biên bản và trợ giúp nằm ở repo chính `a1078ff` |
| Môi trường | Windows 11 + Docker Desktop (WSL2; Docker Engine 29.9.2, Docker Compose v5.6.1), PowerShell 5.1 + Git Bash; ml-service chạy CPU (`ML_THREADS` mặc định 4) |
| Python | **Trong container:** 3.12.15. Image backend và ml-service đều `FROM python:3.12-slim` (`backend/Dockerfile` @ `bc7eaae`); kiểm bằng `docker run --rm --entrypoint python servicedesk-backend:dev --version`. **Trên máy:** CPython 3.12.15 qua uv 0.13.1 (`uv run python --version`) |
| Cách chạy | Code **`bc7eaae`** ở worktree tạm tại `bc7eaae` (`git worktree add --detach`). Docker Compose với `-f <worktree>/docker-compose.yml --env-file <env tạm>`. File env tạm, xoá sau khi chạy: sinh từ `.env.example` của `bc7eaae`, token ngẫu nhiên, PG_* mẫu, `RATE=loose`, `MODELS_DIR` trỏ thư mục `models/` của repo chính; **không dùng `.env`**. Script phía máy (gate3, `app.seed validate`, `app.lock`, pytest) chạy bằng `uv run` với **`PYTHONUTF8=1`** + `PYTHONIOENCODING=utf-8` (không có thì Windows cp1252 làm gate3 dừng ở tc02). pytest gọi bằng `uv run python -m pytest` (`pytest.exe` bị Application Control chặn) |
| Model | `models/BAAI/bge-m3@5617a9f…`, `models/BAAI/bge-reranker-v2-m3@953dc6f…` (đã có sẵn) |
| LLM | `LLM_BACKEND=scripted` (không gọi LLM thật — CLAUDE.md, "code trước, gắn API sau") |
| Giờ chạy cổng 3 | 24/10/2026 01:07 (giờ VN). Một số ca có kết quả phụ thuộc giờ chạy |
| Docker | Server 29.9.2. Phiên chạy phải tự thêm thư mục bin của Docker Desktop vào PATH của tiến trình (PATH người dùng có, nhưng phiên chưa nạp) |

**Tiến độ chạy checklist (24/10/2026, output thô: `reports/b10_run.log` (lưu cục bộ, không đưa lên repo)):**

| Mục | Kết quả |
|---|---|
| 0 | ĐẠT. `docker compose ls -a` rỗng, không còn container `servicedesk*`; còn đủ `servicedesk_pgdata`, `servicedesk_qdrant` |
| 1 | DỪNG. Repo chính **không có `.env`**, chờ người quyết. Đã làm xong: `init-roles.sh` → LF (`i/lf w/lf`, `git diff` rỗng; `git status` vẫn hiện `M` do autocrlf, không có thay đổi nội dung). Model: `ml-service: đủ model trong models` (cần `PYTHONIOENCODING=utf-8`, không thì console cp1252 làm lệnh lỗi sau khi kiểm xong). Dockerfile ở dạng CRLF nhưng không cần đổi (BuildKit đọc được; B8 đã build bình thường) |
| 1 (tiếp) | Người chọn "Env tạm": file env tạm (xoá sau khi chạy) sinh từ `.env.example`, có token ngẫu nhiên, PG_* giữ giá trị mẫu, comment FAKE_SCENARIO/FAKE_NODE_DELAY/APPROVAL_SLA_MINUTES_DEV. Không tạo `.env` trong repo |
| 2 | DỪNG ở alembic. Build backend/mock/ml-service xong, postgres + qdrant healthy. `alembic upgrade head` → `Can't locate revision identified by '0010'`. **Không phải lỗi xác thực.** Nguyên nhân: volume đã được B8 migrate tới `0010_rate_limits` trên `bc7eaae`, còn HEAD `a1078ff` (15/10) chậm hơn `bc7eaae` 50 commit và chỉ có migration tới `0009`. DB không bị đổi gì. Chờ người quyết |
| 2 (lại) | Người chọn "Worktree bc7eaae": dựng worktree tạm tại `bc7eaae`, đổi `init-roles.sh` của worktree sang LF. Env tạm sinh lại từ `.env.example` của bc7eaae, thêm `MODELS_DIR` (thư mục `models/` của repo chính) và `RATE=loose` (3 ngưỡng 429 = 100000, như `Makefile`/`verify.sh` của bc7eaae yêu cầu khi chạy cổng bằng tay). Build 3 image (`GIT_SHA` rỗng vì worktree có `M init-roles.sh` → `lineage.commit_sha` NULL) → postgres + qdrant healthy → `alembic upgrade head` xanh (DB đã ở 0010) → ml-service, backend, worker, mock đều healthy → mock `/health` ok → `seed validate` (17 người dùng, 10 thiết bị) → `seed reset` → worker `healthy` → `/api/health` 200 (db, qdrant, mock, ml ok; `runtime=up`; `kb.status=ready`, alias → `kb_8479e79f…` là KB thật của B8; `llm=scripted`) → `APP_ENV=dev`, `LLM_BACKEND=scripted`. **ĐẠT** |
| 3 | **20/20 ĐẠT** (mục 2.2). Mọi lời gọi `error=null`, `attempts=0`, 0,02–0,04 s. Hai ca 404 (STT 7, 12) cho `empty=true`, `data=null`, không retry. Bốn ca danh sách rỗng (STT 3, 10, 16, 20) cho `empty=true`, `data=[]`. STT 19 khớp seed + test, lệch README (L1) |
| 4 | **6/6 ca ĐẠT** (F1–F6, cả 4 hệ thống ad/vpn/software/files). Bật lỗi: `attempts` = `TOOL_RETRY` + 1, thời gian khớp backoff theo cấu hình hiện hành trong `config/policy.json`, `empty=false`. Sau mỗi `fault-off`, `faults` → `[]` và gọi lại được dữ liệu như mục 3. Ghi chú: chuỗi `error` ở mức tool có chứa URL kèm giá trị slot (vd `/vpn/connections/nv001`). B6/B7 chỉ đưa phần "loại lỗi" vào audit (`_error_kind`, `b06_diagnose.py:45-47`), nên không lộ URL/user_id ra ngoài |
| 5 | **ĐẠT.** Ingest KB fixture xanh: `kb_version=c88b47a2…`, 20 đoạn, truncated 0, Recall@5 1.000 / MRR 1.000 (8 câu có đáp án / 6 câu âm tính); alias → `kb_c88b47a2…`. Collection `kb_8479…` của B8 được giữ ("dọn: không có collection nào cần xoá"). Có 6 cảnh báo `procedure_doc` của account/access/software, đúng dự kiến vì KB fixture chỉ có VPN. Tạo lại backend+worker → healthy. gate3 preflight 5/0. gate3 `all` lần 1 **dừng ở tc02 vì lỗi môi trường Windows** (`UnicodeDecodeError` cp1252 khi `subprocess` đọc output psql), không phải FAIL kịch bản. Lần 1 để lại 1 ticket tc02 dở dang (không có lời gọi ghi). Lần 2 thêm `PYTHONUTF8=1` (chỉ là biến môi trường, không sửa code) → **78 PASS, 0 FAIL** |
| 6 | G1 **KHÔNG ĐẠT**: 1 thiếu (tc28, điểm 3, `kb_version`; lệch code ↔ bộ kiểm, xem L4), 0 bí mật. G2 ĐẠT (0 ERROR, 0 Traceback, 2 WARNING đúng dự kiến). G3 ĐẠT |
| 7 | DỪNG, chờ người quyết. Alias đang ở fixture `kb_c88b…`. Ingest `kb/` sẽ ra cùng `kb_version=8479…` (chỉ phụ thuộc `doc_id:version`), nhưng vì alias không trỏ bản này, pipeline sẽ **xoá rồi dựng lại** `kb_8479…` (`backend/app/rag/ingest/pipeline.py:251-255`) với `pipeline_sha` hiện tại. `pipeline_sha` băm byte của `config/vi_abbrev.yaml` và `vi_stopwords.txt` (`kbversion.py:34-43`); hai file này ở worktree là `w/crlf`, nhiều khả năng là nguyên nhân lệch với bản của B8. Củng cố thêm: B8 tạo worktree bằng `git -c core.autocrlf=false worktree add` (`reports/b8_recall_at5.md`, mục "Cách chạy lại"), tức config ở dạng LF |
| 7 (tiếp) | Người chọn "Giữ fixture, chỉ down": **không ingest `kb/`**. Trước khi down đã kiểm chỉ đọc: Qdrant còn 3 collection `kb_3362…`, `kb_8479…` (B8, nguyên vẹn), `kb_c88b…`; alias `kb_current` → `kb_c88b…` (**fixture**). `docker compose down` → không còn project; còn đủ `servicedesk_pgdata`, `servicedesk_qdrant`. **Lần dựng stack sau phải ingest `kb/` (trên máy có `config/` LF) để đưa alias về KB thật** |
| STT 21–22 | Chạy sau khi đã down, ở worktree `bc7eaae`: `test_db_constraints.py` 33 passed; `test_tools_vs_mock.py` 25 passed |

**Nguồn đặc tả:**
- Cổng 1: `docs/spec/huong-dan-xay-dung-he-thong-2.md:201-211`, `docs/spec/build/nen-tang/P5-tool-registry-mock.md` mục 8.
- Bảng mong đợi: `mock_services/README.md:54-75`. Test tự động cùng bảng: `backend/tests/e2e/test_tools_vs_mock.py:25-56`.
- Cổng 3: `huong-dan…-2.md:248+`, `backend/tests/stack/README.md:139-192`, `backend/tests/stack/gate3.py`.

**Danh sách lệnh cổng 1:** danh sách ở mục 2.2 và 3.3 (khớp bảng test tự động và README) là **danh sách chính thức** theo quyết
định của Tuấn Anh ngày 24/10/2026.

Output thô của lần chạy: `reports/b10_run.log` (lưu cục bộ, không đưa lên repo).

## 2. Cổng 1 — gọi tay 12 tool đọc

> Danh sách lệnh ở cột "Lệnh gọi" của mục 2.2 và 3.3 (khớp bảng test tự động `backend/tests/e2e/test_tools_vs_mock.py` và
> `mock_services/README.md`) là **danh sách chính thức** theo quyết định của Tuấn Anh ngày 24/10/2026.

### 2.1. Cách gọi

Mock chỉ nghe trong mạng compose (không bind cổng ra máy), nên gọi tool **từ trong container backend**, đi qua đúng đường mà B6
dùng: `build_read_registry` → `ToolRegistry.call(..., caller_step="B6")` → HTTP với token `svc_agent` → mock. Trợ giúp là
`reports/b10_call_tool.py` (lưu cục bộ, không đưa lên repo), đưa vào container qua stdin (không mount, không sửa image). Trước khi gọi, khai báo hàm này một lần
trong PowerShell:

```powershell
$OutputEncoding = [Text.UTF8Encoding]::new($false)
function b10 { Get-Content -Raw -Encoding UTF8 reports\b10_call_tool.py | docker compose --env-file .env exec -T backend python - @args }
```

Mỗi lệnh in ra JSON gồm `error`, `attempts`, `empty`, `seconds`, `data`. Ba dạng kết quả:

- **Có dữ liệu:** `error=null`, `empty=false`.
- **"Rỗng / 404 → rỗng":** `error=null`, `empty=true`, `data=null` hoặc `[]`. Đây là dữ liệu hợp lệ, **không phải lỗi**
  (E3 ≠ E2; xem `backend/app/tools/retry.py:46-47`).
- **Lỗi hệ thống:** `error` khác null. Trường hợp này đi E2.

Trước khi bắt đầu, nạp lại seed để dữ liệu đúng như bảng (lệnh này đồng thời tắt mọi lỗi đang bơm):
`docker compose --env-file .env exec -T mock python -m app.seed reset`.

### 2.2. Bảng kết quả

12 tool khai báo ở `backend/app/tools/specs.py:92-103`; schema vào/ra ở `backend/app/tools/models.py`. Tham số `user_id` ứng với
slot `target_user` (`models.py:19`). 20 lời gọi dưới đây trùng với 20 ca của test tự động.

| STT | Tool (hệ thống · endpoint mock) | Lệnh gọi | Kết quả mong đợi | Kết quả thực tế | Đạt/Không | Ghi chú |
|---|---|---|---|---|---|---|
| 1 | `check_account_status` (ad · `GET /ad/users/{id}?account_type=`) | `b10 tool check_account_status user_id=nv007 account_type=email` | `error=null`; `data.account.locked=true`, `data.account.lock_reason="bad_password"` | `error=null`, `attempts=0`; `account.locked=true`, `lock_reason="bad_password"`; `is_service_account=false`, `disable_reason=null` | ĐẠT | Output `AccountStatus` bắt buộc có `is_service_account`, `disable_reason` |
| 2 | `check_lockout_history` (ad · `/ad/users/{id}/lockouts`) | `b10 tool check_lockout_history user_id=nv007` | 3 phần tử, đều `account_type="email"`, mới nhất trước | 3 phần tử email, `at` giảm dần (23/10 17:29, 23/10 05:58, 11/10 17:58), source webmail/webmail/mobile | ĐẠT | |
| 3 | `check_lockout_history` | `b10 tool check_lockout_history user_id=nv002` | `empty=true` (`[]`) | `empty=true`, `data=[]` | ĐẠT | Rỗng là dữ liệu hợp lệ |
| 4 | `check_privilege_level` (ad · `/ad/users/{id}/privilege`) | `b10 tool check_privilege_level user_id=svc_backup` | `level="admin"`, `is_privileged_account=true` | `level="admin"`, `is_privileged_account=true`, `account_type="ad"` | ĐẠT | `account_type` mặc định `ad` |
| 5 | `check_device_registered` (vpn · `/vpn/devices?owner_id=`) | `b10 tool check_device_registered user_id=nv002` | 2 máy: `LAP-0417 registered=true`, `PC-0977 registered=false` | `[(LAP-0417, registered=true, Windows 11), (PC-0977, registered=false)]` | ĐẠT | Không nêu máy → liệt kê mọi máy (TC06). Từ `7e99c0a`, LAP-0417 có `os="Windows 11"` |
| 6 | `check_device_registered` (vpn · `/vpn/devices/{id}`) | `b10 tool check_device_registered user_id=nv001 device_id=LAP-0342` | 1 máy, `registered=true` | 1 máy LAP-0342, `registered=true` | ĐẠT | Có trong test tự động, không có trong README |
| 7 | `check_device_registered` | `b10 tool check_device_registered user_id=nv001 device_id=KHONG-CO` | 404 → `error=null`, `empty=true` | `error=null`, `empty=true`, `data=null`, `attempts=0` | ĐẠT | Không phải lỗi, không retry (`attempts=0`) |
| 8 | `check_vpn_cert_expiry` (vpn · `/vpn/certs/{user}?device_id=`) | `b10 tool check_vpn_cert_expiry user_id=nv001 device_id=LAP-0342` | 1 chứng chỉ: `status="expired"`, `days_to_expiry=-3` | 1 chứng chỉ `VPN-2025-0342`: `status="expired"`, `days_to_expiry=-3` | ĐẠT | TC06; mốc tương đối nên chạy ngày nào cũng là −3 |
| 9 | `check_last_connection` (vpn · `/vpn/connections/{user}`) | `b10 tool check_last_connection user_id=nv001` | Phần tử đầu: `result="failed"`, `error_code="CERT_EXPIRED"` | 4 phần tử; phần tử đầu `failed`/`CERT_EXPIRED` (23/10 15:34), phần tử cuối `success` (19/10) | ĐẠT | |
| 10 | `check_last_connection` | `b10 tool check_last_connection user_id=nv003` | `empty=true` | `empty=true`, `data=[]` | ĐẠT | |
| 11 | `check_catalog_entry` (software · `/software/catalog/{name}`) | `b10 tool check_catalog_entry software_name=Zoom` | `in_catalog=true`, `paid=false` | `name="zoom"`, `in_catalog=true`, `license_type="free"`, `paid=false` | ĐẠT | |
| 12 | `check_catalog_entry` | `b10 tool check_catalog_entry software_name=utorrent` | 404 → `empty=true` | `error=null`, `empty=true`, `data=null` | ĐẠT | TC17: không tồn tại ≠ lỗi |
| 13 | `check_license_available` (software · `/software/licenses/{name}`) | `b10 tool check_license_available software_name=ms-project` | `available=0` | `total=5`, `used=5`, `available=0` | ĐẠT | |
| 14 | `check_license_available` | `b10 tool check_license_available software_name=adobe-acrobat-pro` | `available=3` | `total=10`, `used=7`, `available=3` | ĐẠT | |
| 15 | `check_installed_list` (software · `/software/installed/{device}`) | `b10 tool check_installed_list device_id=LAP-0342` | Đúng thứ tự `["ms-office", "zoom"]` | `["ms-office" (2024), "zoom" (6.1)]` | ĐẠT | |
| 16 | `check_installed_list` | `b10 tool check_installed_list device_id=PC-0977` | `empty=true` | `empty=true`, `data=[]` | ĐẠT | |
| 17 | `check_current_permissions` (files · `/files/permissions/{user}?resource_path=`) | `b10 tool check_current_permissions user_id=nv002 resource_path=finance/Q3` | 1 quyền, `level="read"`, `status="expired"` | 1 quyền `finance/Q3`, `level="read"`, `status="expired"` (hết hạn 18/10) | ĐẠT | |
| 18 | `check_resource_sensitivity` (files · `/files/resources/{path}`) | `b10 tool check_resource_sensitivity resource_path=finance/Q3` | `sensitivity="high"` | `sensitivity="high"`, `owner_department="Finance"` | ĐẠT | |
| 19 | `check_manager_chain` (ad · `/ad/users/{id}/manager-chain`) | `b10 tool check_manager_chain user_id=l1_01` | `["l1_lead", "it_mgr01"]` (theo seed + test) | `["l1_lead", "it_mgr01"]` — khớp seed + test, **lệch README** (L1) | ĐẠT | **Lệch tài liệu** — xem 2.3 |
| 20 | `check_manager_chain` | `b10 tool check_manager_chain user_id=fin_head` | `empty=true` | `empty=true`, `data=[]` | ĐẠT | |

Thêm (không thuộc 12 tool nhưng là phần thủ công của cổng 1):

| STT | Mục | Cách kiểm | Mong đợi | Thực tế | Đạt/Không |
|---|---|---|---|---|---|
| 21 | Ghi audit thiếu trường bắt buộc bị từ chối | Có test: `backend/tests/integration/test_db_constraints.py:168` (chạy trong `make test` hoặc `uv run pytest backend/tests/integration/test_db_constraints.py`) | Test xanh | Chạy ở worktree `bc7eaae` sau khi stack đã down: **33 passed**, exit 0. `pytest.exe` của `.venv` worktree bị Windows Application Control chặn (os error 4551) → chạy bằng `uv run python -m pytest` | ĐẠT |
| 22 | Phần tự động của cổng 1 | `uv run pytest backend/tests/e2e/test_tools_vs_mock.py` (dựng mock bằng uvicorn trên máy, **không dùng docker**) | 25 test xanh (20 ca bảng + phủ 12 tool + B1 + bật/tắt lỗi + token) | Worktree `bc7eaae`: **25 PASSED**, exit 0 (20 ca bảng + phủ 12 tool + B1 + bật/tắt lỗi + token + IdP) | ĐẠT |

### 2.3. Chỗ lệch giữa tài liệu và code

| # | Chỗ lệch | Bên A | Bên B | Đề xuất |
|---|---|---|---|---|
| L1 | `check_manager_chain l1_01` | `mock_services/README.md:72` ghi `[it_mgr01]` | `seed.json`: `l1_01 → l1_lead → it_mgr01`; `test_tools_vs_mock.py:53-54` mong `["l1_lead", "it_mgr01"]` (ghi chú "Phase 4 P14") | Lấy theo seed + test; README cần sửa (việc của người, không làm trong B10) |
| L2 | `check_device_registered nv001 LAP-0342` | Không có trong README | Có trong test (ca 6) | Không phải lỗi; biên bản giữ cả hai |
| L3 | Danh sách lệnh cổng 1 | Danh sách gửi 22/10 chưa được đưa vào | Danh sách dựng từ code (khớp test tự động + README) | **Đã đóng – 24/10.** Tuấn Anh quyết định danh sách dựng từ code là danh sách chính thức |
| L4 | Điểm log 3 khi Qdrant chết (tc28), phát hiện ở G1 | Code `bc7eaae`: `backend/app/rag/retriever.py:230-234`, `alias_target` lỗi tạm → `RetrievalSystemError("search", …)`, không có `kb_version` (lúc đó chưa biết bản KB) | Bộ kiểm `backend/app/audit/check.py:140-142` và spec `docs/spec/build/phase4-thiet-ke-chi-tiet.md:739`: `retrieval_error` phải có `kb_version`, **trừ** `error_stage="alias"` | **Đã chuyển – backend sửa sau tag.** Xem mục 2.4; không sửa trong B10 |
| L5 | Môi trường Windows | `scripts/verify.sh`, `Makefile` cần bash + make; gate3 gọi `subprocess(text=True)` theo locale | Windows 11, PowerShell 5.1, locale cp1252 | Chạy tương đương bằng PowerShell, cần thêm `PYTHONUTF8=1` (không có → gate3 dừng ở tc02 với `UnicodeDecodeError`) và `PYTHONIOENCODING=utf-8` (không có → `app.lock`, `seed` lỗi khi in tiếng Việt). Cũng cần thêm thư mục bin của Docker Desktop vào PATH |

### 2.4. L4 — điểm log 3 thiếu `kb_version` khi Qdrant tắt

**Trạng thái: Đã chuyển – backend sửa sau tag** (phản hồi của Tuấn Anh, 24/10/2026).

**Mô tả.** Kịch bản tc28 của gate3 tắt Qdrant (`compose stop qdrant`) rồi gửi câu hỏi của tc04. Kết quả: B8 không đọc được alias
`kb_current` (`ConnectError: Qdrant get_aliases …`). tc28 kết thúc đúng mã thoát mong đợi (xem `backend/tests/stack/gate3.py`);
lỗi chỉ nằm ở dòng audit thiếu `kb_version`. Cụ thể, dòng audit `B8/retrieval_error` ghi `error_stage="search"` thay vì `"alias"`, và cột `kb_version` để trống vì lúc đó chưa biết bản KB.
Kiểm audit (G1) báo: `05a6c41d-4499-4f5b-ba5a-7983249aec34 | điểm 3 | kb_version` → "1 thiếu, 0 bí mật (9 ticket)".

**Trích dẫn (commit `bc7eaae`):**
- `backend/app/rag/retriever.py:230-234`: lỗi tạm khi đọc alias bị gán stage `"search"`, không có `kb_version`:
  ```python
  try:
      coll = await self._call(self._index.alias_target, ALIAS, retries=retries)
  except _Transient as e:
      raise RetrievalSystemError("search", retries.total, detail=str(e)) from e
  ```
- `backend/app/audit/check.py:140-142`: chỉ miễn `kb_version` khi stage là `"alias"`:
  ```python
  if (step, event) == ("B8", "retrieval_error"):
      alias = _get(row, "detail.error_stage") == "alias"  # lỗi alias: chưa biết bản KB
      return 3, _lacks(row, ["detail.query"] + ([] if alias else ["kb_version"]))
  ```
- `docs/spec/build/phase4-thiet-ke-chi-tiet.md:739` (điểm log 3): "`retrieval_error` thêm `kb_version` trừ
  `detail.error_stage="alias"`".

**Hai hướng xử lý:**
- (a) **Sửa retriever:** lỗi tạm ở bước `alias_target` ghi stage `"alias"`, khớp spec và bộ kiểm hiện tại. Cần xem bên nào dùng
  `error_stage="search"` để phân loại (M9, test của retriever) trước khi đổi.
- (b) **Sửa bộ kiểm + spec:** miễn `kb_version` cho mọi `retrieval_error` chưa biết bản KB (không chỉ `"alias"`). Giữ nguyên nhãn
  `"search"` trong code.

**Đề xuất:** chuyển cho người phụ trách retriever/audit quyết định. B10 không sửa code, bộ kiểm hay spec. Hai hướng ảnh hưởng tới
những chỗ khác nhau (nhãn lỗi trong số liệu M9, hoặc luật của bộ kiểm điểm log), nên để người phụ trách chọn. **Đã chuyển –
backend sửa sau tag (24/10).**

## 3. Cổng 1 — lỗi 500

### 3.1. Cơ chế bật lỗi

- **Endpoint:** `POST /_admin/faults` của mock (`mock_services/app/admin_faults.py`: schema `FaultIn` ở `:25-31`, middleware ở
  `:84-97`, các route ở `:100-127`). Body `{"path_prefix": "/vpn", "mode": "error", "status": 500}`; có thêm `method` (GET/POST) và
  `times` (số lần, mặc định là tới khi tắt). Ngoài `error` còn hai mode khác là `timeout` (504 sau `delay_ms`, mặc định 30 s) và
  `latency`.
- **Tắt:** `DELETE /_admin/faults` (tắt hết), `DELETE /_admin/faults/{id}` (tắt một), hoặc `POST /_admin/reset` / `app.seed reset`
  (nạp lại seed và tắt hết lỗi).
- **Phạm vi:** `/_admin` và `/health` không bơm lỗi được (`admin_faults.py:21`). Không có biến env hay cờ nào khác để bật lỗi.
- **Gọi từ đâu:** `/_admin/*` không cần token, nhưng mock chỉ nghe trong mạng compose. Trợ giúp `b10 fault-on <prefix> [status]`
  / `b10 faults` / `b10 fault-off` gọi các route này từ trong container backend.

### 3.2. Agent được thiết kế xử lý lỗi 500 thế nào

| Tầng | Hành vi | Nguồn |
|---|---|---|
| `call_with_retry` | 5xx/429/timeout/mất kết nối được coi là lỗi tạm: retry `TOOL_RETRY` lần với backoff theo cấu hình hiện hành trong `config/policy.json`. Hết lượt thì **trả chuỗi lỗi, không raise**. 404 → dữ liệu rỗng, không retry. 4xx khác → raise (lỗi hợp đồng → E9) | `backend/app/tools/retry.py:39-56`; `config/policy.json` (`TOOL_RETRY`, `BACKOFF_BASE_SECONDS`) |
| `ToolRegistry.call` | Không bao giờ raise khi hệ thống ngoài lỗi; luôn trả `ToolResult(error=…, empty=False)` | `backend/app/tools/registry.py:6-12`, `:156-164` |
| Circuit breaker (mỗi `target_system`) | 5 lỗi liên tiếp trong 60 s → mở 30 s: lời gọi bị từ chối ngay với `error="circuit_open"` (không chạm mock), sau đó half-open. Đếm theo lời gọi registry (đã gồm retry), không theo từng HTTP attempt | `backend/app/tools/breaker.py:5-8`; `registry.py:100-103`; `backend/app/settings.py:171-173` |
| B6 → B7 | Bất kỳ tool nào lỗi hệ thống → `S_ESCALATED`, **E2** `tool_system_error`, `tool_errors=["<tool>: <loại lỗi>"]` (không có URL/user_id), ghi `tool_retry_count`. Ticket chuyển cho người (L2), **không** đoán tiếp với dữ kiện thiếu | `backend/app/graph/nodes/b06_diagnose.py:7-9`, `:84-91` |
| Hết hạn cả lượt | `TurnBudgetExceeded` → E2 `turn_budget_exceeded` | `retry.py:55`; `b06_diagnose.py:78-81` |

Ranh giới của biên bản: kiểm tay ở đây dừng ở **mức tool** (đúng như huong-dan:210 "tool báo lỗi hệ thống"). Hành vi B7 → E2
ở mức ticket được phủ bằng test (`backend/tests/unit/test_call_with_retry.py`, `test_tools_vs_mock.py:94-109`, các test node
B6). gate3 không kiểm được ca này vì nó nạp lại seed và tắt lỗi trước mỗi kịch bản.

### 3.3. Bảng ca lỗi 500

Mỗi ca chạy theo thứ tự: `fault-on` → gọi tool → `fault-off` → gọi lại. Registry dựng mới mỗi lần gọi `b10`, nên breaker luôn bắt
đầu ở trạng thái đóng và không bị mở lây giữa các lần gọi tay.

| # | Tool bị bật lỗi | Cách bật | Hành vi mong đợi | Hành vi thực tế | Đạt/Không |
|---|---|---|---|---|---|
| F1 | `check_last_connection` (vpn) | `b10 fault-on /vpn 500` → `b10 tool check_last_connection user_id=nv001` | `error` bắt đầu bằng `HTTPStatusError` và chứa `500`; `attempts` = `TOOL_RETRY` + 1, thời gian khớp backoff theo cấu hình hiện hành trong `config/policy.json`; `empty=false`; `data=null`. Đây là lỗi hệ thống (→ E2), **không phải** "không tồn tại" | `error="HTTPStatusError: Server error '500 Internal Server Error' for url 'http://mock:8100/vpn/connections/nv001'…"`, `attempts` = `TOOL_RETRY` + 1, thời gian khớp backoff theo cấu hình hiện hành trong `config/policy.json`, `empty=false`, `data=null` | ĐẠT |
| F1' | (tắt lỗi) | `b10 fault-off` → gọi lại lệnh trên | Giống hệt STT 9: `error=null`, `failed`/`CERT_EXPIRED` | `fault-off` → 200 `cleared`; `faults` → `[]`; gọi lại: `error=null`, `attempts=0`, phần tử đầu `failed`/`CERT_EXPIRED` như STT 9 | ĐẠT |
| F2 | `check_account_status` (ad) | `b10 fault-on /ad 500` → `b10 tool check_account_status user_id=nv007 account_type=email` | Như F1 | `error="HTTPStatusError: Server error '500 Internal Server Error' for url 'http://mock:8100/ad/users/nv007?account_type=email'…"`, `attempts` = `TOOL_RETRY` + 1, thời gian khớp backoff theo cấu hình hiện hành trong `config/policy.json`, `empty=false`, `data=null` | ĐẠT |
| F2' | (tắt lỗi) | `b10 fault-off` → gọi lại | Như STT 1 | `faults` → `[]`; gọi lại: `error=null`, `attempts=0`, `locked=true`, `lock_reason=bad_password` như STT 1 | ĐẠT |
| F3 | `check_catalog_entry` (software) | `b10 fault-on /software 500` → `b10 tool check_catalog_entry software_name=Zoom` | Như F1 | `error="HTTPStatusError: Server error '500 Internal Server Error' for url 'http://mock:8100/software/catalog/Zoom'…"`, `attempts` = `TOOL_RETRY` + 1, thời gian khớp backoff theo cấu hình hiện hành trong `config/policy.json`, `empty=false`, `data=null` | ĐẠT |
| F3' | (tắt lỗi) | `b10 fault-off` → gọi lại | Như STT 11 | `faults` → `[]`; gọi lại: `error=null`, `in_catalog=true`, `paid=false` như STT 11 | ĐẠT |
| F4 | `check_resource_sensitivity` (files) | `b10 fault-on /files 500` → `b10 tool check_resource_sensitivity resource_path=finance/Q3` | Như F1 | `error="HTTPStatusError: Server error '500 Internal Server Error' for url 'http://mock:8100/files/resources/finance/Q3'…"`, `attempts` = `TOOL_RETRY` + 1, thời gian khớp backoff theo cấu hình hiện hành trong `config/policy.json`, `empty=false`, `data=null` | ĐẠT |
| F4' | (tắt lỗi) | `b10 fault-off` → gọi lại | Như STT 18 | `faults` → `[]`; gọi lại: `error=null`, `sensitivity=high` như STT 18 | ĐẠT |
| F5 | 500 khác 404 | `b10 fault-on /software 500` → `b10 tool check_catalog_entry software_name=utorrent` → `b10 fault-off` | Khi đang có lỗi: `error≠null`, `empty=false`. So với STT 12 (404 → `empty=true`, `error=null`), hai trường hợp phải phân biệt được | Khi có lỗi: `error` chứa 500, `attempts` = `TOOL_RETRY` + 1, thời gian khớp backoff theo cấu hình hiện hành trong `config/policy.json`, `empty=false`. STT 12 (không có lỗi, 404): `error=null`, `empty=true`, `attempts=0`. Hai trường hợp phân biệt được | ĐẠT |
| F6 | Danh sách lỗi | `b10 faults` sau `fault-on`, rồi lại sau `fault-off` | Lần đầu có 1 phần tử `remaining=null`; lần sau `[]` | Trước F1: `[]`. Sau `fault-on /vpn`: 1 phần tử `fault_id=1`, `remaining=null`. Sau mỗi `fault-off` (4 lần): `[]` | ĐẠT |

## 4. Cổng 3

### 4.1. Vị trí trong `scripts/verify.sh`

- `verify.sh` **không có cổng 1**: `KNOWN_GATES="02345"` (`scripts/verify.sh:35`). Phần tự động của cổng 1 nằm trong
  `make test` (bước 2).
- Cổng 3 là **bước 5** (`run_gate 3`, `verify.sh:217-228`). Chạy trước: bước 1 `make lint`, bước 2 `make test`, bước 3 `make up`
  + kiểm `APP_ENV=dev`, bước 4 `ensure_ingest` = `make ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated`
  (`:155`). Chạy sau: bước 8 trả backend+worker về cấu hình `.env` (`:162-167`).
- `step_gate3` (`:157`) làm hai việc: `recreate "" "" ""`, tức `docker compose up -d --force-recreate --no-deps --wait backend worker`
  với `FAKE_SCENARIO`, `FAKE_NODE_DELAY`, `APPROVAL_SLA_MINUTES_DEV` rỗng rồi chờ `/api/health` 200 (`:136-141`); sau đó
  `make gate3 S=all` (= `uv run python -m tests.stack.gate3 all` với `COMPOSE`, `PYTHONPATH=backend`).
- **Service cần có:** postgres, qdrant, ml-service (healthy, đã nạp bge-m3 + reranker), backend, worker (healthy), mock. Không cần
  LLM thật: `LLM_BACKEND=scripted` với preset `config/scripted/tc*.yaml`.
- **Chốt an toàn của gate3** (dừng với exit 2 trước mọi HTTP): `APP_ENV=dev`, URL là `127.0.0.1`, `LLM_BACKEND=scripted`,
  `FAKE_SCENARIO` không đặt, cấm `down -v`/`volume rm|prune` (`backend/tests/stack/README.md:163-165`).
- Windows không có `make` và bash cho verify.sh, nên biên bản chạy **từng bước tương đương** bằng PowerShell (Phụ lục A).

Cổng 3 gồm hai phần:
- **(a) Tự động: gate3**, mục 4.2–4.3. Kết quả: **78/78 PASS**.
- **(b) Thủ công: biểu đồ hai đường + ngưỡng B9**, mục 4.4. Kết quả: **Hoãn – theo quyết định chọn ngưỡng trên model thật ở mốc G**.

### 4.2. (a) Bảng kịch bản gate3

Một số ca có kết quả phụ thuộc giờ chạy. Nếu một kịch bản vắt qua mốc giờ thì FAIL "khung giờ không đổi" → chạy lại.

| STT | Kịch bản | Kết quả | Tiêu chí |
|---|---|---|---|
| 0 | preflight | ĐẠT | xem `backend/tests/stack/gate3.py` |
| 1 | `tc02` | ĐẠT | xem `backend/tests/stack/gate3.py` |
| 2 | `tc04` | ĐẠT | xem `backend/tests/stack/gate3.py` |
| 3 | `tc05` | ĐẠT | xem `backend/tests/stack/gate3.py` |
| 4 | `tc06` | ĐẠT | xem `backend/tests/stack/gate3.py` |
| 5 | `tc09` | ĐẠT | xem `backend/tests/stack/gate3.py` |
| 6 | `tc13` | ĐẠT | xem `backend/tests/stack/gate3.py` |
| 7 | `tc16` | ĐẠT | xem `backend/tests/stack/gate3.py` |
| 8 | `tc28` | ĐẠT | xem `backend/tests/stack/gate3.py` |
| — | Tổng (`uv run python -m tests.stack.gate3 all`) | `==== 78 PASS, 0 FAIL ====` (run `704f3e0e`, 24/10/2026 01:07) | |

Cách đọc lỗi thường gặp: xem `backend/tests/stack/README.md:187-192`.

### 4.3. (a) Kiểm log sau gate3

| # | Kiểm | Lệnh | Mong đợi | Thực tế | Đạt/Không |
|---|---|---|---|---|---|
| G1 | 8 điểm log + quét bí mật trên `audit_logs` (chỉ đọc) | `docker compose --env-file .env exec -T backend python -m app.audit.check --since <giờ bắt đầu, ISO +07:00>` | Không báo thiếu điểm log, không lộ bí mật | `audit_check: nguồn app_monitor (READ ONLY)` → **1 thiếu, 0 bí mật (9 ticket)**: ticket tc28 `05a6c41d…`, điểm 3, thiếu `kb_version`. Dòng audit `B8/retrieval_error` có `error_stage="search"`, `kb_version` rỗng, lỗi `ConnectError: Qdrant get_aliases …`. Xem L4 ở mục 2.3 | KHÔNG ĐẠT (lệch code ↔ bộ kiểm, L4: đã chuyển – backend sửa sau tag) |
| G2 | Log backend/worker không có traceback lạ | `docker compose --env-file .env logs --no-color --since 30m backend worker \| Select-String -Pattern "Traceback","ERROR"` | Chỉ có lỗi đúng dự kiến của tc28 (Qdrant tắt) | 602 dòng: INFO 490, WARNING 2, ERROR 0, Traceback 0. Hai WARNING `app.api.health: kb probe lỗi` (TimeoutError, ConnectError) rơi đúng lúc tc28 tắt Qdrant. `ml:rerank` 9 lần: tb ~11,1 s, max 12,2 s (CPU) | ĐẠT |
| G3 | Stack về trạng thái đúng `.env` | `docker compose --env-file .env up -d --force-recreate --no-deps --wait backend worker` rồi `curl.exe -fsS http://127.0.0.1:8000/api/health` | 200 | Tạo lại backend+worker → healthy; `/api/health` 200. Env tạm vẫn giữ RATE=loose: không có `.env` để "trả về"; stack bị `down` ở mục 7 | ĐẠT |

### 4.4. (b) Phần thủ công: biểu đồ hai đường + ngưỡng B9

**Yêu cầu** (`docs/spec/build/nhanh/B08-B09-tra-cuu.md`):
- §7 (dòng 298): `RETRIEVAL_THRESHOLD` theo cấu hình hiện hành trong `config/policy.json`; ngưỡng chọn lại theo quy trình P3 mục 7.1 rồi cập nhật `policy.json`
  [Chốt cổng 3 + Đề xuất D-22].
- §11 (dòng 341), dòng "Thủ công": "Biểu đồ hai đường (trả lời bừa, E3 oan) theo ngưỡng + ngưỡng đã chọn". Đạt khi "đã cập nhật
  `policy.json`".

**Kết quả: Hoãn – theo quyết định chọn ngưỡng trên model thật ở mốc G** (phản hồi của Tuấn Anh, 24/10/2026; khớp D-22 và
`PROGRESS.md:1346-1347`, `:5952` @ `bc7eaae`). Tới thời điểm này trên repo không có biểu đồ, bảng quét hay biên bản chọn ngưỡng
nào. B10 không chạy quét ngưỡng.

Những gì đã tìm (24/10/2026, chỉ đọc):

| Hạng mục | Tìm thấy | Nguồn |
|---|---|---|
| Giá trị hiện tại | `RETRIEVAL_THRESHOLD` theo cấu hình hiện hành trong `config/policy.json` | `config/policy.json` @ `bc7eaae`; giống nhau ở mọi nhánh `origin/*` có commit sau 18/10 (29 nhánh) |
| Script quét | Có `python -m app.rag.eval_cli --kb-dir … --sweep [--csv]` (= `make eval-rag ARGS=--sweep`), in bảng 13 ngưỡng 0,30–0,90 bước 0,05 (Recall@5 / trả lời bừa / MRR theo ngưỡng). **Không vẽ PNG, không có cột "E3 oan" riêng.** Code ghi rõ: "chỉ để QUAN SÁT độ nhạy, KHÔNG dùng để chọn RETRIEVAL_THRESHOLD (D-22)" | `backend/app/rag/eval_cli.py:3-8, 50-52, 134`; `backend/app/rag/ingest/gate.py:223-238` @ `bc7eaae`; quyết định Q-3c-15 (`PROGRESS.md:1260` @ `bc7eaae`: "không vẽ PNG", CSV do người chuyển hướng vào `eval/reports/`) |
| File PNG/CSV/biểu đồ | Không có file `.png`/`.svg`/`.csv` nào về ngưỡng ở `bc7eaae` hay ở 29 nhánh trên; không có `eval/reports/` | `git ls-tree -r` từng nhánh |
| Lần chạy quét đã ghi | Chỉ có một lần **trên KB fixture** (28/09, L5 chặng 3c): "`eval-rag --sweep` in cùng số, bảng 13 ngưỡng ổn định (FG=0 từ T=0,40 trở lên)". Không có bảng số, không có đường E3 oan, không chọn ngưỡng | `PROGRESS.md:1919-1929` @ `bc7eaae` |
| Kế hoạch chọn ngưỡng | Hoãn tới khi có model thật: "FakeMl chỉ chứng minh cơ chế; số liệu cổng/ngưỡng thật chọn trên model thật (D-22)"; "xem lại ở Phase 5 + khi chọn ngưỡng ở mốc G" | `PROGRESS.md:1346-1347`, `:5952` (Việc treo 17) @ `bc7eaae` |
| Mục cổng 3 trong PROGRESS | Mục "Phase 3 — chặng 3h … e2e cổng 3, `make gate3`" chỉ ghi phần e2e/gate3; không có dòng nào về biểu đồ hai đường | `PROGRESS.md:3122` @ `bc7eaae` |
| PR / commit message | `gh pr list --search "sweep OR threshold OR ngưỡng"`: không PR nào về ngưỡng B9 (chỉ có ngưỡng 429 #62 và ngưỡng cảnh báo M9) | GitHub, 24/10/2026 |

Khi có kết quả, cần ghi:
- Bộ câu đã dùng (số câu có đáp án, số câu âm tính).
- KB và commit đã đo.
- Bảng hoặc biểu đồ trả lời bừa và E3 oan theo ngưỡng.
- Ngưỡng đã chọn, kèm commit cập nhật `policy.json` nếu có đổi.

## 5. Số liệu B9

**Bổ sung sau lượt đo thứ Hai 26/10; B10 nộp bản hiện tại trước.**

| Chỉ số | Giá trị | Điều kiện đo (commit, KB, cấu hình) | Nguồn (nhánh + commit + đường dẫn) |
|---|---|---|---|
| (bổ sung sau lượt đo 26/10) | | | |

Phạm vi đã tìm (24/10/2026, sau `git fetch --all`; chỉ đọc):

- `git log --all -i --grep=b9` cho ra 2 commit, đều là commit code của **node** B9, không phải nhiệm vụ B9:
  `9680471` (28/09, "node B8-B9 that") và `5ed423d` (30/09, "S0 B9 chi cho cau tra loi").
- Xét mọi nhánh `origin/*` có commit sau 18/10 (29 nhánh): tìm file mà nhánh thêm hoặc sửa so với `origin/main` trong `reports/`,
  `docs/`, `PROGRESS.md`, `eval/`, `scripts/`. Chỗ nhắc "B9" duy nhất là một dòng trong `docs/spec/build/phase4-thiet-ke-chi-tiet.md`
  (dòng ghi phiên bản tài liệu, có ở mọi nhánh) và một dòng ablation trong `docs/spec/build/nen-tang/P8-danh-gia-M8.md` (nhánh
  `origin/docs-p8-v14`, `ea1b3b8`). Cả hai đều nói về node B9. Không nhánh remote nào có thư mục `reports/`.
- `gh pr list --state all --search "B9"`: 0 PR. `gh issue list --state all --search "B9"`: 1 issue không liên quan (#8 "[M9-A1]
  View SQL…", đã đóng).

Để đối chiếu, **node B9 của graph** là cổng độ liên quan sau truy hồi:
- Từ Phase 4 S0-P1, B8 không còn rẽ sang B9 (`backend/app/graph/nodes/b08_retrieve.py:6-8`, `:63`).
- B9 chạy trong `b10_route`, sau `b10_need_type`, và **chỉ áp cho câu trả lời**. Khi không có chunk hoặc `retrieval_score` <
  `RETRIEVAL_THRESHOLD` (theo cấu hình hiện hành trong `config/policy.json`), ticket đi E3 `no_grounding` với step `B9`, event `no_evidence`
  (`backend/app/graph/nodes/b10_route.py:6-8`, `:105-109`).
- Cờ ablation `GROUNDING_GATE_ACTIONS` cho B9 chặn cả hành động (`b10_route.py:95-97`).

## 5b. Số liệu B8 (tham chiếu — không phải B9)

| Chỉ số (bộ `kb/eval/retrieval_set.yaml`, 34 câu có đáp án / 22 câu âm tính) | Giá trị |
|---|---|
| Recall@5 | **1.000** (34/34) |
| MRR@5 | **0.882** |
| Tỉ lệ trả lời bừa (ngưỡng theo cấu hình hiện hành trong `config/policy.json`) | 0.000 |

Nguồn: `reports/b8_recall_at5.md`. Đây là số tái lập trên commit `bc7eaae` (kb/ tree `2703720`), chạy ngày 23–24/10/2026.

## 6. Kết luận

| Mục | Kết luận |
|---|---|
| Cổng 1 — 12 tool | **ĐẠT — 20/20 lời gọi** khớp bảng mong đợi (12 tool, seed `bc7eaae`). Phần liên quan: STT 21 (audit thiếu trường bị từ chối) 33 passed, STT 22 (bản tự động) 25 passed. Danh sách lệnh là danh sách chính thức theo quyết định của Tuấn Anh 24/10 (L3 đã đóng) |
| Cổng 1 — lỗi 500 | **ĐẠT — 6/6 ca** xử lý đúng. Bật 500 trên `/vpn`, `/ad`, `/software`, `/files` → tool trả lỗi hệ thống (`attempts` = `TOOL_RETRY` + 1, thời gian khớp backoff theo cấu hình hiện hành trong `config/policy.json`, `empty=false`, không bị nhầm với "không tồn tại"). Tắt lỗi → `faults=[]`, chạy lại bình thường |
| Cổng 3 (a) tự động | **Đạt có ghi chú – gate3 78/78 PASS; kiểm audit 1 lệch (L4).** gate3 gồm preflight + 8 kịch bản. G2, G3 đạt. G1: tc28 thiếu `kb_version` ở điểm log 3 (mục 2.4). L4: **Đã chuyển – backend sửa sau tag** |
| Cổng 3 (b) thủ công | **Hoãn – theo quyết định chọn ngưỡng trên model thật ở mốc G.** Biểu đồ hai đường (trả lời bừa / E3 oan) + ngưỡng B9. `RETRIEVAL_THRESHOLD` giữ theo cấu hình hiện hành trong `config/policy.json` (mục 4.4) |
| Số liệu B9 | Bổ sung sau lượt đo thứ Hai 26/10; B10 nộp bản hiện tại trước (mục 5) |
| Điểm lệch | L1 `mock_services/README.md:72` ghi chuỗi quản lý của `l1_01` là `[it_mgr01]`, còn seed + test là `[l1_lead, it_mgr01]`. L4 `retriever.py:230-234` ↔ `audit/check.py:140-142` / `phase4…:739`. L5 các điều chỉnh để chạy trên Windows (`PYTHONUTF8`, `PYTHONIOENCODING`, PATH docker, Application Control chặn `pytest.exe`) |
| Việc tồn đọng | (1) L4: đã chuyển, backend sửa sau tag. (2) Sửa README mock (L1). (3) Lần dựng stack sau phải ingest `kb/` để alias rời fixture. (4) Ticket tc02 của lần gate3 dừng giữa chừng còn dở dang trong `servicedesk_pgdata`. (5) Số liệu B9: bổ sung sau lượt đo 26/10. (6) Biểu đồ ngưỡng B9: hoãn tới mốc G. (7) Kết quả chạy trên `bc7eaae`, chưa phải nhánh `d2-kichban-quan` |

**Kết luận chung B10:**
- **Cổng 1 đạt:** 20/20 lời gọi tool, 6/6 ca lỗi 500. Danh sách lệnh là danh sách chính thức theo quyết định của Tuấn Anh 24/10.
- **Cổng 3 (a) tự động đạt có ghi chú:** gate3 78/78 PASS; kiểm audit có 1 lệch (L4), **đã chuyển – backend sửa sau tag**.
- **Cổng 3 (b) thủ công** (biểu đồ hai đường + ngưỡng B9): **Hoãn – theo quyết định chọn ngưỡng trên model thật ở mốc G**.
- **Số liệu B9:** bổ sung sau lượt đo thứ Hai 26/10; B10 nộp bản hiện tại trước.
- Lần chạy trên code **`bc7eaae`** (worktree tách rời, vì volume B8 ở migration 0010), **không phải** `d2-kichban-quan` @ `a1078ff`.
- Trên Windows, gate3 (và các script Python in tiếng Việt) **phải chạy với `PYTHONUTF8=1`**. Không có biến này, `subprocess`
  giải mã output psql bằng cp1252 → `UnicodeDecodeError`, gate3 dừng ở tc02.

Người xác nhận: ____________________  Ngày: ____________

---

## Phụ lục A — Chuẩn bị stack cho B10

> **Chỉ chạy SAU KHI phiên B8 đã `docker compose down`.** Compose ghi cứng `name: servicedesk` (`docker-compose.yml:4`), nên
> worktree B8 và repo chính **dùng chung tên project, tên container và volume**. Nếu `up` ở repo chính khi B8 còn chạy, container
> của B8 sẽ bị tạo lại bằng code và `.env` của repo chính, làm hỏng số liệu B8.

### A.1. Kiểm trước

1. Không còn container nào của project: `docker compose ls` và `docker ps --filter "name=servicedesk"` đều không có
   `servicedesk` đang chạy.
2. Volume: `docker volume ls --filter name=servicedesk` cho ra `servicedesk_pgdata` và `servicedesk_qdrant`. Cả hai do B8 tạo:
   Postgres đã migrate tới `0010`, Qdrant đang trỏ alias `kb_current` vào **KB thật** (`kb/`). **Không** `down -v`, **không**
   `volume rm`/`prune`.
3. **Mật khẩu Postgres:** theo `b8_run.log` (lưu cục bộ, không đưa lên repo), B8 dựng volume bằng một file env tạm sinh từ `.env.example`. Vì vậy
   `init-roles.sh` đã tạo role với giá trị `PG_*PASSWORD` **mẫu**. `.env` của repo chính phải giữ đúng các dòng `PG_*PASSWORD`
   mẫu (`backend/tests/stack/README.md`: "Không đổi các dòng `PG_*PASSWORD`"). Nếu lệch, alembic sẽ báo
   `password authentication failed for user app_migrate` → **dừng, hỏi Tuấn Anh**, không tự xoá volume.
4. `.env` (tự soát bằng trình soạn thảo, **không** `cat`/dán đi đâu): `APP_ENV=dev`, `LLM_BACKEND=scripted`, đủ `SVC_AGENT_TOKEN`,
   `SVC_EXECUTOR_TOKEN`, `SVC_WORKER_TOKEN`, `JWT_SIGNING_KEY`, `MFA_ENC_KEY`; **`ML_SERVICE_TOKEN` ≥ 32 ký tự**
   (`ml_service/app/settings.py:17`; ngắn hơn thì ml-service không khởi động); các token `SVC_*` cũng ≥ 32 ký tự và khác nhau
   (`mock_services/README.md`: không đạt thì mock trả 503). Comment (`#`) **cả hai** dòng `FAKE_SCENARIO`, `FAKE_NODE_DELAY`, và
   dòng `APPROVAL_SLA_MINUTES_DEV` nếu có giá trị.
   *Lưu ý PowerShell 5.1:* `$env:X = ''` **xoá** biến chứ không đặt rỗng, nên compose sẽ lấy giá trị trong `.env`. Không thể dùng
   cách ghi đè bằng biến shell như verify.sh; phải để `.env` đúng ngay từ đầu.

### A.2. Đổi CRLF → LF cho file dùng trong container

Máy đặt `core.autocrlf=true` và repo không có `.gitattributes`. `git ls-files --eol` cho thấy file trong working tree đang là CRLF:

| File | Dùng ở đâu | Cần đổi? |
|---|---|---|
| `docker/postgres/init-roles.sh` | Mount vào `/docker-entrypoint-initdb.d/` của postgres | **Có**. Chỉ chạy khi volume trống; volume B8 đã init rồi nên lần này nó không chạy, nhưng vẫn đổi để an toàn nếu sau này phải init lại |
| `scripts/verify.sh` | Bash trên máy (cần `make`) | Không dùng trong B10 |
| `.claude/hooks/pre-commit-test.sh`, `docs/m9-giao-viec/tao-issue-m9.sh` | Không dùng trong container | Không |

Dockerfile của backend, mock và ml-service không `COPY` file `.sh` nào và không có `ENTRYPOINT` shell (CMD là `uvicorn`/`python`),
nên không còn file nào khác phải đổi.

```powershell
$p = "docker\postgres\init-roles.sh"
$t = [IO.File]::ReadAllText((Resolve-Path $p)) -replace "`r`n", "`n"
[IO.File]::WriteAllText((Resolve-Path $p), $t)          # .NET ghi UTF-8 không BOM
git ls-files --eol docker/postgres/init-roles.sh        # mong: i/lf  w/lf
git status --porcelain docker/postgres/init-roles.sh    # mong: rỗng (index vốn là LF)
```

### A.3. Lệnh tương đương `make up` (không có `make` trên Windows)

Theo `Makefile:46-75`, chạy ở gốc repo chính bằng PowerShell:

```powershell
$C = "docker compose --env-file .env"   # để đọc; mỗi lệnh dưới ghi đầy đủ
$env:PYTHONPATH = "ml_service"; uv run python -m app.lock ./models; Remove-Item Env:PYTHONPATH   # kiểm model bge-m3 + reranker theo lock
$sha = ""; if (-not (git status --porcelain --untracked-files=no)) { $sha = git rev-parse HEAD }   # cây bẩn → rỗng (lineage NULL)
docker compose --env-file .env build --build-arg GIT_SHA=$sha backend
docker compose --env-file .env build mock
docker compose --env-file .env build ml-service
docker compose --env-file .env up -d --wait postgres qdrant
docker compose --env-file .env run --rm --no-deps backend alembic upgrade head      # volume B8 đã ở 0010 → không làm gì
docker compose --env-file .env up -d ml-service backend worker mock                 # ml-service nạp model CPU, tối đa ~4 phút
docker compose --env-file .env exec -T mock python -c "import httpx; httpx.get('http://127.0.0.1:8100/health').raise_for_status()"
$env:PYTHONPATH = "mock_services"; uv run python -m app.seed validate; Remove-Item Env:PYTHONPATH   # = make seed (1/2)
docker compose --env-file .env exec -T mock python -m app.seed reset                                  # = make seed (2/2)
docker inspect -f "{{.State.Health.Status}}" (docker compose --env-file .env ps -q worker)          # mong: healthy
curl.exe -fsS http://127.0.0.1:8000/api/health                                                     # mong: 200
```

### A.4. Lệnh tương đương `make ingest` (KB fixture cho cổng 3)

```powershell
$kb = (Resolve-Path backend\tests\fixtures\kb).Path
docker compose --env-file .env run --rm --no-deps -v "${kb}:/srv/kb:ro" backend python -m app.rag.ingest.cli --kb-dir /srv/kb --allow-unevaluated
```

Lệnh này đổi alias `kb_current` từ KB thật (của B8) sang KB fixture. Nếu cần quay lại KB thật sau B10, dùng cùng lệnh với
`$kb = (Resolve-Path kb).Path` và bỏ `--allow-unevaluated`. Chạy trong PowerShell, không chạy trong Git Bash: `b8_run.log` (lưu cục bộ, không đưa lên repo) ghi
lại lỗi đổi đường dẫn của MSYS (đường dẫn Windows bị ghép sai).

### A.5. Lệnh tương đương `make gate3` / `make test` / `make lint`

```powershell
$env:COMPOSE = "docker compose --env-file .env"; $env:PYTHONPATH = "backend"
uv run python -m tests.stack.gate3 preflight
uv run python -m tests.stack.gate3 all
Remove-Item Env:COMPOSE, Env:PYTHONPATH
# make test (3 lệnh):
uv run pytest backend/tests/unit backend/tests/integration backend/tests/e2e
uv run pytest mock_services/tests -o pythonpath=mock_services
uv run pytest ml_service/tests -o pythonpath=ml_service -m "not ml_real"
```

`make test` dùng testcontainers, tức là **có** chạy docker. Không chạy nó trong lúc B8 đang chạy.

### A.6. Ghi chú máy

- **Không giữ máy thức tự động** (`caffeinate` chỉ có trên macOS). Trước khi chạy: cắm sạc, đặt Power mode "Never sleep", không
  chạy việc nặng khác. Máy ngủ giữa lượt → E2 `turn_budget_exceeded`, FAIL oan.
- Docker Desktop cần khoảng 8 GB RAM cho WSL2 (`backend/tests/stack/README.md`).
