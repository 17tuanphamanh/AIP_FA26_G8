# Ngữ cảnh phiên review — bản chi tiết (chuyển giao cho phiên Claude chat mới)

*Cập nhật: 27/09/2026, sau khi 2b-4 commit 2a9f3ee + CI 36274714302 xanh. **Code Phase 2 xong**; cổng 2 chờ một thành viên khác xác nhận. Việc tiếp theo: **Phase 3 (RAG, ml-service, B2–B9 thật)** — phiên Claude chat mới. Phiên Claude chat mới **đọc file này đầu tiên** rồi làm tiếp đúng vai trò. File gom mọi thứ đã thống nhất trong các phiên trước: vai trò, quy trình, luật, trạng thái từng phase, mọi quyết định kèm lý do, bài học, việc treo, lệnh hay dùng, thuật ngữ.*

---

## Mục lục

1. Bối cảnh đồ án
2. Vai trò của Claude chat và cách trả lời
3. Môi trường, công cụ, đường dẫn
4. Quy trình một bước (chặng) — từ plan tới CI, và chuyển phiên
5. Luật bắt buộc với coding agent
6. Mutation testing — cách làm và cách đọc
7. Quy trình cập nhật spec (chỉ Claude chat làm)
8. Trạng thái hiện tại và lịch sử commit
9. Kiến trúc đã xây — tóm tắt kỹ thuật
10. Toàn bộ quyết định đã chốt (theo thời gian) + lý do
11. Việc tiếp theo: commit 2b-3, rồi 2b-4 và checklist review
12. Việc treo theo phase
13. Bài học đã rút ra
14. Lệnh hay dùng
15. Thuật ngữ
16. Mẫu "Dán cho agent" và lời mở phiên

---

## 1. Bối cảnh đồ án

- **Đề tài:** AI Agent tự động hóa IT Service Desk cấp 1 với Human-in-the-Loop (EN: *Agentic AI for Level-1 IT Service Desk Automation with Human-in-the-Loop*). Đồ án tốt nghiệp ĐH FPT, chuyên ngành AI, nhóm 4 người. Mục tiêu điểm **8,5+**.
- **3 Objective:** Obj 1 (50–60%) agent L1: M1 phân loại + slot, M2 RAG, M3 tool + chẩn đoán, M4 điều phối; Obj 2 (30–40%) HITL: **M5 quyết định khi nào cần người (đóng góp chính)**, M6 phê duyệt, M7 audit; Obj 3 (0–20%) đánh giá M8.
- **Nguyên tắc:** Objective quyết định xây gì → Phase quyết định xây khi nào → RQ chỉ quyết định đo gì. Luôn gắn **[Chốt] / [Suy luận] / [Đề xuất]**. Thay đổi nhỏ, kiểm chứng được. An toàn: **giảm False Negative trước**, giảm escalate thừa sau.
- **Luồng 20 bước B1→B20**, 14 trạng thái, mã thoát E0–E9 (E9 = lỗi chưa lường trước, ngang E2), 8 điểm log bắt buộc, 8 giá trị `close_reason`. Chi tiết trong `NGU-CANH-DAY-DU.md` và khối CTX-1.1 đầu mỗi file `build/`.
- **Nhóm:** 4 thành viên (TV1–TV4; TV4 yếu hơn, kiêm tester). Tuấn Anh dùng Mac và **tự code toàn bộ** cùng agent; nhóm có 3 máy gaming (VRAM chưa ghi). Nhóm đã tự train 2 model (intent B3, injection B2) trên Kaggle/Colab.
- **GVHD:** không hỏi được các câu thiết kế → nhóm tự quyết (xây hợp lý trước, tối ưu sau), **chỉ báo cáo** cho thầy (`decisions.md`).
- **Chế độ xây (chốt 25/09):** "code trước, gắn API sau" — Phase 1–7 dùng `ScriptedLLM`; phần cần LLM thật dồn về **mốc G** (sau Phase 7, trước Phase 8).

## 2. Vai trò của Claude chat và cách trả lời

**Vai trò:** Tuấn Anh dán plan / báo cáo / output của coding agent (Claude Code CLI) vào Claude chat. Claude chat:

1. **Review** plan/báo cáo: đối chiếu spec trong Project, tìm lỗ hổng (đặc biệt test yếu, FN an ninh, lệch spec).
2. **Ra quyết định** thay nhóm khi agent hỏi (Q…), kèm lý do.
3. **Viết prompt "Dán cho agent"** ngắn, rõ, ở cuối mỗi lượt.
4. **Cập nhật spec** trong Project + chép xuống repo (mục 7).
5. Hướng dẫn Tuấn Anh chạy lệnh `!` / Terminal và **cách đọc kết quả**.
6. **Quản lý phiên (yêu cầu của Tuấn Anh, 27/09):** **Claude Code: mỗi chặng một phiên mới** — hết chặng (CI xanh) thì đưa lời mở phiên Claude Code mới (mục 16). **Claude chat: một phiên cho cả một phase lớn** (vd cả Phase 2); hết phase mới cập nhật file này và chuyển phiên Claude chat.

7. **Báo đổi model (yêu cầu 27/09):** khi review plan mỗi chặng, ghi rõ một dòng **"Model đề xuất cho chặng này: Opus / opusplan / Sonnet"** kèm lý do. Báo **chuyển lên Opus** ngay khi chặng chạm đồng thời/khóa/recover, an ninh, M5/calibrator, B17 thực thi; hoặc khi thấy dấu hiệu: mutation sống không giải thích được, plan sót nhiều điểm checklist, sửa qua lại > 2 vòng. Việc lặp ít rủi ro (UI Phase 7, seed, test theo mẫu) → Sonnet. Mặc định hiện tại: 2b-4 dùng `opusplan`.

