# Phase 4 — Thiết kế chi tiết (HITL: B15–B16, nhắc, xem phiếu, ghi đè, audit)

*Thuộc bộ `build/`. Phiên bản **1.7 — 03/10/2026, cổng 4 ĐẠT** (**4a xong**: S0 `5ed423d` mục 4.0.1; DỪNG 2 `f64fd86` mục 4.10 · **4b xong**: DỪNG 1 `cd3f094` mục 5.6; DỪNG 2 `3b9d745` mục 5.7 · **4c xong**: DỪNG 1 `aac90b1` mục 6.4; DỪNG 2 `b457e6e` mục 6.5 · **4d xong**: DỪNG 1 `e510a6e` mục 7.7; DỪNG 2 `858573d` mục 7.8 · **nghiệm thu** mục 7.9) — **đã chốt đủ 21 câu Q-4-A…U** (Q-4-U = phương án A+). 0.4: soát lại với code; 0.5: phối hợp M9 (mục 0.2); 0.6: Q-4-U phân tích sâu (mục 3.3). Q-4-U (B9 cho yêu cầu hành động) làm ở **S0 = DỪNG 1 của 4a**. Đủ 4 chặng 4a–4d; 4a làm ngay sau khi 3h DỪNG 3b commit. Nguồn: `huong-dan-xay-dung-he-thong-2.md` §5 Phase 4, `B15-B16` v1.4, `B20` §8, `P6`, `P7`, `phase3-thiet-ke-chi-tiet.md` v1.9, `claude/phase4-phan-tich-va-chia-chang.md` v0.2 (mã G4-1…14). Code đã đọc trên máy tại `02ed795` (nhánh `dev-tuananh`).*

*Nhãn: **[Chốt]** spec đã chốt · **[Đề xuất]** chờ Tuấn Anh chốt · **[Suy luận]** rút từ code/spec, agent phải kiểm lại trên code.*

**Kế hoạch tóm tắt (đọc trước):**

| Thứ tự | Chặng | Nội dung | Tầng | DỪNG | Mở khi |
|---|---|---|---|---|---|
| 1 | **4a / S0** | B9 chỉ cho câu trả lời; căn cứ hành động = `procedure_doc` kiểm tất định ở B11; cờ ablation (mục 3.3, 4.0) | B | 1 | ngay |
| 2 | **4a / nợ** | CI Node 24 + `ubuntu-24.04` (hạn 19/10); `make verify`; HMAC username ma; `commit_sha`; mypy tests; đo checkpoint (mục 4.1–4.9) | C | 1 | S0 commit + CI xanh |
| 3 | **4b** | B15 thật theo [Chốt]; R17–R19 đòi chủ máy; đồng bộ `users`; chuỗi quản lý; seed `l1_lead`; B17 kiểm người duyệt; `effects.peek` (mục 5) | A | 2 | 4a xong |
| 4 | **4c** | B16 báo từ chối + điểm log 6; nhắc 50/80%; dự phòng; API xem phiếu + hộp thư (mục 6) | B | 1–2 | 4b xong |
| 5 | **4d** | Ghi đè; `audit_check`; e2e i1–i17; `make gate4` + biên bản thành viên (mục 7) | A | 2 | 4c xong |

Mỗi chặng = **một phiên agent mới** (`/exit` → `claude` → `/model opus`). Chạy song song với M9 theo mục 0.2.

---

## 0. Cách dùng file này

- Đây là **bản thiết kế hiện thực duy nhất của Phase 4**. Khi lệch với `B15-B16`, `B20`, `P6`, `P7` hoặc bản phân tích v0.2 → **file này thắng**, trừ bất biến toàn cục (13 điều) và mục **[Chốt]** gốc.
- Code đã xanh ở Phase 1–3 mà khác chữ ở đây → agent **báo**, không tự sửa code cũ.
- Agent đọc: mục 0.1, 1, 2 rồi **đúng mục của chặng**.

### 0.1. Sự thật của code (`02ed795`) mà Phase 4 phải theo

| Chủ đề | Code hiện có | Hệ quả cho Phase 4 |
|---|---|---|
| B15 | Node giả `graph/nodes/b15_prepare_approval.py`: `deps.approver_id` (`FAKE_APPROVER_ID`), `effects.once("approval_create")`, `effects.once("notify_approver")`, `goto(... audit_detail={approver_id, deadline})` | 4b thay thân node (giữ `make(deps)`); bản giả chuyển `graph/nodes/fake/` cho gate2 |
| B16 | `approval_wait.py`: `interrupt` → `approvals.close(...)` → 3 nhánh; **không** báo người dùng khi từ chối; điểm log 6 thiếu trường | 4c |
| `SqlApprovals` | `create(ticket, approver, deadline, hash)` — **chưa** nhận `backup_approver_id`, `conflict_detected`, `conflict_type`; `close` (điều kiện `pending`), `get`, `get_status`, `lock_row`; `ApprovalRow` chưa có `backup_approver_id`, `reminder_*`, `created_at` | 4b mở rộng `create`/`ApprovalRow` |
| FK người duyệt | `approvals.approver_id`, `backup_approver_id`, `audit_logs.approver_id` là **FK `users`**; `users` chỉ có dòng khi người đó đã đăng nhập (hoặc được `_ensure_manager` kéo theo) | Người duyệt chưa đăng nhập → INSERT lỗi FK → **E9** (G4-17). `gate3` hiện phải cho `l1_01` đăng nhập trước |
| Route duyệt | `api/approvals.py`: `may_decide_as` = có `approval:decide` **và** `a.approver_id == p.user_id` **và** không xung đột; `_action_targets` lấy `action.target` (VPN là chuỗi `device:…`) + `requested_for` | Người dự phòng **không** duyệt được (G4-18); hàm xung đột ở route và ở B15 phải là **một** hàm |
| Xung đột | `auth/authz.py::approval_conflict(approver_id, ApprovalParties)` → `self` / `boss_of_approver` (chỉ sếp **trực tiếp**, từ `users.manager_id`) / `targets_approver` | B15 dùng lại hàm này (mở rộng, không viết hàm thứ hai) |
| Quyền | `PERMS`: l1, manager có `approval:decide`, `decision:override`; l2 **không** có `approval:decide`. `can_override(p, t)` = có `decision:override` **và** không phải người gửi | Ghi đè dùng `decision:override` + `can_override` (v0.2 G4-9 ghi `override:create` — **sai**, bỏ) |
| Token | `validate_access` đọc `users.employment_status` (DB app, đồng bộ AD khi login/refresh), cache ≤ 30 s | Người duyệt bị khoá trong AD mà token còn hạn vẫn duyệt được tới khi refresh (G4-19) |
| `audit_logs` | Đã có cột điểm 5 (`approver_id, deadline, conflict_detected, action_plan_hash`), điểm 6 (`approval_result, note, response_time_seconds`), ghi đè (`original_decision, override_decision, overrider_id`), `idempotency_key` + `ux_audit_idem` | Không migration cho audit; ghi đè = 1 dòng `step="OVERRIDE"` |
| B17 | Kiểm "đã duyệt" = state **và** `approvals.status='approved'`; hash; `ad_get_user(B17_RECHECK)` cho **người gửi + người hưởng lợi** — **không** kiểm người duyệt | 4b thêm người duyệt (G4-19) |
| Luật VPN | R17/R18/R19 (`approval_required`) **không** đòi `device_owner_is_requester`; R20 (`allow`) có đòi | Máy người khác/máy không tồn tại ngoài giờ → HITL (G4-16). h14 hiện kỳ vọng `R17 → HITL` cho `LAP-9999` (máy không tồn tại) |
| Seed AD | `l1_01`, `l1_02`, `l2_01` có `manager_id = it_mgr01`; `it_mgr01` không có sếp; chỉ `l1_01` có máy (`PC-0123`); `it_mgr01` không có máy | Ca "người gửi là sếp người duyệt → Trưởng BP duyệt" **không dựng được** (sếp trực tiếp của L1 chính là Trưởng BP) (G4-22) |
| Worker | `graph/worker_jobs.py::scan_deadlines` 15 s (clarify/confirm/approval) → `deliver_event(timeout)` | 4c thêm `scan_approval_reminders` |
| gate2 / gate3 | `make gate2` cần `FAKE_SCENARIO` **đặt** trong `.env`; `gate3.py` (3b, chưa commit) **dừng** nếu `FAKE_SCENARIO` đặt | Không chạy cả hai trên một `.env` → `make verify` phải tự đổi (mục 4.4) |
| CI | `ubuntu-latest`; `actions/checkout@v4`, `actions/cache@v4`, `astral-sh/setup-uv@v6` (Node 20) | Việc treo 1, **hạn 19/10** |
| Lineage | `b12_assess.py`: `commit_sha: None`; cột `lineage.commit_sha String(40)` | Việc treo 13 |
| Username ma | `auth/service.py::_event` ghi `username_attempted=username` nguyên văn; `auth_failures` là **view** trên `security_events` (đếm khoá theo `username_attempted`) | Q-3e-14: băm một chỗ → đếm khoá tự dùng cùng giá trị |

### 0.2. Chạy song song với M9 (Lưu Dương luồng A, Tạ Duy Anh luồng B) [Chốt phối hợp]

Nguồn: `claude/ke-hoach-m9-chia-viec.md` mục 2 (chủ file). Phase 4 **không** sửa khối/file của M9, và thiết kế để **tránh** đụng:

| Chỗ đụng | Chủ M9 | Phase 4 làm thế nào |
|---|---|---|
| `backend/app/worker.py` (đăng ký job) | Duy Anh (B1) | Phase 4 **không** sửa `worker.py`: nhắc duyệt (4c) chạy **bên trong** `WorkerJobs.scan_deadlines` ở `graph/worker_jobs.py` (cùng chu kỳ 15 s), không đăng ký job mới |
| Migration `*_monitor_*` | Dương (chủ migration duy nhất của M9) | Phase 4 **không có migration** (bỏ `0008_approvals_inbox_idx` của bản 0.4 — chỉ mục hộp thư để sau, dữ liệu nhỏ). Sau mỗi lần rebase lên nhánh có merge M9: `uv run alembic heads` phải = 1 |
| `backend/app/main.py` (khối `# M9`) | Dương | Phase 4 **không** sửa `main.py`: route xem phiếu thêm vào `api/approvals.py`, route ghi đè thêm vào `api/tickets.py` (router đã được include) |
| `.importlinter` | Dương | Phase 4 không thêm hợp đồng; nếu buộc phải thêm module mới vào danh sách nguồn của hợp đồng có sẵn → sửa **đúng dòng** đó, ghi PLAN |
| `settings.py`, `docker-compose.yml`, `.env.example` (khối `# M9`) | Dương | Phase 4 thêm trường/biến ở **khối riêng** có chú thích `# Phase 4` (4a: `app_git_sha`, validator `FAKE_*`; 4b: `APPROVAL_SLA_MINUTES_DEV`), không sửa khối `# M9` |

**Luật cho mọi PLAN-4x:** Bước 0 `git fetch` + xem `origin/dev-tuananh` có merge M9 mới không; có → rebase trước khi code, chạy `alembic heads` = 1, `make test` mốc. Không sửa file/khối M9; xung đột khi rebase ở khối M9 → giữ bản M9, DỪNG báo.

**M9 phụ thuộc Phase 4 (báo Dương/Duy Anh khi merge):** luật 7 `reflex_approval` cần `approvals.first_viewed_at` + `decided_at` — có từ **4c** (route xem phiếu); `override_count` có từ **4d** (`audit_logs step="OVERRIDE"`); S0 (4a) giữ nguyên step/event E3 (`B9`/`no_evidence`), thêm `detail.grounding.kb_gap` ở B10 (M9 có thể thêm chỉ số "yêu cầu hành động thiếu KB").

---

## 1. Phạm vi và cổng 4

### 1.1. Trong phạm vi

B15 thật (chọn người duyệt, xung đột lợi ích, người duyệt không hợp lệ), B16 đủ (tin từ chối, điểm log 6), nhắc 50/80%, API xem phiếu + hộp thư người duyệt, ghi đè (TC23), `scripts/audit_check.py`, e2e cổng 4, `make gate4`, và nợ kỹ thuật dồn về Phase 4 (4a).

### 1.2. Ngoài phạm vi

| Việc | Để khi nào |
|---|---|
| Luồng đăng ký máy (3-Q38) | Phase 5 (Q-4-D) |
| Bảng `notifications`, kênh ngoài | Phase 7 (Q-4-E) |
| Màn L1 (ép xem ≥ `MIN_REVIEW_SECONDS`) | Phase 7 |
| Ca `targets_approver` e2e (vd reset tài khoản của người duyệt) | Phase 5 — Phase 4 test ở mức node B15 (Q-4-Q) |

### 1.3. Cổng 4 — sửa chữ so với hướng dẫn §5 [Đề xuất]

- TC27: "409, phiếu đánh dấu bỏ qua vì muộn" → **"409 + audit `late_event`; phiếu giữ `pending`, worker bắn timeout → E6"** (chốt 2b-3 Q2 — đổi `status` làm ticket kẹt, FN).
- "Luật deny không bao giờ tạo phiếu": VPN **không có** luật `deny` → test bằng policy fixture tiêm vào test (luật `deny` giả), **không** thêm `deny` vào `config/policy.json` (G4-20).
- TC19 + 2 ca xung đột: "Trưởng BP duyệt" với ca `self` và `boss_of_approver` (e2e); ca `targets_approver` ở test node B15 (1.2).
- "Duyệt → thực thi" chạy trên biến thể VPN R19 (`nv003`) — R17 luôn E7 vì mock 409 máy chưa đăng ký (G4-2).

---

## 2. Quyết định Phase 4 (mã `Q-4-…`) — [Chốt 30/09/2026, Tuấn Anh: A…T đồng ý hết; U = A+]

| Mã | Vấn đề | Chốt |
|---|---|---|
| Q-4-A | Mở Phase 4 khi nào | Ngay sau commit 3b; gate3 thành viên + smoke song song, xong trước khi đóng cổng 4 |
| Q-4-B | Không có người duyệt hợp lệ | E5 `no_valid_approver`, 0 phiếu (thêm `reason_detail`, không thêm mã thoát) |
| Q-4-C | TC07/TC08 | Biến thể VPN R19 (`nv003`) |
| Q-4-D | Đăng ký máy | Không làm ở Phase 4; TC09 duyệt → E7 có handoff |
| Q-4-E | Bảng `notifications` | Không thêm; hộp thư = `GET /api/approvals?mine=1` |
| Q-4-F | Cổng 4 thủ công khi chưa có UI | `make gate4` qua API + biên bản, người không làm chính chạy |
| Q-4-G *(sửa v0.2)* | G4-3 máy của người duyệt | **Không** thêm fact `device_owner_id`. Vá bằng Q-4-M (luật đòi chủ máy) + kiểm phòng thủ ở B15 |
| Q-4-H | Lịch trực | `config/approvers.yaml` tĩnh theo intent |
| Q-4-I | `make verify` | Làm ở 4a, dùng từ 4b |
| Q-4-J | Phân tầng nghi thức A/B/C | Áp từ Phase 4 |
| Q-4-K | Dữ liệu | Tuấn Anh hỏi nhóm hôm nay |
| **Q-4-L** | Thứ tự chọn người duyệt (G4-15) | Theo [Chốt]: **xung đột → Trưởng BP**; người chính không hợp lệ → dự phòng; Trưởng BP cũng xung đột/không hợp lệ → E5 |
| **Q-4-M** | R17–R19 không đòi chủ máy (G4-16) | Thêm `action.facts.device_owner_is_requester is_true` vào R17, R18, R19 → máy người khác / không tồn tại luôn E5. h14 đổi kỳ vọng R17/HITL → E5 |
| **Q-4-N** | FK `users` của người duyệt (G4-17) | B15 upsert người duyệt từ AD bằng hàm đồng bộ dùng chung với auth (không tạo phiên) |
| **Q-4-O** | Người dự phòng (G4-18) | Được quyết **sau khi đã nhắc lần 2** (`reminder_2_at IS NOT NULL`), cùng kiểm xung đột; audit `decided_as=backup` |
| **Q-4-P** | Người duyệt bị khoá sau khi duyệt (G4-19) | B17 kiểm lại `decided_by` qua AD (`B17_RECHECK`): phải active + còn nhóm duyệt → sai: E5 `approver_no_longer_valid` |
| **Q-4-Q** | Seed không dựng được ca "sếp của người duyệt" (G4-22) | Thêm `l1_lead` (Trưởng nhóm Helpdesk, nhóm IT-L1, sếp của `l1_01`, báo cáo `it_mgr01`) + 3 máy **chưa đăng ký**: `PC-0124` (`l1_01`), `LAP-0700` (`l1_lead`), `LAP-0900` (`it_mgr01`); `targets_approver` test ở node B15 |
| **Q-4-R** | "Sếp" chỉ tính trực tiếp (G4-23) | `boss_of_approver` = người gửi nằm trong **chuỗi quản lý** của ứng viên (≤ 5 cấp, từ AD) — chặt hơn [Chốt] (giảm FN) |
| **Q-4-S** | Khoá HMAC username ma (Q-3e-14) | Dẫn xuất từ `JWT_SIGNING_KEY` (`HMAC(jwt_key, "auth-username-v1")`) — **không** thêm biến `.env` mới (thành viên đang chạy gate3 không vỡ stack) |
| **Q-4-T** | gate2/gate3 xung đột `FAKE_SCENARIO` (G4-24) | `make verify` tạo lại backend+worker bằng biến shell cho từng cổng rồi trả về cấu hình `.env`; kết quả ghi `.verify/summary.txt` để agent tự đọc |
| **Q-4-U** | B9 chặn yêu cầu hành động (Việc treo 17, Q-3h-11: tc09 0,047) (G4-25) | **A+**: độ giống (B9) chỉ cho câu trả lời; căn cứ hành động = `procedure_doc` khai cho `action_type`, kiểm tất định có trong KB ở B11 (thiếu → E3 `no_procedure`); cờ `GROUNDING_GATE_ACTIONS` cho ablation. Mục 3.3. Ghi D-34 |

---

## 3. Lỗ hổng bổ sung (v0.3 của bản phân tích — soát code 30/09)

| Mã | Mức | Lỗ hổng | Vá [Đề xuất] |
|---|---|---|---|
| **G4-15** | **Chặn** (lệch [Chốt]) | Mã giả v0.2 chọn `[primary, backup, head]` → `l1_01` tự gửi thì `l1_02` duyệt. [Chốt] B15 + cổng 4: có xung đột → **Trưởng BP IT** | Mục 3.1. Bảng test v0.2 §4 dòng 2, 4 **sai** — thay bằng 3.2 |
| **G4-16** | **Chặn** (FN) | R17/R18/R19 không đòi chủ máy. `nv001` xin gia hạn máy `LAP-0417` (của `nv002`) lúc 20:00 → R18 → phiếu duyệt; ban ngày cùng ca → E5 (h11). `LAP-9999` (không tồn tại) → R17 → phiếu (h14 hiện chấp nhận). Người duyệt đồng ý thì chỉ nhờ mock trả 404 mới không ghi — hệ thống thật chưa chắc kiểm chủ máy | Q-4-M. Mọi ca máy không phải của người gửi → không luật nào → E5 (nhất quán ngày/đêm). B15 thêm chốt phòng thủ: hành động có đích máy mà `facts.device_owner_is_requester is not True` → E5 `approval_target_unverified`, 0 phiếu |
| **G4-17** | **Chặn** (E9 khi vận hành) | Người duyệt/dự phòng chưa đăng nhập lần nào → không có dòng `users` → INSERT `approvals` lỗi FK → E9 | Q-4-N: B15 tra AD (`ad_get_user`, bước mới `B15_APPROVER`) → upsert `users` bằng hàm dùng chung với `AuthService` (tách `_upsert` + `role_from_groups` + `_ensure_manager` thành hàm công khai), không tạo phiên, không đổi token nếu role không đổi |
| **G4-18** | Nên | Nhắc 80% "báo người dự phòng" nhưng route chỉ cho `approver_id` quyết → dự phòng nhận thông báo mà không làm gì được | Q-4-O |
| **G4-19** | Nên (FN nhỏ) | Người duyệt bị khoá trong AD, token còn hạn → vẫn duyệt; B17 không kiểm lại người duyệt | Q-4-P (1 lời gọi AD song song với 2 lời gọi đã có) |
| **G4-20** | Nên | Cổng 4 "deny không tạo phiếu" nhưng VPN không có `deny` | Policy fixture trong test (1.3) |
| **G4-21** | Nên (tài liệu) | Hướng dẫn §5: TC27 "phiếu đánh dấu bỏ qua vì muộn" trái chốt 2b-3 Q2 | Sửa chữ cổng 4 (1.3) |
| **G4-22** | **Chặn** (cổng 4 không đạt được) | Seed: sếp trực tiếp của mọi L1 là `it_mgr01` = Trưởng BP → ca "người gửi là sếp người duyệt → Trưởng BP duyệt" luôn thành tự duyệt → E5; `it_mgr01` không có máy nên không gửi được yêu cầu VPN | Q-4-Q (thêm seed mock, không đổi code) |
| **G4-23** | Nên (FN) | `boss_of_approver` chỉ xét sếp trực tiếp. Sau Q-4-Q, `it_mgr01` gửi yêu cầu → `l1_01` (sếp trực tiếp là `l1_lead`) không xung đột → nhân viên duyệt cho sếp của sếp mình | Q-4-R. `it_mgr01` gửi → `l1_01` xung đột (chuỗi) → Trưởng BP = chính mình → **E5 `no_valid_approver`** |
| **G4-24** | Nên (quy trình) | `make gate2` cần `FAKE_SCENARIO` đặt, `gate3` cần không đặt; agent không được sửa `.env` | Q-4-T, mục 4.4 |
| **G4-25** | **Chặn** (cổng 4 + demo) | B9 trước B10 → yêu cầu hành động điểm rerank thấp ra E3, không tới M5 (tc09 0,047) | Q-4-U, mục 3.3, làm ở S0 |