8. **Nhắc cổng cần người khác kiểm (chốt 28/09):** Tuấn Anh **tự code toàn bộ** (bỏ phương án giao cho "thành viên B"). Vì cổng chỉ đạt khi **người xác nhận không phải người làm chính** [Chốt], mỗi khi tới cổng (hoặc phần thủ công của cổng) Claude chat phải **báo rõ**: cổng nào, người khác cần chạy lệnh gì, trên commit nào, đạt khi nào. Áp dụng cho cổng 1 (gọi tay 12 tool), cổng 3–8, và **Phase 10: người chạy thực nghiệm không phải người xây M5** [Chốt]. Việc dữ liệu (KB, bộ câu kiểm tra, kịch bản M8, gán nhãn, đo VRAM) vẫn giao cho nhóm.

**Cách trả lời bắt buộc (preference đã lưu trong memory project):**

- Với mỗi thứ Tuấn Anh dán: giải thích **lý do** của từng quyết định, nêu **input/output** (agent vừa làm gì, ra kết quả gì) và **cần kiểm gì / thế nào là đạt**. Tuấn Anh muốn **vừa làm vừa học**.
- Dùng bảng khi so sánh phương án; mỗi phương án nêu đánh đổi.
- Kết thúc bằng khối **"Dán cho agent"** (code block) và, nếu có lệnh, khối **"Chạy"** + **"Đạt khi"**.
- Tiếng Việt, thẳng, không vòng vo. Khi agent đúng thì nói rõ agent đúng; khi mình (Claude chat) sai thì nhận và sửa.
- Tuấn Anh hay hỏi "làm gì tiếp / sửa ở đâu": trả lời theo **bước đánh số**, lệnh copy được, nói rõ gõ ở **Claude Code (có `!`)** hay **app Terminal**.

**Thói quen review đã hình thành (giữ nguyên):**

- Soi "test có thật sự phân biệt đúng/sai không" (dữ liệu test làm hai kết quả ra cùng giá trị = test yếu; danh sách quét rỗng = xanh oan).
- Soi chỗ fail-closed: thiếu dữ liệu / lỗi → chặn, không âm thầm cho qua.
- Soi FN an ninh (gộp cảnh báo, bỏ sót sự cố, **ticket biến mất khỏi mọi hàng đợi**).
- Soi "một nguồn sự thật" (một giá trị chỉ một nơi quyết định; một nguồn đồng hồ; bảng seed là nguồn ưu tiên duy nhất).
- Soi lệch giữa spec và code trước khi commit.
- Soi rò tài nguyên khi request bị hủy (khóa advisory cấp session nằm trên kết nối pool).

## 3. Môi trường, công cụ, đường dẫn

| Thứ | Giá trị |
|---|---|
| Repo | `~/Documents/AIP_FA26_G8` (máy Mac: `/Users/pham12356iloud.com/Documents/AIP_FA26_G8`) |
| Nhánh / remote | `dev-tuananh` / GitHub `17tuanphamanh/AIP_FA26_G8` |
| Spec trong repo | `docs/spec/` (bản sao của Project, gồm cả `claude/`; mọi file ngữ cảnh đều có trong repo) |
| Tiến độ cho agent | `PROGRESS.md`, `CLAUDE.md` ở gốc repo |
| Stack | Python 3.12, uv (`pyproject` + `uv.lock`), FastAPI, Pydantic v2, LangGraph 1.2.12 + AsyncPostgresSaver, PostgreSQL 16 (port 55432), SQLAlchemy 2 + Alembic, Qdrant v1.19.1, APScheduler, httpx; React sau |
| Docker | colima trên Mac; Makefile tự nhận socket (`DOCKER_HOST`, `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`) |
| Test | pytest, testcontainers, FakeClock, ScriptedLLM, respx. **EPOCH test auth = năm 2099** (sửa bom hẹn giờ 2b-3) |
| Kiểm tĩnh | ruff, mypy, import-linter (5 hợp đồng) + test AST (hợp đồng 6: `SIDE_EFFECT_FUNCS`), gitleaks |
| CI | GitHub Actions (`ci`) |
| Compose | postgres, qdrant, backend, worker, mock (ml-service **chưa có**). **`APP_ENV` bắt buộc** (`${APP_ENV:?…}`) |
| `.env` | perm 600, gitignored, bí mật sinh ngẫu nhiên. **Không ai in ra.** Tuấn Anh đã thêm `APP_ENV=dev`, `FAKE_APPROVER_ID=l1_01` (27/09) |

**Claude chat làm việc với máy Tuấn Anh** qua cầu nối thiết bị: xin quyền thư mục `~/Documents/AIP_FA26_G8/docs/spec` (`device_request_folder_access`), sửa bằng python trên máy (`$HOME/mnt/spec/...`), rồi stage lên cloud → `project_write` bằng `local_path`. Phiên mới phải xin lại quyền thư mục. Nếu phiên không liên kết máy thì chỉ sửa được spec trong Project; nhờ agent chép xuống `docs/spec/`.

## 4. Quy trình một chặng — từ plan tới CI, và chuyển phiên