### 3.1. Thuật toán chọn người duyệt (thay mục 3.1 v0.2)

```python
async def choose_approver(roster, rc, action, facts) -> Choice | Refuse:
    if action_has_device_target(action) and facts.get("device_owner_is_requester") is not True:
        return Refuse("E5", "approval_target_unverified")                 # G4-16 phòng thủ
    l1 = [await lookup(u) for u in (roster.primary, roster.backup)]       # ad_get_user(B15_APPROVER); lỗi AD → Refuse("E2","approver_lookup_error")
    valid_l1 = [c for c in l1 if valid(c, role="l1")]                     # active + nhóm IT-L1 (G4-6)
    first = valid_l1[0] if valid_l1 else None
    conflict = conflict_type(rc, first, action) if first else None        # self | boss_of_approver (chuỗi, Q-4-R) | targets_approver
    if first is None or conflict:                                         # [Chốt] xung đột → Trưởng BP; hết L1 hợp lệ → Trưởng BP
        head = await lookup(roster.head)
        if not valid(head, role="manager") or conflict_type(rc, head, action):
            return Refuse("E5", "no_valid_approver")                      # Q-4-B, 0 phiếu
        return Choice(approver=head, backup=None, conflict_detected=bool(conflict),
                      conflict_type=conflict, reason="conflict" if conflict else "no_valid_l1")
    backup = next((c for c in valid_l1[1:] if not conflict_type(rc, c, action)), None)
    if backup is None:
        head = await lookup(roster.head)
        backup = head if valid(head, role="manager") and not conflict_type(rc, head, action) else None
    return Choice(approver=first, backup=backup, conflict_detected=False, conflict_type=None)
```

`conflict_type` là **một** hàm dùng chung cho B15 và route duyệt (mở rộng `auth/authz.approval_conflict`), nhận chuỗi quản lý của ứng viên từ AD (B15) hoặc từ `users` (route).

### 3.2. Bảng test xung đột (thay bảng v0.2 §4; test-writer viết từ bảng này ở 4b)

Seed sau Q-4-Q dùng **máy chưa đăng ký** cho ca xung đột → khớp R17 ở **mọi giờ** (không phụ thuộc đồng hồ, `make gate4` chạy được ban ngày).

| # | Người gửi | Hành động | Tình huống | Mong đợi |
|---|---|---|---|---|
| x1 | nv003 | renew LAP-0501 (của mình) | R19 | approver `l1_01`, backup `l1_02`, `conflict_detected=false`, `choice_reason=normal` |
| x2 | l1_01 | renew PC-0124 (của mình, chưa đăng ký) | R17; `l1_01` → self | approver **`it_mgr01`**, backup None, `conflict_type=self` (TC19) |
| x3 | l1_lead | renew LAP-0700 (của mình, chưa đăng ký) | R17; `l1_01` → boss (trực tiếp) | approver **`it_mgr01`**, `conflict_type=boss_of_approver` |
| x4 | it_mgr01 | renew LAP-0900 (của mình, chưa đăng ký) | R17; `l1_01` → boss (chuỗi); head → self | **E5 `no_valid_approver`**, 0 phiếu |
| x5 | nv001 | renew LAP-0417 (của nv002), 20:00 | không luật nào (Q-4-M) | E5 `llm_layer_disabled`, 0 phiếu |
| x6 | nv001 | renew LAP-9999 (không tồn tại) | không luật nào (Q-4-M; h14 mới) | E5 `llm_layer_disabled`, 0 phiếu |
| x7 | nv003 | renew LAP-0501 | `l1_01` disabled (`/_admin/users/l1_01/status`) | approver `l1_02`, backup `it_mgr01` |
| x8 | nv003 | renew LAP-0501 | `l1_01`, `l1_02` disabled | approver `it_mgr01`, backup None, `choice_reason=no_valid_l1`, `conflict_detected=false` |
| x9 | nv003 | renew LAP-0501 | AD lỗi 500 khi tra người duyệt — bơm lỗi bằng hook **ngay trước B15** (`deps.scenario.hook(state, "before_approver_lookup")` trong test), không bơm từ đầu (B1 cũng tra AD) | E2 `approver_lookup_error`, 0 phiếu |
| x10 | nv003 | renew LAP-0501 | roster test đặt `primary: l2_01` | B15 loại `l2_01` (`wrong_group`) → approver `l1_02` (L2 không bao giờ duyệt) |
| x11 | (node) | `requested_for=l1_01` dựng tay | `targets_approver` | approver `it_mgr01`, `conflict_type=targets_approver` |
| x12 | (node) | đích máy, `device_owner_is_requester` thiếu/false | phòng thủ | E5 `approval_target_unverified`, 0 lời gọi AD, 0 phiếu |
| x13 | — | luật `deny` (policy fixture) | — | không vào B15, 0 phiếu |
| x14 | nv003 | như x1, B15 chạy lại sau khi đã tạo phiếu (giết process) | TC33 | đúng 1 phiếu, 1 `notify_approver`, approver giữ như phiếu cũ |
| x14b | nv003 | như x14 nhưng AD lỗi lúc chạy lại | P9 `peek` | vẫn `S_PENDING_APPROVAL` với phiếu cũ, **không** E2, 0 lời gọi AD ở lần chạy lại |

### 3.3. B9 cho yêu cầu hành động — Q-4-U (G4-25, Việc treo 17) [Chốt A+ 30/09/2026]

#### 3.3.1. Bằng chứng đo được (phase3 11.10 #17, reranker thật `bge-reranker-v2-m3`, ngưỡng 0,6)

| Câu | Loại câu | Tài liệu đúng | Hạng | Điểm |
|---|---|---|---|---|
| tc05 "VPN báo lỗi 809, hướng dẫn mình khắc phục với" | hỏi cách làm | KB-VPN-003 | 1 | 0,981 |
| tc06 "vpn không vào được" (bỏ thẻ) | mô tả triệu chứng | — | — | 0,677 |
| tc09 "cấp lại VPN cho máy PC-0977" | **ra lệnh** | KB-VPN-005 | **1** | **0,047** |
| tc09 + thêm mục viết đúng cách nói vào KB-VPN-005 | ra lệnh | KB-VPN-005 (mục mới) | **1** | **0,261** |

**Đọc số [Suy luận]:** reranker **xếp hạng đúng** (tài liệu đúng luôn đứng đầu) nhưng **thang điểm lệch theo loại câu**: reranker được huấn luyện trên cặp *câu hỏi → đoạn trả lời*; câu mệnh lệnh không "được trả lời" bởi đoạn quy trình nên điểm tuyệt đối thấp. Một ngưỡng duy nhất không phục vụ được cả hai loại câu. Sửa dữ liệu (0,047 → 0,261) không đủ; hạ ngưỡng xuống ~0,05 thì gần như mọi câu hỏi âm tính (không có đáp án trong KB) đều qua → trả lời bừa (vi phạm D-22: ≤ 5%). Đây là lỗi **đo sai đại lượng**, không phải lỗi ngưỡng.

#### 3.3.2. [Chốt] gốc muốn gì — và đã có gì bảo đảm điều đó

B08 §1 [Chốt]: *"Lấy đúng đoạn tài liệu nội bộ làm căn cứ cho mọi câu trả lời **và mọi hành động**."* Hai ý khác nhau:

| Ý | Rủi ro nó chặn | Cơ chế hợp lý |
|---|---|---|
| Căn cứ cho **câu trả lời** | LLM bịa chính sách → người dùng làm sai quy trình bảo mật | Độ liên quan câu hỏi–đoạn (B9) + trích dẫn do code kiểm + prompt — **đúng đại lượng**, giữ nguyên |
| Căn cứ cho **hành động** | Agent làm một việc công ty không có quy trình | Hỏi "hành động này có **quy trình** trong KB không" — câu hỏi **tất định về danh mục**, không phải độ giống văn bản giữa câu người dùng và đoạn KB |

Những lớp **đã có** trên code chặn "làm việc không có quy trình": `action_types` là danh sách đóng (`slots.yaml`, `sanitize_slots` loại giá trị lạ); mỗi `action_type` phải có `ActionMeta` (thiếu → không khởi động) và `PLAN` (thiếu → không khởi động, h23); luật M5 quyết; B17 kiểm lại luật/hash/người. Tức phần "có được làm không" đã **tất định**. Thiếu đúng một mắt xích: nối mỗi `action_type` với **tài liệu quy trình** trong KB.

#### 3.3.3. Phân tích theo kiểu thất bại (ưu tiên FN)

| Nếu nhánh hành động bỏ cổng độ giống | Lớp nào chặn | Tăng FN? |
|---|---|---|
| Làm hành động không có trong danh mục | `action_types` đóng + `PLAN` + `ActionMeta` | Không |
| Làm hành động có danh mục nhưng KB không còn quy trình (tài liệu bị tắt/xoá) | **Mới — A+ (P10):** kiểm `procedure_doc` có trong KB đang ghim → không → E3 `no_procedure` | Không |
| Làm sai đối tượng (máy người khác, máy ma) | `facts` từ tool + R17–R20 đòi chủ máy (Q-4-M) + chốt B15 | Không |
| Câu người dùng chứa injection đòi hành động | B2; M5 không đọc câu; slot qua `sanitize_slots` | Không |
| Phase 6: lớp LLM cho AUTO khi KB không có căn cứ | S0-P9 (chunk dưới ngưỡng không vào B14) + ràng buộc D-34 (không luật + `kb_gap` → tối đa HITL) | Không |
| Câu hỏi bị phân loại nhầm thành `action` | Đi B11: hỏi slot; không slot hợp lệ → E4; không sinh câu trả lời nào | Không (chỉ tốn lượt) |

Ngược lại, **giữ** cổng độ giống cho hành động gây hại đo được: TC09/HITL không bao giờ tới M5 trên stack thật → cổng 4 và demo Obj 2 không chạy; E3 "thiếu KB" giả làm nhiễu tín hiệu bổ sung KB cho Trưởng BP; tăng tỉ lệ chuyển người vô ích (đi ngược luận điểm HAS-Bench > 40%).

#### 3.3.4. Các phương án

| | Cách | Kết luận |
|---|---|---|
| **A+ (CHỐT)** | (1) Cổng độ giống B9 chỉ cho `need_type=info` (như A). (2) **Căn cứ quy trình tất định** cho hành động: mỗi `action_type` khai `procedure_doc` (doc_id KB); B11 sau khi dựng `Action` kiểm tài liệu đó **có, bật, người gửi được xem** trong collection đã ghim ở B8 → không → E3 `no_procedure`; RAG lỗi → E2. Tin kết quả/phiếu duyệt ghi nguồn quy trình. (3) Cờ `GROUNDING_GATE_ACTIONS` (mặc định `false`; `true` = hành vi cũ) cho ablation ở Phase 10 | Giữ **cả hai** ý của [Chốt]; thay đại lượng sai bằng kiểm tất định; đo được bằng cờ |
| A | Chỉ (1) | Làm mất ý "mọi hành động có căn cứ KB" của [Chốt] |
| B | Ngưỡng riêng cho hành động | Vẫn là độ giống (đại lượng sai); cần dữ liệu chọn ngưỡng thứ hai → loại |
| C | Dùng slot `action` B3/B6 thay `need_type` | Trộn tín hiệu; B6 tự suy action cả khi người dùng chỉ hỏi (TC06) → loại |
| D | Hạ ngưỡng / viết lại KB | Đã thử (0,261); hạ ngưỡng tăng trả lời bừa → loại |
| E | LLM viết lại câu lệnh thành câu hỏi rồi truy hồi | Tốn 1 lời gọi, mở thêm bề mặt injection vào truy hồi, "căn cứ" dựa trên câu do LLM sinh — vòng tròn → loại |

#### 3.3.5. Ghi vào tài liệu gốc (khi S0 đóng)

`decisions.md` **D-34**: *"Căn cứ của câu trả lời = độ liên quan truy hồi (B9, ngưỡng); căn cứ của hành động = quy trình được khai báo cho `action_type` và có mặt trong KB đang chạy (kiểm tất định ở B11). Hành động được quản bởi chính sách (M5) và con người (M6), không bởi độ giống văn bản."* Sửa `B08-B09` §1 (thay "hệ quả… phải có KB đạt ngưỡng" + bảng kiểm K2 "action_type ↔ tài liệu" → `procedure_doc` + kiểm ingest), `B10` §5, `B11` (bước kiểm quy trình), NGU-CANH §4.1/§6.1 chú thích. Luận điểm báo cáo: tách *grounding nội dung* khỏi *grounding hành động* — đóng góp thiết kế nhỏ nhưng rõ, có số đo 3.3.1 và ablation bằng cờ.

**Giữ nguyên:** RAG lỗi → E2 cho mọi yêu cầu; không đổi `RETRIEVAL_THRESHOLD`; ngưỡng thật chọn khi có bộ kiểm tra của TV1.

---

## 4. Chặng 4a — S0 (B9 cho yêu cầu hành động) + nợ kỹ thuật + `make verify`

**Hai DỪNG, một phiên agent:**
- **DỪNG 1 = S0** (mục 4.0, tầng **B**: PLAN ngắn trong MẪU A, mutation 1 lượt, security-reviewer). Chặn cổng 4 → làm trước.
- **DỪNG 2 = nợ kỹ thuật + `make verify`** (mục 4.1–4.9, tầng **C**).

### 4.0. S0 — cổng căn cứ B9 chỉ cho nhánh trả lời (Q-4-U)

**Mục tiêu:** yêu cầu hành động tới được M5/HITL dù điểm truy hồi thấp; câu trả lời vẫn bị chặn y như cũ khi không có căn cứ.
**Đầu vào:** `b08_retrieve.py`, `b10_route.py` (code `02ed795` + 3b). **Đầu ra:** 2 node sửa, test S0, preset gate3 cập nhật.

| Mã | Chốt |
|---|---|
| S0-P1 | `b08_retrieve`: **bỏ** nhánh B9. RAG không lỗi (kể cả rỗng, điểm thấp) → luôn `goto(S_RETRIEVING, next_node="b10_route", step="B8", event="retrieved", retrieved=…, retrieval_score=…, kb_version=…)`; điểm log 3 thêm `above_threshold: bool`. Nhánh E2 `rag_system_error` **giữ nguyên** |
| S0-P2 | `b10_route`: `b10_need_type` chạy **trước** mọi kiểm ngưỡng (như hiện nay). `need.type == "info"` → nếu `not chunks or retrieval_score < deps.constants.RETRIEVAL_THRESHOLD` → `goto(S_ESCALATED, next_node="b20_audit", step="B9", event="no_evidence", exit_code=E3, escalation_reason_detail="no_grounding", retrieval_score=…)` — **cùng** step/event/mã/`reason_detail` với nhánh cũ (B20, mẫu tin E3, M9 không đổi); 0 lời gọi `expand_for_answer`/`b10_answer`. Đạt ngưỡng → như cũ |
| S0-P3 | `need.type == "action"` → B11 như cũ, **bất kể** điểm; audit B10 thêm `grounding = {"top_score", "above_threshold", "kb_gap": not above_threshold}` |
| S0-P4 | Lỗi LLM ở `b10_need_type` → E2 như cũ (ca điểm thấp trước ra E3, nay E2 — ghi "spec cần sửa") |
| S0-P5 | Test AST: `b11_slots`, `risk/policy_engine` (lớp luật), `b17_execute`, `executor/` **không** đọc `retrieved`/`retrieval_score` từ state; `b12_assess` chỉ đọc qua `evidence_for_estimator` (S0-P9). Liệt kê ≥ 4 module quét |
| S0-P6 | Preset ScriptedLLM (`config/scripted/*.yaml`, fixture `vpn_scripts`): mọi ca E3 nay cần phản hồi `b10_need_type` (`info`). `ScriptExhausted` ở test cũ = thiếu preset, **không** phải lỗi logic — thêm preset, không đổi kỳ vọng E3 |
| S0-P7 | `gate3.py` tc09: kỳ vọng trở lại 11.6 h6 — `S_PENDING_APPROVAL` (R17, thêm R18 nếu ngoài giờ), 0 lời gọi ghi; tc16 vẫn E3 + mẫu "Mình chưa có thông tin về việc này" |
| S0-P9 | B12 → B14: hàm thuần `evidence_for_estimator(chunks, score, threshold)` trả `chunks` khi `score >= threshold`, không thì `[]`; `b12_assess` gọi estimator qua hàm này (không truyền thẳng `state["retrieved"]`). Ràng buộc ghi cho Phase 6 (D-34): không luật nào khớp + `kb_gap` → route tối đa HITL, không AUTO |
| S0-P10 | Căn cứ quy trình: `ActionMeta` thêm `procedure_doc: str` (regex `doc_id` KB, **bắt buộc**); `config/action_metadata.yaml`: `renew_vpn_cert`, `reissue_vpn_access` → `KB-VPN-004` ("Gia hạn và cấp lại chứng chỉ VPN"), `check_vpn_status` → `KB-VPN-001`. **Không** chép vào `Action` (không đổi `action_plan_hash`). `RagPort.procedure_available(doc_id, ctx, *, kb_version) -> bool` = scroll `limit=1` trên `kb_<kb_version>` với `base_filter(ctx)` + `doc_id` (Filter chỉ dựng trong `rag/filters.py`). B11: sau `build_action`, trước `goto(S_ASSESSING)`: `False` → E3 `no_procedure` (step `B11`, `REASON_DETAILS` thêm); `RetrievalSystemError` → E2 `rag_system_error`. Audit B11 `procedure_doc`. `make ingest` in **cảnh báo** (không chặn) khi `procedure_doc` nào không có/bị tắt/`restricted` trong KB mới |
| S0-P11 | Cờ `GROUNDING_GATE_ACTIONS: bool = False` (Settings, qua `NodeDeps`): `True` → nhánh action cũng áp ngưỡng B9 như cũ (ablation Phase 10, đối chiếu hành vi 3h). Test cả hai giá trị |
| S0-P8 | Không đổi `RETRIEVAL_THRESHOLD`, không đổi thứ tự/logic B8 (D-23, retry), không thêm key `TicketState` (dùng `retrieval_score` sẵn có) |

**Test:**

| # | Test | Đạt khi |
|---|---|---|
| s1 | info + `top_score` < ngưỡng | E3 `no_grounding`, audit step `B9`, **1** lời gọi `b10_need_type`, **0** `b10_answer`, 0 `expand` |
| s2 | action + `top_score` < ngưỡng | tới B11 (`S_RETRIEVING → …`), audit `kb_gap=true` |
| s3 | action + 0 chunk | tới B11 |
| s4 | info + 0 chunk | E3, 0 `expand` |
| s5 | info + `top_score` đúng bằng ngưỡng | đi tiếp trả lời |
| s6 | AST S0-P5 | sạch; quét ≥ 4 module |
| s12 | Action hợp lệ, `procedure_doc` có trong KB | tới B12, audit B11 `procedure_doc=KB-VPN-004` |
| s13 | KB đang ghim không có `KB-VPN-004` (fixture tắt tài liệu) | E3 `no_procedure`, 0 lời gọi ghi, 0 phiếu |
| s14 | `procedure_available` lỗi Qdrant | E2 `rag_system_error` |
| s15 | `GROUNDING_GATE_ACTIONS=true`, action điểm thấp | E3 `no_grounding` như 3h |
| s16 | `action_metadata.yaml` thiếu `procedure_doc` | không khởi động |
| s11 | `evidence_for_estimator`: điểm dưới / bằng / trên ngưỡng | `[]` / chunks / chunks; B12 với estimator giả ghi nhận đầu vào → nhận `[]` khi `kb_gap` |
| s7 | e2e h7 (TC16) | vẫn E3 + mẫu tin cũ |
| s8 | e2e TC09 với FakeMl ép điểm rerank 0,05 (hook `FakeMlService`) | `S_PENDING_APPROVAL`, 0 lời gọi ghi |
| s9 | e2e yêu cầu hành động + Qdrant lỗi | E2 `rag_system_error` (giữ fail-closed) |
| s10 | e2e TC04 (câu hỏi có căn cứ) | như g5, không đổi |

**Mutation (1 lượt):** M-S0-1 bỏ kiểm ngưỡng ở nhánh info (s1, s7 đỏ) · M-S0-2 áp ngưỡng cho nhánh action (s2, s8 đỏ) · M-S0-3 `<` → `<=` (s5) · M-S0-4 kiểm ngưỡng **sau** `expand`/`b10_answer` (s1: số lời gọi `b10_answer` ≠ 0) · M-S0-5 B12 truyền thẳng `state["retrieved"]` cho estimator (s6, s11) · M-S0-6 bỏ kiểm `procedure_available` (s13) · M-S0-7 `procedure_available` không dùng `base_filter` (test: tài liệu quy trình `restricted` + người gửi employee → phải E3) · M-S0-8 cờ bị đảo nghĩa (s15).

**security-reviewer (S0):** không đường nào gửi câu trả lời KB mà chưa qua ngưỡng **và** hậu kiểm trích dẫn; KB không là đầu vào lớp luật/B11/B17, và chunk dưới ngưỡng không tới B14; E2 ≠ E3 giữ nguyên; mẫu tin E3 không đổi.

**DỪNG 1:** `! make verify` chưa có (làm ở DỪNG 2) → Tuấn Anh chạy `make test`, rồi `make up` + `make gate3 S=tc09` và `make gate3 S=tc16` như 3h. Đạt khi: test xanh; tc09 → `S_PENDING_APPROVAL`; tc16 → E3.

**Spec cần sửa (S0):** agent in nguyên văn → Claude chat ghi `decisions.md` D-34, `B08-B09` §1, `B10` §5, NGU-CANH chú thích luồng, phase3 Việc treo 17 → đóng.

#### 4.0.1. Chốt khi hiện thực S0 (30/09/2026, commit `5ed423d`)

Khi 4.0 và 3.3 nói khác bảng này, **bảng này thắng**. Kết quả: `make test` backend 3166 · mock 94 · ml 77; mutation M-S0-1…10 10/10 (1 lượt, md5 khớp); security-reviewer 0 FAIL / 5 NGHI (NGHI-1, NGHI-5 sửa kèm test; còn lại → Q-4a-1…3); gate3 tc09 **8/0** (reranker thật 0,0473 → B11 `procedure_doc=KB-VPN-004` → R17 → `S_PENDING_APPROVAL`, 1 phiếu, 0 ghi — trong giờ; nhánh R17+R18 ngoài giờ mới kiểm ở unit), tc16 **5/0**.

| # | Chỗ | Chốt |
|---|---|---|
| 1 | S0-P10 | `procedure_available(doc_id, ctx) -> ProcedureCheck{available, kb_version, retries}` — **alias hiện hành tại B11** (alias → `kb_version` → kiểm `pipeline_sha`, như `retrieve`), **không** dùng `kb_version` ghim ở B8 (S0-A3: B11 có thể chạy sau lượt hỏi lại 24 h; KB vừa rút quy trình → E3). Lỗi alias/pipeline/Qdrant/hạn → `RetrievalSystemError("procedure")` (stage mới). `procedure_filter(role, doc_id)` ở `rag/filters.py`. Audit B11: `procedure_doc`, `procedure_kb_version`. E3 event `no_procedure` kèm `intended_action`/`facts`; E2 event `rag_system_error`, `retrieval_error="procedure"` |
| 2 | S0-P10 | `DOC_ID_PATTERN` một nguồn ở `domain/action.py` (không ở `ticket_state.py` — vòng import); `rag/models.py` import lại |
| 3 | S0-P10 ingest | Cảnh báo ở `rag/ingest/procedures.py`, stderr, ngay sau bước 3: thiếu / `enabled=false` / ngoài `allowed_sensitivity("employee")`; mã thoát không đổi |
| 4 | S0-A1 | `build_handoff(state, templates, *, retrieval_threshold)` (B20 truyền `deps.constants.RETRIEVAL_THRESHOLD`): điểm thiếu hoặc < ngưỡng → "Tài liệu KB gần nhất (điểm dưới ngưỡng, KHÔNG dùng làm căn cứ — có thể KB còn thiếu): …", áp mọi mã thoát. M-S0-9 |
| 5 | Q-4a-1 | `reason_detail == "no_procedure"` → hằng `NO_PROCEDURE_NOTE` ở phần "vì sao escalate": "Quy trình của hành động dự kiến không có trong KB hiện hành — tài liệu đã tra không phải căn cứ, không làm tay theo tài liệu cũ." M-S0-10 |
| 6 | S0-P2 | Nhánh E3 info ghi `need_type="info"`, nhánh cờ ghi `"action"`; cả hai truyền `kb_version` (cột audit như dòng B9 cũ — NGHI-5). Điểm log 3 (`query`, `top_score`, `kb_version`, `above_threshold`) ở dòng **B8 `retrieved`**, luôn có → 7.2 (audit_check) điểm 3 đọc dòng B8 |
| 7 | S0-P2/P9 | Điểm thiếu hoặc **NaN** = dưới ngưỡng ở B10, B8 `above_threshold`, handoff, `evidence_for_estimator` (ở `risk/estimator.py`) — NGHI-1 |
| 8 | S0-P5 | Test AST quét `b11_slots`, `risk/policy_engine`, `risk/context`, `domain/policy`, `b17_execute`, `executor/*`; B12 chỉ đọc `retrieved`/`retrieval_score` bên trong lời gọi `evidence_for_estimator` |
| 9 | Q-4a-2 | **Không** kiểm quy trình ở B17 (giữ S0-P5). Quy trình bị rút sau B11 (chỉ ở nhánh chờ duyệt ≤ 30 phút) → **người duyệt là lớp chặn** → 4c P6: `ApprovalView` hiển thị `procedure_doc` + tiêu đề (D-34) |
| 10 | Q-4a-3 | `evidence_for_estimator` xét theo điểm top (không lọc từng chunk) — xét lại ở Phase 6 |
| 11 | Mutation | M-S0-1 bắt ở s1, s4 (s7/h7 tương đương — preset `cannot_answer` là lớp thứ hai); M-S0-2 bắt ở s2/s3 (unit), s8 (e2e); thêm M-S0-9, M-S0-10 |
| 12 | Test | s7 = h7, s10 = h2 (giữ); c5 chạy B8 → B10 với preset info, vẫn E3; hai test node "E3 ở B8" → "B8 luôn → b10_route" (S0-A2) |
| 13 | gate3 | tc09 cần `FAKE_APPROVER_ID` (B15 giả tới 4b) + `ha.lt` đã đăng nhập; chạy bằng biến shell `FAKE_SCENARIO=` (G4-24, tới khi có `make verify`) |
| 14 | Phase 10 | `GROUNDING_GATE_ACTIONS` chưa có trong compose/`.env.example` — thêm khi làm ablation |

**DỪNG 2 — nợ kỹ thuật + `make verify`. Mục tiêu:** trả hết nợ dồn về "Phase 4 S0" và dựng công cụ để mọi DỪNG sau chỉ cần **một** lệnh chạy của Tuấn Anh.
**Đầu ra:** CI Node 24 + runner ghim; `make verify`; HMAC username ma; `lineage.commit_sha`; `mypy backend/tests` trong `make lint`; số đo `durability="sync"`.
**Nghi thức (tầng C):** mutation tay 2 cái cho HMAC; security-reviewer soát phần HMAC.

### 4.1. P-x chốt trước — DỪNG 2 (agent không hỏi lại)

| Mã | Chốt |
|---|---|
| P1 | CI: `runs-on: ubuntu-24.04`; nâng `actions/checkout`, `actions/cache`, `astral-sh/setup-uv` lên major chạy **Node 24** (ứng viên: checkout@v5, cache@v5, setup-uv@v7 — agent ghi bản chọn + lý do; tiêu chí: run CI không còn annotation Node 20). Không đổi bước nào khác |
| P2 | HMAC (Q-3e-14 + Q-4-S): một hàm `auth/username_hash.py::stored_username(username, *, known: bool, key: bytes) -> str` → `known` giữ nguyên, không → `"h:" + hmac_sha256(key, username).hexdigest()` (66 ký tự). `key = hmac.new(jwt_signing_key, b"auth-username-v1", sha256).digest()`, tính một lần lúc dựng `AuthService`. Áp ở **mọi** chỗ ghi `username_attempted` và ở `count_failures` (view `auth_failures` đọc `security_events` → đếm bằng cùng giá trị băm). **Không** thêm biến `.env`, không đổi schema |
| P3 | `known` = username có dòng trong `users` (tra một lần mỗi lượt đăng nhập, đã có sẵn trong luồng login). Không lộ khác biệt ra ngoài: phản hồi và thời gian của username ma giữ như 3e |
| P4 | `commit_sha`: `Makefile` tính `GIT_SHA := $(shell git rev-parse HEAD)` **chỉ khi** `git status --porcelain --untracked-files=no` rỗng (file tracked có thay đổi chưa commit → rỗng; file untracked như `PLAN-*.md` không tính — không thì máy Tuấn Anh không bao giờ "sạch"); `$(COMPOSE) build --build-arg GIT_SHA=$(GIT_SHA) backend`. `backend/Dockerfile`: `ARG GIT_SHA=""` + `ENV APP_GIT_SHA=$GIT_SHA` đặt **cuối** file (không phá cache lớp cài phụ thuộc). `Settings.app_git_sha: str \| None` — chỉ nhận `^[0-9a-f]{40}$`, khác → `None` + 1 dòng WARNING lúc khởi động (không từ chối khởi động). Mọi chỗ dựng `lineage` lấy từ `Settings` (hiện: `b12_assess.py`, lineage của B10 qua `goto`) |
| P5 | mypy tests: chạy `uv run mypy backend/tests`. **≤ 80 lỗi** → sửa hết, thêm dòng `uv run mypy backend/tests` vào `make lint` (cache riêng nếu cần). **> 80** → DỪNG, báo số lỗi theo mã lỗi + 5 file nhiều nhất (Q). Cấm `ignore_errors = true` cả gói; `# type: ignore[mã]` chỉ khi kèm lý do trên cùng dòng |
| P6 | `durability="sync"` (Việc treo 16): **không** đổi code runtime. Viết `backend/tests/stack/bench_checkpoint.py` đo `aput` của `AsyncPostgresSaver` trên **Postgres testcontainers** (cùng image `postgres:16`, cùng colima — không cần mật khẩu stack, không làm bẩn DB stack; agent không đọc `.env`) với state tổng hợp 5 / 20 / 50 KB × 200 lần → in p50/p95 từng cỡ. Chạy trong `make verify` bước tùy chọn `BENCH=1` (export `DOCKER_HOST`/`TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE` như `make test`). Ghi số vào PROGRESS; p95 > 50 ms → Q |
| P7 | `make verify` theo mục 4.4. `FAKE_SCENARIO=""` phải được `Settings` coi là **không đặt** (validator rỗng → `None`, cả `FAKE_NODE_DELAY`) — thêm test đơn vị. Nếu đã đúng sẵn thì ghi "đã có" |
| P8 | Không đụng: `.env*` (trừ `.env.example` — 4a không cần sửa), `docs/spec/`, logic node, luật. Việc treo khác (4, 9, 11, 12) không làm ở 4a |

### 4.2. File

```
.github/workflows/ci.yml                  # P1
Makefile                                  # verify, verify-status, GIT_SHA (P4, P7); .PHONY
scripts/verify.sh                         # mục 4.4 (bash, set -euo pipefail)
.gitignore                                # .verify/
backend/Dockerfile                        # ARG/ENV GIT_SHA cuối file
backend/app/settings.py                   # app_git_sha; FAKE_* rỗng → None
backend/app/auth/username_hash.py         # P2 (mới)
backend/app/auth/service.py               # _event, count_failures, các chỗ username_attempted
backend/app/graph/nodes/b12_assess.py     # commit_sha từ Settings (qua deps, không đọc env trong node)
backend/tests/stack/bench_checkpoint.py   # P6
backend/tests/unit/…                      # test mục 4.5
```

### 4.3. Tuấn Anh / thành viên cần biết

- Không thêm biến `.env` nào (Q-4-S). Thành viên chỉ cần pull + `make up` lại.
- `lineage.commit_sha` chỉ có giá trị khi build từ cây sạch — chạy gate xác nhận trên cây sạch.

### 4.4. `make verify` (Q-4-I, Q-4-T)

**Gọi:** `make verify` (mặc định `G=3`) · `make verify G=2` · `make verify G=23` · `make verify G=0` (chỉ lint + test) · thêm `BENCH=1` cho P6. `G` là chuỗi chữ số, mỗi chữ số một cổng; 4d thêm chữ số `4` (mục 7.1 P6) — 4a viết vòng lặp theo chữ số để 4d chỉ thêm một nhánh.

**Các bước** (dừng ở bước đỏ đầu tiên; bước 8 **luôn** chạy nếu đã qua bước 3):

| # | Bước | Đạt khi |
|---|---|---|
| 0 | Chuẩn bị: `mkdir -p .verify`; ghi HEAD, `git status --porcelain \| wc -l`; kiểm có `.env` (**chỉ** `test -f`, không đọc) | luôn |
| 1 | `make lint` | exit 0 |
| 2 | `make test` → tách 3 dòng tổng của pytest (backend/mock/ml) | exit 0 |
| 3 | `make up` (đã build + chờ mock, worker healthy, `/api/health`) | exit 0 |
| 4 | (G có 3) `make ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated` | exit 0 (kể cả "KB không đổi") |
| 5 | (G có 3) `FAKE_SCENARIO= FAKE_NODE_DELAY= $(COMPOSE) up -d --force-recreate --no-deps backend worker` → chờ worker healthy + `/api/health` 200 (≤ 180 s) → `make gate3 S=all` | 0 FAIL |
| 6 | (G có 2) `FAKE_SCENARIO=approval FAKE_NODE_DELAY=40 $(COMPOSE) up -d --force-recreate --no-deps backend worker` → chờ như 5 → `make gate2 S=all` | 0 FAIL |
| 7 | (`BENCH=1`) `bench_checkpoint` | in số |
| 8 | Trả về cấu hình `.env`: `$(COMPOSE) up -d --force-recreate --no-deps backend worker` (không biến shell) → chờ healthy | exit 0 |
| 9 | `gh run list --branch <nhánh hiện tại> -L 1` — lỗi thì ghi "bỏ qua (gh)" | không bắt buộc |

**Đầu ra:** `.verify/run-<YYYYmmdd-HHMMSS>.log` (toàn bộ) và `.verify/summary.txt` (ghi đè mỗi lần) dạng:

```
verify G=3 HEAD=<7 ký tự> dirty=<số file> bắt đầu=<giờ> kết thúc=<giờ>
| # | Bước | Kết quả | Thời gian | Ghi chú |
| 1 | lint | PASS | 41s | |
| 2 | test | PASS | 9m12s | backend 2915 passed · mock 94 · ml 77 |
| 5 | gate3 | PASS | 6m03s | 8/8 PASS, 0 FAIL |
…
KẾT LUẬN: XANH | ĐỎ ở bước <n> (<tên>) — 30 dòng cuối log: <đường dẫn>
```

**Luật:** không `down -v`, không `volume rm/prune`; không in giá trị biến môi trường (chỉ tên); không `set -x`; `APP_ENV` phải là `dev` (dùng lại chốt an toàn của gate2/gate3). `make verify-status` = in `.verify/summary.txt`. Lệnh `!` quá 120 s bị đẩy nền là **bình thường**: Tuấn Anh chỉ gõ `! make verify`, rồi báo agent "xong" — **agent tự đọc `.verify/summary.txt`** và dán vào MẪU B.

### 4.5. Test

| # | Test | Đạt khi |
|---|---|---|
| 4a-1 | Đăng nhập username ma `matkhau123` (không có trong `users`) | `security_events.username_attempted` = `h:` + 64 hex; chuỗi `matkhau123` không có ở bảng nào (quét như e9) |
| 4a-2 | Username có trong `users` sai mật khẩu | lưu nguyên văn |
| 4a-3 | Username ma sai 5 lần trong 10 phút | bị khoá như người thật (đếm qua view bằng giá trị băm); `test_locked_ghost_username_responds_exactly_like_locked_real_user` sửa kỳ vọng sang giá trị băm, ý test giữ nguyên |
| 4a-4 | `stored_username` | cùng đầu vào + cùng khoá → cùng kết quả; khác `jwt_signing_key` → khác |
| 4a-5 | `Settings.app_git_sha` | 40 hex → giữ; rỗng / `abc` / 41 ký tự → `None` |
| 4a-6 | B12 lineage | `commit_sha` = giá trị Settings (có → ghi; `None` → NULL) |
| 4a-7 | `FAKE_SCENARIO=""`, `FAKE_NODE_DELAY=""` | Settings coi là không đặt; `select_nodes` chọn node thật |
| 4a-8 | `bash -n scripts/verify.sh` (+ `shellcheck` nếu máy có) | sạch |

### 4.6. Mutation (tay, 2 cái — HMAC)

| Mã | Phá | Test phải đỏ |
|---|---|---|
| M-4a-1 | Username ma lưu nguyên văn | 4a-1 |
| M-4a-2 | Ghi dùng băm nhưng đếm khoá dùng chuỗi gốc | 4a-3 |

### 4.7. Soát bảo mật (security-reviewer, chỉ phần HMAC)

Bất biến kiểm: không còn đường ghi `username_attempted` nguyên văn cho username ma (grep mọi lời gọi `sink.record`/`_event`); khoá không log, không nằm trong `repr(Settings)`; thời gian phản hồi username ma không đổi đáng kể (không thêm truy vấn chỉ ở nhánh ma).

### 4.8. DỪNG 2 của 4a — Tuấn Anh chạy

`! make verify G=23` → agent đọc summary. Đạt khi: lint + test xanh, gate3 0 FAIL, gate2 0 FAIL, stack trở về cấu hình `.env`. Sau push: CI xanh, không annotation Node 20.

### 4.9. Spec cần sửa (4a) — agent in nguyên văn khi xong

Mục mẫu: CI (bản action đã chọn), P5 (số lỗi mypy đã sửa), P6 (số đo), mọi chỗ lệch 4.1–4.5.

### 4.10. Chốt khi hiện thực DỪNG 2 (30/09/2026, commit `f64fd86`, CI run 36726470829 xanh)