1. **Agent lập plan** (chưa code): file sửa/tạo, test, mutation dự kiến (test nào đỏ, assert nào), câu hỏi Q cần chốt.
2. **Claude chat review plan** → chốt Q, sửa chỗ yếu → khối "Dán cho agent". Nếu thân plan còn chỗ cũ lệch chốt: bảo Tuấn Anh chọn **"Tell Claude what to change"** (agent sửa plan, chưa code) thay vì Yes.
3. **Agent code** → `make lint` + unit (sandbox) → mutation logic (sandbox).
4. **Mutation SQL**: agent viết script `mutate_sql.py` (áp đột biến, chạy test, tự khôi phục, so nội dung file); **Tuấn Anh chạy từng lệnh** bằng `!` (cần Docker), dán kết quả; Claude chat kiểm "đỏ đúng chỗ".
5. **`! make test`** trên code sạch (Tuấn Anh chạy).
6. **Claude chat cập nhật spec** (mục 7) → báo agent danh sách file spec.
7. Agent **đối chiếu spec với code** (báo chỗ chữ lệch; code đúng thì sửa spec), stage đích danh, commit, push, **dừng**.
8. Tuấn Anh **xem CI trong app Terminal** + đối chiếu headSha → báo "CI xanh (run …)". *Số run thật lấy ở cột ID của `gh run list`, không dùng số mẫu.*
9. Claude chat cập nhật file này (mục 8, 11) → đưa **lời mở phiên Claude Code mới** (mục 16) → Tuấn Anh đóng phiên agent cũ, mở phiên Claude Code mới, dán lời mở.
10. Agent (phiên mới) đọc CLAUDE.md + PROGRESS, ghi số run vào PROGRESS (đi vào commit đầu chặng sau) → lập plan chặng sau.
11. **Hết phase lớn** (vd xong 2b-4 = hết Phase 2): Claude chat cập nhật đầy đủ file này → đưa lời mở phiên Claude chat mới.

## 5. Luật bắt buộc với coding agent

- **KHÔNG đọc/in `.env`.** Test auth dùng khóa sinh ngẫu nhiên trong fixture (`APP_ENV_FILE` rỗng khi test).
- **Không `--no-verify`.** Hook pre-commit chạy gitleaks + unit; hook commit-msg chặn dòng AI.
- **Không nới sandbox.** `gh` trong sandbox lỗi TLS keychain (x509 OSStatus -26276) → Tuấn Anh chạy ngoài.
- Lệnh cần Docker → Tuấn Anh chạy bằng **`!` ở đầu dòng** trong Claude Code; lệnh pytest trực tiếp phải **`cd` về gốc repo + biến colima** (mục 14).
- **Không commit/push trừ khi được bảo.** Commit message **tiếng Việt không dấu**, **không** Co-Authored-By / link phiên / dấu vết AI; tác giả Tuan Anh Pham.
- **Stage đích danh từng file**; kiểm stage không có `.env*`, `__pycache__`, `.pyc`, `settings.local.json`.
- Agent **không sửa `docs/spec/`**; chỉ ghi PROGRESS (việc spec cần sửa). Spec do Claude chat sửa.
- Xóa file chỉ khi có phép rõ ràng. Agent không tự điền số run CI.
- Chỉ cấp quyền `gh run list/view/watch` (chỉ đọc).

## 6. Mutation testing — cách làm và cách đọc

**Mục đích:** cố ý phá code một chỗ → test phải đỏ. Test vẫn xanh = test không bảo vệ chỗ đó.

**Cách làm:** agent áp một đột biến, nói trước **test nào đỏ, ở assert nào, giá trị bao nhiêu** → chạy → hoàn nguyên → cuối cùng không còn dấu đột biến. Đổi code (vd runner) thì **chạy lại cả bộ** mutation logic.

**Cách đọc:**

| Thấy | Nghĩa |
|---|---|
| **FAILED** đúng assert dự đoán | Bị bắt ✅ (dòng FAILED in 2 lần = pytest in lại ở tóm tắt, vẫn 1 test) |
| **FAILED** ở assert khác / vì lý do khác | Test dựng ca sai — sửa test (vd 2b-3 L17: đỏ vì "phiếu đã quyết" chứ không vì khóa) |
| **ERROR** ở dòng tổng / `no tests ran` / lỗi Docker | Lỗi môi trường — không tính |
| **PASSED** | Test yếu — sửa/thêm test rồi chạy lại (vd 2b-3 L25: khóa được GC tự nhả → xanh oan) |
| Đột biến làm test **treo** | Test phải có timeout để đỏ chứ không treo (2b-3 L28 "drain treo quá 2.0 giây") |

**Số liệu đã có:** 2b-1: 11 logic + 3 SQL; 2b-2: 15 logic + 7 SQL; **2b-3: 28 logic + 8 SQL** — tất cả bị bắt.

## 7. Quy trình cập nhật spec (chỉ Claude chat làm)

- **Nguồn sự thật:** Project "Đồ Án". `docs/spec/` trong repo là bản sao đầy đủ (kể cả `claude/ngu-canh-phien-review.md`).
- **Các bước (cách đã dùng ở 2b-3, gọn nhất):**
  1. Xin quyền thư mục `~/Documents/AIP_FA26_G8/docs/spec`; kiểm md5 bản trên máy.
  2. Viết script python trên máy (`device_bash`, `$HOME/work/edit.py`) thay chuỗi chính xác, **assert chuỗi cũ xuất hiện đúng 1 lần**.
  3. Stage các file đã sửa lên cloud → copy vào working dir → `project_write` (`local_path`) cùng path.
  4. Kiểm md5 hai bên khớp; nhờ Tuấn Anh chạy `git --no-optional-locks diff --stat docs/spec`.
  5. Báo agent danh sách file spec để stage chung commit.
- **Quy ước viết:** không viết lại mã giả gốc; thêm mục **"5.1 Chốt khi hiện thực …"** (bảng Điểm | Chốt | Lý do) + dòng **nhật ký thay đổi** + tăng phiên bản. Quyết định ghi vào `build/decisions.md` mục **4.1** (mã `2b-Q…`, `2b-QA…`, `2b-3-Q…`).
- **Trước commit:** agent đối chiếu spec vừa sửa với code. Nếu lệch mà code đúng ý đã chốt → **sửa spec theo code**, không sửa code đã xanh chỉ để khớp chữ.

## 8. Trạng thái hiện tại và lịch sử commit

| Chặng | Nội dung | Commit / CI |
|---|---|---|
| Phase 0 | Chốt N1–N5, Q1–Q14 thành quyết định nhóm, D-01…D-33 | (tài liệu) |
| Phase 1 (1a, 1b, 1c) | DB 22 bảng + role + trigger; mock + 12 tool + ToolResult; auth/MFA/IDOR | 62b0d0e, CI 36195560365 ✅ |
| 2a | Runtime LangGraph, goto, effects.once, boundary E9, khóa ticket, runner, worker, heartbeat | 9b310d4, CI 36226646863 ✅ |
| 2b-1 | B1 thật (phiên theo họ token), cảnh báo dò mật khẩu, migration 0004 `alerts.subject` | 6c43153, CI 36240526098 ✅ |
| 2b-2 | B20 thật, hàng đợi L2, `resolution_path`, chặn key lạ, migration 0005 `turns.recover_attempts` | b68e800, CI **36243253945** ✅ (chạy lại bây giờ sẽ đỏ vì bom EPOCH — đã sửa trong 2b-3) |
| 2b-3 | Route ticket/sự kiện/duyệt, privacy guard fail-closed, 202 + giao khóa, `run_new`, recover snapshot rỗng → E9, lifespan, health `runtime` | **dcc5ddc, CI 36270415646 ✅** |
| 2b-4 | `make gate2` (10 kịch bản trên stack compose thật), `StackScenario` chỉ số theo state, thẻ `[fake:<preset>]`, `FAKE_SCENARIO`/`FAKE_NODE_DELAY` fail-closed | **2a9f3ee, CI 36274714302 ✅**. 10/10 kịch bản 0 FAIL trên máy Tuấn Anh. **Cổng 2 đạt (28/09):** Tạ Duy Anh chạy `make gate2 S=all` trên `2a9f3ee` (WSL 2, RTX 4050 Laptop 6 GB) — 89 PASS / 0 FAIL, threads đạt (20 ticket = 20 thread) |
| Phase 3 | RAG, ml-service, B2–B9 thật | ⬜ tiếp theo (phiên Claude chat mới) |

Số test: 2a 1312 backend + 86 mock; 2b-1 1371; 2b-2 1448; 2b-3 1550 (unit 1409); **2b-4 1643 backend (1501 unit + 113 integration + 29 e2e) + 86 mock**.

Tiến độ ước lượng toàn đồ án [Suy luận]: ~22% theo code, ~27–30% nếu tính thiết kế. Phần quyết định điểm (M5 Phase 6, thực nghiệm Phase 8–10) chưa bắt đầu.

## 9. Kiến trúc đã xây — tóm tắt kỹ thuật

**Hạ tầng/DB (Phase 1a):** 22 bảng (P7); role `app_migrate`, `app_rw`, `app_monitor`; `audit_logs`, `security_events` append-only (quyền + trigger + chặn TRUNCATE); migration 0001–0005.

**Tool registry + mock (1b):** `registry.call` trả `ToolResult(tool, data, error, attempts, empty)`, **không raise**; breaker mở → `error="circuit_open"` (E2); chỉ lỗi hợp đồng mới raise (→ E9); ghi 404/409 → E7; retry 2 lần backoff 1s/2s. Mock có `/_admin/faults`.

**Auth (1c):** đăng nhập qua IdentityProvider (mock AD); JWT + refresh xoay vòng, dùng lại → thu hồi cả họ token; khóa 15 phút sau 5 lần sai/10 phút; MFA chỉ qua CLI, fail-closed; IDOR → **404 giống hệt**; worker không có `SVC_EXECUTOR_TOKEN`; `manager_id` NULL không khớp allow.

**Runtime (2a):** `goto()` kiểm chuyển + ghi audit cùng transaction, khóa idempotent sha256(ticket, step, event, turn_id, loop_seq); `effects.once`; `with_error_boundary` (re-raise `GraphBubbleUp`/`GraphInterrupt`, còn lại → E9); `PgTicketLock` (advisory lock cấp session, pool riêng); runner submit/resume/recover (giữ turn_id); recover gặp `b17_execute` → E7; `late_event` → 409 + audit; worker `scan_deadlines` 15s, `scan_stale_turns` 60s; heartbeat + healthcheck.

**B1 thật (2b-1):** phiên → AD → khóa → disabled/terminated → role → `RequesterContext.from_ad` (frozen). Phiên = họ token. AD lỗi → E2 `identity_unverifiable`; AD 404 → `S_BLOCKED invalid_credentials`; role không ánh xạ → E2 `role_unmappable`. Cảnh báo dò mật khẩu `AlertWriter.raise_once` khóa `(password_bruteforce, user_id, lock_start)`.

**B20 thật (2b-2):** `finalize_once` trước → điểm log 8 từ dòng đã lưu → `escalation_create` + `notify_user` qua `effects.once`. `resolution_path` B20 tự suy. `goto()`/boundary chặn key ngoài `TicketState`. Lỗi ở B20 → ném tiếp; worker tăng `recover_attempts` **trước** mỗi lần; >3 → B20: `finalize_failed_permanent`, node khác: E9 `recover_exhausted`. `GET /api/escalations/queue` (l1, l2), lọc `is_parent=false`.