Khi 4.1–4.8 nói khác bảng này, **bảng này thắng**. Kết quả `make verify G=23 BENCH=1` (cây chưa commit, `env=.env`): lint PASS · test backend 3221 (2968 unit + 253 integration/e2e) · mock 94 · ml 77 · gate2 **89/0** · gate3 **72/0** · bench PASS · trả về `.env` PASS. Mutation M-4a-1…8 **8/8** đỏ, md5 khớp; M-S0-1…10 chạy lại trên mã cuối 10/10. security-reviewer 3 lần (HMAC: H2 FAIL → Q-4a-5; soát lại H2+H6: H6 FAIL → thêm vector đáp án; Q-4a-6: 0 FAIL).

| # | Chỗ | Chốt |
|---|---|---|
| 1 | P1 | `actions/checkout@v5`, `actions/cache@v5`, `astral-sh/setup-uv@v7` — major thấp nhất có `runs.using: node24` (đọc `action.yml` 30/09/2026); input không đổi; `runs-on: ubuntu-24.04`. Push file workflow cần token có scope `workflow` (`gh auth refresh -h github.com -s workflow`, Tuấn Anh làm một lần) |
| 2 | P2/P3 — Q-4a-5 (chuyển tiếp) | Đếm/khoá: username ma → `count_failures((băm,))`; username có dòng `users` → `count_failures((nguyên văn, băm))` — **một** câu SQL `IN`, port nhận `tuple[str, ...]`. Lý do: lần sai lưu băm lúc **chưa** có dòng (trước khi chính người đó đăng nhập, hoặc trước khi `_ensure_manager` tạo dòng người quản lý) phải còn được đếm sau khi dòng được tạo. Ghi `username_attempted` vẫn theo `known`. `bruteforce_alert` (subject + `detail.username`) dùng cùng giá trị lưu; `permission_denied(role_unmappable)` cùng quy tắc (chưa có dòng → băm dù mật khẩu đúng) |
| 3 | P2/P3 — Q-4a-6 (mang khoá) | Dòng `users` **vừa tạo** (kết quả `INSERT … ON CONFLICT DO NOTHING RETURNING` — **không** chỉ cột, mọi UNIQUE là arbiter; không SELECT trước) → `_carry_ghost_lock`: đếm lần sai trong cửa sổ bằng `count_failures(_failure_keys)`, ≥ `MAX_AUTH_FAILURES` → `locked_until` = lần sai cuối (`last_failure_at`, cùng điều kiện lọc) + `LOCKOUT`; `last` None → tính từ `now` (fail-closed). Dòng đã có: không đếm, không ghi đè (`locked_until`, `token_version`, `mfa_secret_enc` giữ). Port `upsert_user`: "role cũ None ⟺ chính lời gọi tạo dòng"; trùng username với `user_id` khác → `ValueError`. Chỉ có **một** đường tạo dòng `users` trong mã chạy thật (`SqlAuthStore.upsert_user` ← `AuthService._upsert` ← `_sync_login_user` / `_ensure_manager`). Lỗi ở bước mang khoá lan ra (khối `try` bao quanh chỉ bắt `IdentityUnavailable`) → request đăng nhập thất bại |
| 4 | P2 — test vector | 4a-4 thêm vector đáp án HMAC tính độc lập (khoá test công khai `b"k"*32`) + công thức viết lại trong test. Dòng hằng có `# gitleaks:allow` (gitleaks `generic-api-key` báo nhầm vì tên biến có `KEY` + 64 hex) — **không** tạo `.gitleaksignore`, không đổi tên biến |
| 5 | P4 | `app_git_sha` rỗng → `None` **im lặng** (cây bẩn luôn truyền rỗng); WARNING chỉ khi sai dạng, không in giá trị. Dockerfile: `ARG`/`ENV` sau `USER app`, trước `EXPOSE`/`CMD`. `commit_sha` tới node qua `NodeDeps.commit_sha` (wiring ← Settings). `Makefile` `BUILD_BACKEND` dùng chung cho `up` và `ingest` |
| 6 | P5 | `uv run mypy backend/tests` trần dừng ở lỗi cấu hình (2 `conftest.py` trùng module) → lệnh đúng: `MYPYPATH=backend uv run mypy --explicit-package-bases --cache-dir .mypy_cache/tests backend/tests`. Đo 235 lỗi / 94 dòng / 44 file (> 80 → DỪNG, Q-4a-4 cho sửa hết) → 0; `# type: ignore` trong `backend/tests` 162 → 157; `DyingAudit.record` thêm `lineage`. Đã vào `make lint` |
| 7 | P6 | `bench_checkpoint.py` (testcontainers `postgres:16`, `open_postgres_saver` + serde runtime, state tổng hợp, 10 khởi động + 200 mẫu/cỡ), `make verify BENCH=1` bước 7. Số đo 30/09/2026 (một lần ghi checkpoint, không phải cả lượt): p50/p95 **5 KB 0,97/1,31 ms · 20 KB 1,00/2,07 ms · 50 KB 1,14/2,37 ms** — < 50 ms → giữ `durability="sync"`, Việc treo 16 đóng |
| 8 | P7 / 4.4 | Recipe `verify` gọi `MAKE_BIN=make bash scripts/verify.sh`, **không** dùng `$(MAKE)` (dòng có `$(MAKE)` khiến `make -n verify` chạy thật); thêm `verify-status`; 4a-7 "đã có" (`env_ignore_empty=True`). Lượt đầy đủ `G=23 BENCH=1` ≈ 14 phút (gate2 ≈ 7,5 phút do `FAKE_NODE_DELAY=40`) — đẩy nền là bình thường. `lineage.commit_sha` NULL khi chạy trên cây bẩn (đúng P4) |
| 9 | Test / mutation | 4.5 thêm 4a-9 (chuyển tiếp do tự đăng nhập), 4a-10 (do `_ensure_manager`), 4a-11 (`role_unmappable`), 4a-12…16 = Q-4a-6 (a) đủ ngưỡng → khoá mang sang, AD 0 lời gọi, biên ±1 s, không sự kiện mới · (b) ngưỡng−1 → không khoá · (c) lần sai rơi khỏi cửa sổ → không khoá · (d) dòng đã có → không đếm/không ghi đè · (e) nguyên văn + băm cộng dồn; + 3 test hợp đồng store (upsert đồng thời đúng 1 lần "tạo", trùng username → lỗi, `last_failure_at`) chạy cả in-memory lẫn Postgres thật. 4.6 thêm M-4a-3 (→ 4a-9, 4a-10), M-4a-4 "khoá HMAC = thẳng khoá ký" (→ 4a-4), M-4a-5 bỏ phép đếm, M-4a-6 `>=` → `>`, M-4a-7 đếm cả khi dòng đã có, M-4a-8 khoá tính từ `now` |
| 10 | Việc treo | **22** AD thật khớp username không phân biệt hoa/thường (HMAC phân biệt) · **23** (R1, Q-4a-7) bước mang khoá không cùng giao dịch với INSERT — khe 3 round-trip; lỗi sau INSERT → về mức trước Q-4a-6 · **24** (R2, Q-4a-8) AD đổi username của người đã có dòng → không mang khoá trượt của username mới; *giới hạn đã biết:* mock AD không đổi username. Việc treo 1, 10, 13, 14, 16 đóng ở 4a |
| 11 | → 4b | 4b P5 tách `_ensure_manager` + `_upsert` thành `auth/user_sync.py::sync_user_from_ad` → **phải mang theo `_carry_ghost_lock` và cờ "vừa tạo" của `upsert_user`**: B15 `ensure` người duyệt chưa có dòng cũng là một đường tạo dòng. Thêm test 4b: người duyệt từng bị khoá trượt khi là username ma → B15 tạo dòng → `locked_until` được mang sang; M-4a-5 phải vẫn đỏ sau khi tách |

---

## 5. Chặng 4b — B15 thật (tầng A)

**Mục tiêu:** chọn đúng người duyệt theo [Chốt] (không ai tự duyệt, kể cả qua cấp bậc), không bao giờ tạo phiếu cho hành động mà người gửi không sở hữu đích, không E9 vì người duyệt chưa đăng nhập; B17 kiểm lại cả người duyệt.
**Đầu vào:** 4a xong, CI xanh. **Đầu ra:** node `b15_prepare_approval` thật, `config/approvers.yaml`, luật R17–R19 mới, seed mock mới, `conflict_type` dùng chung, B17 kiểm người duyệt.
**Nghi thức (tầng A):** PLAN-4b.md + MẪU A · **2 DỪNG** · test-writer viết test bảng 3.2 **trước** code · mutation ×2 lượt + md5 · security-reviewer mỗi DỪNG.

### 5.1. P-x chốt trước