**API + nối runtime (2b-3):**
- Route: `POST /api/tickets`, `GET /api/tickets/{id}`, `POST /api/tickets/{id}/messages`, `POST /api/tickets/{id}/confirm`, `POST /api/approvals/{id}/decision`. Router mỏng ở `app/api/{tickets,approvals,background,errors}.py`.
- Thứ tự kiểm messages/confirm: 413 (64 KB, đếm byte đọc thật) → quyền → tải ticket → không đọc được 404 → không phải chủ 403 → ticket con 409 → body 422 → privacy guard → `start_event`. 403/404-có-thật ghi 1 `permission_denied`, guard không được gọi.
- `POST /api/tickets`: một transaction INSERT `tickets(created_at = Clock của app)` + `turns` → task nền `run_new` → 202. `run_new` dưới khóa: lượt đã đóng hoặc đã có state → no-op.
- Sự kiện: `start_event` lấy khóa trong request, guard trạng thái → 409/422, hợp lệ → **giao khóa** cho task nền (try/finally + cờ `handed_off`), 202. Đang giữ khóa quá `lock_timeout` → 503 + Retry-After. Worker vẫn dùng `deliver_event`.
- Duyệt: `lock_row` FOR UPDATE → 404 / `may_decide_as` 403 / xác định muộn (`clock.now() >= deadline`) → **nhả hàng** → muộn: `mark_late` (chỉ audit `late_event`, **không đổi status**) + 409; rejected thiếu note → 422; note qua guard → `start_event`. Route không ghi quyết định (B16 `approvals.close WHERE status='pending'`). `approver_id` chỉ từ token.
- GET: response model khai báo (`TicketView`); có `final_state` → status từ `tickets`, còn mở → checkpoint; `waiting_for` chỉ từ checkpoint; checkpoint lỗi → 503.
- Privacy guard: port `PrivacyGuard`; `NotRedactingGuard` chỉ khi `APP_ENV ∈ {dev,test}`; env khác (hoặc có `FAKE_APPROVER_ID`) → backend + worker từ chối khởi động.
- Recover: lượt mở + snapshot rỗng → chạy state đầu dựng từ dòng `tickets` (như `run_new`, **không gọi** `run_new` vì tự khóa chết), giữ `turn_id`; quá 3 lần → `_give_up_before_checkpoint` → E9 `recover_exhausted` (audit `no_checkpoint`) qua B20.
- Task nền: set giữ tham chiếu, `done_callback` log exception, tắt app chờ ≤ N giây rồi hủy; `CancelledError` không thành E9. `BackgroundRuns.drain` đã sửa lỗi quay vô hạn.
- `create_app(runtime_factory, guard)`: lifespan mở runtime; lỗi → route ticket/duyệt 503, `/api/health` 200 + `"runtime": "up"|"down"`.
- `SqlApprovals` → `app/approval/store.py` (`close`, `lock_row`, `mark_late`); B15 giả dùng `FAKE_APPROVER_ID` (thiếu dòng `users` → E9).

## 10. Toàn bộ quyết định đã chốt + lý do

### 10.1. Phase 0 (`decisions.md` §1–§4)

- **N1:** LLM đa provider, ngân sách < 1 triệu đồng; `spend.cap_usd` 38. **N2:** 3 máy gaming + 1 Mac; VRAM chờ ghi. **N3:** 70/20/10 + độ nhạy. **N4:** R01–R20 (R22 cũ → R17). **N5:** Kaggle/Colab, fp32; ONNX ngoài git.
- Q1–Q14 thành quyết định nhóm (§2); D-01…D-33 "đã chốt theo đặc tả" (§3). N1/N2 chỉ chặn mốc G.

### 10.2. Phase 1

- **1b:** FORBIDDEN 5 nới cho `S_ESCALATED`; hợp đồng 6 thành test AST; cấm 2 chặn mọi `approval_result != approved`; cấm 3 thiếu hash thì chặn; cấm 4 audit cùng transaction.
- **1a:** `redacted_request` (không có `raw_request`); `transaction_log` `begun`; `audit_logs` `raw_prob`/`p_method`; trigger chặn TRUNCATE; Alembic bằng `app_migrate`.
- **1c:** các điểm auth ở mục 9; Caddy `X-Forwarded-For` để Phase 7.

### 10.3. Phase 2a

Như mục 9 phần runtime; ghi chú bảng `notifications` cần trước Phase 4; TC34–36 để Phase 5.

### 10.4. Phase 2b-Q1…Q7

| Mã | Chốt | Lý do chính |
|---|---|---|
| Q1 | Một writer cảnh báo idempotent; khóa `(rule_id, subject, window_start)`; `subject` không DEFAULT | Khóa cũ gộp cảnh báo nhiều người = FN an ninh |
| Q2 | Port `PrivacyGuard`; `NotRedactingGuard` chỉ khi `APP_ENV` ∈ {dev, test} | Fail-closed, không chạy dữ liệu thật mà không che (D-07) |
| Q3 | Route duyệt trong 2b; `FAKE_APPROVER_ID` dev/test only | Chứng minh cổng 2 trên stack thật |
| Q4 | Mọi E5 là deny case | Hash lệch = kế hoạch bị sửa sau duyệt |
| Q5 | 2b kiểm 6/8 `close_reason`; 2 giá trị L2 để Phase 7; ghi một lần theo từng cột | Ticket escalate đóng với `close_reason = NULL` |
| Q6 | Lỗi B20: ném tiếp, chạy lại tối đa 3 lần rồi `finalize_failed_permanent` | Không để ticket biến mất khỏi hàng đợi |
| Q7 | `role_unmappable` → E2; AD 404 → `invalid_credentials`; TicketBusy → 503 + Retry-After; non-owner đọc được → 403, không → 404; `wake_parent` sau khi nhả khóa | Lỗi cấu hình phải tới L2; tránh deadlock con–cha |

### 10.5. Phase 2b-2 (2b-QA…QD)

| Mã | Chốt | Lý do |
|---|---|---|
| QA | B20 suy `resolution_path` tại một chỗ; `goto()`/boundary chặn key ngoài `TicketState` | LangGraph bỏ im lặng key lạ |
| QB | Đếm bằng `turns.recover_attempts`, tăng trước khi recover | Đếm số lần thử, không đếm thất bại |
| QC | `finalize_once` trước, điểm log 8 từ dòng đã lưu | Audit và `tickets` luôn khớp |
| QD | Route queue; `handoff_note.request` chỉ từ `redacted_request`; `closed_at` ở B20; `created_at` từ `Clock` app | Một nguồn đồng hồ |

### 10.6. Phase 2b-3 (2b-3-Q1…Q5, QA…QD) — spec: B15 §5.1, P1 §7/§10, 01 §4.2, decisions 4.1

| Mã | Chốt | Lý do |
|---|---|---|
| Q1 | Sự kiện qua API trả **202**, giao khóa cho task nền (try/finally + cờ đã giao) | Chốt 14.3; request bị hủy mà không nhả thì kết nối về pool vẫn giữ khóa → ticket khóa vĩnh viễn |
| Q2 | **A:** `mark_late` không đổi `approvals.status`, chỉ audit `late_event` (`reason = expired \| already_decided`); mọi đường 409 để lại đúng 1 `late_event`; **bằng hạn = muộn** | Đổi `pending → late_ignored` trước chu kỳ quét → worker không bắn timeout → ticket kẹt (FN) |
| Q3 | `APP_ENV` bắt buộc, compose `${APP_ENV:?…}` | Không mặc định = fail-closed |
| Q4 | Không seed `FAKE_APPROVER_ID` vào DB; thiếu → E9; 2b-4 `gate2.py` đăng nhập l1 trước | Không lọt user giả sang env khác |
| Q5 | 413 trước quyền, đếm byte đọc thật (chunked cũng chặn) | Không tốn tài nguyên, không lộ gì |
| QA | Thứ tự kiểm messages/confirm (mục 9); người lạ vào ticket con → 404 không 409 | 409 trước 404 lộ sự tồn tại ticket (IDOR) |
| QB | GET: response model khai báo; status một nguồn theo trạng thái đóng/mở; checkpoint lỗi → 503 | Một nguồn sự thật; không lộ `risk`, `requester_context` |
| QC | Chết trước checkpoint đầu: recover chạy state đầu từ dòng `tickets`; quá 3 lần → E9 qua B20 | Trước đó ticket không `final_state` = biến mất khỏi hàng đợi |
| QD | Runtime lỗi lúc khởi động → route 503, health 200 + `runtime` | Không 503 âm thầm khi `make up` vẫn xanh |

Cũng chốt: `view_started_at` tùy chọn, `view_duration` tính phía server; EPOCH test auth → 2099; guard chạy sau kiểm quyền.

## 11. Việc tiếp theo

**Đóng Phase 2 (song song, không chặn Phase 3):**

1. Mã commit 2b-4 = **2a9f3ee** (đã điền mục 8).
2. **Xong (28/09):** Tạ Duy Anh xác nhận cổng 2 (89 PASS / 0 FAIL trên `2a9f3ee`); VRAM máy thứ nhất (6 GB) đã ghi vào `decisions.md` §1.3. Còn đo 2 máy gaming kia (N2). Agent ghi "cổng 2 đạt" vào PROGRESS ở commit tiếp theo.
3. Chưa rõ agent 2b-4 đã rà hết mọi chỗ đọc trạng thái sau 202 bằng `after_event` hay chưa — hỏi lại ở đầu Phase 3 nếu PROGRESS không ghi.

**Phase 3 (cổng code tự động của Phase 2 đã xanh → được mở, theo `decisions.md` §4):**

- Kế hoạch nền: `claude/rag-hien-trang-va-viec-sau-phase2.md` + `build/nen-tang/P3-rag-pipeline.md`, `P4-ml-service.md`, `P2-llm-gateway.md`, `B02`, `B03-B05`, `B06-B07`, `B08-B09`.
- **Nút thắt là dữ liệu, không phải code:** cần 5 tài liệu KB VPN + `kb-facts.md` + 30 câu kiểm tra có đáp án + ≥ 20 câu không có đáp án (D-22). Chưa có → làm trước phần không cần dữ liệu (ml-service `/embed` `/rerank` `/count_tokens`, `make ingest` khung, `retrieve()` với embedder giả, B2 privacy guard thật thay `NotRedactingGuard`).
- **Chế độ tăng tốc (Tuấn Anh chốt 27/09):** bỏ lịch 10 tuần, chạy theo **cổng** — xong cổng nào sang phase sau ngay. Giữ đủ quy trình (plan → mutation logic + SQL → review) cho phần an toàn / đồng thời / M5; giảm nghi thức (ít mutation, Sonnet, gộp chặng nhỏ) cho phần lặp ít rủi ro. Ước lượng [Suy luận]: xong code Phase 3–7 khoảng 2,5–3,5 tuần nếu dữ liệu làm song song.
- **Giao việc dữ liệu cho nhóm (đề xuất đã gửi Tuấn Anh):** TV1 KB VPN + bộ câu kiểm tra; TV3+TV4 hướng dẫn gán nhãn + kịch bản M8 (mục tiêu 150); TV2 gọi tay 12 tool (cổng Phase 1) + xác nhận cổng 2 + `nvidia-smi`.
- **Model:** Phase 3 phần ml-service/ingest → `opusplan` hoặc Sonnet; B2 privacy guard (an ninh, FN) → Opus.
- Checklist soi plan Phase 3: lập ở phiên mới, dựa trên P3 §cổng 3, D-21 (chunk ≤ 380 token), D-22 (ngưỡng E3 chọn trên bộ không đáp án), D-23 (truy hồi lại không lọc intent), E2 ≠ E3 (lỗi hệ thống ≠ không có tài liệu, bất biến 6), CI dùng embedder giả, model 2 GB ngoài git.

## 12. Việc treo theo phase