| Mã | Chốt |
|---|---|
| P1 | `config/approvers.yaml`: `vpn: {primary: l1_01, backup: l1_02, head: it_mgr01}`. Model Pydantic `extra=forbid`, nạp lúc khởi động (`open_runtime`, cùng chỗ `check_intent_config`): mọi intent trong `ENABLED_INTENTS` phải có roster; 3 id khác nhau, khớp `^[a-z0-9_]{3,64}$`. Nhóm/AD **không** kiểm lúc khởi động (mock có thể chưa lên) — kiểm ở B15 |
| P2 | `valid(ad, role)`: `employment_status == "active"` **và** `role_from_groups(ad.groups) == role` (`l1` cho primary/backup, `manager` cho head). `probation` **không** hợp lệ để duyệt. Không tìm thấy (404/rỗng) → không hợp lệ (`not_found`), **không** phải lỗi. Lỗi hệ thống sau retry → E2 `approver_lookup_error` |
| P3 | Tra AD: `deps.directory.call("ad_get_user", {"user_id": …}, caller_step="B15_APPROVER")`; thêm `B15_APPROVER` vào `ad_get_user.allowed_steps` (hằng như `RECHECK_STEP`); cache trong một lần chạy node (một người tra một lần). Thêm điểm gọi vào `test_turn_budget.py::NODE_CALL_SITES` |
| P4 | Chuỗi quản lý (Q-4-R): đi `manager_id` qua AD tối đa 5 cấp, chặn vòng; tra lỗi giữa chừng → E2; không tìm thấy → dừng chuỗi (coi như hết). `conflict_type(requester_id, cand_id, cand_chain, action)` là **hàm thuần** ở `domain/approval.py` (mới): `self` → `boss_of_approver` (requester ∈ chain) → `targets_approver` (`action.requested_for == cand_id`) → None. `auth/authz.approval_conflict` gọi hàm này (route dựng chain từ bảng `users`, ≤ 5 cấp) — **một** định nghĩa |
| P5 | Đồng bộ `users` (Q-4-N): tách từ `AuthService` thành hàm công khai `auth/user_sync.py::sync_user_from_ad(store, idp_or_ad, ad_user, now)` (gồm `_ensure_manager` + `_upsert` **+ `_carry_ghost_lock`** — mục 4.10 #11, giữ nguyên hành vi đổi role → thu hồi phiên và mang khoá trượt khi dòng vừa tạo); `AuthService` gọi lại hàm này (không đổi hành vi login — test auth hiện có phải xanh). NodeDeps thêm port `approver_users: ApproverUsers` (`async ensure(ad_user) -> None`) — bắt buộc, không mặc định. Gọi `ensure` cho approver + backup **trước** `effects.once("approval_create")` |
| P6 | Chốt phòng thủ (G4-16): hàm thuần `action_has_device_target(action)` = `action.target.startswith("device:")`; đúng mà `action.facts.get("device_owner_is_requester") is not True` → E5 `approval_target_unverified`, **trước** mọi lời gọi AD |
| P7 | Luật (Q-4-M): thêm `{"fact": "action.facts.device_owner_is_requester", "op": "is_true"}` vào `conditions.all` của R17, R18, R19 trong `config/policy.json`. h-rule thêm 3 dòng: "ngoài giờ + máy người khác → E5", "thử việc + máy người khác → E5", "máy không tồn tại → E5". h14 đổi kỳ vọng: E5 `llm_layer_disabled`, vẫn `slot_fact_collision=true`, 0 lời gọi ghi, **0 phiếu**. **`test_h11_at_20h_r18_hitl_no_write`** (3h chấp nhận HITL cho máy người khác lúc 20:00) đổi thành E5 `llm_layer_disabled`, 0 phiếu — đổi tên test cho đúng nghĩa |
| P8 | `SqlApprovals.create(ticket_id, approver_id, deadline, action_plan_hash, *, backup_approver_id, conflict_detected, conflict_type)`; `ApprovalRow` thêm `backup_approver_id, created_at, reminder_1_at, reminder_2_at, decided_at, conflict_type`. Port `Approvals` (fakes) đổi theo; node giả (fake B15) truyền giá trị mặc định (None/False/None) |
| P9 | Chạy lại B15 (TC33): **`effects` hiện không có hàm đọc trước** (chỉ `once`). Thêm `effects.peek(state, kind, *, step, sub="") -> str \| None` (cùng `effect_key`, chỉ SELECT `side_effects.result_ref`). B15: sau chốt phòng thủ → `peek("approval_create")` có → **bỏ qua chọn người/tra AD/ensure**, dùng phiếu cũ (`approvals.get` → báo + `goto` theo `a.approver_id`). Lý do: chạy lại mà AD đang lỗi → E2 trong khi phiếu `pending` vẫn còn (phiếu mồ côi). Test x14b |
| P10 | Điểm log 5: `goto(..., intended_action=action, audit_columns={"approver_id", "deadline", "conflict_detected"})` (`intended_action` là key sẵn có → cột `audit_logs.intended_action` có giá trị; 4c P5 đọc cột này. `audit_columns` là tham số mới của `goto`, chỉ nhận khoá trong hằng `_POINT_COLUMNS` = {approver_id, deadline, conflict_detected, response_time_seconds}; khoá khác → `ValueError`. Ghi đè 4d **không** đi qua `goto` — ghi bằng `AuditWriter` trực tiếp) + `action_plan_hash` (field sẵn có) + `audit_detail={backup_approver_id, conflict_type, choice_reason ∈ {normal, conflict, no_valid_l1}, rejected_candidates: [{user_id, reason ∈ {not_found, inactive, wrong_group, self, boss_of_approver, targets_approver}}], sla_minutes}`. Không chữ tự do |
| P11 | `REASON_DETAILS` thêm `no_valid_approver`, `approver_lookup_error`, `approval_target_unverified`, `approver_no_longer_valid`. Nhánh E5/E2 của B15: `goto(S_ESCALATED, next_node="b20_audit", step="B15", …)`, `escalation_reason_detail` là **chuỗi hằng** (test AST) |
| P12 | Hạn SLA: `deps.constants.SLA_MINUTES`; đè bằng `APPROVAL_SLA_MINUTES_DEV` (int 1–30) **chỉ** khi `APP_ENV ∈ {dev,test}` (`settings.require_dev_fakes`), env khác đặt → từ chối khởi động. **Thêm `APPROVAL_SLA_MINUTES_DEV: ${APPROVAL_SLA_MINUTES_DEV:-}` vào khối `x-backend-env` của `docker-compose.yml`** (không có dòng này thì biến shell của `make verify G=4` không vào container) + dòng rỗng có chú thích trong `.env.example`. Audit ghi `sla_minutes` thật đã dùng |
| P13 | B17 (Q-4-P): khi `via_approval`, tra thêm `decided_by` của phiếu (từ `approvals.get`) song song với người gửi/người hưởng lợi (`B17_RECHECK`). Không `valid(ad, l1)` và không `valid(ad, manager)` → E5 `approver_no_longer_valid`, 0 lời gọi ghi; lỗi AD khi tra `decided_by` → **E2 `approver_lookup_error`** (Q-4b-1; nhánh sẵn có của người gửi/người hưởng lợi giữ E5 `person_no_longer_valid` — bản 1.0 ghi "như nhánh sẵn có" là sai). `decided_by` None mà `approved` → E5 `recheck_failed` |
| P14 | Seed mock (Q-4-Q) `mock_services/seed.json`: `l1_lead` (username `khoa.dv`, "Đặng Văn Khoa", "Trưởng nhóm Helpdesk", IT, groups `[IT-Users, IT-L1]`, `manager_id: it_mgr01`, active, `hired_days_ago: 1500`, password hash cùng cách seed hiện có — mật khẩu dev ghi ở đúng chỗ các mật khẩu dev khác đang ghi); `l1_01.manager_id` → `l1_lead`; máy `PC-0124` (l1_01), `LAP-0700` (l1_lead), `LAP-0900` (it_mgr01), cả 3 `registered: false`, không cert. Agent grep mọi test dựa vào `manager_id` của `l1_01` / số máy của `l1_01` và sửa kỳ vọng có lý do |
| P15 | B15 giả → `graph/nodes/fake/b15_prepare_approval.py`; `select_nodes` như 3c; `FAKE_APPROVER_ID` chỉ còn phục vụ node giả (gate2). Node thật **không** gọi `deps.scenario.pick`, giữ `deps.scenario.hook(state, "after_approval_create")` (cho TC33 trên stack) |

### 5.2. Mã giả node

```python
def make(deps: NodeDeps) -> NodeFn:
    async def b15_prepare_approval(state):
        rc, action = state["requester_context"], state["intended_action"]
        if action_has_device_target(action) and action.facts.get("device_owner_is_requester") is not True:
            return await goto(state, S_ESCALATED, next_node="b20_audit", step="B15", event="approval_refused",
                              exit_code="E5", escalation_reason_detail="approval_target_unverified",
                              audit_detail={"stage": "target_guard"})
        try:
            choice = await choose_approver(deps, deps.approvers[state["intent"]], rc, action)   # 3.1 + P2–P4
        except ToolSystemError:
            return await goto(..., exit_code="E2", escalation_reason_detail="approver_lookup_error", ...)
        if isinstance(choice, Refuse):                                                          # no_valid_approver
            return await goto(..., exit_code="E5", escalation_reason_detail="no_valid_approver",
                              audit_detail={"rejected_candidates": choice.rejected})
        for ad_user in choice.ad_users_to_sync:                                                 # approver + backup
            await deps.approver_users.ensure(ad_user)                                           # P5 (FK)
        h = hash_action(action); deadline = now + sla(deps)
        a_id = await effects.once(state, "approval_create", deps.approvals.create, state["ticket_id"],
                                  choice.approver.user_id, deadline, h, step="B15",
                                  backup_approver_id=..., conflict_detected=..., conflict_type=...)
        await deps.scenario.hook(state, "after_approval_create")
        a = await deps.approvals.get(a_id)                                                      # P9
        await effects.once(state, "notify_approver", deps.approvals.notify_approver, a_id, a.approver_id, step="B15")
        return await goto(state, S_PENDING_APPROVAL, next_node="approval_wait", step="B15", event="queued",
                          approval_id=a_id, action_plan_hash=h, intended_action=action,        # cột audit intended_action cho hộp thư 4c P5
                          audit_columns={"approver_id": a.approver_id, "deadline": a.deadline,
                                         "conflict_detected": ...},
                          audit_detail=point5(...))                                             # P10
    return b15_prepare_approval
```

### 5.3. Test (ngoài bảng 3.2)

| # | Test | Đạt khi |
|---|---|---|
| b1 | `conflict_type` thuần: 3 loại + thứ tự ưu tiên + chain rỗng + vòng | đúng |
| b2 | Route duyệt dùng cùng hàm: `l1_lead` gửi, phiếu (giả lập) giao `l1_01` → `l1_01` quyết | 403 |
| b3 | Người duyệt chưa có dòng `users` (xoá trước khi chạy) | Phiếu tạo được; `users` có dòng approver + manager chain; **không** có dòng `sessions` mới |
| b4 | `approvers.yaml` thiếu intent đang bật / trùng id / khoá lạ | Khởi động thất bại |
| b5 | `APPROVAL_SLA_MINUTES_DEV` ở `APP_ENV=prod` | Khởi động thất bại |
| b6 | B17: `decided_by` bị `disabled` (hook trước B17) | E5 `approver_no_longer_valid`, 0 lời gọi ghi |
| b7 | B17: AD lỗi khi tra `decided_by` | E2 |
| b8 | Điểm log 5 | Cột `approver_id, deadline, conflict_detected, action_plan_hash` không NULL; `detail` đủ khoá P10; không chữ tự do |
| b9 | `goto(audit_columns={"foo": 1})` | `ValueError` |
| b10 | Test auth hiện có (login, đổi role, `_ensure_manager`) | Xanh, không sửa kỳ vọng (trừ chỗ seed đổi `manager_id` của `l1_01` — ghi lý do) |

### 5.4. Mutation bắt buộc

| Mã | Phá | Test phải đỏ |
|---|---|---|
| M-4b-1 | Xung đột → chọn dự phòng thay Trưởng BP | x2, x3 |
| M-4b-2 | Không kiểm xung đột cho Trưởng BP | x4 |
| M-4b-3 | `boss_of_approver` chỉ sếp trực tiếp | x4 |
| M-4b-4 | `valid()` bỏ kiểm `employment_status` | x7 |
| M-4b-5 | Lỗi AD coi như "không hợp lệ" (đi tiếp) | x9 |
| M-4b-6 | Bỏ điều kiện chủ máy ở R18 | h-rule "ngoài giờ + máy người khác" |
| M-4b-7 | Bỏ điều kiện chủ máy ở R17 | x6 / h14 mới |
| M-4b-8 | Bỏ chốt phòng thủ B15 | x12 |
| M-4b-9 | Báo người duyệt vừa chọn thay vì `a.approver_id` | x14 |
| M-4b-10 | B17 bỏ kiểm `decided_by` | b6 |
| M-4b-11 | Route dùng hàm xung đột riêng chỉ sếp trực tiếp | b2 |
| M-4b-12 | Không `ensure` người duyệt trước khi tạo phiếu | b3 (E9) |
| M-4b-13 | Bỏ `peek`, chạy lại luôn chọn người/tra AD | x14b |
| M-4b-14 | B15 không truyền `intended_action` vào `goto` | 4c c10 (danh sách thiếu `action_type`) / audit_check điểm 5 |

### 5.5. DỪNG

- **DỪNG 1:** P1, P2–P4 (`domain/approval.py`, chain, route dùng chung), P5 (tách `user_sync`), P7 (luật + h-rule + h14), P14 (seed), P12; test-writer viết test bảng 3.2 (đỏ trước). `make verify G=23`.
- **DỪNG 2:** node thật (5.2, P6, P8–P11, P15), B17 (P13), mutation ×2, security-reviewer (bất biến: không tự duyệt; deny không phiếu; hết hạn không thực thi; mọi side effect B15 qua `effects.once`; không chữ tự do trong audit). `make verify G=23`.

### 5.6. Chốt khi hiện thực 4b — DỪNG 1 (30/09/2026)

Khi 5.1–5.5 nói khác bảng này, **bảng này thắng**. Kết quả `make verify G=23` (22:51 → 23:05, cây chưa commit, `env=.env`): lint PASS · backend 3382 (3129 unit + 253 integration/e2e) · mock 100 · ml 77 · gate2 **89/0** · gate3 **72/0** (chạy ngoài giờ 23:02) · trả về `.env` PASS. Mutation `mutate_4b.py` M-4b-1…7, 11: 2 lượt × 8/8 đỏ, md5 khớp; `mutate_4a.py --hmac` sau khi tách: 8/8. security-reviewer: 0 FAIL / 3 NGHI (S1d → Q-4b-6; S1e → Việc treo; S5a chỉ báo).

| # | Chỗ | Chốt |
|---|---|---|
| 1 | Q-4b-1 | B17: lỗi AD khi tra `decided_by` → E2 `approver_lookup_error` (sửa chữ P13). Nhánh người gửi/người hưởng lợi giữ E5 `person_no_longer_valid`. Xét người gửi/người hưởng lợi trước, `decided_by` sau, trong **một** `gather` (TQ-11) — làm ở DỪNG 2 |
| 2 | Q-4b-2 | Thêm **b2b**: `it_mgr01` gửi, phiếu giao `l1_01`, `l1_01` quyết → 403 (chuỗi 2 cấp; giết M-4b-11). Test route dựng danh bạ riêng theo seed P14, không dùng `seed_ad_users` |
| 3 | Q-4b-3 | x14 giết process **tại hook `after_approval_create`** (trước `notify_approver`), tắt `l1_01` trong AD giữa hai lần chạy; đúng 1 phiếu, đúng 1 `notify_approver` cho `a.approver_id`. M-4b-9 = "bỏ `peek` + báo người vừa chọn" |
| 4 | Q-4b-4 | b8 kiểm thêm `audit_logs.intended_action` không NULL, có khoá **`type`** + `target` (giết M-4b-14 ngay ở 4b) — bản 1.1 ghi `action_type` là sai, xem 5.7 #5 |
| 5 | Q-4b-5 | Process chạy B15 thật thiếu `JWT_SIGNING_KEY`: WARNING lúc khởi động (không đổi điều kiện khởi động — cùng lý do Q-4-S); B15 ra E2 **trước** `ensure`, `reason_detail` hằng riêng `approver_sync_unavailable` (`REASON_DETAILS`), 0 phiếu |
| 6 | Q-4b-6 = A | Route giữ chuỗi dựng từ bảng `users` (P4); `users.manager_id = NULL` mang hai nghĩa ("không có sếp" / "không biết" — sếp không ra role, không có trong AD, sâu > 5, vòng) nên chuỗi ở route có thể **cụt**. Lớp chặn chính là B15 thật (chuỗi từ AD, không lọc theo role). DỪNG 2 thêm test B15: sếp trung gian không ra role → vẫn phát hiện `boss_of_approver`. Việc treo: phân biệt hai nghĩa của NULL (cần schema — sau Phase 4) |
| 7 | TQ-2/TQ-4 | `auth/user_sync.py`: lớp `AdUserSync` (+ `LockPolicy`) chứa `_ensure_manager`/`_upsert`/`_carry_ghost_lock` — **một** định nghĩa cho `AuthService` và B15; `username_hash.failure_keys` thuần. `ApprovalParties(requester_id, approver_chain, action)`; route bỏ `_action_targets` (đích `device:…` không bao giờ trùng `user_id` → không mất kiểm) |
| 8 | TQ-3/TQ-7 | `ensure(ad_user, lookup, *, now)` (lookup có cache, mọi lời gọi qua registry bước `B15_APPROVER`). Nhánh `peek`: `choice_reason` suy tất định từ phiếu cũ (`conflict_detected` → `conflict`; `approver_id == roster.head` → `no_valid_l1`; còn lại `normal`) + `detail.recovered=true`; `rejected_candidates=null` |
| 9 | P12 / A24 | `open_runtime`: kiểm SLA dev **đầu tiên**, roster sau `check_plans`, cả hai trước DB. Lỗi → API vẫn chạy, route ticket/duyệt 503; worker dừng (hành vi sẵn có `main.py`, không sửa) |
| 10 | P7 | R17/R18/R19 thêm `device_owner_is_requester is_true`. Mỗi luật còn test khớp dương với máy của chính người gửi (C5, bảng 11.2, `test_hrule_4b_owner`, e2e h6/h10, gate3 tc09 · tc02/tc06). `test_b02_screen` e12/e18 **vô tình dựa vào lỗ G4-16** (xin cho máy người khác lúc 07:00 → R18) → nay E5 ở B13/B14; kiểm "B2 cho qua" giữ và chặt hơn (điểm escalate đầu = `B13/B14`, không có `B2`). `test_b12_assess` P5 ca máy người khác 20h → E5 |
| 11 | P14 | Seed 17 người (`l1_lead`/`khoa.dv`, `l1_01 → l1_lead`, `PC-0124`/`LAP-0700`/`LAP-0900` chưa đăng ký). Test đổi: `test_endpoints.py:45-46, :92`, `test_tools_vs_mock.py:53`. `tests/fakes/auth.py::seed_ad_users` là bản chép tay **cố ý lệch** seed (`l1_01 → it_mgr01`) để test auth không đổi kỳ vọng — test chuỗi quản lý 4b dùng `tests/fakes/ad_seed.py` hoặc dựng tay. Đăng nhập `ha.lt` ở gate3 nay tạo thêm dòng `users` của `l1_lead` |
| 12 | Việc treo | S1e: `targets_approver` chỉ so `requested_for` — Phase 5 (intent tài khoản, `target="user:…"`) phải xét lại. Q-4b-6 (NULL hai nghĩa). gate3 in cảnh báo thiếu `FAKE_APPROVER_ID` → chốt ở DỪNG 2 (B15 thật không dùng) |

### 5.7. Chốt khi hiện thực 4b — DỪNG 2 (01/10/2026, mốc `1f0f489` — sau merge M9 A0 + B0)

Khi 5.1–5.6 (kể cả mã giả 5.2) nói khác bảng này, **bảng này thắng**. Kết quả `make verify G=23` (04:40 → 04:54, cây chưa commit, `env=.env`): lint PASS (import-linter **10/10** gồm hợp đồng M9 "monitor-only-api-worker") · backend **3501** (3243 unit — 45 của M9 — + 258 integration/e2e, 0 skip) · mock 100 · ml 77 · gate2 **89/0** · gate3 **78/0** (= 72 + 6 kiểm mới Q-4b-7; chạy ngoài giờ 04:51 → tc02/tc06 R18 + tc09 R17 đều giao `l1_01`, dự phòng `l1_02`, không xung đột; `ha.lt` duyệt 202 → B17 kiểm lại người duyệt → gia hạn đúng 1 lần) · trả về `.env` PASS. S11 test-writer 67 test (59 đỏ đúng lý do trước code); mutation M-4b-1…14 **2 lượt × 14/14**; security-reviewer 0 FAIL / 2 NGHI (cùng gốc → Q-4b-8).

| # | Chỗ | Chốt |
|---|---|---|
| 1 | 5.2 thứ tự B15 | P6 chốt phòng thủ → `effects.peek("approval_create")` (có → nhánh phiếu cũ: `approvals.get` → `once(notify_approver, a.approver_id)` → `goto`; KHÔNG chọn người/tra AD/ensure) → `approver_users.available` (False → E2 `approver_sync_unavailable`) → hook `before_approver_lookup` → `choose_approver` (lookup có cache `memo_lookup`, mỗi người một `ad_get_user` bước `B15_APPROVER`) → `ensure` người duyệt + dự phòng → `once(approval_create)` → hook `after_approval_create` → `approvals.get` → `once(notify_approver, a.approver_id)` → `goto(S_PENDING_APPROVAL)` |
| 2 | 5.2 nhánh E | `event` = chính `reason_detail` (`approval_target_unverified`, `approver_sync_unavailable`, `approver_lookup_error`, `turn_budget_exceeded`, `no_valid_approver`), không phải `approval_refused`. `audit_detail.stage` ∈ {target_guard, sync_unavailable, lookup, turn_budget, choose}; `choose` kèm `rejected_candidates`. Không có `ToolSystemError`: registry trả `ToolResult.error` → `ApproverLookupError` → E2; `TurnBudgetExceeded` → E2 `turn_budget_exceeded`; lỗi hợp đồng / thiếu roster intent → E9. Lời tra AD nằm trong `make()` (`deps.directory.call`) để `NODE_CALL_SITES` nhận (P3; sàn tổng 14 → 17) |
| 3 | P8 / P9 | `ApprovalRow` thêm cả `conflict_detected`. Port `EffectStore.peek(key) -> str \| None` (SQL: SELECT `side_effects.result_ref`, kết nối riêng — dòng `run_once` chưa commit không thấy); `effects.peek` dùng **cùng** biểu thức `effect_key` với `once` (dòng khoá của `once` giữ nguyên văn — M-3g-7 bám). Có test PG x14+x14b qua `SqlEffectStore.peek` thật |
| 4 | P10 | `goto(audit_columns=…)`: hằng `_POINT_COLUMNS` = {approver_id, deadline, conflict_detected, response_time_seconds}; khoá khác → `ValueError` nêu tên khoá, TRƯỚC khi ghi. Hàm cũ chép trường state → cột đổi tên `_state_columns`. `detail` điểm 5 có **6** khoá: `backup_approver_id, conflict_type, choice_reason, rejected_candidates, sla_minutes, recovered` — `recovered` luôn có (false nhánh thường, true nhánh `peek`); `rejected_candidates` list (rỗng khi không loại ai) ở nhánh thường, null ở nhánh `peek` |
| 5 | Q-4b-4 (sửa 5.6 #4) | `Action` không có trường `action_type`: JSON `audit_logs.intended_action` có khoá **`type`** + `target`. b8 kiểm `intended_action->>'type'`. 4c P5 đọc `intended_action->>'type'` (đã sửa ở 6.1) |
| 6 | P5 / Q-4b-5 | Port `ApproverUsers.available` (False khi thiếu `JWT_SIGNING_KEY`); bản thật `auth/user_sync.AuthApproverUsers(AdUserSync \| None)`; `ensure` khi sync None hoặc nhóm AD không ra role → `RuntimeError` (E9 — bug). Wiring: `auth/service.lock_policy(config)` công khai (AuthService + wiring dùng chung); `graph/wiring.approver_users()` dẫn xuất khoá HMAC username như lúc đăng nhập (không dựng `TokenSigner` → worker không thêm kiểm độ dài khoá); `_open(approvers=None)` tự nạp qua `open_approvers(settings)` (`wiring.py:236` → `settings.py:533-542`: `load_approvers` schema + `check_approvers_config` intent) |
| 7 | Q-4b-8 = A | `ensure` (đồng bộ `users` qua `AdUserSync` dùng chung với đăng nhập) nằm **ngoài** `effects.once` — **ngoại lệ bất biến 5.5 "mọi side effect B15 qua `effects.once`"**: khi role trong `users` khác AD, `ensure` tăng `token_version`, thu hồi phiên, ghi `role_changed`; điều kiện tự hết sau lần đầu → chạy lại không nhân đôi (test `test_q4b8_ensure_role_changed_once_then_no_repeat`); hướng thay đổi chỉ giảm quyền cũ. Việc treo 27: `role_changed` không ghi nguồn (login / B15) |
| 8 | P13 | B17 tra `decided_by` (đọc bằng `approvals.get`; "đã duyệt" vẫn qua `get_status`) trong **cùng** `gather` với người gửi/người hưởng lợi, xét SAU. Detail: E5 `recheck_failed` `recheck="no_decided_by"`; E2 `approver_lookup_error` {user_id, role="approver", ad_error=true}; E5 `approver_no_longer_valid` {user_id, role="approver", reason}. `test_b17_execute` người duyệt giả `l1-fake` → `l1_01`; `test_beneficiary_terminated_is_e5` AD 2 → 3 lời gọi + `calls_by[l1_01]==1` |
| 9 | Harness | `GraphHarness` + `open_pg_runtime(roster_in_ad=True)` gộp `ROSTER_CHAIN` (`l1_01, l1_02, it_mgr01, l1_lead` từ `seed.json`) vào AD giả khi test không truyền `directory` (`setdefault`); `roster_in_ad=False` → E5 `no_valid_approver` (có test). Bảng `users` giả không gieo sẵn roster → B15 phải `ensure` (b3/M-4b-12 kiểm ở unit qua FK giả của `MemoryApprovals`). 0 test đổi kỳ vọng vì harness. Test cần CẢ route lẫn B15 thật chỉ ở PG: `test_b15_pg::test_x2_tc19_pg_route_and_real_b15_self_conflict_head_decides` |
| 10 | Q-4b-7 = A (gate3) | `gate3.py` bỏ `FAKE_APPROVER_ID` (FLAGS, cảnh báo, docstring); hằng `ROSTER_APPROVER/ROSTER_BACKUP = l1_01/l1_02`; `_check_approver` CHỈ KHI có phiếu: `(approver_id, backup_approver_id, conflict_detected) == (l1_01, l1_02, false)` + audit B15 `queued.approver_id = l1_01`. `gate2.Ctx.approvals` chỉ thêm trường (gate2 vẫn node giả + `FAKE_APPROVER_ID`). README cổng: E2 `approver_sync_unavailable` → thiếu `JWT_SIGNING_KEY`; E5 `no_valid_approver` → roster không hợp lệ trong mock AD |
| 11 | 5.4 mutation | M-4b-9 và M-4b-13 bị cùng nhóm test giết (x14, x14b, nhánh `peek`) — "báo người vừa chọn" tương đương dưới `peek` (đúng lý do Q-4b-3). M-4b-12 giết ở unit (FK giả); b3 PG xanh ở verify |
| 12 | M9 | 4b không import `app.monitor`; không trùng file M9. Mốc diff 4b = `1f0f489`. `reason_detail` mới của 4b và đổi hành vi R17–R19 đã báo M9 |

---

## 6. Chặng 4c — B16 + nhắc + xem phiếu + dự phòng (tầng B)

**Mục tiêu:** người dùng biết vì sao bị từ chối; người duyệt có hộp thư, xem đúng object đã băm, được nhắc đúng 1 lần mỗi mốc; người dự phòng duyệt được sau nhắc 2.
**Nghi thức (tầng B):** PLAN ngắn · 1–2 DỪNG · mutation 1 lượt · test-writer cho IDOR xem phiếu · security-reviewer cuối chặng.

### 6.1. P-x chốt trước

| Mã | Chốt |
|---|---|
| P1 | B16 từ chối: sau `approvals.close`, `effects.once(state, "notify_user", deps.notifier.notify_user, ticket_id, text, "none", step="B16")` + `conversation=[rejection_msg(text, ref)]`. `MSG_KINDS` thêm `"rejection"` (khớp `NOTICE_KINDS` của DB). `text` theo mẫu, không LLM: "Yêu cầu {nhãn hành động} cho máy {device_id} chưa được duyệt. Lý do: {nhãn reason_code \| 'không nêu'}. Ghi chú của người duyệt: {note đã che}". `note` qua `deps.output_guard` — vi phạm → bỏ phần ghi chú, audit `note_suppressed=true` |
| P2 | Điểm log 6 (cả 3 nhánh): cột `approval_result`, `note` (đã che; chỉ nhánh có note), `response_time_seconds` (= `ev.at − a.created_at`; timeout → NULL). **Cách ghi (5.7 #4):** `approval_result`, `note` là khoá state sẵn có (cột cùng tên, ghi như trường của `goto`); CHỈ `response_time_seconds` đi qua `audit_columns`; `detail`: `view_duration`, `decided_without_view` (= `first_viewed_at` NULL), `decided_as ∈ {primary, backup}`, `reason_code`, `close_applied` (số dòng `close` cập nhật: 0/1) |
| P3 | Nhắc: hàm `WorkerJobs._scan_approval_reminders` gọi **ở cuối** `scan_deadlines` (`graph/worker_jobs.py`; **không** sửa `worker.py` — mục 0.2), lỗi của nó bắt riêng, không làm hỏng phần quét hạn. Mốc: `m1 = created_at + 0,5·(deadline − created_at)`, `m2 = created_at + 0,8·(deadline − created_at)`. `SqlApprovals.mark_reminder_once(approval_id, n, now) -> ReminderTarget \| None` = `UPDATE approvals SET reminder_n_at=:now WHERE approval_id=:id AND status='pending' AND reminder_n_at IS NULL AND deadline > :now RETURNING approver_id, backup_approver_id`. Chỉ gửi khi trả 1 dòng. Nhắc 1 → người duyệt; nhắc 2 → người duyệt + dự phòng (nếu có). Gửi qua `approvals.notify_approver(approval_id, user_id, kind="reminder_1"\|"reminder_2")` (Phase 4 vẫn log — hộp thư là API). Đã qua `m2` mà chưa nhắc 1 (worker chết lâu) → chỉ nhắc 2 (đặt cả hai cột) |
| P4 | Dự phòng (Q-4-O): `may_decide_as` đúng khi `p.user_id == a.approver_id` **hoặc** (`p.user_id == a.backup_approver_id` **và** `a.reminder_2_at` không NULL); **và** không xung đột (P4 của 4b). Sự kiện mang `decided_as`. Không đổi `approver_id` của phiếu |
| P5 | `GET /api/approvals?mine=1&status=pending\|approved\|rejected\|timeout` — `require("approval:decide")`; `mine` bắt buộc = 1 (khác → 422); trả tối đa 50 phiếu mà tôi là người duyệt hoặc dự phòng đủ điều kiện (P4): `approval_id, ticket_id, status, created_at, deadline, reminder_1_at, reminder_2_at, role_as, action_type, device_id` (`action_type` = `intended_action->>'type'`, `device_id` suy từ `intended_action->>'target'` (`device:…`) — đọc cột `audit_logs.intended_action` của dòng B15 `queued`, không đọc checkpoint từng phiếu; 5.7 #5) |
| P6 | `GET /api/approvals/{id}` → `ApprovalView {approval_id, ticket_id, status, deadline, requester{role, department}, request_summary (tickets.redacted_request[:500]), action (Action từ checkpoint), action_plan_hash, risk (RiskDecision), facts, role_as, procedure{doc_id, title}}` — `procedure` từ `ActionMeta.procedure_doc` + tiêu đề tài liệu (D-34, Q-4a-2: người duyệt thấy căn cứ quy trình; không tìm thấy tiêu đề → chỉ `doc_id`, không chặn). Quyền: người duyệt / dự phòng đủ điều kiện → xem + ghi `first_viewed_at` (`UPDATE … WHERE first_viewed_at IS NULL AND status='pending'`); `manager` (có `audit:read:all`) → xem, **không** ghi; còn lại (L1 khác) → **404**; L2/nhân viên → 403 (tầng 2). `hash_action(action) != approvals.action_plan_hash` → **409 `plan_changed`**, không trả bản nào (G4-13) |
| P7 | **Không migration** ở Phase 4 (mục 0.2 — tránh đụng chuỗi migration M9). Chỉ mục hộp thư → việc treo, làm khi có số đo chậm |

### 6.2. Test

| # | Test | Đạt khi |
|---|---|---|
| c1 | Từ chối có note chứa SĐT | Người dùng nhận 1 tin `kind=rejection`, SĐT đã che; resume 2 lần → vẫn 1 `notify_user` B16 |
| c2 | Điểm log 6 ba nhánh | Cột + detail đủ P2; timeout: `response_time_seconds` NULL |
| c3 | Nhắc (FakeClock): 14 phút, 15, 16, 24, 25, 30 phút với SLA 30 | Nhắc 1 đúng 1 lần ở 15; nhắc 2 đúng 1 lần ở 24 (gửi 2 người); không nhắc sau hạn |
| c4 | Hai worker cùng quét | Mỗi mốc đúng 1 thông báo |
| c5 | Dự phòng quyết trước nhắc 2 / sau nhắc 2 | 403 / 202, `decided_as=backup` |
| c6 | Dự phòng là người gửi (không thể theo 4b, dựng tay) | 403 |
| c7 | Xem phiếu: người được giao / dự phòng trước nhắc 2 / L1 khác / manager / L2 / nhân viên | 200 + ghi / 404 / 404 / 200 không ghi / 403 / 403 |
| c8 | Xem 2 lần | `first_viewed_at` giữ lần đầu |
| c9 | Sửa `intended_action` trong checkpoint sau khi tạo phiếu | GET → 409 `plan_changed` |
| c10 | Danh sách `mine=1` | Chỉ phiếu của tôi (+ dự phòng đủ điều kiện); `mine` thiếu → 422 |
| c11 | Duyệt không xem | `decided_without_view=true`, `view_duration` null |

### 6.3. Mutation (1 lượt)

Bỏ `IS NULL` ở nhắc (c3/c4) · nhắc sau hạn (c3) · dự phòng không cần nhắc 2 (c5) · xem phiếu không kiểm người được giao (c7) · `ApprovalView` không so hash (c9) · manager xem cũng ghi `first_viewed_at` (c7) · tin từ chối gửi thẳng không qua `effects.once` (test AST + c1).

### 6.4. Chốt khi hiện thực 4c — DỪNG 1 (01/10/2026, mốc `a88617a`; HEAD lúc verify `97cd896` = + 2 file docs M9)

Khi 6.1–6.3 hoặc 5.7 nói khác bảng này, **bảng này thắng**. Kết quả `make verify G=23` (12:28 → 12:42, cây chưa commit, `env=.env`): lint PASS (import-linter 10/10) · backend **3555** · mock 100 · ml 77 · gate2 **89/0** (B16 dùng chung node giả — không đổi) · gate3 **66/0** (chạy TRONG giờ → tc02/tc06 không qua đường duyệt; 78 khi ngoài giờ) · trả về `.env` PASS. Unit 3288 (= 3243 + 45 mới; trước code 38 đỏ đúng lý do / 7 xanh canh). Mutation **5/5**: unit M-4c-1a, M-4c-2a, M-4c-7 + SQL (`mutate_4c.py --integration`, testcontainers) M-4c-1b (bỏ `reminder_n_at IS NULL` → c4 + "đánh dấu lần 2 trả None" đỏ), M-4c-2b (bỏ `deadline > :now` → 2 ca đúng hạn/quá hạn đỏ); md5 khớp.

| # | Chỗ | Chốt |
|---|---|---|
| 1 | Q-4c-1 (sửa 5.7 #4) | `note` **không** phải khoá `TicketState` (chỉ `approval_result` là khoá state). `_POINT_COLUMNS` = **5 khoá**: `approver_id, deadline, conflict_detected, response_time_seconds, note`. `approval_result` đưa vào `audit_columns` vẫn `ValueError`. B16 che lại `note` bằng privacy guard (khuôn `clarify_wait`) **trước** `approvals.close` → phiếu, cột `audit_logs.note`, tin nhắn dùng CÙNG bản đã che (test SĐT ở graph, HTTP, PG). Output guard chặn → bỏ câu "Ghi chú…", `note_suppressed=true` |
| 2 | Q-4c-2 (sửa P3) | Truy vấn nhắc đặt trên **`SqlDeadlineStore`** (`db/runtime.py`, vốn đã đọc/ghi `approvals` cho quét hạn) + port `DeadlineStore` (`graph/ports.py`) + bản giả — vì `worker.py` chỉ truyền `runner, deadlines, turns` và Phase 4 không sửa `worker.py` (M9 đã sửa tài liệu M9 8.1/1.4 cho khớp, `97cd896`). SQL `mark_reminder_once` giữ NGUYÊN VĂN P3 cho n=1, n=2. Gửi nhắc qua MỘT hàm `log_approver_notice` dùng chung với `SqlApprovals.notify_approver` |
| 3 | P3 "đã qua m2 mà chưa nhắc 1" | Chạy câu P3 n=2 (gửi) rồi n=1 (chỉ ghi sổ, không gửi); `next_reminder` sau mốc 2 không bao giờ trả nhắc 1 → worker khác chen giữa không gửi nhắc 1 muộn |
| 4 | A11 / M9 luật 7 | `SqlDeadlineStore.mark_fired` (worker đóng phiếu timeout, nhánh 409) nay đặt `decided_at` — trước 4c thiếu. Test unit + PG. `decided_at` có ở cả 3 nhánh |
| 5 | c4 | Hai worker bị `asyncio.Barrier` ép cùng đọc phiếu trước khi đánh dấu → tranh chấp tất định, M-4c-1b luôn bị bắt |
| 6 | P1 / P2 | `close` trả số dòng (0/1) → `close_applied`. Hành động không có nhãn (vd hành động giả gate2) → câu chung, không E9. `decided_as="primary"` cố định ở DỪNG 1 (chỉ người duyệt chính quyết được tới khi có P4) → DỪNG 2 thay bằng vai trò thật |
| 7 | A12 | `approvals.created_at` theo giờ DB, `deadline` theo giờ app — chấp nhận (cùng máy); mốc nhắc theo `created_at`, hạn QUYẾT vẫn theo giờ app → không ảnh hưởng an toàn. Test PG tự đặt `created_at` |
| 8 | Test cũ đổi | `test_goto_audit_columns.py` thêm khoá `note` (Q-4c-1); `test_guard_api.py` đổi chỗ import `ReasonCode` sang `domain.messages` (kỳ vọng giữ) |

### 6.5. Chốt khi hiện thực 4c — DỪNG 2 (01/10/2026, mốc `aac90b1`)

Khi 6.1–6.4 nói khác bảng này, **bảng này thắng**. Kết quả `make verify G=23` (15:56 → 16:11, HEAD `aac90b1` + cây chưa commit, `env=.env`): lint PASS (import-linter 10/10) · backend **3637** (= 3358 unit + 279 integration/e2e, trong đó 12 PG mới), 0 skip · mock 100 · ml 77 · gate2 **89/0** · gate3 **66/0** (TRONG giờ) · trả về `.env` PASS. Test-writer 66 test mới (unit 40 đỏ đúng lý do / 14 xanh canh trước code). Mutation DỪNG 2 **5/5** (unit M-4c-3, 4, 5, 6 + SQL M-4c-3b) → **cả 4c 10/10**; md5 khớp. Security-reviewer **0 FAIL / 5 NGHI** — 3 đã sửa (S4b, S1c, R1), 1 thành Q-4c-3, 2 thành Việc treo 28, 29.

| # | Chỗ | Chốt |
|---|---|---|
| 1 | P4 | MỘT hàm `auth/authz.approval_role(p, a) -> "primary" \| "backup" \| None` (có quyền + người được giao → `primary`; dự phòng **và** `reminder_2_at` không NULL → `backup`; xung đột → None). `may_decide_as` = `approval_role(...) is not None`. Route quyết, xem phiếu, hộp thư dùng chung hàm này. Sự kiện và thân 202 mang `decided_as` (giá trị do server tính, không lấy từ body) |
| 2 | P5 (hộp thư) | Lọc vai trò bằng SQL ở `WHERE` **trước** `LIMIT 50` (không lọc sau khi đã cắt 50); lọc xung đột ở route → có thể trả < 50. `status` **không** bắt buộc (thiếu = mọi trạng thái). Lỗi `mine`/`status` → 422, kiểm **sau** bước quyền. Nối dòng audit B15 `queued` theo `ticket_id` **+** `action_plan_hash` (`LEFT JOIN LATERAL`). B15 giả (gate2) không ghi `intended_action` → `action_type`/`device_id` null |
| 3 | P6 (xem phiếu) | `ApprovalView` **12** khoá (đúng 12 tên P6 kể; "13" trong PLAN là lỗi đếm). `role_as` ∈ {`primary`, `backup`, `viewer`} (`viewer` = manager). Thứ tự: quyền trước → không được xem → **404 cùng thân với id không tồn tại** → rồi mới so hash. So `hash_action(action)` với hash của **PHIẾU** (`ApprovalRow.action_plan_hash`), không với hash trong state; không có action → 409 `plan_changed`. Phiếu đã đóng vẫn xem được, **không** ghi `first_viewed_at`. Dự phòng = người gửi → 404 (c6 mở rộng). `procedure` null khi hành động không có trong `action_metadata`; tài liệu chỉ ở bản KB cũ → chỉ `doc_id` |
| 4 | Route quyết (soát S4b) | Ghi chú từ chối **rỗng sau khi che** (vd chỉ ký tự vô hình U+200B, U+00AD) → 422 `rejected_requires_note`. B16 giữ `""` (dùng `is not None`, không đổi thành None) → không câu "Ghi chú…". Trước khi sửa: lọt `strip()` → `close` vi phạm CHECK `rejected_needs_note` → E9 |
| 5 | Id phiếu (soát S1c) | `approval_id` trên đường dẫn chỉ nhận `[0-9]{1,18}`; khác (vd `"²"`, quá BIGINT) → **404**, không chạm DB (trước: 500) |
| 6 | Test AST (soát R1) | `decided_as` **không** vào `TYPED_KEYS` (miễn trừ theo tên khoá toàn cục quá rộng). Luật hẹp `ROLE_KEYS`: chỉ nhận biến mà MỌI lần gán trước cổng là `approval_role(...)` import thẳng từ `app.auth.authz`. Self-check 5 ca |
| 7 | Q-4c-3 = A | Route **quyết** giữ **403** + `permission_denied` cho phiếu có thật nhưng không được giao (đúng c5, c6, b2/b2b, g4-06); route **xem** trả 404. Lý do: id BIGINT tăng dần nên tồn tại phiếu vốn đoán được; 403 + `permission_denied` là tín hiệu dò phiếu cho M9. → Việc treo 30 |
| 8 | Mutation thêm | **M-4c-3b** (SQL `inbox` bỏ `AND a.reminder_2_at IS NOT NULL`) → test PG lọc vai trò đỏ. Lớp IDOR ở SQL độc lập với `approval_role` (unit không giết được vì `approval_role` chặn lại) |
| 9 | Log | `_audit_action` hỏng → `log.warning` chỉ id phiếu (nội dung không vào log) |
| 10 | Việc treo mới | **28** `first_viewed_at` là MỘT cột cho cả phiếu → dự phòng mở, người chính duyệt không mở → `decided_without_view=false`; luật 7 M9 bỏ sót (cần lần xem theo người — migration, sau Phase 4; báo M9 khi xong). **29** B17 so hash với state, không với phiếu → **làm ở 4d** (7.1 P7). **30** đổi id phiếu sang UUID → thống nhất route quyết + xem về 404 |

---

## 7. Chặng 4d — Ghi đè + `audit_check` + e2e cổng 4 + `make gate4` (tầng A)

**Nghi thức (tầng A):** PLAN-4d.md · 2 DỪNG · mutation ×2 · security-reviewer.

### 7.1. P-x chốt trước

| Mã | Chốt |
|---|---|
| P1 | `POST /api/tickets/{id}/override` → **201**. Dùng `require("decision:override", recent_login=True)` — [Chốt P6 §4, P10 §3.2: ghi đè cần đăng nhập lại ≤ 10 phút]; cơ chế đã có ở `auth/deps.py` (403 `reauth_required` + `permission_denied` reason `reauth_required`, như route thu hồi phiên `api/auth.py`). Thứ tự: 413 → quyền → **reauth** → ticket không có / không đọc được → 404 → `can_override` sai (người gửi tự ghi đè) → 403 + `permission_denied` → ticket chưa kết thúc (`final_state` NULL) → 409 `ticket_open` → body sai → 422 (`invalid_request()` chung, không trả input) → guard L1 trên `note` (lỗi → 503) → ghi |
| P2 | Body `extra=forbid`: `override_decision: Literal["AUTO","HITL","L2","ANSWER"]`, `reason_code: Literal["too_risky_for_auto","approval_unnecessary","should_not_escalate","wrong_answer","policy_gap","other"]`, `note: str ≤ 1000` (bắt buộc khi `reason_code="other"`) |
| P3 | `original_decision` do server suy từ audit của ticket: có dòng `risk_decided` → `detail.route` (AUTO/HITL/L2); không có mà kết thúc qua B10 (`deflected_info_only`) → `ANSWER`; còn lại → `L2`. `override_decision == original_decision` → 422 `same_as_original` |
| P4 | Ghi **1** dòng `audit_logs`: `step="OVERRIDE"`, `event="override_recorded"`, `from_status/to_status` NULL, cột `original_decision`, `override_decision`, `overrider_id` (ghi **thẳng** bằng `AuditWriter` — không qua `goto`/`audit_columns`, vì `_POINT_COLUMNS` 4b chỉ có 4 khoá điểm 5–6; 5.7 #4), `note` (đã che), `detail={reason_code}`; `idempotency_key = sha256("override:" + ticket_id + ":" + overrider_id)` → người đó ghi lần 2 → **409 `already_overridden`** (đúng 1 dòng). **Không** đổi `tickets`, không checkpoint, không `start_event`, không executor |
| P5 | `scripts/audit_check.py` (+ `make audit-check ARGS=…`): đầu vào danh sách `ticket_id` hoặc `--since <ISO>`; mỗi ticket → xác định điểm log áp dụng theo event có mặt (bảng 7.2) → kiểm cột/khoá bắt buộc; quét **mọi** cột text/jsonb của `audit_logs` (+ file log nếu `--log`) bằng luật `secret` của `config/privacy_patterns.json` + danh sách canary (`--canary`) → 0 kết quả. In bảng `ticket | điểm thiếu | trường thiếu`, thoát 1 khi có lỗi. Chỉ đọc (role `app_ro` nếu có, không thì `app_rw` chỉ SELECT) |
| P6 | `make gate4` (khuôn gate3, chốt an toàn: `APP_ENV=dev`, URL 127.0.0.1, `LLM_BACKEND=scripted`, `FAKE_SCENARIO` không đặt, **`APPROVAL_SLA_MINUTES_DEV=2`** phải đặt — kiểm CÓ/KHÔNG). `make verify G=4` tạo lại backend+worker với `FAKE_SCENARIO= APPROVAL_SLA_MINUTES_DEV=2` rồi trả về `.env` như 4a |
| P7 | **Việc treo 29 (từ 6.5 #10):** B17 so thêm `hash_action(action)` với `approvals.action_plan_hash` (`ApprovalRow` đã có trường, B17 đã đọc `row`) — lệch → E5 `action_plan_changed_since_approval`, 0 lời gọi ghi. Test cùng i8 (đổi hash phiếu bằng SQL) + mutation "B17 bỏ so hash phiếu" |

### 7.2. Điểm log áp dụng (cho `audit_check`)

| Điểm | Áp dụng khi ticket có event | Cột / khoá bắt buộc |
|---|---|---|
| 1 | B3 `intent_classified` hoặc B4 (E1) | `intent` (trừ E1 oos), `confidence`, detail `layer`, `dropped_slot_keys` |
| 2 | B6 `diagnosed` / B7 | detail `tools_called`, `tool_retry_count`, `facts` |
| 3 | B8 / B9 | `query`, detail `top_score`, `kb_version` (trừ lỗi alias) |
| 4 | `risk_decided` | `decided_by`, `policy_decision`, `risk_level`, `reason`, detail `route`, `policy_sha256` |
| 5 | B15 `queued` | `approver_id`, `deadline`, `conflict_detected`, `action_plan_hash`, detail `choice_reason` |
| 6 | B16 (approved/rejected/timeout) | `approval_result`, detail `decided_without_view`; `note` khi rejected; `response_time_seconds` trừ timeout |
| 7 | B17 | `success`, `action_plan_hash_matched` (khi qua duyệt), detail `write_calls` |
| 8 | ticket đã kết thúc | dòng B20 có `final_state`, `close_reason` hoặc `exit_code` |

### 7.3. E2E cổng 4 (`backend/tests/e2e/test_gate4_hitl.py`)

| # | Kịch bản | Đạt khi |
|---|---|---|
| i1 | TC07-vpn: nv003 renew LAP-0501 → `l1_01` duyệt | renew đúng 1 lời gọi; `S_CONFIRMING` → xác nhận → `S_RESOLVED`; điểm 1–8 đủ (audit_check) |
| i2 | TC08-vpn: từ chối có note | `S_REJECTED`, `rejected_by_approver`, tin `rejection`, 0 lời gọi ghi |
| i3 | Từ chối không note | 422, phiếu vẫn `pending` |
| i4 | TC09: nv002 PC-0977 → duyệt | E7 `exec_failed`, handoff 4 phần "máy chưa đăng ký — L2 đăng ký máy" |
| i5 | Bảng 3.2 x1–x9, x14 | như bảng |
| i6 | TC20 (FakeClock +31 phút) | E6, 0 lời gọi ghi, phiếu `timeout` |
| i7 | TC27: bấm sau hạn, trước chu kỳ quét | 409 + 1 `late_event`; phiếu vẫn `pending` → worker quét → E6 |
| i8 | TC26: đổi `intended_action` sau khi duyệt (hook trước B17) | E5 `action_plan_changed_since_approval`, 0 lời gọi ghi |
| i9 | Tranh chấp: 2 người (người duyệt + dự phòng sau nhắc 2) bấm đồng thời | đúng 1 lần thực thi; người sau 409 |
| i10 | Luật deny (policy fixture) | 0 phiếu, E5 `is_deny_case` |
| i11 | L2 gọi quyết định / xem phiếu | 403 / 403 |
| i12 | Nhắc 50/80% (FakeClock) + dự phòng quyết | như c3, c5 |
| i13 | TC23: ghi đè ticket i1 bởi `l1_02` (`AUTO`→… hoặc `HITL`→`L2`) | 201, 1 dòng OVERRIDE; `tickets` không đổi (so trước/sau); lần 2 → 409 |
| i14 | Ghi đè: người gửi tự ghi đè / ticket đang mở / `same_as_original` / note có mật khẩu | 403 / 409 / 422 / note đã che |
| i14b | Ghi đè khi lần đăng nhập gần nhất > 10 phút (FakeClock) | 403 `reauth_required`, 0 dòng `OVERRIDE`, 1 `permission_denied` reason `reauth_required`; đăng nhập lại → 201 |
| i15 | TC33: giết sau `approval_create` → recover | 1 phiếu, 1 `notify_approver` |
| i16 | Canary chạy hết i1 + i2 + i13 với mật khẩu trong câu và trong note | như e9 (0 lần) |
| i17 | `audit_check` trên mọi ticket của file | 0 thiếu, 0 bí mật |

### 7.4. `make gate4` — kịch bản (người không làm chính chạy)

`g4-01` duyệt (i1) · `g4-02` từ chối + từ chối thiếu note (i2, i3) · `g4-03` hết hạn 2 phút: nhắc 1 (~60 s), nhắc 2 (~96 s), E6, 0 ghi · `g4-04` dự phòng `l1_02` quyết sau nhắc 2 · `g4-05` bấm muộn → 409 · `g4-06` TC19 `l1_01` PC-0124 → `it_mgr01`; `l1_01` quyết → 403 · `g4-07` `l1_lead` LAP-0700 → `it_mgr01` · `g4-08` `it_mgr01` LAP-0900 → E5, 0 phiếu · `g4-09` L2 quyết/xem → 403; L1 khác xem → 404 · `g4-10` xem lần đầu ghi `first_viewed_at` · `g4-11` ghi đè + lần 2 409 · `g4-12` `audit_check --since <giờ bắt đầu>` 0 lỗi. In bảng PASS/FAIL + biên bản `backend/tests/stack/bienban-gate4-<ngày>.md` (người chạy điền tên, máy, commit).

### 7.5. Mutation bắt buộc

Ghi đè đổi `tickets.final_state` (i13) · bỏ `recent_login=True` ở route ghi đè (i14b) · ghi đè lưu note chưa che (i14) · ghi đè cho ticket đang mở (i14) · bỏ idempotency ghi đè (i13) · timeout → `S_EXECUTING` (i6) · bấm muộn đổi status phiếu (i7) · `audit_check` bỏ quét bí mật (i16 cài canary thẳng vào `audit_logs.detail` bằng SQL → phải đỏ) · `audit_check` bỏ điểm 5 (i17 với dòng B15 thiếu `approver_id` giả lập).

### 7.6. DỪNG

- **DỪNG 1:** ghi đè (P1–P4) + `audit_check` (P5) + B17 so hash phiếu (P7) + i13, i14, i17, i8. `make verify G=23`.
- **DỪNG 2:** e2e còn lại + `make gate4` + mutation ×2 + security-reviewer + "spec cần sửa (4d)". `make verify G=234` rồi **thành viên** chạy `make gate4 S=all`.

### 7.7. Chốt khi hiện thực 4d — DỪNG 1 (02/10/2026, mốc code `b74da3f`; HEAD lúc verify `475fd1e` = + docs M9)

Khi 7.1–7.6 nói khác bảng này, **bảng này thắng**. Sandbox: lint PASS (import-linter 10/10) · unit **3621** (= 3358 + 262 mới + 1 ghim route). Test-writer: 8 file mới (unit 262, PG 17, e2e 8) — trước code **241 đỏ / 21 xanh** (xanh = kiểm đã có trước 4d: 413, 403 tầng quyền, 403 `reauth_required`, h2/h3). `make verify G=23` lượt 2 (14:46 → 15:04, cây chưa commit): lint PASS · backend **3927** (3621 unit + 306 integration/e2e) · mock 100 · ml 77 · gate2 **89/0** · gate3 **55/9** — cả 9 FAIL là tc02, do **rerank nguội** (dòng 9), không phải 4d · trả về `.env` PASS. Gate3 đầy đủ lấy ở lượt verify sau khi gộp M9 (ghi ở PROGRESS và mục chốt DỪNG 2). Mutation lượt 1 **14/14** (11 unit + 3 PG: M-4d-1, 8, 9); md5 khớp.

| # | Chỗ | Chốt |
|---|---|---|
| 1 | Q-4d-1 = A (sửa 7.2) | `audit_check` kiểm **đúng chỗ code ghi** — bảng điểm dưới thay bảng 7.2. Bốn cột `audit_logs.confidence`, `query`, `success`, `action_plan_hash_matched` có trong schema nhưng **chưa từng được ghi** (dữ liệu ở `detail`); KHÔNG sửa B3/B8/B17 → **Việc treo 31** (sau Phase 4: ghi cột hay bỏ cột; truy vấn đánh giá đọc `detail`) |
| 2 | Q-4d-2 = A (sửa P4) | `Desk` dựng ở `main.py` (M9 — không sửa) không có `AuditWriter` → `decision_trail` + `record_override` đặt trên `ApprovalRepo`/`SqlApprovals` (tiền lệ: hộp thư 4c đọc `audit_logs`). Ghi qua `AuditWriter.record_new` = `INSERT … ON CONFLICT DO NOTHING RETURNING` trên cùng partial index `idempotency_key` → True chỉ khi vừa ghi dòng mới; 409 `already_overridden` quyết bằng kết quả INSERT (không kiểm trước, không khe đua). Tên port lệch nghĩa — tách riêng khi được sửa `main.py` |
| 3 | P1 (thứ tự thật) | 413 → quyền → reauth (403 `reauth_required`) → 404 → người gửi tự ghi đè 403 + `permission_denied` reason `self_override` → `final_state` NULL 409 `ticket_open` → body 422 (`invalid_request`, `fields: ["note"]` — tên trường KHÔNG có tiền tố `body.`) → 422 `same_as_original` (**trước** guard: yêu cầu chắc chắn bị từ chối thì không gửi note qua guard) → guard (503; có bí mật → `privacy_secret_redacted`, kể cả lần bấm thứ 2) → `other` mà note rỗng sau khi che 422 → ghi → 409 `already_overridden`. Thân 201: `ticket_id, original_decision, override_decision, reason_code, notices` |
| 4 | P3 | `detail.route` thật là `AUTO \| HITL \| ESCALATE_L2` → `ESCALATE_L2` ánh xạ `L2`. Dòng `risk_decided` MỚI NHẤT theo `log_id`. Thiếu `detail.route` (node giả B12 của gate2) → suy từ cột `policy_decision` (`allow→AUTO`, `approval_required→HITL`, khác → `L2`). Không có `risk_decided` mà có `B10/deflected_info_only` → `ANSWER`; còn lại → `L2` |
| 5 | P4 | Dòng OVERRIDE: `turn_id` NULL, `created_at` = Clock app, `note` che xong rỗng (không phải `other`) → NULL. Khoá theo (ticket, người) → hai người khác nhau ghi đè cùng ticket = hai dòng |
| 6 | P5 | Lõi ở `backend/app/audit/check.py` (có trong image; `python -m app.audit.check`); `scripts/audit_check.py` là vỏ mỏng; `make audit-check ARGS=…` chạy **trong container** (máy không đọc `.env`). Role: `MONITOR_DATABASE_URL` (app_monitor) nếu đặt, không thì app_rw — **cả hai** ép READ ONLY theo phiên (`default_transaction_read_only=on`), test PG chứng minh INSERT bị từ chối ở cả hai đường. In nhãn role, không in DSN, không bao giờ in giá trị trúng. Quét chỉ luật `kind="secret"` (không `entropy` — hash hex sẽ trúng); trúng mà nhóm `v` bắt đầu bằng mặt nạ `secret_mask` = đã che → bỏ qua (**sửa ở 7.8 #6**: chỉ bỏ qua khi sau mặt nạ không còn chữ/số). "(có khoá)" chấp nhận None; 0/False không coi là thiếu; một dòng thiếu nhiều trường = một `Missing` |
| 7 | P7 | B17 lớp 2 ngay sau `approvals.get`, trước mọi lời tra AD: `hash_action(action) != approvals.action_plan_hash` → E5 `action_plan_changed_since_approval`, `detail.hash_source="approval"`, 0 lời gọi ghi. Lớp 1 (so với state) giữ nguyên, không có `hash_source`. Không test B17 cũ nào phải đổi (`MemoryApprovals.create` vốn lưu hash) |
| 8 | TC26 / Q-4d-3 | Giả định "B17 là nơi DUY NHẤT so hash" **sai**: đổi `intended_action` lúc phiếu còn chờ → cấm `F3_plan_hash_mismatch` (`domain/states.py`) chặn `S_PENDING_APPROVAL → S_EXECUTING` ngay ở `goto` của B16 → `IllegalTransition` → **E9**, 0 lời gọi ghi (an toàn, nhưng sai mã so với TC26). Test: **i8a** = chết sau checkpoint B16 rồi recover → B17 lớp 1 → E5; **i8b** = đổi hash phiếu bằng SQL → lớp 2 → E5; **i8c** = đổi lúc chờ → hiện E9. **Q-4d-3 (chốt, làm ở đầu DỪNG 2):** B16 khi `approved` tự so hash (state + phiếu) TRƯỚC `goto(S_EXECUTING)`; lệch → `S_ESCALATED` step `B16` E5 `action_plan_changed_since_approval` + `hash_source`, `hash_old`, `hash_new`; cấm F3 giữ làm lớp cuối; i8c đổi kỳ vọng sang E5 |
| 9 | gate3 / rerank nguội | tc02 (kịch bản ĐẦU của gate3) → `B8 retrieval_error` E2 `rag_system_error`, `error_stage=rerank`, `deadline`, retry 0, giây 49,4 — lời gọi rerank đầu tiên sau khi ml-service rảnh lâu. KHÔNG nới `TIMEOUT_S["rerank"]` / `rag_deadline_s`. DỪNG 2 thêm bước **làm nóng rerank** vào preflight của `gate3.py` và `gate4.py` (một truy vấn bỏ đi, không tính PASS/FAIL). **Việc treo 32:** ml-service tự làm nóng khi khởi động (liên hệ Việc treo 4) |
| 10 | i17 | Danh sách ticket cấp module, i17 đặt cuối file; chạy riêng (danh sách rỗng) → `pytest.fail` rõ lý do, không xanh giả. Lời gọi ghi trong e2e = mọi POST tới mock trừ `/ad/authenticate`, `/_admin` |
| 11 | Mutation thêm | M-4d-11 (bỏ `same_as_original`), 12 (bỏ `can_override`), 13 (`render` in giá trị trúng), 14 (`ESCALATE_L2` không đổi sang `L2`). M-4d-6, 7 chạy ở lượt 2 |
| 12 | M9 | `origin/dev-tuananh` tiến tới `1d5c92a` (PR #20, #22: `app/monitor/*`, `test_monitor_*`, `monitor_seed.py`, migration `0008_monitor_views` trỏ `0007`) — không trùng file 4d. Commit DỪNG 1 rồi `git pull --rebase`, `alembic heads` = 1, verify một lần trên cây đã gộp rồi mới push |

**Bảng điểm `audit_check` (thay 7.2)** — điểm áp dụng theo dòng có mặt trong ticket:

| Điểm | Dòng áp dụng | Bắt buộc |
|---|---|---|
| 1 | `B3/intent_classified`; mọi dòng `step=B4` | `detail.layer`, `detail.dropped_slot_keys` (có khoá); `detail.intent`, `detail.confidence` khác null trừ `intent_out_of_scope`, `multi_intent_not_enabled`; `intent_classified` thêm cột `intent` |
| 2 | `B6/diagnosed`; mọi dòng `step=B7` | `detail.tools_called`, `detail.facts` (có khoá); `detail.tool_retry_count` khác null |
| 3 | `B8/retrieved`, `B8/retrieval_error`; `B9/no_evidence` | B8: `detail.query`; `retrieved` thêm `detail.top_score`, cột `kb_version`; `retrieval_error` thêm `kb_version` trừ `detail.error_stage="alias"`. B9: cột `kb_version`, `detail.grounding.top_score` (có khoá) |
| 4 | `B13/B14/risk_decided` | cột `decided_by`, `policy_decision`, `risk_level`, `reason`; `detail.route`, `detail.policy_sha256` |
| 5 | `B15/queued` | cột `approver_id`, `deadline`, `conflict_detected`, `action_plan_hash`; `detail.choice_reason` |
| 6 | `B16/approved`, `B16/rejected`, `B16/approval_timeout` | cột `approval_result`; `detail.decided_without_view` (có khoá); approved/rejected: cột `response_time_seconds`, `detail.decided_as`; rejected: cột `note` |
| 7 | `B18/executed_ok`, `B17/exec_failed`, `B17/exec_interrupted` | `detail.success` (có khoá), `detail.write_calls`; ticket có `B16/approved` (trừ `detail.stage="txlog_before_recheck"`): `detail.action_plan_hash_matched` |
| 8 | `tickets.final_state` có | ≥ 1 dòng `B20/closed` có cột `final_state` và (`close_reason` hoặc `exit_code`) |

### 7.8. Chốt khi hiện thực 4d — DỪNG 2 (03/10/2026; verify trên `fe51980` + cây DỪNG 2; commit trên `67cd5f9` = + PR #26 của M9)

Khi 7.1–7.7 nói khác bảng này, **bảng này thắng**. Sandbox: lint PASS (import-linter 10/10) · unit **3835** (sau gộp PR #26: **3864** = + 29 test M9). `make verify G=234` lượt 2 (02/10 22:39 → 23:01): lint PASS · backend **4181** · mock 100 · ml 77 · gate2 **89/0** · gate3 **78/0** (ngoài giờ, có làm nóng rerank) · gate4 72/1 — FAIL duy nhất là g4-12 (dòng 10, lỗi của script cổng, không phải của hệ thống). `make verify G=4` (23:39 → 23:51) sau khi sửa g4-12: backend **4186** · **gate4 73/0** (làm nóng: embed 525 ms, rerank 1594 ms; `audit_check` trên 9 ticket của lần chạy: 0 thiếu, 0 bí mật; quét log 0 trúng). Gate3 đầy đủ trên cây gộp M9 #20/#22 mà 7.7 hẹn: **66/0** (02/10 17:11, trong giờ). Mutation lượt 2: unit **16/16** (+ 4 mã `audit/check.py` chạy lại sau Q-4d-8) · tích hợp **8/8** (PG M-4d-1, 8, 9; e2e M-4d-6, 7, 10, 15, 16); md5 khớp. Security-reviewer (mốc diff `1d5c92a`, Q-4d-5): 1 FAIL thấp + 2 NGHI, đã sửa (dòng 15). Lint + test trên cây đã gộp PR #26 (`make verify G=0`) chạy trước commit — số ghi ở PROGRESS.

| # | Chỗ | Chốt |
|---|---|---|
| 1 | Q-4d-3 hiện thực (TQ-14) | B16 nhánh `approved`, **sau** `close` (phiếu vẫn `approved`, có `decided_by`, `decided_at` — người duyệt đã quyết thật) và **trước** `goto(S_EXECUTING)`, gọi `_plan_mismatch`: **lớp state** = đúng phép so của cấm F3 (`hash_action(intended_action)` so `state.action_plan_hash`; thiếu hash → lệch, `hash_old` null) rồi **lớp phiếu** (`approvals.action_plan_hash`; không có phiếu → bỏ lớp); cả hai lệch → ghi `state`. Lệch → `S_ESCALATED`, step `B16`, event `action_plan_changed_since_approval`, **E5**, `approval_result="approved"`, `escalation_reason_detail` cùng tên; `detail` = 5 khoá điểm log 6 + `hash_source`, `hash_old`, `hash_new`, `action_plan_hash_matched=false`. B16 không gửi tin; B20 gửi mẫu E5. Thiếu `intended_action` → không so, cấm F3 chặn → **E9** (lớp cuối, giữ nguyên). 0 lời gọi ghi ở mọi nhánh |
| 2 | Bảng điểm `audit_check` | Điểm 6 thêm dòng áp dụng `B16/action_plan_changed_since_approval` (bảng dưới). Không ghi dòng này vào điểm 6 thì lần duyệt đó mất dấu vết người duyệt (M-4d-17 ghim) |
| 3 | 7.3 i8 tách bốn ca | **i8a** đổi hành động SAU duyệt (chết đầu B17 rồi recover) → B17 lớp 1 → E5 · **i8b** đổi hash phiếu lúc chờ → B16 lớp phiếu → E5 (trước Q-4d-3 là B17 lớp 2) · **i8c** đổi hành động lúc chờ → B16 lớp state → E5 (trước là F3 → E9) · **i8d** đổi hash phiếu SAU checkpoint B16 (chết đầu B17 rồi recover) → B17 lớp 2 → E5. Bốn ca đều 0 lời gọi ghi |
| 4 | 7.3 i5 | x5, x6 dùng e2e cổng 3 có sẵn (`test_h11_at_20h_…`, `test_h14_g01_…`); x14 = i15; x7/x8 khoá người duyệt trên mock SAU khi `ha.lt` đăng nhập; x9 bơm 500 đúng `GET /ad/users/l1_01`; **x4** đăng nhập manager bằng `gate4_env.login_manager` (ghi danh MFA trong tiến trình test qua `app.state.auth`, OTP theo FakeClock — không nới auth) |
| 5 | Luật viết e2e cổng 4 | DB dùng chung cả module → kiểm theo **ticket/phiếu của test**, không đếm toàn cục (`scan_deadlines().delivered`; `permission_denied` so phần tăng thêm). Test nhắc dùng FakeClock phải đặt lại `approvals.created_at` bằng giờ app (mốc nhắc tính từ giờ DB — 6.4 #7). `late_event` của người bấm sau mang `step="B16"` (`graph/late_event.py`) → tập event ở B16 = {`approved`, `late_event`} |
| 6 | Q-4d-8 = B (**sửa 7.7 #6**) | `_masked`: chỉ bỏ qua khi nhóm `v` = mặt nạ `secret_mask` + **chỉ** dấu câu/khoảng trắng. Sau mặt nạ còn chữ/số (ví dụ mặt nạ dính liền `abc123` — đường lách guard) → **tính là trúng**. Lý do: bỏ qua mọi chuỗi "bắt đầu bằng mặt nạ" là False Negative của công cụ soát |
| 7 | Q-4d-6 = C, Q-4d-7 | Không sửa trong 4d. **Việc treo 33:** lỗi DB lúc INSERT ghi đè có thể đưa tham số câu lệnh (gồm `note` ĐÃ CHE) vào log → `hide_parameters` toàn hệ thống, sau Phase 4, phối hợp M9 (`db/session.py` có khối M9). **Việc treo 34:** luật `entropy` của privacy guard bỏ qua token có chứa mặt nạ (lõi 3e) → soát lại bộ test e* của 3e |
| 8 | Q-4d-9 = B (**sửa 7.4**) | `make gate4` **không** đăng nhập manager: Trưởng BP bắt buộc MFA, script cổng không giữ OTP và không ghi danh MFA trên stack (sẽ ghi đè OTP của chủ máy). **g4-08 bỏ khỏi `S=all`**; ca x4 phủ ở e2e `i5_x4` + unit bảng 3.2. Preflight đăng nhập 5 người (`chau.hm`, `ha.lt`, `duc.pv`, `khoa.dv`, `long.nh`); `it_mgr01` chỉ là người được giao. Preset `g4_0900.yaml` bỏ; còn `config/scripted/g4_{0501,0124,0700}.yaml` |
| 9 | Thứ tự `S=all` | preflight → g4-01 → g4-11 → g4-02 → g4-06 → g4-07 → g4-09 → g4-10 → g4-04 → g4-03 → g4-05 → g4-12. Chốt an toàn: `APPROVAL_SLA_MINUTES_DEV=2` kiểm ở **cả** backend và worker (`=2 \| =0 \| =khac`, không in giá trị khác), `FAKE_SCENARIO` không đặt |
| 10 | Q-4d-10 = A (**sửa 7.4 g4-12**) | g4-12 chạy `audit_check` trên **đúng danh sách ticket lần chạy đã tạo** (truyền id), không `--since`; mã ≠ 0 → in nguyên bảng (không có giá trị); danh sách rỗng (chạy lẻ `S=g4-12`) → FAIL rõ lý do. Quét log `compose logs --since <giờ bắt đầu>` giữ nguyên. Công cụ `audit_check` không đổi. Lý do: `--since` chọn ticket theo HOẠT ĐỘNG (có dòng audit mới) rồi soát toàn bộ dòng → trên stack dùng chung kéo theo ticket node giả của gate2 và ticket cũ (worker đóng hạn làm chúng có dòng mới). README ghi chú điều này cho `make audit-check ARGS="--since …"` |
| 11 | TQ-15 làm nóng rerank (7.7 #9) | `gate3.py::warm_rerank` (gate4 dùng lại): `compose exec -T backend python -c …` gọi thẳng ml-service (`/embed` 1 câu + `/rerank` 10 đoạn, timeout 120 s); một lần mỗi lần chạy gate3/gate4, sau chốt an toàn, trước kịch bản đầu (kể cả `S` lẻ); 0 ghi DB; chỉ in `embed_ms`/`rerank_ms` hoặc `warm_error=<tên lớp>`; không tính PASS/FAIL. Không nới `TIMEOUT_S["rerank"]` / `rag_deadline_s` (Việc treo 32 giữ) |
| 12 | TQ-16 g4-05 | Trên stack có worker thật nên không ghim được "phiếu vẫn `pending` sau bấm muộn" (worker có thể quét trước). g4-05 kiểm bất biến: 409 + đúng 1 `late_event` (`expired` \| `already_decided`) → E6, phiếu `timeout`, 0 ghi. Ca "vẫn `pending`" ghim ở e2e i7 + unit `test_late_click_before_scan` + M-4d-7 |
| 13 | TQ-17 biên bản | Chỉ sinh khi `S=all`: `backend/tests/stack/bienban-gate4-<ngày>.md`; người chạy/máy/chữ ký để trống cho người chạy điền; mẫu `bienban-gate4-MAU.md` (commit). Biên bản đã điền của máy Tuấn Anh **không** commit — biên bản chính thức là của người không làm chính (mục 8) |
| 14 | 4.4 `make verify` | `G=234` (và `G=4`): `recreate <FAKE_SCENARIO> <FAKE_NODE_DELAY> <SLA>` — gate2/gate3 SLA rỗng, gate4 `2`; ingest KB một lần trước cổng đầu cần (3 \| 4); gate4 = bước 10; bước 8 trả stack về `.env` gỡ cả `APPROVAL_SLA_MINUTES_DEV`, có trap HUP. **Q-4d-4:** macOS tự bọc `caffeinate -i -w $$` + cảnh báo khi chạy pin (lượt 02/10 16:02 đỏ tc04 vì Mac ngủ 418 s — hạn lượt theo đồng hồ tường hết → E2 `turn_budget_exceeded`; không phải lỗi code) |
| 15 | Mutation + soát bảo mật | Thêm M-4d-15 (B16 bỏ so hash), 16 (B16 bỏ lớp phiếu), 17 (`audit_check` bỏ dòng B16 E5 khỏi điểm 6). M-4d-6 = `goto` nhánh timeout của B16 → `S_EXECUTING`; M-4d-7 = route quyết `close(timeout)` ở nhánh bấm muộn; M-4d-10 (B17 lớp 2) nay do **i8d** bắt. Soát bảo mật: `make audit-check` in lại `--canary` → thêm `@`; verify.sh trap HUP; g4-12 in đuôi log → chỉ in nhãn; thêm test q8 |
| 16 | M9 | PR #26 (A2) gộp bằng `git pull --ff-only` trước commit: 10 file `app/monitor/*`, `test_monitor_dash_*`, `monitor_seed.py`; không migration (`alembic heads` = 1, `0008`); không trùng file 4d. `override_count` của M9 import `OVERRIDE_STEP`, `OVERRIDE_EVENT` từ `app/domain/override.py` → **hai hằng này là hợp đồng với M9**, đổi phải báo trước. Luật 7 của M9: lần duyệt mà kế hoạch bị đổi nằm ở `B16/action_plan_changed_since_approval` với `approval_result="approved"` → lọc theo `approval_result`, không theo `event` |
| 17 | 7.6 thành viên | `backend/tests/stack/README.md` mục đầu: thứ tự gate3 (chưa đặt SLA) → thêm `APPROVAL_SLA_MINUTES_DEV=2` + `make up` → gate4; chạy `S=preflight` trước mỗi cổng; cắm sạc, mở nắp |

**Bảng điểm `audit_check` — dòng 6 (thay dòng 6 ở 7.7; các dòng khác giữ):**

| Điểm | Dòng áp dụng | Bắt buộc |
|---|---|---|
| 6 | `B16/approved`, `B16/rejected`, `B16/approval_timeout`, `B16/action_plan_changed_since_approval` | cột `approval_result`; `detail.decided_without_view` (có khoá); approved/rejected/`action_plan_changed_since_approval`: cột `response_time_seconds`, `detail.decided_as`; rejected: cột `note`; `action_plan_changed_since_approval` thêm `detail.hash_source`, `detail.action_plan_hash_matched` khác null |

**`make gate4` — kịch bản (thay 7.4):** `g4-01` duyệt · `g4-11` ghi đè + lần 2 409 · `g4-02` từ chối + từ chối thiếu note · `g4-06` TC19 `l1_01` PC-0124 → `it_mgr01`; `l1_01` quyết → 403 · `g4-07` `l1_lead` LAP-0700 → `it_mgr01` · `g4-09` L2 quyết/xem → 403; L1 khác xem → 404 · `g4-10` xem lần đầu ghi `first_viewed_at` · `g4-04` dự phòng `l1_02` quyết sau nhắc 2 · `g4-03` hết hạn 2 phút: nhắc 1, nhắc 2, E6, 0 ghi · `g4-05` bấm muộn → 409 (dòng 12) · `g4-12` `audit_check` trên ticket của lần chạy + quét log (dòng 10). `g4-08` không có trên stack (dòng 8).

### 7.9. Nghiệm thu cổng 3 + cổng 4 bởi người không làm chính (03/10/2026, commit `1455b55`)

Người chạy: **Tạ Duy Anh**, máy riêng MSI Thin GF63 (Intel Core i5-12450H, RAM 16 GB, Docker/WSL được cấp 7,6 GB), Windows + WSL 2 Ubuntu, thứ Bảy (ngoài giờ), commit `1455b55` (0 tệp đã theo dõi đang sửa) = 4d DỪNG 2 `858573d` + docs `567237a` + PR #24 của M9. Biên bản đã ký của cả hai lượt lưu ở Project: `claude/bien-ban-cong-3-4-duy-anh-20261003.md` (bản đã điền không commit vào repo — TQ-17).

| Việc | Kết quả | Ghi chú |
|---|---|---|
| `make gate3 S=all` | **78 PASS, 0 FAIL** | 78 kiểm = nhánh ngoài giờ (R18 → duyệt → gia hạn). **Trả NỢ-3-1** của Phase 3 |
| `make gate4 S=all` lượt 1 (run `83026cac`, 12:11 → 12:17) | 60 PASS, **4 FAIL** | Mười kịch bản đầu và g4-12 xanh. g4-03, g4-05 mỗi cái 2 FAIL: ticket ra `B8/retrieval_error` **E2** (`error_stage=rerank`, 50 s sau B6; log backend `ml:embed` 3467 ms rồi hết giờ 3 lần) → không có phiếu duyệt → kiểm "chờ duyệt" FAIL + kịch bản dừng giữa chừng (`cần đúng 1 phiếu, thấy 0`), 9 kiểm bị bỏ |
| `make gate4 S=all` lượt 2 (run `6bf9628f`, 15:42:58 → 15:51:18) | **73 PASS, 0 FAIL** — ĐẠT | Sau khi tắt việc nặng khác và `make up`. preflight 5 · g4-01 11 · g4-11 4 · g4-02 7 · g4-06 4 · g4-07 3 · g4-09 5 · g4-10 12 · g4-04 7 · g4-03 7 · g4-05 6 · g4-12 2. Khớp số máy Tuấn Anh (lượt 01:06, cùng commit) |

**Đọc kết quả lượt 1.** Hệ thống xử lý an toàn: tra cứu KB lỗi → E2 → chuyển L2, không tạo phiếu, 0 lời gọi ghi — không phải False Negative. Cổng đỏ vì điều kiện của kịch bản không đạt (cần ticket tới `S_PENDING_APPROVAL`), cùng dấu vết với "rerank nguội" (7.7 #9, Việc treo 32). Nguyên nhân [Suy luận]: người chạy xác nhận máy đang chạy việc nặng khác, Docker 7,6 GB đã dùng swap; làm nóng ở preflight không đủ khi máy bị tranh CPU giữa lượt. Không sửa code, không nới `TIMEOUT_S` / `rag_deadline_s`.

**Việc treo 35 (mở 03/10/2026).** Sau lượt 1, người chạy thấy container `worker` chiếm khoảng 98% CPU khi không còn test (Postgres 0%), log im từ 05:15:31 tới 05:22:16 UTC — trùng lúc g4-03 bắt đầu. Chưa giải thích được. Đã loại: (a) "`monitor_rules_minute` chỉ in một lần" là đúng thiết kế (lượt đầu INFO, sau DEBUG); (b) worker máy Tuấn Anh lúc rảnh 0,75% CPU (cùng commit) — nhưng trên máy Tuấn Anh `make verify` luôn tạo lại worker sau gate4 nên chưa loại được "kẹt sau một lượt gate4". Cần: `docker stats` ngay sau một lượt gate4 chạy trực tiếp (không qua `verify`) + log worker + số lượt `turns` chưa kết thúc. Ảnh hưởng nếu là lỗi thật: tra cứu KB chậm (E2 thừa) và quét hạn duyệt trễ; không mở đường thực thi sai (bấm muộn vẫn bị route chặn 409).

**Bài học dựng máy thành viên** (đưa vào `backend/tests/stack/README.md` ở commit đóng): (1) "Bước 0 — tạo `.env`" từ `.env.example`, tự sinh 6 bí mật (`JWT_SIGNING_KEY`, `MFA_ENC_KEY`, `SVC_AGENT_TOKEN`, `SVC_EXECUTOR_TOKEN`, `SVC_WORKER_TOKEN`, `ML_SERVICE_TOKEN`), tắt `FAKE_SCENARIO`/`FAKE_NODE_DELAY`; không dùng chung `.env`. (2) Máy có `.env` cũ + volume Postgres cũ → `password authentication failed for user "app_migrate"` (script khởi tạo role chỉ chạy khi volume trống) → hỏi người làm chính rồi xoá đích danh `servicedesk_pgdata`, `servicedesk_qdrant` (không `down -v`, không `prune`). (3) Cổng 4: **sửa** dòng có sẵn `APPROVAL_SLA_MINUTES_DEV=` thành `=2`, không thêm dòng thứ hai. (4) Không chạy việc nặng khác trong lúc chạy cổng.

---

## 8. Lịch và thứ tự

| Chặng | Ước lượng agent | Phụ thuộc | Người khác |
|---|---|---|---|
| 4a ✓ | S0 `5ed423d` + DỪNG 2 `f64fd86` (CI 36726470829 xanh) | Phase 3 đóng `5d0a990` ✓; Q-4-U chốt ✓ | — |
| 4b ✓ | DỪNG 1 `cd3f094` (CI 36750953436) + DỪNG 2 `3b9d745` (CI 36783587264) | 4a | — |
| 4c ✓ | DỪNG 1 `aac90b1` (CI 36823466624) + DỪNG 2 `b457e6e` (CI 36885395186) | 4b | — |
| 4d ✓ | DỪNG 1 `e510a6e` (+ `fe51980`, CI 36995043374) mục 7.7 · DỪNG 2 `858573d` (+ docs `567237a`, CI 37040959717) mục 7.8 · cây gộp PR #24 `1455b55` (CI 37041941104; máy Tuấn Anh: backend 4344, gate3 78/0, gate4 73/0) | 4c | **Duy Anh ✓** 03/10 trên `1455b55`: gate3 78/0, gate4 73/0 (lượt 2), đã ký — mục 7.9 (NỢ-3-1 đã trả) |

Cổng 4 đạt khi: `make lint`, `make test` xanh; CI xanh; e2e i1–i17; mutation 4b/4d ×2, 4c ×1 đủ; `make gate4 S=all` 0 FAIL do người không làm chính chạy; spec "Chốt khi hiện thực 4a–4d"; `decisions.md` §1.1 (R17–R19 thêm chủ máy) + §4.1 (Q-4-A…T).

**Cổng 4 ĐẠT (03/10/2026):** mọi điều kiện trên đã thoả — lint, test, CI xanh trên `1455b55`; e2e i1–i17; mutation 4b/4d ×2, 4c ×1; `make gate4 S=all` 0 FAIL do Tạ Duy Anh chạy (mục 7.9); mục "Chốt khi hiện thực" 4a–4d; `decisions.md` §1.1 + §4.1. Việc còn mở sau cổng: Việc treo 25–35 (PROGRESS), NỢ-3-2 (smoke LLM thật).

## 9. Nhật ký

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 30/09/2026 | 0.1 | Tạo file: sự thật code `02ed795`; 10 lỗ hổng bổ sung G4-15…24; thuật toán chọn người duyệt theo [Chốt]; bảng test xung đột mới; 20 câu Q-4; chặng 4a đủ |
| 03/10/2026 | 1.7 | **Cổng 4 đạt:** mục 7.9 nghiệm thu bởi Tạ Duy Anh (gate3 78/0 — trả NỢ-3-1; gate4 lượt 1 60/4 do ml-service hết giờ khi máy tải nặng, lượt 2 73/0); Việc treo 35 (worker ~98% CPU sau gate4, chưa giải thích); bài học dựng máy thành viên → README; lịch 4d hash/CI; dòng "Cổng 4 ĐẠT" |
| 03/10/2026 | 1.6 | 4d DỪNG 2: mục 7.8 "Chốt khi hiện thực" (17 dòng: Q-4d-3 hiện thực ở B16 + dòng điểm 6 mới, i8 bốn ca, luật viết e2e, Q-4d-8 = B sửa 7.7 #6, Q-4d-6/7 → Việc treo 33, 34, Q-4d-9 = B bỏ g4-08, Q-4d-10 = A g4-12 theo ticket lần chạy, TQ-15/16/17, `verify G=234` + caffeinate Q-4d-4, M-4d-15…17, gộp PR #26 M9 + hợp đồng `OVERRIDE_STEP/EVENT`); kịch bản gate4 thay 7.4; lịch 4d hash/CI |
| 02/10/2026 | 1.5 | 4d DỪNG 1: mục 7.7 "Chốt khi hiện thực" (12 dòng + bảng điểm `audit_check` thay 7.2: Q-4d-1 = A, Q-4d-2 = A, thứ tự P1 thật, `ESCALATE_L2 → L2`, `audit_check` READ ONLY, B17 lớp 2, TC26 — cấm F3 ở B16 + Q-4d-3, rerank nguội + Việc treo 31, 32); lịch 4c hash/CI, 4d người chạy cổng = Duy Anh |
| 01/10/2026 | 1.4 | 4c DỪNG 2: mục 6.5 "Chốt khi hiện thực" (10 dòng: `approval_role` một định nghĩa, hộp thư lọc SQL trước LIMIT, `ApprovalView` 12 khoá + 404/hash phiếu, ghi chú rỗng sau che → 422, id lạ → 404, AST `ROLE_KEYS`, Q-4c-3 = A, M-4c-3b, Việc treo 28–30); 4d thêm P7 (Việc treo 29); lịch 4c ✓ |
| 01/10/2026 | 1.3 | 4c DỪNG 1: mục 6.4 "Chốt khi hiện thực" (Q-4c-1 `note` vào `_POINT_COLUMNS` — sửa 5.7 #4; Q-4c-2 nhắc trên `SqlDeadlineStore` — sửa P3; `decided_at` nhánh timeout; c4 Barrier; A12); lịch 4b CI 36783587264 |
| 01/10/2026 | 1.2 | 4b DỪNG 2: mục 5.7 "Chốt khi hiện thực" (12 dòng: thứ tự B15 thật, event nhánh E, `peek`, `audit_columns` + 6 khoá detail, Q-4b-4 khoá `type`, `available`, Q-4b-8 ngoại lệ `ensure`, P13 detail, harness, gate3 Q-4b-7, mutation, M9); sửa 5.6 #4; 4c P2 (chỉ `response_time_seconds` qua `audit_columns`), 4c P5 (`intended_action->>'type'`), 4d P4 (ghi đè qua `AuditWriter`) |
| 30/09/2026 | 1.1 | 4b DỪNG 1: mục 5.6 "Chốt khi hiện thực" (Q-4b-1…6, TQ-2/3/4/7, thứ tự kiểm khởi động, P7 + test dựa lỗ G4-16, seed 17 người, Việc treo); P13 sửa chữ nhánh lỗi AD của `decided_by` → E2 |
| 30/09/2026 | 1.0 | 4a DỪNG 2 hiện thực `f64fd86`: mục 4.10 "Chốt khi hiện thực DỪNG 2" (11 dòng: Node 24 action, HMAC chuyển tiếp Q-4a-5, mang khoá Q-4a-6, `gitleaks:allow` cho vector đáp án, lệnh mypy tests, số đo bench, Việc treo 22–24); 4b P5 mang theo `_carry_ghost_lock` |
| 30/09/2026 | 0.9 | S0 hiện thực `5ed423d`: mục 4.0.1 "Chốt khi hiện thực S0" (14 dòng); 4c P6 `ApprovalView.procedure`; D-34 ghi `decisions.md`, B08/B10/B11 thêm mục chốt Phase 4 |
| 30/09/2026 | 0.8 | 4d P1: ghi đè cần đăng nhập lại ≤ 10 phút (`recent_login=True`, [Chốt] P6 §4 / P10 §3.2 — bổ sung từ chat Phase 7); thứ tự 413 → quyền → reauth → 404 → `can_override` → 409 → 422; test i14b + mutation |
| 30/09/2026 | 0.7 | Tuấn Anh chốt Q-4-U = A+; thêm bảng kế hoạch tóm tắt đầu file; lịch 4a cập nhật mốc Phase 3 đóng `5d0a990` |
| 30/09/2026 | 0.6 | Q-4-U phân tích sâu (3.3.1–3.3.5): số đo theo loại câu, tách căn cứ câu trả lời / căn cứ hành động, bảng kiểu thất bại; phương án A+ (`procedure_doc` + kiểm tất định ở B11 + cờ ablation); S0-P10, P11, test s12–s16, M-S0-6…8 |
| 30/09/2026 | 0.5 | Mục 0.2 phối hợp M9: không sửa `worker.py`/`main.py`/khối `# M9`; bỏ migration 0008; nhắc duyệt gọi trong `scan_deadlines`; khối `# Phase 4` riêng trong settings/compose; luật rebase + `alembic heads`=1; phụ thuộc M9 (luật 7 cần 4c, `override_count` cần 4d) |
| 30/09/2026 | 0.4 | Soát lại với code (mục 9 bổ sung): `effects.peek` cho B15 chạy lại (tránh phiếu mồ côi khi AD lỗi); B15 truyền `intended_action` (hộp thư đọc cột audit); `GIT_SHA` bỏ qua file untracked; bench dùng testcontainers; compose phải truyền `APPROVAL_SLA_MINUTES_DEV`; x9 bơm lỗi AD bằng hook trước B15; `test_h11_at_20h` đổi thành E5; `_POINT_COLUMNS` bỏ cột ghi đè |
| 30/09/2026 | 0.3 | Việc treo 17 thành việc chặn (Q-3h-11): thêm G4-25, Q-4-U, mục 3.3 (phân tích 4 phương án, đề xuất A: B9 chỉ áp nhánh trả lời), mục 4.0 S0 = DỪNG 1 của 4a |
| 30/09/2026 | 0.2 | Tuấn Anh chốt 20 câu Q-4. Bảng 3.2 dùng máy chưa đăng ký (R17, không phụ thuộc giờ) + `PC-0124`; viết đủ 4b (P1–P15, mã giả, mutation 12), 4c (P1–P7), 4d (ghi đè, `audit_check`, e2e i1–i17, `make gate4`); lịch |