| Khi | Việc |
|---|---|
| Ngay (nhóm) | 1 thành viên gọi tay 12 tool (cổng Phase 1); 3 máy gaming chạy `make up` + ghi VRAM (N2); soạn 5 tài liệu KB VPN + `kb-facts.md` + bộ câu kiểm tra; bộ kịch bản M8 + hướng dẫn gán nhãn (TV3/TV4); gửi GVHD tóm tắt `decisions.md` |
| 2b-4 | ha.lt đăng nhập một lần trước ticket cần duyệt; `gate2.py` đăng nhập l1 trước |
| Phase 3 | B6 lọc tool theo `arg_slots`; chạy thật **một lần** luồng VPN với model rẻ; ScriptedLLM trả cả ca xấu; ml-service vào compose; CI dùng embedder giả; privacy guard thật thay `NotRedactingGuard` |
| Trước Phase 4 | Bảng `notifications` (migration mới + P7 lên 23 bảng); route xem phiếu ghi `first_viewed_at`; B15 thật thay B15 giả |
| Phase 5 | Worker đối soát ticket cha ở `parent_wait` (phòng mất `wake_parent`); TC32–36; model intent/injection theo P11 |
| Phase 7 | 2 `close_reason` của L2 + route đóng escalation + TC23; luật M9 cho `finalize_failed_permanent` và `no_checkpoint`; chốt `subject` 13 luật M9 còn lại; frontend khóa refresh 1 tab; Caddy `X-Forwarded-For`; `view_started_at` từ UI |
| Mốc G | Chọn model bằng probe, điền `pricing`, chạy các phần dồn |

## 13. Bài học đã rút ra

**Test & mutation**

- Mutation bắt được test **xanh oan**: `created_at` theo `now()` DB còn test theo FakeClock; dữ liệu chèn đúng thứ tự → bỏ `ORDER BY` vẫn xanh; khóa được GC tự nhả → test "nhả khóa" xanh oan (2b-3 L25); đỏ vì lý do khác (L17).
- Không có `ORDER BY` thì SQL không bảo đảm thứ tự.
- Ca cốt lõi cần **bản Postgres**, không chỉ unit với store giả.
- Test dựng ca phức tạp nên **kiểm điều kiện đầu vào** trước.
- Test quét "mọi bảng / mọi route" phải **assert danh sách không rỗng** (≥ số kỳ vọng).
- Test integration dùng chung DB: worker quét cả dữ liệu sót của test khác → kiểm theo id của test, không đếm tổng.
- Bom hẹn giờ: EPOCH test cố định + thứ dùng giờ thật (cookie jar httpx) → test đỏ sau vài giờ; CI xanh chỉ vì chạy trước giờ đó. Dời EPOCH ra xa (2099).
- `BaseException` mô phỏng process bị giết; `CancelledError` cũng là `BaseException` → boundary không bắt.

**Thiết kế**

- LangGraph 1.x **bỏ im lặng** key không khai báo trong `TicketState`.
- LangGraph ghi **checkpoint input trước node đầu**, nên "chưa có checkpoint" chỉ xảy ra trước lần invoke đầu tiên (khe giữa commit `tickets.create` và invoke).
- **Đếm số lần thử, không đếm số lần thất bại.**
- **Một nguồn sự thật:** một giá trị một nơi quyết định; một nguồn đồng hồ; trạng thái phiếu chỉ B16 đổi.
- **Fail-closed:** không DEFAULT cho cột/env bắt buộc có ý nghĩa; guard dev-only thì env khác không khởi động.
- Khóa advisory cấp session sống trên **kết nối pool**: không nhả khi request bị hủy = khóa vĩnh viễn.
- Hàm tự lấy khóa không được gọi từ chỗ đang giữ khóa đó (tự khóa chết).
- Thứ tự kiểm quyết định lộ thông tin: 404 phải trước mọi mã khác phụ thuộc sự tồn tại tài nguyên.
- `max(0, …)` có thể che lỗi. Hai NULL không trùng trong UNIQUE. Dữ liệu quan sát không dùng làm dữ liệu điều khiển.

**Môi trường**

- `.pyc` cũ làm mutation sai → `PYTHONDONTWRITEBYTECODE=1`.
- Migration đã chạy trên DB lâu dài thì không sửa.
- pytest trực tiếp thiếu `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE` → Ryuk lỗi.
- `!` chạy ở thư mục hiện tại của phiên → luôn `cd` về gốc repo.
- zsh: `#` không là comment khi gõ tay; `<id>` bị hiểu là chuyển hướng; `!` phải ở đầu dòng; mỗi lần một lệnh.
- `git status` có thể để lại `.git/index.lock` → `git --no-optional-locks`.
- Postgres tra tên bảng không kèm schema kể cả dòng từ `information_schema` → dùng tên đủ schema.

## 14. Lệnh hay dùng

```bash
# Test đầy đủ (Tuấn Anh, trong Claude Code)
! cd /Users/pham12356iloud.com/Documents/AIP_FA26_G8 && make test

# Pytest đích danh
! cd /Users/pham12356iloud.com/Documents/AIP_FA26_G8 && DOCKER_HOST=unix://$HOME/.colima/default/docker.sock TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock PATH=/Applications/Docker.app/Contents/Resources/bin:$PATH PYTHONDONTWRITEBYTECODE=1 uv run pytest backend/tests/integration/<file>.py -k "<tên test>"

# Mutation SQL qua script của agent (mỗi lần một mã S1…Sn; đường dẫn script agent đưa)
! cd /Users/pham12356iloud.com/Documents/AIP_FA26_G8 && DOCKER_HOST=unix://$HOME/.colima/default/docker.sock TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock uv run python <đường dẫn>/mutate_sql.py S1

# Xem spec đã đổi
! cd /Users/pham12356iloud.com/Documents/AIP_FA26_G8 && git --no-optional-locks diff --stat docs/spec

# Dựng stack
! cd /Users/pham12356iloud.com/Documents/AIP_FA26_G8 && make up
! docker compose ps worker     # phải (healthy)

# Xem CI (app Terminal, không cần !)
cd ~/Documents/AIP_FA26_G8
gh run watch $(gh run list --branch dev-tuananh -L 1 --json databaseId -q '.[0].databaseId') --exit-status
gh run list --branch dev-tuananh -L 1                    # số run = cột ID
gh run view SỐ_RUN --json headSha -q '.headSha[0:7]'     # SỐ_RUN = số thật ở cột ID
gh run view SỐ_RUN --log-failed                          # khi CI đỏ

# Kiểm .env mà không lộ bí mật
grep -E '^(APP_ENV|FAKE_APPROVER_ID)=' ~/Documents/AIP_FA26_G8/.env
```

## 15. Thuật ngữ

| Từ | Nghĩa |
|---|---|
| Agent | Claude Code CLI đang code trong repo |
| Chặng | Một bước nhỏ trong phase (2a, 2b-1, 2b-2…) |
| Cổng (gate) | Điều kiện nghiệm thu cuối phase; phần thủ công do người không làm chính xác nhận |
| Mutation / đột biến | Cố ý phá code để kiểm test có bắt được không |
| Fail-closed | Khi thiếu/lỗi thì chặn, không cho qua |
| FN / FP | Bỏ sót sự cố / báo động thừa |
| IDOR | Truy cập tài nguyên của người khác bằng cách đổi id |
| Họ token | Chuỗi refresh token nối nhau qua `token_family_id` |
| Idempotent | Chạy lại nhiều lần kết quả như một lần |
| `effects.once` | Chạy side effect đúng một lần theo khóa (bảng `side_effects`) |
| Late event | Sự kiện tới khi ticket không còn chờ đúng loại đó → 409 |
| Recover | Worker chạy lại lượt bị kẹt (process chết) |
| Giao khóa | Request lấy khóa ticket rồi chuyển quyền nhả cho task nền |
| `run_new` / `start_event` | Chạy lượt đầu của ticket mới / nhận sự kiện từ API (worker dùng `deliver_event`) |
| Xanh oan | Test xanh dù code sai (test không phân biệt được) |
| Seed | Dữ liệu cố định nạp sẵn |
| Mốc G | Thời điểm gắn LLM thật (sau Phase 7) |

## 16. Mẫu "Dán cho agent" và lời mở phiên

**Duyệt commit 2b-3 (đang chờ dán):**
```
Duyệt commit 2b-3. Trước khi commit, thêm 1 assert nhỏ: test quét guard phải assert số bảng đã quét ≥ 22 (lọc đúng schema public, không xanh oan khi danh sách rỗng); chạy lại test đó trong sandbox nếu được, không thì ghi rõ chưa chạy.

Tôi đã cập nhật spec (đã sửa luôn 3 chỗ chữ lệch bạn báo: recover không gọi run_new; nhả hàng ngay sau khi xác định muộn; route dùng start_event, note qua guard). Thêm 4 file vào commit:
- docs/spec/build/nhanh/B15-B16-phe-duyet.md
- docs/spec/build/nen-tang/P1-langgraph-runtime.md
- docs/spec/build/01-kien-truc-project.md
- docs/spec/build/decisions.md

Message thêm các dòng:
"- spec: B15 5.1 (mark_late khong doi status, 202 + giao khoa), P1 muc 7 (run_new, snapshot rong -> E9), 01 api->guard, decisions 2b-3 (nguoi cap nhat)"
"- test: doi EPOCH auth sang 2099, sua bom hen gio tu 1c"

Đối chiếu lại nhanh 3 chỗ vừa sửa với code. Stage đích danh, kiểm stage (không .env*, __pycache__, .pyc, settings.local.json), commit, push, báo tôi mã commit rồi DỪNG chờ CI.
```

**Duyệt plan (chung):**
```
Chốt <chặng>:
Q-x: <lựa chọn> + <bổ sung/điều kiện>.
...
Làm như chặng trước: lint + unit, mutation logic, mutation SQL qua script (đưa tôi từng lệnh, cd gốc repo + biến colima), rồi báo tôi ! make test. Chưa commit.
```

**Báo CI:**
```
CI của <mã> xanh (run <số>). Sang <chặng sau>: lập plan trước, chưa code.
```

**Lời mở phiên Claude chat mới (chỉ khi hết một phase lớn; dán vào phiên mới trong Project "Đồ Án"):**
```
Đọc claude/ngu-canh-phien-review.md trong Project trước (đọc hết cả 16 mục). Đây là phiên review tiếp nối. Trạng thái: <chặng> — <commit/CI hoặc việc đang chờ>. Việc tiếp theo: <…>.
```

**Mở phiên Claude Code mới (mỗi chặng một phiên):**
```
Đọc CLAUDE.md và PROGRESS.md (mục Phase 2, chặng 2b). <chặng> đã commit <mã>, đã push. Tôi sẽ báo kết quả CI.
Luật giữ nguyên: không đọc/in .env; không --no-verify; không nới sandbox; lệnh cần Docker thì báo tôi chạy bằng ! (pytest kèm biến colima và cd về gốc repo); stage đích danh; không commit/push trừ khi tôi bảo; commit tiếng Việt không dấu, không dòng AI.
Khi tôi báo CI xanh: ghi số run vào PROGRESS (vào commit đầu chặng sau), rồi lập plan chặng sau theo PROGRESS. Chưa code cho tới khi tôi duyệt.
```

---

## Tài liệu liên quan trong Project

`build/decisions.md` (§1–§4.1), `build/nhanh/B01-xac-thuc.md` §5.1, `build/nhanh/B15-B16-phe-duyet.md` §5.1, `build/nhanh/B20-audit-escalate-L2.md` §5.1, `build/nen-tang/P1-langgraph-runtime.md` (§5.1, §7, §10), `build/01-kien-truc-project.md` §4.2, `P5-tool-registry-mock.md` §6.1, `P6-auth-bao-mat.md`, `P7-db-thay-doi.md` (§2.12, §2.13), `P9-monitor-M9.md` §6–7, `B02-sang-loc-injection.md`, `claude/rag-hien-trang-va-viec-sau-phase2.md`.
