# Kế hoạch khung frontend + API giả (phương án B)

*Tạo 29/09/2026, cập nhật v1.1 cùng ngày theo **Bản 4 (đã duyệt)** và kiểm tra xây song song với Phase 3 + M9. Mục đích: dựng giao diện 4 vai trò **song song** với Phase 3–6 do **Tuấn Anh** làm bằng một phiên agent riêng (quyết 30/09). Nguồn chốt: `build/nen-tang/P10-giao-dien.md` (màn hình, bảo mật phía giao diện, cổng 7), `P6-auth-bao-mat.md` §4, §8, `huong-dan` Phase 7. Thiết kế: `claude/thiet-ke-ui-ux.md` mục 8e + canvas Bản 4. Code đối chiếu: repo `dev-tuananh` tại commit `6797455` (3e dừng 3); M9: `claude/ke-hoach-m9-monitor.md`, `claude/ke-hoach-m9-chia-viec.md`.*

> **Trạng thái v1.2 (30/09/2026, chiều): MỞ LẠI — làm được ngay, nối backend dần.** Sáng 30/09 tạm dừng; chiều cùng ngày kiểm lại: Phase 3 đã đóng (`5d0a990`, CI xanh), route thật không đổi so với mục 1.1, và `build/phase4-thiet-ke-chi-tiet.md` v0.7 đã **chốt hợp đồng** các route L1 (hộp thư, xem phiếu, ghi đè) → dữ liệu giả nay dựng theo hợp đồng thật, không còn đoán. Điều kiện: (1) chốt người làm (12.4); (2) job CI frontend thêm **sau** khi 4a merge (12.1); (3) theo các tinh chỉnh ở mục 4.6.

> **Tiến độ (08/10/2026, 22:15):** **N-A3 PHẦN 1 đã commit cục bộ `c063134`** (21 file `frontend/`, 17 sửa + 4 xoá mock, +1621 −701; chưa push — `origin/fe-tuananh` vẫn `a98d238`, đi trước 1 commit). Verify 08/10 01:14:15 không `VERIFY_MGR`: **XANH** 44 PASS / 0 FAIL / 8 BỎ QUA, vitest 522/522. PHẦN 2 chờ PR #30 (A3, `dev-luuduong` @ `3f15afb`, chưa merge) + image backend/worker dựng lại. **Stack: rerank chỉ kịp hạn khi máy cắm sạc** (xem 12b "Sự cố tc04 08/10").
> **Tiến độ (07/10/2026, đêm):** `a98d238` đã push (`origin/fe-tuananh`), nằm trong PR #27 (chưa merge). **N-A3 PHẦN 1 xong, CHƯA commit** — 21 file sửa dở trong worktree (16 sửa, 4 xoá mock, +1621 −701), vitest 522/522, chờ PR #30 (A3, `dev-luuduong` @ `3f15afb`, chưa merge) để làm PHẦN 2 (`gen:api`, verify, commit).

> **Tiến độ (07/10/2026, 20:45):** thêm **N-L2Q `a98d238`** (hàng đợi L2: tìm ca, thẻ nhóm, thu gọn, phân trang trong nhóm, báo ca mới ở nhóm khuất) — verify 07/10 20:34:47 **XANH** 44 PASS / 0 FAIL / 8 BỎ QUA (F5-1…6 do không `VERIFY_MGR`; F2-3, F3-7 như cũ; F5 đã PASS ở lượt 06/10 16:38), vitest 447/447. `a98d238` chưa push; `origin/fe-tuananh` vẫn `66691dc`. Kế tiếp: N-A3 phần 1 (mốc HEAD `a98d238`, test từ t109, mutation từ M79).

> **Tiến độ (02/10/2026, 21:46):** F0 `682debc` · F1 `69b1aaa` · F2 `482d144` · F3 `b9e7b99` · F4 `75a88fb` · F5 `210b158` · F6 `e3e6adc` · N4c `136953c` · **N4d `66691dc`** (nối thật ghi đè 4d). Verify 02/10 21:40:57 **XANH**: 49 PASS, 0 FAIL, 2 BỎ QUA (F2-3, F3-7); F4-10 PASS trên route thật; vitest 384/384. **Frontend đã nối xong MỌI route backend hiện có** (đăng nhập, chat, hàng đợi L2, quyết định, hộp thư + xem phiếu, ghi đè). Remote: `origin/fe-tuananh` đã có tới `136953c` (push 21:12 ngày 02/10); `66691dc` chưa push; nhánh sau `origin/dev-tuananh` 23 commit. Kế tiếp: push + mở PR `fe-tuananh → dev-tuananh` (**không rebase** — nhánh đã ở remote, rebase buộc force-push; để PR gộp, FE chỉ đụng `frontend/`) → job CI frontend → chờ backend: M9 A3, Phase 5 T20, Phase 7. [Suy luận] ≈ 58% khối lượng Phase 7.

Ký hiệu: **[Chốt]** = đã có trong spec/code; **[Suy luận]** = rút ra từ spec/code; **[Đề xuất]** = mới, nhóm duyệt.

---

## 0. Tóm tắt một màn hình

| Mục | Nội dung |
|---|---|
| Ai làm | **Tuấn Anh tự làm** [Chốt 30/09] bằng một phiên Claude Code riêng ở **worktree `fe-tuananh`** (mục 11), song song với phiên Phase 4. Claude chat soi mỗi DỪNG theo checklist mục 8. Cách làm: **dựng hết các màn (F0–F6) bằng API thật + dữ liệu giả, rồi nối thật / tinh chỉnh dần** khi backend ra route |
| Làm gì | `frontend/` theo cây P10 §2. Route đã có → gọi **API thật**. Route chưa có → **MSW** trả dữ liệu giả theo hợp đồng P10 |
| Thiết kế | **Bản 4** trên canvas (trang "Bản 4"), đã duyệt 29/09/2026. Bản 1–3 chỉ để tham khảo, **không code theo** |
| Không làm | Không sửa `backend/`, `docs/spec/`, compose, Caddy; không thêm route/CORS. Không tính là qua cổng 7 (cổng 7 vẫn ở Phase 7) **[Chốt]** |
| Mốc demo thứ Sáu 02/10 | Bắt đầu từ 30/09 nên chỉ kịp **F0 + F1 + F2** (đăng nhập, chat nhân viên thật) [Suy luận: 2,5–3 ngày công]. Hàng đợi L2 (F3) nếu kịp; không kịp → phần L2 demo bằng Swagger |
| Sau demo | F3–F6 làm dần. Mỗi khi backend ra route mới (M9 A3; Phase 4: 4c hộp thư + xem phiếu, 4d ghi đè; Phase 5; Phase 7) → xoá handler giả tương ứng, nối thật |
| Lợi về thời gian [Suy luận] | Phần giao diện của Phase 7 ra khỏi đường găng của Tuấn Anh. Tới Phase 7 Tuấn Anh chỉ còn làm backend T31, policy; UI đã có sẵn chỉ cần bỏ mock |

---

## 1. Kiểm tra API thật trong repo (29/09/2026; kiểm lại 30/09 sau khi Phase 3 đóng — route không đổi)

### 1.1. Route đã có → nối thật ngay

| Route | Trả về (theo code) | Ghi chú cho UI |
|---|---|---|
| `POST /api/auth/login` `{username, password, otp?}` | `{access_token, token_type, expires_in, csrf_token}` + cookie `refresh` (HttpOnly, `Path=/api/auth`) + cookie `csrf` (đọc được, `Path=/`) | `username` phải khớp `^[a-z][a-z0-9._-]{0,127}$` → validate phía UI trước khi gửi. Manager thiếu OTP → **401 `mfa_required`** → hiện ô OTP. Lỗi sai luôn là thông báo chung |
| `POST /api/auth/refresh` | như login | Bắt buộc header `X-CSRF-Token` = giá trị cookie `csrf` (đọc **lúc gọi**, vì cookie xoay vòng mỗi lần). Thiếu cookie → **403 `csrf`** (backend kiểm CSRF trước), không phải 401 |
| `POST /api/auth/logout`, `/logout-all` | 204 | |
| `GET /api/auth/me` | `{user_id, role, permissions[]}` | Không có tên hiển thị → UI hiện `user_id` (tạm) |
| `POST /api/tickets` `{text ≤ 4000}` | **202** `{ticket_id, status, notices[]}` | `notices` là thông báo của privacy guard (vd đã ẩn mật khẩu) → **phải hiển thị** |
| `GET /api/tickets/{id}` | `TicketView {ticket_id, status, waiting_for, conversation[], exit_code, close_reason, final_state, created_at, closed_at}` | `waiting_for ∈ clarify / approval / confirm / reply / null` quyết định ô nhập nào hiện |
| `POST /api/tickets/{id}/messages` `{text}` | 202 như trên | Chỉ khi `waiting_for = clarify` |
| `POST /api/tickets/{id}/confirm` `{confirmed, note?}` | 202 | Chỉ khi `waiting_for = confirm` |
| `POST /api/approvals/{id}/decision` `{decision, note?, reason_code?, view_started_at?}` | 202; 409 "Yêu cầu đã chuyển sang bước khác"; 422 `rejected_requires_note` | `reason_code` là enum 7 giá trị: `missing_info, not_authorized, policy_violation, duplicate, wrong_device, security_concern, other` |
| `GET /api/escalations/queue?limit=` | mảng `{escalation_id, ticket_id, exit_code, priority, label, reason_detail, is_deny_case, handoff_note, assigned_to, created_at}` | Quyền `escalation:handle` (l1, l2). Manager → 403 |
| `GET /api/health` | `{…, runtime: up/down}` | Dùng cho banner "hệ thống đang khởi động" |

Tài khoản demo: seed `mock_services/seed.json`, mật khẩu demo công khai ở `mock_services/README.md` mục "Dữ liệu demo". Nhân viên `an.nv`; L1 `ha.lt`, `duc.pv`; L2 `long.nh`; Trưởng BP IT `quan.tm` (cần MFA).

### 1.2. Route chưa có → MSW (dữ liệu giả)

| Route | Màn hình Bản 4 | Backend làm ở |
|---|---|---|
| `GET /api/dashboard/business`, `GET /api/dashboard/ai`, `GET /api/alerts`, `POST /api/alerts/{id}/ack` | B4MgrDashboard, cảnh báo | **M9 A3 (Lưu Dương) — sớm, trước Phase 7**. Có `response_model` → sinh kiểu tự động. Dương gửi openapi khi mở PR A3 **[Chốt kế hoạch M9]**. **03/10: code A3 ở PR #30 (`origin/dev-luuduong` @ `3f15afb`, chưa merge) → chặng N-A3 đang mở**, hợp đồng thật + điểm lệch ở 12b "N-A3" |
| ~~`GET /api/approvals?mine=1&status=…`~~ | B4L1Queue tab "Chờ duyệt" | **ĐÃ NỐI (N4c `136953c`).** Có thật từ 4c `b457e6e` (01/10) — trả `{"items":[InboxItem]}` (không phải mảng trần); `mine=1` bắt buộc (thiếu → 422); `status ∈ pending\|approved\|rejected\|timeout`; tối đa 50 (`INBOX_LIMIT`); `action_type`, `device_id` có thể `null`. Nối ở chặng "nối thật 4c" |
| ~~`GET /api/approvals/{id}`~~ → `ApprovalView` | B4L1Detail | **ĐÃ NỐI (N4c).** Có thật từ 4c: L1 khác → **404**, L2/nhân viên → 403, hash lệch → **409 `plan_changed`**; `role_as ∈ primary\|backup\|viewer` (manager xem = `viewer`, không ghi lần xem đầu); `requester.department`, `risk`, `procedure` có thể `null`. 202 của `decision` thêm `decided_as` |
| ~~`POST /api/tickets/{id}/override`~~ → 201 | Hộp thoại "Ghi đè…" | **ĐÃ NỐI (N4d `66691dc`).** Có thật từ 4d DỪNG 1 `e510a6e` (02/10). Thân 201 `{ticket_id, original_decision, override_decision, reason_code, notices}`; thứ tự lỗi: 413 → 403 `forbidden` → 403 `reauth_required` → 404 → 403 `forbidden` (người gửi tự ghi đè) → 409 `ticket_open` → 422 `invalid_request` (thiếu note khi "other" → `fields:["note"]`, không tiền tố `body.`) → 422 `same_as_original` → 503 guard → 409 `already_overridden`. Gốc: **Phase 4 chặng 4d [Chốt §7.1 P1–P4]**: chỉ ticket đã kết thúc; lần 2 → 409 `already_overridden`; trùng quyết định gốc → 422 `same_as_original` |
| Danh sách ca để L1 **tìm** ticket cần ghi đè | Tab "Hệ thống đã tự xử lý" | **Không có trong Phase 4** → Phase 7 (9 #6). Tới lúc đó: ô nhập mã ticket (xem 4.6) |
| `GET /api/me/notifications` | Chuông + khối Thông báo | **Phase 7** [Chốt Q-4-E: Phase 4 không thêm bảng `notifications`] |
| `GET /api/tickets?mine=1` | Lịch sử "Gần đây" trên thanh bên | **Phase 7** (Phase 4 không có). Tới lúc đó: danh sách ticket tạo trong phiên, giữ trong bộ nhớ (xem 4.6) |
| `POST /api/tickets/{cha}/reply`, `children_progress` | B4EmpDigest (tin tổng hợp + tiến độ nhiều ý, D-31) | Phase 5 |
| `GET /api/escalations/{id}`, `POST /api/escalations/{id}/close` | B4L2Detail | Phase 7 (T31) |
| `GET/PUT /api/policy`, `/versions`, `/restore`, `/simulate` | B4MgrPolicy | Phase 7 |

### 1.3. Lỗ hổng hợp đồng phát hiện khi kiểm [Suy luận]

1. `login`, `me`, `escalations/queue` trả `dict[str, Any]` (không có `response_model`) và `conversation` là `list[dict]` → **openapi không sinh được kiểu**. Phải viết tay kiểu cho các chỗ này (mục 3.2).
2. `TicketView` **chưa có `deadline` và `server_now`**, trong khi P10 §5 chốt đồng hồ đếm ngược dùng giờ máy chủ → đồng hồ của nhân viên để **tạm ẩn**.
3. Chưa có route lịch sử ticket của tôi → lịch sử trên thanh bên dùng dữ liệu giả.
4. ~~Citation giả~~ → đã có thật (Q-fe-2): `answer` kèm `sources`, cùng `question`, `result`, `escalation`. Phase 4 thêm `kind:"rejection"` (4c P1: tin từ chối có lý do + ghi chú đã che).
5. `ApprovalView` (4c P6) có `deadline` nhưng **không** có `server_now` → đồng hồ L1 lấy giờ máy chủ từ **header `Date`** của chính response (cùng origin nên đọc được) và tính độ lệch với đồng hồ máy khách **[Đề xuất — không cần sửa backend]**. ~~Header thiếu → hiện hạn dạng giờ tuyệt đối~~ → code F4 làm theo P5: header thiếu → độ lệch 0 (dùng giờ máy khách); PLAN-fe mục 7 #15.

→ Các mục này ghi vào **Nợ API cho giao diện** (mục 9) để Tuấn Anh thêm đúng lúc, **không** làm bây giờ.

---

## 2. Cấu trúc và công cụ

```
frontend/  (React + Vite + TypeScript + Tailwind + TanStack Query + React Router) [Chốt P10 §2]
 dev-public/mockServiceWorker.js   ← CHỈ dùng khi dev (xem 4.3), không nằm trong public/
 src/
  api/
   schema.gen.ts        sinh từ openapi.json (commit vào git; CI không cần backend)
   contracts-tam.ts     kiểu viết tay: route chưa có + route trả dict (mục 1.3) — mỗi kiểu ghi nguồn
   types.ts             ĐIỂM IMPORT DUY NHẤT cho component (re-export từ 2 file trên)
   client.ts            fetch + access token trong bộ nhớ + refresh có khoá
   errors.ts            ánh xạ mã HTTP → thông báo tiếng Việt
  auth/                 LoginPage, AuthProvider, useMe(), RequirePerm
  routes/employee|l1|manager|l2/   như P10 §2
  components/
   Sidebar.tsx          thanh bên hợp nhất 264 px (Bản 4) — thay TopBar + SideNav của bản cũ
   StatusBadge, Countdown, Citation, ActionView, ReasonPicker, OverrideDialog,
   DigestMessage, ProgressPanel, NotificationList, Segmented, ListGroup
  styles/tokens.css     token Bản 4 (mục 4.5) — Tailwind đọc từ đây, không rải mã màu trong component
  mocks/
   handlers/*.ts        MỖI FILE = một nhóm route CHƯA CÓ (approvals, notifications, my-tickets, l1-auto,
                        escalation-detail, policy, dashboard, alerts, reply)
   fixtures/*.ts        dữ liệu giả, lấy tên người từ seed
   browser.ts           setupWorker(...handlers), onUnhandledFrame: "bypass" (MSW 3 đổi tên từ onUnhandledRequest)
  demo/DemoBar.tsx      Nên có, làm cuối (F6)
```

**Nguyên tắc chuyển giả → thật [Đề xuất]:** handler MSW chỉ khai báo route **chưa có**; mọi request khác đi thẳng qua proxy tới backend (`bypass`). Khi backend ra route, **xoá file handler + chuyển kiểu từ `contracts-tam.ts` sang `schema.gen.ts`**, component không phải sửa vì chỉ import từ `types.ts`.

**Lệnh (`package.json`):** `dev`, `build`, `lint` (eslint), `typecheck` (`tsc --noEmit`), `gen:api` (openapi-typescript đọc `http://127.0.0.1:8000/openapi.json`), `check:dist` (mục 4.3). Phiên bản thư viện: bản ổn định lúc cài, khoá bằng `package-lock.json`.

**Vite proxy:** `/api` → `http://127.0.0.1:8000`. Trình duyệt thấy cùng origin → cookie `SameSite=Strict` chạy, **không cần CORS** (backend không bật CORS, giữ nguyên) **[Chốt P6 §7: CORS chỉ origin frontend — ở prod Caddy lo]**. Vì dev chạy qua Vite proxy nên **không cần sửa compose/Caddy** cho tới Phase 7 (xem 12).

---

## 3. Hợp đồng kiểu

### 3.1. Sinh tự động
`npm run gen:api` khi stack đang chạy → `schema.gen.ts`. Chạy lại mỗi khi Tuấn Anh (hoặc Dương với A3) báo backend đổi route. Diff của file này là cách phát hiện hợp đồng đổi.

### 3.2. Viết tay (`contracts-tam.ts`)
Mỗi kiểu có chú thích 2 dòng: **nguồn** (file code:dòng hoặc mục spec) và **khi nào xoá**. Ví dụ:

```ts
// Nguồn: backend/app/api/auth.py me() — trả dict, openapi không có schema.
// Xoá khi: route có response_model (Nợ API #3).
export type Me = { user_id: string; role: "employee" | "l1" | "manager" | "l2"; permissions: string[] };

// Nguồn: graph/nodes/b20_audit.py, clarify_wait.py. Xoá khi: TicketView khai báo kiểu conversation.
export type ConversationItem = { role: "user" | "assistant"; kind?: string; text: string; ref?: unknown };

// Nguồn: P10 §3.2 + B15-B16 §8 (approvals). Route CHƯA CÓ — Phase 4.
export type ApprovalView = { approval_id: string; ticket_id: string; deadline: string; server_now: string;
  request_redacted: string; action: Record<string, unknown>; action_plan_hash: string;
  decided_by_rule?: string; p_calibrated?: number; diagnosis: unknown; conflict_detected: boolean };

// Nguồn: ke-hoach-m9-monitor.md §5.1. Route CHƯA CÓ — M9 A3. Xoá khi A3 merge (gen:api).
export type BusinessDashboard = {
  automation_rate: number | null; escalation_rate_raw: number | null; escalation_rate_weighted: number | null;
  deflection_rate: number | null; approval_expired_count: number;
  decided_by_distribution: Record<string, number>; top_matched_rules: { rule_id: string; count: number }[];
  e1_split?: Record<string, number>;
  e3_cases?: { ticket_id: string; intent: string; created_at: string; kb_version: string; request_excerpt: string }[];
  unavailable: string[] };
```

```ts
// Nguồn: phase4-thiet-ke-chi-tiet.md §6.1 P5 (4c). Xoá khi 4c merge (gen:api).
export type ApprovalListItem = { approval_id: string; ticket_id: string;
  status: "pending" | "approved" | "rejected" | "timeout"; created_at: string; deadline: string;
  reminder_1_at: string | null; reminder_2_at: string | null; role_as: "primary" | "backup";
  action_type: string; device_id: string | null };

// Nguồn: §6.1 P6 (4c). Thay ApprovalView phỏng đoán ở trên. Không có server_now → header Date (1.3 #5).
export type ApprovalViewP4 = { approval_id: string; ticket_id: string; status: ApprovalListItem["status"];
  deadline: string; requester: { role: string; department: string }; request_summary: string;
  action: Record<string, unknown>; action_plan_hash: string; risk: Record<string, unknown>;
  facts: Record<string, unknown>; role_as: "primary" | "backup";
  procedure: { doc_id: string; title?: string | null } };  // 4c P6 (D-34): căn cứ quy trình; thiếu tiêu đề → chỉ doc_id

// Nguồn: §7.1 P2 (4d). note bắt buộc khi reason_code = "other".
export type OverrideIn = { override_decision: "AUTO" | "HITL" | "L2" | "ANSWER";
  reason_code: "too_risky_for_auto" | "approval_unnecessary" | "should_not_escalate" | "wrong_answer" | "policy_gap" | "other";
  note?: string };
```

Kiểu của route chưa có là **phỏng đoán theo spec** → chấp nhận phải sửa khi backend ra. Giữ component nhận props nhỏ để sửa rẻ. Riêng dashboard: **tên trường lấy đúng theo kế hoạch M9 §5.1–5.2**, không tự đặt; chỉ số nằm trong `unavailable` (vd `override_count` trước Phase 4) → hiện "chưa có dữ liệu", **không** hiện 0.

---

## 4. Luật bắt buộc (Tuấn Anh soát theo mục 8)

### 4.1. Bảo mật phía giao diện [Chốt P10 §4, P6]
1. **Access token chỉ trong biến bộ nhớ** (React context/module). **Cấm** localStorage/sessionStorage/IndexedDB cho token. Tải lại trang → gọi refresh để lấy token mới.
2. **Refresh có khoá xuyên tab** bằng `navigator.locks.request("auth-refresh", …)` + gộp lời gọi trong một tab (single-flight). Lý do: refresh token xoay vòng; hai tab cùng gửi một refresh cũ → backend coi là **dùng lại** → **thu hồi cả họ token** → mọi tab bị đăng xuất. (Đây là việc treo "frontend khoá refresh 1 tab" của Phase 7.)
3. `X-CSRF-Token` đọc từ cookie `csrf` **ngay lúc gọi refresh**, không dùng bản nhớ từ lần trước.
4. 401 → refresh **một lần** → gọi lại request; vẫn 401 → về trang đăng nhập. Không vòng lặp.
5. Nội dung từ LLM/agent hiển thị qua Markdown đã lọc HTML (react-markdown **không** bật HTML thô). **Cấm `dangerouslySetInnerHTML`** (eslint chặn).
6. **Không `console.log` nội dung tin nhắn**; eslint `no-console: error` (cho phép `console.error` không kèm dữ liệu).
7. Không tải gì từ CDN, không font từ Google Fonts (CSP `default-src 'self'` ở Caddy). Font Be Vietnam Pro **tự host**: cài gói `@fontsource/be-vietnam-pro` (400, 600, 700) → Vite đóng gói vào `dist/`, cùng origin. SF Pro là font hệ thống của Mac/iPhone, không cần tải.
8. Menu và route hiện theo `permissions` từ `/api/auth/me`, **không** so tên role. Ẩn nút chỉ để tiện; quyền thật do backend.
9. Nhiều tab: access token mới chia sẻ qua `BroadcastChannel` (chỉ bộ nhớ, kiểm dạng tin, `logout` phát tin) — Q-fe-13.

### 4.2. Hiển thị [Chốt P10 §3, §5]
1. Theme sáng, chữ nội dung 17 px (≥ 16 px theo P10), tương phản ≥ 4,5:1 cho chữ (đọc trên máy chiếu).
2. Nhân viên **không thấy mã `S_*`**; L1/L2 thấy cả nhãn lẫn mã. Bảng nhãn ở mục 5.
3. **E0 trung tính:** `S_BLOCKED` hiện "Yêu cầu này không thể xử lý tự động", **không** chữ nào gợi ý "phát hiện tấn công" **[Chốt 7.1]**. (Hàng đợi L2 được thấy nhóm "An ninh" — chỉ nhân viên phải trung tính.)
4. L2 **không có nút duyệt** ở bất kỳ màn nào **[Chốt 2.2]**. Ca bị luật cấm: lựa chọn "Đã hoàn tất" bị khoá (như B4L2Detail).
5. Chi tiết duyệt hiện **đúng object Action đã băm** (bảng đủ trường + JSON gốc) + `action_plan_hash`, không tóm tắt khác **[Chốt 5.2.1]**.

### 4.3. Dữ liệu giả không được lọt vào bản build (fail-closed) [Đề xuất]
1. MSW chỉ khởi động khi `import.meta.env.DEV && import.meta.env.VITE_API_MOCK === "1"`.
2. File worker ở `dev-public/`; `vite.config.ts`: `publicDir: mode === "development" ? "dev-public" : "public"`.
3. `npm run check:dist`: sau `vite build`, grep `dist/` **không được có** `mockServiceWorker` hay `msw` → có thì thoát 1. Chạy trong CI.
4. Màn hình đang dùng dữ liệu giả có **nhãn "Dữ liệu minh hoạ"** ở góc (chỉ ở dev) — để demo không trình bày sai với GVHD.

### 4.4. Phạm vi sửa
Chỉ `frontend/`. Job `frontend` trong `.github/workflows/ci.yml` và target `make fe-check` trong `Makefile` do **Tuấn Anh** thêm  — xem 12.1. Không đụng `backend/`, `docs/spec/`, `.env`, `docker-compose*.yml`, `Caddyfile`. Không commit/push thẳng `dev-tuananh` — làm trên nhánh `fe-tuananh` (worktree, mục 11) rồi PR.

### 4.5. Token thiết kế Bản 4 [Chốt — đã duyệt 29/09/2026]

Chi tiết và tương phản: `thiet-ke-ui-ux.md` mục 8e. Tóm tắt để đưa vào `styles/tokens.css` + `tailwind.config`:

| Nhóm | Giá trị |
|---|---|
| Font | `-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Be Vietnam Pro', 'Segoe UI', sans-serif`; mã/ID: `'SF Mono', 'JetBrains Mono', monospace` (JetBrains Mono cũng tự host nếu dùng) |
| Thang chữ (5 cỡ) | 34/41 700 (tiêu đề trang) · 22/28 600 (tiêu đề khối) · 17/26 400 (nội dung) · 15/20 (phụ) · 13/18 600 (nhãn nhóm, meta). **Không** thêm cỡ khác |
| Màu chữ | `#1D1D1F` chính · `#6E6E73` phụ · `#AEAEB2` chỉ cho biểu tượng/số dòng (không dùng cho chữ cần đọc) |
| Nền, viền | trắng · nhóm `#F5F5F7` · viền `#E5E5EA` · segmented `#EEEEF0` |
| FPT | xanh `#0055A4` (mọi nút chính, link) · cam `#F37021` (logo, chấm "chờ con người") · nút gửi `#E8630A` · chữ cam `#B4500B` trên `#FFF4EC` · chấm xong `#4DB848` |
| Nguy hiểm | `#C62828` trên `#FCEBEB`; chữ đậm `#7A1C1C` |
| Nút | viên thuốc cao 44 (bo 22); nút chính xanh chữ trắng; nút phụ `#F2F2F7` chữ xanh; nút nhỏ cao 30 |
| Bố cục | thanh bên 264 px (không có thanh trên); cột chat nhân viên 720 px; lề nội dung 40–48; khối cách 24; nhóm danh sách bo 16, dòng 44–52; thanh quyết định L1 cao 76 dính đáy; sheet từ chối giữa màn bo 20 |

Danh sách màn Bản 4 (bản sao chỉ-đọc cho agent: `docs/spec/claude/ban4/B4*.dc.html` + README): B4Login · B4EmpHome · B4EmpChat · B4EmpStates (các trạng thái chat + thông báo) · B4EmpDigest · B4L1Queue (2 tab: Chờ duyệt / Hệ thống đã tự xử lý) · B4L1Detail (Bảng/JSON + sheet từ chối) · B4L2Queue · B4L2Detail · B4MgrDashboard · B4MgrPolicy · B4Sidebar (4 vai trò).

### 4.6. Tinh chỉnh Bản 4 theo hợp đồng Phase 4 [Đề xuất — áp khi code, canvas sửa sau]

| Màn | Bản 4 đang vẽ | Sửa khi code | Lý do |
|---|---|---|---|
| Thanh bên nhân viên | Lịch sử "Gần đây" từ server + chuông có số | Lịch sử = ticket tạo **trong phiên này** (bộ nhớ, mất khi tải lại); **ẩn chuông** tới Phase 7 | Phase 4 không có `tickets?mine=1`, không có `notifications` (Q-4-E) — không hiện dữ liệu giả ở màn chính |
| B4EmpStates | Khối "Thông báo" | Bỏ khối; kết quả duyệt/từ chối hiện **trong hội thoại** (tin `kind:"rejection"` của 4c) | Như trên |
| B4L1Queue | Nhiều loại hành động (cài phần mềm, quyền…) | Fixture chỉ VPN (`renew_vpn_cert`, `reissue_vpn_access`); cột `role_as` ("Dự phòng" khi `backup`); dấu nhắc khi `reminder_1_at`/`reminder_2_at` có giá trị | Phase 4 chỉ có intent VPN; dự phòng duyệt được sau nhắc 2 (Q-4-O) |
| B4L1Queue tab "Hệ thống đã tự xử lý" | Danh sách ca | **Ẩn tab** tới Phase 7; nút "Ghi đè…" đặt ở màn xem ticket, mở bằng **ô nhập mã ticket** | Chưa có route liệt kê (9 #6) |
| B4L1Detail | Bảng/JSON + sheet từ chối | Thêm 3 trạng thái: **409 `plan_changed`** ("Hành động đã thay đổi sau khi tạo phiếu — không thể duyệt", không hiện object nào); **404** ("Không tìm thấy phiếu"); "Bạn đang duyệt với vai trò dự phòng" khi `role_as=backup` | 4c P6, G4-13 (chống TOCTOU) |
| Hộp thoại ghi đè | Chưa vẽ chi tiết | 4 lựa chọn `override_decision` (trừ quyết định gốc), 6 `reason_code`, ô ghi chú bắt buộc khi "Khác"; lỗi 409 `ticket_open` / `already_overridden`, 422 `same_as_original` hiện đúng câu | 4d P1–P4 |

---

## 5. Bảng nhãn trạng thái cho nhân viên [Đề xuất, theo 14 trạng thái đã chốt]

| Trạng thái | Nhãn nhân viên thấy | Polling |
|---|---|---|
| `S_NEW`, `S_SCREENING`, `S_CLASSIFYING` | Đang tiếp nhận yêu cầu | 2 giây |
| `S_DIAGNOSING` | Đang kiểm tra hệ thống | 2 giây |
| `S_RETRIEVING` | Đang tra cứu hướng dẫn | 2 giây |
| `S_ASSESSING` | Đang đánh giá yêu cầu | 2 giây |
| `S_EXECUTING` | Đang thực hiện | 2 giây |
| `S_CLARIFYING` | Cần bạn bổ sung thông tin | 10 giây |
| `S_PENDING_APPROVAL` | Đang chờ IT duyệt | 10 giây |
| `S_CONFIRMING` | Chờ bạn xác nhận kết quả | 10 giây |
| `S_ESCALATED` | Đã chuyển kỹ thuật viên hỗ trợ | dừng |
| `S_RESOLVED` | Đã hoàn tất | dừng |
| `S_REJECTED` | Yêu cầu không được duyệt | dừng |
| `S_BLOCKED` | Yêu cầu này không thể xử lý tự động | dừng |

Polling 2 giây khi đang xử lý, 10 giây khi `waiting_for ≠ null` **[Chốt P10 §3.1]**; dừng khi có `final_state`. Sau mỗi 202 → gọi lại ngay một lần rồi theo nhịp. Chấm trạng thái trên lịch sử thanh bên: cam = chờ con người (clarify/approval/confirm), xanh lá = xong, xám = đã chuyển/không xử lý.

**Ánh xạ lỗi (`errors.ts`):** 401 → refresh (mục 4.1); 403 "Bạn không có quyền thực hiện thao tác này"; 404 "Không tìm thấy"; 409 → hiện `detail` + tải lại ticket; 413 "Nội dung quá dài"; 422 → báo lỗi tại đúng ô; 429 "Thao tác quá nhanh, thử lại sau"; 503 → đọc `Retry-After`, tự thử lại sau N giây, hiện "Hệ thống đang bận". Riêng dashboard: 503 (thiếu kết nối monitor, fail-closed của M9) → "Số liệu tạm thời không có", **không** hiện số cũ.

---

## 6. Các chặng

Mỗi chặng: agent lập plan ngắn → code → `lint + typecheck + build + check:dist` xanh → tự chạy tay theo "Đạt khi" → PR → Tuấn Anh review theo mục 8.

| Chặng | Nội dung | API | Ước lượng [Suy luận] | Model cho agent |
|---|---|---|---|---|
| **F0** Khung | Scaffold Vite/React/TS/Tailwind/Query/Router, eslint (luật 4.1), proxy, `gen:api`, MSW khung + `check:dist`, `types.ts`, **token Bản 4 (4.5) + font tự host**, `Sidebar` rỗng | — | 0,5 ngày | Sonnet |
| **F1** Đăng nhập + điều hướng | B4Login (validate username, ô OTP khi `mfa_required`), `client.ts` (token bộ nhớ, refresh khoá xuyên tab, CSRF từ cookie), `useMe`, `RequirePerm`, `Sidebar` theo permission (4 vai trò), trang 403/404, đăng xuất | Thật | 1 ngày | **Opus** (an ninh: token, refresh, CSRF) |
| **F2** Chat nhân viên | B4EmpHome + B4EmpChat: gửi yêu cầu, hiện `notices`, polling theo bảng 5, hội thoại, ô trả lời khi `clarify`, nút "Đã ổn / Chưa ổn" khi `confirm`. **B4EmpStates**: đủ các trạng thái Phải có (đang xử lý, cần bổ sung, chờ duyệt, đã chuyển L2, E0 trung tính). Lịch sử thanh bên + Citation + thông báo = giả | Thật + giả | 1–1,5 ngày | Sonnet |
| **F3** L2 | B4L2Queue thật (nhóm theo `priority`, cờ deny). B4L2Detail: ghi chú bàn giao từ item hàng đợi (thật); hội thoại + đóng (2–3 kết quả, "Đã hoàn tất" khoá với ca deny) = giả | Thật + giả | 0,5–1 ngày | Sonnet |
| **F4** L1 | B4L1Queue tab "Chờ duyệt" theo `ApprovalListItem` (sắp theo hạn, đỏ khi < 20%, đồng hồ theo header `Date`) + OverrideDialog theo `OverrideIn` + các trạng thái 4.6. **Nối thật khi 4c/4d merge**. B4L1Detail (Bảng/JSON đúng object + hash), ReasonPicker (7 `reason_code` thật) + ô lý do bắt buộc khi từ chối. Nút quyết định gọi **qua cùng client** để khi có Phase 4 là chạy thật | Giả (decision thật sẵn) | 1 ngày | Sonnet |
| **F5** Trưởng BP IT | B4MgrDashboard + cảnh báo/ack: **nối thật ngay khi A3 merge** (trước đó MSW theo kiểu 3.2). B4MgrPolicy (JSON, lỗi **từng dòng**, lịch sử + quay lui) = giả tới Phase 7 | Thật (A3) + giả | 1,5 ngày | Sonnet |
| **F6** Nên có | B4EmpDigest (DigestMessage + ProgressPanel, D-31), DemoBar (`DEMO_MODE`), nút gợi ý nhanh, chống duyệt < 5 giây | Giả | 1 ngày | Sonnet |

**Demo thứ Sáu 02/10:** F0 → F3 (bắt buộc), F4 nếu kịp. Kịch bản demo: `an.nv` gửi yêu cầu có thẻ `[fake:<preset>]` → xem trạng thái chạy → ca bị escalate → đăng nhập `long.nh` thấy ticket trong hàng đợi L2. Màn L1/Trưởng BP IT (nếu hiện) mang nhãn "Dữ liệu minh hoạ".

**Sau demo:** F4 → F5 → F6, không gấp. **F4 phải xong trước khi Phase 4 backend xong** (xem 12.3). Mỗi khi A3/Phase 4/5/7 xong → một chặng nhỏ "nối thật": `gen:api`, xoá handler, sửa kiểu.

**Kế hoạch làm việc frontend (chốt 06/10/2026).** Trạng thái lúc lập: `origin/fe-tuananh` = `66691dc` chưa vào `dev-tuananh` (`632e05a`); PR #30 (A3) chưa merge; worktree có 3 file `routes/l2/*` sửa dở từ 03/10 (tìm ca, thẻ nhóm, thu gọn, phân trang — chưa test, chưa verify); CI chưa có job frontend.

| # | Việc | Ai | Cần stack | Xong khi |
|---|---|---|---|---|
| 1 | Merge PR #27 (`fe-tuananh` @ `66691dc` → `dev-tuananh`), không rebase | Tuấn Anh | Không | PR đóng, CI xanh |
| 2 | ~~**Chặng N-L2Q**~~ — **XONG `a98d238` (07/10)**. Prompt `claude/prompt-fe-l2q.md` | Agent FE + Claude chat soát | Chỉ lúc verify | verify xanh, commit |
| 3 | ~~**Chặng N-A3 phần 1**~~ — **XONG, commit cục bộ `c063134` (08/10), chưa push** (đổi kế hoạch: commit trước khi PR #30 merge để không để 21 file treo). Prompt `claude/prompt-fe-noi-a3.md` | Agent FE + Claude chat soát | Không | DỪNG 2 đạt |
| 4 | Job CI `frontend` + `make fe-check` (Claude chat soạn, Tuấn Anh thêm vào `dev-tuananh`) — làm song song với 2–3 | Tuấn Anh | Không | CI có 2 job, xanh |
| 5 | **N-A3 phần 2** — `gen:api`, `schema.check.ts`, verify CÓ `VERIFY_MGR=1`, commit riêng; rồi push cả `c063134` + commit phần 2 | Agent FE + Tuấn Anh | Có | chờ PR #30 merge + image dựng lại |
| 6 | Chờ backend: Phase 5 T20 → chặng "nối nhiều ý"; Phase 7 (T31 đóng ca, chính sách, thông báo, lịch sử ticket, phân trang, `deadline`) → chặng "nối Phase 7"; sau đó cổng 7 do Dương / Duy Anh xác nhận | — | — | — |

Thứ tự 2 → 3 là bắt buộc (N-A3 đòi cây sạch; số test/mutation nối tiếp nhau). Kiểm tay trước demo thật vẫn giữ: ghi đè thật 1 lần, duyệt VPN thật qua giao diện, ack 1 cảnh báo thật, đặt lại OTP `quan.tm`.

**Chặng N-A3 — ĐANG MỞ (03/10).** Nối Tổng quan + Cảnh báo với route thật M9 A3. Prompt: `claude/prompt-fe-noi-a3.md` (Project). PHẦN 1 (code + vitest t94… + mutation M56…, không cần stack) làm ngay; PHẦN 2 (`gen:api` + `schema.check.ts` + verify + commit) chờ PR #30 merge và image backend + worker dựng lại. Chi tiết ở 12b "N-A3".

**Chặng N4d — XONG `66691dc` (02/10).** Chi tiết ở 12b "N4d ghi chú". **Kế tiếp:** push + PR `fe-tuananh → dev-tuananh` (không rebase), rồi job CI frontend (12.1).

**Chặng N4c — XONG `136953c` (02/10).** Làm khác ghi chú dưới ở 2 điểm (xem 12b "N4c ghi chú"): không `gen:api`; không xoá handler mà đổi thành "thật + minh hoạ". **Chặng N4d (kế tiếp):** nối ghi đè theo `e510a6e` — hiện `notices` + quyết định gốc sau 201, lỗi `fields:["note"]`, mock chỉ chặn `tkt-demo-`, bỏ câu "có từ Phase 4 (4d)", sửa 2 lỗi thẩm mỹ; verify không tạo dòng ghi đè thật.

*(Ghi chú gốc 01/10, giữ để đối chiếu)* **Chặng "nối thật 4c" (kế tiếp sau F6, 01/10):** `gen:api` → `listApprovals` đọc `{items}`; `ApprovalListItem`/`ApprovalViewP4` theo `schema.gen.ts` (các trường `null` ở mục 1.2, `role_as` có `viewer`, `decided_as`); xoá handler/fixture `apv-demo-*` của hộp thư + xem phiếu (giữ cho `decision` chỉ khi còn cần minh hoạ — quyết khi lập plan); F4-8 thành kiểm danh sách thật; **bắt buộc chạy lại F4-8 và F5-7**. Không tạo phiếu duyệt thật trong verify.

---

## 7. Đạt khi (từng chặng)

| Chặng | Đạt khi |
|---|---|
| Mọi chặng | `npm run lint`, `typecheck`, `build`, `check:dist` sạch; không file nào ngoài phạm vi 4.4 bị sửa; không mã màu/cỡ chữ ngoài token 4.5 (`grep -rn "#[0-9A-Fa-f]\{6\}" src/routes src/components` chỉ trả về rỗng) |
| F0 | `npm run dev` mở trang sáng; `VITE_API_MOCK=1` thì MSW chạy, `=0` thì không; `check:dist` **đỏ** khi cố ý copy worker vào `public/` (thử một lần rồi hoàn nguyên); DevTools → Network: không request nào ra ngoài origin (font tải từ `/assets/`) |
| F1 | Đăng nhập 4 tài khoản demo → thanh bên đúng quyền (L1 **không thấy** mục chính sách; L2 không có mục duyệt). F5 (tải lại) vẫn đăng nhập. `npm run verify` F1-6: 2 tab tải lại cùng lúc × 5 → cả 2 vẫn đăng nhập; vitest t6, t9, t12, t13 xanh. DevTools → Application: không có token trong Local/Session Storage. Manager không OTP → hiện ô OTP |
| F2 | Gửi yêu cầu → thấy `ticket_id`, nhãn trạng thái đổi theo polling, dừng polling khi kết thúc; hội thoại hiện đúng; ca escalate hiện tin escalation; không thấy mã `S_*`; ca E0 chỉ hiện câu trung tính |
| F3 | `long.nh` thấy ticket vừa escalate ở F2; `quan.tm` vào hàng đợi → báo không có quyền (403 thật); ca deny không chọn được "Đã hoàn tất" |
| F4 | Từ chối không lý do → không gửi được; đồng hồ đỏ khi còn < 20%; tab Bảng và JSON cùng hiện đủ trường của một object + hash |
| F5 | Sau A3: `quan.tm` thấy số thật; chỉ số trong `unavailable` hiện "chưa có dữ liệu"; `ha.lt` (L1) không vào được màn Trưởng BP IT; bấm "Đã xem" lần 2 → hiện thông báo 409 thay vì lỗi chung |

---

## 8. Checklist review cho Tuấn Anh (~15 phút mỗi PR)

1. `grep -rn "localStorage\|sessionStorage" frontend/src` → chỉ được có ở chỗ không liên quan token (tốt nhất là không có).
2. `grep -rn "dangerouslySetInnerHTML" frontend/src` → rỗng.
3. `client.ts`: refresh nằm trong `navigator.locks`; CSRF đọc từ cookie lúc gọi; 401 chỉ thử lại 1 lần.
4. Menu/route dùng `permissions`, không `role === "…"`.
5. `mocks/handlers/` **không** có route đã có thật (mục 1.1, và dashboard/alerts **sau khi A3 merge**). Có → xoá, vì sẽ che API thật.
6. `check:dist` có trong CI và xanh.
7. Không file nào ngoài `frontend/` (trừ CI/Makefile đã duyệt).
8. `grep -rn "fonts.googleapis\|cdn\." frontend/src frontend/index.html` → rỗng.
9. Chạy tay 1 ca "Đạt khi" của chặng.

Người review không phải người làm → đúng nguyên tắc "người xác nhận không phải người làm chính" **[Chốt]**.

---

## 9. Nợ API cho giao diện (Tuấn Anh làm đúng phase, không làm bây giờ) [Đề xuất]

| # | Việc | Khi | Lý do |
|---|---|---|---|
| 1 | `TicketView` thêm `deadline` (của lần chờ hiện tại) + `server_now` | **Phase 7** (không có trong spec Phase 4) | P10 §5 đồng hồ nhân viên. Tới lúc đó ẩn đồng hồ nhân viên |
| 2 | ~~`ApprovalView` có `server_now`~~ | — | **Đóng:** 4c đã có `deadline` + đúng object đã băm; giờ máy chủ lấy từ header `Date` (1.3 #5) |
| 3 | `response_model` cho `login`, `me`, `escalations/queue`; kiểu cho `conversation` | Phase 4 hoặc 7 | Sinh kiểu tự động, bỏ viết tay. (Route M9 đã có sẵn `response_model` trong A3) |
| 4 | `GET /api/tickets?mine=1` (lịch sử) | **Phase 7** (spec Phase 4 v0.7 đã chốt không có; đề xuất dời lên Phase 4 của v1.1 bỏ) | Bản 4 đặt lịch sử ngay trên thanh bên nhân viên (kiểu trợ lý chat). Route chỉ đọc, lọc theo `user_id` của token, nhỏ; để tới Phase 7 thì màn chính của nhân viên chạy dữ liệu giả suốt 3 phase |
| 11 | Hình dạng `/api/policy*` theo đề xuất F5 (Q-fe-26): `PolicyView {version_id, version, content, updated_by, updated_at, is_current}`; PUT `{content, base_version_id}` → 201 / 422 `{error:"invalid_policy", errors:[{loc,msg}]}` / 409 `version_conflict` / 403 `reauth_required`; quay lui **tạo phiên bản mới** (append-only, `restored_from`) | Phase 7 | P10 §3.3 chỉ có tên route; frontend F5 đã dựng theo đề xuất này |
| 12 | `GET /api/approvals` phân trang (hoặc con trỏ): tab "Hết hạn" của ha.lt đã chạm trần 50 (`INBOX_LIMIT`) → phiếu cũ hơn không xem được. Không ảnh hưởng an toàn (phiếu hết hạn đã sang L2) | Phase 7, cùng #10 | PLAN-fe mục 7 #35 |
| 5 | `me` thêm tên hiển thị **và tên đăng nhập** | Phase 7 (tuỳ chọn) | Hiện tên thay `user_id`; có tên đăng nhập thì hộp đăng nhập lại (ghi đè) chỉ hỏi mật khẩu (Q-fe-25) |
| 6 | Danh sách ca hệ thống đã tự xử lý mà L1 được phép ghi đè (vd `GET /api/tickets?auto_resolved=1&overridable=1`) | **Phase 7** (Phase 4 chỉ có route ghi đè) | TC23 (L1 ghi đè) cần chỗ để L1 **tìm** ca cần ghi đè; spec mới có route ghi đè, chưa có route liệt kê. Tên route do Tuấn Anh chốt khi làm Phase 4 |
| 8 | `TicketView` thêm câu yêu cầu đã che (`tickets.redacted_request`, cắt ≤ 500) hoặc đưa vào `conversation` lúc tạo ticket | Phase 7 (hoặc sớm hơn nếu phiên backend thấy nhỏ) | Q-fe-18: hiện câu hỏi đầu sau khi tải lại trang |
| 9 | `POST /api/escalations/{id}/close`: `completed` → 422 cho ca E5 **và** E6 (Q-fe-21); UI đã khoá sẵn | Phase 7 (T31) | Khoá ở UI chỉ là tiện; quyền thật do backend |
| 10 | `GET /api/escalations/queue` thêm phân trang (con trỏ `after=(priority, created_at, id)`) và/hoặc `?ticket_id=` | **Phase 7 (T31), ưu tiên cao** | Quá 200 ca mở thì L2 không thấy ca hạng thấp → ca bị bỏ quên (rủi ro FN vận hành). Q-fe-23 |
| 7 | `GET /api/me/notifications` + bảng `notifications` | **Phase 7** [Chốt Q-4-E] | Chuông ẩn tới lúc đó (4.6) |

---

## 10. Rủi ro

| Rủi ro | Dấu hiệu | Xử lý |
|---|---|---|
| Hợp đồng route chưa có lệch khi backend làm thật | Diff `schema.gen.ts` lớn | Chấp nhận; component nhận props nhỏ; kiểu tạm tập trung một file |
| Cookie `Secure` không lưu khi chạy `http://localhost` trên một số trình duyệt [Suy luận] | Đăng nhập được nhưng F5 mất phiên | Dev bằng Chrome; không được thì chạy qua Caddy HTTPS nội bộ. **Không** bỏ cờ `Secure` ở backend |
| Mock che mất API thật | Màn hình chạy dù backend tắt | Checklist mục 8 #5; nhãn "Dữ liệu minh hoạ" |
| Frontend lấn thời gian Phase 4 | Tuấn Anh ngồi sửa UI thay vì soi 4b/4d | Chỉ chạy phiên frontend khi phiên Phase 4 đang chờ (gate, CI, `make verify`); 4b/4d (tầng A) ưu tiên review trước; câu về hợp đồng dashboard → hỏi **Dương** |
| Giao diện chiếm thời gian luồng chính **[Chốt P10 §7]** | Tuấn Anh sửa UI | Tuấn Anh không code UI; chỉ review |
| Agent code theo bản thiết kế cũ | Có thanh trên, màu navy, cỡ chữ lạ | Chỉ Bản 4; checklist 7 "Mọi chặng" grep mã màu |

---

## 11. Chuẩn bị máy (Tuấn Anh, worktree riêng)

Lý do dùng worktree: phiên Phase 4 đang làm trên `dev-tuananh` ở thư mục chính; hai phiên agent cùng một thư mục sẽ đổi nhánh / stage lẫn file của nhau. Worktree = thư mục thứ hai dùng chung `.git`, nhánh riêng.

1. Ở thư mục chính: `git fetch origin` → `git worktree add -b fe-tuananh ../AIP_FA26_G8-fe origin/dev-tuananh`.
2. Stack backend **chạy ở thư mục chính** như thường (`make up` — backend nghe `127.0.0.1:8000`); worktree frontend **không cần `.env`**, không chạy `make up`.
3. Mở agent trong worktree: `cd ../AIP_FA26_G8-fe` → `claude --add-dir ../AIP_FA26_G8/docs/spec` (spec và `docs/spec/claude/*` không được track nên worktree không có — `--add-dir` cho agent đọc bản ở thư mục chính) → `/model opus`.
4. Demo cần `quan.tm` đã cài MFA (Q-fe-14) — secret thêm vào app xác thực (vd app **Mật khẩu** của macOS: mục → Sửa → Thiết lập mã xác minh → Nhập khoá thiết lập; chỉ dán chuỗi base32 sau `Secret:`, không kèm `&issuer`). Lệnh `reset` in secret mới và làm secret cũ mất hiệu lực → sau mỗi lần reset phải cập nhật app. Trước buổi demo thật: reset một lần (secret dev đã từng lộ trong chat). terminal riêng ở thư mục chính, `docker compose exec backend python -m app.auth.mfa enroll quan.tm --by <tên> --reason "demo"`; lưu secret vào app xác thực, không dán vào chat.
5. Máy cần Node `^22.22 || ^24 || >=26` (`node -v`; Q-fe-11 — react-router 8, msw 3, vitest 5 đòi). CI dùng Node 24 LTS. Thư viện frontend cài trong `frontend/node_modules` (bỏ qua bằng `frontend/.gitignore` riêng — không sửa `.gitignore` gốc).
6. **Stack cho verify FE phải ở cấu hình gate3** (node thật, không `FAKE_SCENARIO`). `.env` hiện đặt `FAKE_SCENARIO=approval` + `FAKE_NODE_DELAY` → sau mỗi `make verify` của Phase 4 (bước cuối trả về `.env`) backend chạy node giả gate2: mọi ticket dừng ở "Chờ IT duyệt", thẻ `[fake:tcXX]` ra E9. Trước verify FE (hoặc khi test tay): kiểm `docker compose exec backend printenv FAKE_SCENARIO` → phải rỗng; không rỗng thì (thư mục chính, khi Phase 4 **không** dùng stack):
   `FAKE_SCENARIO= FAKE_NODE_DELAY= docker compose up -d --no-deps --force-recreate --wait --wait-timeout 120 backend worker`
   Phải rỗng **cả hai** biến — `FAKE_NODE_DELAY` có mà `FAKE_SCENARIO` rỗng → backend từ chối khởi động. Không sửa `.env`, không `--build`. Sau đó **làm nóng RAG**: `make gate3 S="preflight tc04"` (≈ 22 s, không cần OTP; phải 10 PASS) — tránh F2-1 đỏ E2 `rerank deadline` khi ml-service lâu không được gọi. Báo phiên Phase 4 trạng thái stack. Mỗi lúc chỉ một bên dùng stack (verify FE ~5–15 phút; `make verify G=23` Phase 4 ~14 phút). Lệnh có `!` chỉ gõ trong phiên Claude Code; ở Terminal thường bỏ `!` (zsh hiểu `!` là phủ định → lệnh sau `&&` không chạy).
7. Hợp nhất: mỗi DỪNG xanh → commit trên `fe-tuananh`. **Cập nhật 02/10:** nhánh đã được push lên `origin/fe-tuananh` (tới `136953c`) → **không rebase nữa** (rebase đổi lịch sử, buộc force-push — trái luật). Cách làm: `git push origin fe-tuananh` (tiến thẳng) → mở MỘT PR `fe-tuananh → dev-tuananh` cho cả 10 commit; nếu GitHub báo xung đột thì `git merge origin/dev-tuananh` vào `fe-tuananh` (FE chỉ đụng `frontend/` nên ít khả năng). ~~Trước PR: `git fetch origin && git rebase origin/dev-tuananh`.~~

---

## 12. Xây song song — ảnh hưởng tới các phase/luồng khác (kiểm 29/09/2026)

Đang chạy cùng lúc: **Phase 4** (Tuấn Anh, `dev-tuananh`), **M9 luồng A** (Lưu Dương, `m9-luuduong`), **M9 luồng B** (Tạ Duy Anh, `m9-duyanh`), **frontend** (Tuấn Anh, worktree `fe-tuananh`).

### 12.1. File — không đụng nhau nếu giữ đúng chủ

| File/thư mục | Chủ | Frontend có cần? | Biện pháp |
|---|---|---|---|
| `frontend/**` | Tuấn Anh (phiên agent frontend) | Có | Không ai khác sửa [Suy luận: kế hoạch M9 không liệt kê `frontend/`] |
| `backend/**`, migration | Tuấn Anh (phiên Phase 4); migration M9 chỉ Dương | Không | Phiên frontend không sửa; thiếu API → ghi vào mục 9 |
| `docker-compose*.yml`, `settings.py`, `main.py` | Dương (khối M9) + Tuấn Anh | **Không cần tới Phase 7** (dev dùng Vite proxy) | Service Caddy phục vụ `dist/` thêm ở Phase 7, sau khi M9 merge, khối riêng |
| `.github/workflows/ci.yml`, `Makefile` | Tuấn Anh | Có (job `frontend`, `make fe-check`) | **Chỉ Tuấn Anh thêm**, một lần, **sau khi chặng 4a merge** (4a sửa cả hai file: CI Node 24 + `ubuntu-24.04`, `make verify`). Job frontend dùng cùng bản action Node 24 mà 4a chọn; khối riêng ở cuối file. Trước đó TV chạy `npm run lint/typecheck/build/check:dist` tay và dán kết quả vào PR |
| `docs/spec/**` | Tuấn Anh / Claude chat | Không | Agent frontend in "Spec cần sửa (fe)" trong MẪU B |

### 12.2. Hợp đồng dùng chung

| Chỗ giao | Ảnh hưởng | Biện pháp |
|---|---|---|
| M9 A3 → dashboard | Bản 4 ban đầu có chỉ số tự đặt (tỉ lệ có người duyệt, thời gian duyệt TB, chi phí) không có trong API M9 | **Đã sửa** B4MgrDashboard: chỉ dùng trường M9 §5.1 (`automation_rate`, `escalation_rate_weighted`/`raw`, `deflection_rate`, `approval_expired_count`, `decided_by_distribution`, `top_matched_rules`, `e3_cases`, cảnh báo + ack, `override_count` = chưa có dữ liệu) |
| Chỉ số AI (`/api/dashboard/ai`) | Bản 4 chưa vẽ màn này | [Đề xuất] F5 làm màn đơn giản: bảng tên chỉ số + giá trị + "chưa có dữ liệu" cho mục `unavailable`; không cần thiết kế thêm |
| `dashboard:read:own` (L1) | A3 cho L1 xem số của phiếu giao cho mình; Bản 4 không có màn này | [Suy luận] Không bắt buộc theo P10; để Nên có, không làm trong F4 |
| Phase 4 (hộp thư, xem phiếu, ghi đè) | **Đã chốt** ở `phase4-thiet-ke-chi-tiet.md` v0.7 → MSW dựng đúng hợp đồng (3.2) | Phase 4 không sửa `frontend/`, không migration, không sửa `main.py` → không đụng nhau. Khi 4c/4d merge: `gen:api`, xoá handler `approvals`, `override` |

### 12.3. Cổng và lịch

| Việc | Ảnh hưởng | Biện pháp |
|---|---|---|
| Cổng thủ công Phase 4 | **Không còn phụ thuộc frontend** [Chốt Q-4-F: `make gate4` qua API + biên bản] | F4 không gấp; làm sau F0–F3 |
| Cổng 7 | Người xác nhận phải khác người làm UI | Tuấn Anh làm UI nên **Dương hoặc Duy Anh** chạy cổng 7 thủ công + ký biên bản |
| Tải review của Tuấn Anh | Phase 3 + ~9 PR M9 + 7 PR frontend cùng tuần | Gộp PR frontend: F0+F1 một PR, F2+F3 một PR trước demo thứ Sáu; review theo checklist 8 (~15 phút) |
| Invariant backend (Phase 3) | Không bị ảnh hưởng — UI chỉ đọc API, không đổi luồng graph | Không cần làm gì |

### 12.4. Cần Tuấn Anh quyết

1. ~~Dời `tickets?mine=1` / route liệt kê ghi đè lên Phase 4~~ → đã giải quyết: spec Phase 4 v0.7 không có, để Phase 7 (9 #4, #6).
2. ~~Ai làm frontend?~~ → **Tuấn Anh tự làm** (30/09), worktree `fe-tuananh`, mục 11.

---

## 12b. Chốt khi lập PLAN-fe (30/09/2026, MẪU A của agent frontend)

| Mã | Chốt |
|---|---|
| Q-fe-1 | Giữ sandbox (không bật `allowLocalBinding`). Agent kiểm tĩnh; lệnh cần mạng/cổng (`npm install`, `gen:api`, `dev`) Tuấn Anh chạy bằng `!` hoặc terminal riêng rồi dán kết quả |
| Q-fe-2 | Code đã có tin `answer` (kèm `sources` 3 khoá `chunk_id, title, heading_path`), `question`, `result`, `escalation` (`domain/messages.py`) → **Citation dùng nguồn thật**, F2 không còn dữ liệu giả. Sửa 1.3 #4. `kind` lạ (vd `rejection` từ 4c) → hiện `text` dạng tin thường, không lỗi |
| Q-fe-3 | `errors.ts` đọc cả hai dạng lỗi `{detail}` và `{error:"invalid_request", fields}`; refresh 401 **hoặc** 403 (`csrf`) = hết phiên, về đăng nhập, không lặp; `mfa_not_enrolled` có câu riêng; 503 health (degraded) ≠ `runtime:down` |
| Q-fe-4 | P6 §4 + P10 §3.2 **[Chốt]**: ghi đè cần đăng nhập lại ≤ 10 phút; phase4 §7.1 P1 thiếu bước này → báo phiên Phase 4 thêm `require("decision:override", recent_login=True)` ở 4d. UI: 403 `reauth_required` → hộp nhập lại mật khẩu (+ OTP nếu manager) gọi `login` rồi gửi lại **một** lần |
| Q-fe-5 | MSW cho `decision` chỉ chặn id tiền tố `apv-demo-`; id khác đi thẳng API thật. Ngoại lệ duy nhất của checklist 8 #5; xoá cùng handler `approvals` khi 4c merge |
| Q-fe-6 | L1/L2 có `ticket:read:any` → hội thoại ở chi tiết L2 dùng `GET /api/tickets/{id}` thật; chỉ mock `close` |
| Q-fe-7 | Thêm 2 token `sidebar` `#F7F8FA`, `selected` `#E6EEF7` (`#0055A4` trên nền này ≈ 6,5:1); `#C7C7CC`, `#E9E9EE` quy về token sẵn có; mọi nút lớn cao 44 |
| Q-fe-8 | Ẩn mục menu chưa có màn. Trang đầu theo quyền: `dashboard:read:all` → Tổng quan; `approval:decide` → Hàng đợi duyệt; `escalation:handle` → Hàng đợi escalate; còn lại → chat nhân viên. Không so tên role |
| Q-fe-9 | Hiện `user_id` + chữ tắt; lời chào không tên (9 #5) |
| Q-fe-10 | Hộp ghi đè hiện đủ 4 lựa chọn; 422 `same_as_original` hiện câu dễ hiểu |
| Q-fe-11 | `engines.node = "^22.22.0 \|\| ^24.0.0 \|\| >=26.0.0"` (thay `>=20`). TypeScript ghim **5.9.3** — ngoại lệ duy nhất không lấy latest (TS 7 lệch peer openapi-typescript 7.13) |
| Q-fe-12 | **Agent tự kiểm, Tuấn Anh chỉ gõ 1 lệnh** (từ F1): `npm run verify` = lint + typecheck + vitest + build + check:dist + check:style + Playwright headless Chromium (dev không mock / có mock / preview; từ F1: đăng nhập thật nếu `/api/health` = 200, không thì BỎ QUA). Ghi `frontend/.verify/summary.txt`; agent tự đọc. Giữ sandbox: lệnh chạy bằng `!`. Playwright đưa lên sớm vì cổng 7 vốn dùng Playwright (P10 §6) |
| Q-fe-13 | **Chia sẻ access token giữa các tab bằng `BroadcastChannel`** (security-reviewer C9-1): backend `validate_access` đòi đúng dòng `sessions` còn sống, mỗi refresh thu hồi dòng cũ → tab A refresh làm token tab B chết → hai tab refresh qua lại. Token vẫn **chỉ trong bộ nhớ** (kênh là nhắn tin cùng origin, không phải storage). Tin có kiểm dạng (loại, `user_id`, mốc thời gian), bỏ tin sai dạng / cũ hơn / khác người dùng (khác người → hết phiên); không bao giờ gửi CSRF hay refresh token; đăng xuất phát tin `logout` → các tab xoá token. Trong khoá: nếu token hiện tại đã khác token vừa bị 401 → gửi lại bằng token mới, **không** refresh; 50 ms chờ tin chỉ là lớp phụ. **Không** sửa backend (thu hồi theo phiên là thiết kế an ninh của P6) |
| Q-fe-14 | `quan.tm` chưa cài MFA (backend trả `mfa_not_enrolled`) → Tuấn Anh cài bằng CLI `app.auth.mfa enroll` ở **terminal riêng** (lệnh in secret — không chạy qua `!`, không dán vào chat). Chuẩn bị demo phải có bước này (ghi §11; báo phiên backend thêm vào `mock_services/README.md`) |
| Q-fe-15 | Tải lại trang đúng lúc refresh đang chạy có thể làm mất cookie mới → lần sau bị coi là dùng lại token → thu hồi cả họ. **Chấp nhận cho demo, không nới backend** (thời gian ân hạn làm yếu phát hiện dùng lại token). Ghi việc treo Phase 7 để cân nhắc |
| Q-fe-16 | Đăng xuất = nút biểu tượng 32 px (`aria-label` + tooltip "Đăng xuất") ở hàng người dùng; tên mục theo **quyền**, dùng chung cho mọi vai trò ("Hàng đợi escalate") — không đổi theo role |
| Q-fe-17 | Không có cookie `csrf` → không gọi refresh (backend chắc chắn trả 403 `csrf`); thêm 1 test + 1 mutation |
| Q-fe-18 | `TicketView.conversation` không có câu yêu cầu đầu. (b) Làm ngay: giữ câu vừa gõ **trong bộ nhớ**, chỉ hiện khi 202 có `notices` rỗng (guard không che gì); có che → "Nội dung đã được ẩn bớt thông tin nhạy cảm". Tiêu đề chỉ lấy từ câu yêu cầu. Tải lại trang → "Yêu cầu của bạn". (a) Nợ API #8 |
| Q-fe-19 | Backend (`domain/answer.py` `render_answer`) đã nối "Nguồn:" vào cuối câu trả lời → frontend chỉ cắt đoạn đó **khi khớp đúng** danh sách `sources`; không khớp thì giữ nguyên (lặp chứ không mất). Không sửa backend (văn bản thuần vẫn cần nguồn cho kênh khác) |
| F2 ghi chú | `check:style` luật 4 chặn plugin/API dựng HTML thô (`rehype-raw`, `allowDangerousHtml`, `innerHTML`…) — react-markdown 10 tự hiện HTML thô thành chữ, luật này giữ lớp bảo vệ đó. Verify F2 cần backend cấu hình gate3; ca hỏi thêm kiểm bằng vitest t25 |
| Q-fe-20 | Verify F3-4 dùng `an.nv` (không có `escalation:handle`) thay `quan.tm` (bắt buộc OTP, verify không tự đăng nhập được); kiểm cả trang "không có quyền" lẫn gọi thẳng API → 403. `quan.tm` kiểm tay khi làm F5 |
| Q-fe-21 | Khoá "Đã hoàn tất" cho **E5 và E6** (B20 §4.3 + decisions Q2 [Chốt]); E6 có lý do riêng, không banner E5. Phase 7 T31: backend phải trả 422 cho cả hai (nợ API #9) |
| Q-fe-22 | Tên nhóm và huy hiệu lấy từ `label` của server (bảng seed); cùng `priority` → gộp nhãn khác nhau ("Hạ tầng / Lỗi hệ thống"). Không tô màu theo mức (tránh bảng ưu tiên thứ hai ở frontend) |
| F3 ghi chú | Hàng đợi gọi `limit=200` (tối đa) và hiện số ca; verify F3 dùng lại ticket E3/E0 của F2 (mỗi lượt verify chỉ tạo 3 ticket). Escalation dev không đóng được tới Phase 7 → hàng đợi dài dần là bình thường |
| Q-fe-23 | Hàng đợi dev > 200 ca mở (API tối đa `limit=200`, sắp ca cũ trước, chưa có phân trang) → ca hạng thấp mới tạo không hiện. **Không** `down -v` (luật dự án; mất MFA `quan.tm`, KB, dữ liệu Phase 4). Verify F3 kiểm theo điều kiện: có trong 200 ca → kiểm vị trí nhóm; ngoài 200 ca **và** đủ 200 → kiểm khung cảnh báo "quá 200 ca" (hành vi đúng của UI); ngoài mà < 200 → FAIL. F3-2 dùng ticket mới nào đang hiện. Nợ API #10 |
| Q-fe-24 | Ticket fixture `tkt-demo-*` không có ở backend → GET thật 404. Nút "Ghi đè…" theo quyền `decision:override` + dữ liệu approval (phiếu đã quyết/hết hạn có link "Xem ticket · Ghi đè…"; phiếu đang chờ không có), **không** phụ thuộc GET ticket. GET lỗi → câu trung tính "Chưa tải được chi tiết yêu cầu.". Không mock GET ticket (P8 "thật"); fixture `tkt-demo-*`/`apv-demo-*` xoá cùng handler khi 4c/4d merge |
| Q-fe-25 | `me` không có tên đăng nhập → hộp đăng nhập lại hỏi tên + mật khẩu (+ OTP). Một luồng login duy nhất (`auth/useLoginSteps.ts` dùng chung với LoginPage). So `sub` token mới với `user_id` cũ: cùng người → gửi lại ghi đè đúng 1 lần; khác người hoặc không đọc được `sub` → không gửi, `queryClient.clear()` + xoá "Gần đây", về trang đầu người mới kèm câu báo (history state, không vào URL). Mật khẩu/OTP chỉ trong state hộp thoại, xoá khi đóng |
| F4 ghi chú | F4-5: MSW 3 cho mọi request (cả passthrough) qua worker → `fromServiceWorker()` luôn true; kiểm bằng 404 `not_found` thật + header `server: uvicorn`. 4b thêm 403 `permission_denied` (xung đột lợi ích theo chuỗi quản lý) → câu 403 trung tính chung, test t51. Tab cũ khi hộp đăng nhập lại chuyển người khác: bị đăng xuất qua kiểm `sub` của BroadcastChannel (`client.ts:84, 145–147`, test t9c/t15/t16); lớp dự phòng `takeRefreshed` so `sub` (`client.ts:125–128`) **chưa có test riêng** → làm đầu F5. Lỗi thẩm mỹ để F6: giá trị dài trong bảng rủi ro ngắt giữa chữ; nội dung lờ mờ sau thanh quyết định (nền 95%) |
| Q-fe-26 | Kiểu Policy bám cột `policy_versions` (`version` chuỗi, `updated_by/at`, `is_current`); quay lui = **tạo phiên bản mới** chép nội dung bản cũ (lịch sử chỉ nối thêm, `restored_from`), không lật `is_current` tại chỗ. Đề xuất — chốt lại ở Phase 7 (nợ API #11) |
| Q-fe-27 | `/alerts` "Tất cả" = gọi không kèm `status`; máy khách sắp critical → warning → info rồi `window_start` giảm dần |
| Q-fe-28 | 503 giả bật bằng cookie `mock_monitor=unavailable`, chỉ handler MSW đọc |
| Q-fe-29 | Chặn fixture lọt build 2 lớp: plugin Vite `no-mocks-in-build` + `check:dist` quét `apv-demo-`/`tkt-demo-` (đã thử đỏ cả hai) |
| Q-fe-30 | Tách `useReauthRetry` dùng chung cho ghi đè (F4) và chính sách (F5); t47/t48 không sửa, M23 vẫn đỏ |
| Q-fe-31 | "7/30 ngày" = ngày lịch tính cả hôm nay, `from` = 00:00 giờ VN; JSON lỗi cú pháp → tab Bảng báo "sửa ở tab JSON" |
| F5 ghi chú | `JSON.parse` quyết định hợp lệ; bộ phân tích tự viết chỉ định vị dòng/cột; khoá trùng → cảnh báo vàng (không chặn Lưu); giới hạn 64 KB tính theo byte UTF-8. `unavailable` → "Chưa có dữ liệu", `null` → "—", không bao giờ hiện 0 thay null. 503 → không còn số cũ. Verify quan.tm: `VERIFY_MGR=1`, Chromium có giao diện, người nhập OTP **một lần**; script dừng sau 2 lần OTP sai (tránh khoá — 5 lần/10 phút → khoá 15 phút). Lệch Bản 4: PLAN-fe mục 7 #20–23 (không nút Mô phỏng, tab Bảng chỉ xem, thêm "Tải lại", `/alerts` chưa có bản vẽ) |
| Q-fe-32 | Thanh quyết định L1 nằm **ngoài** vùng cuộn (anh em với vùng cuộn, `shrink-0`), nền trắng đặc + viền trên, không `sticky`, không nền trong suốt; bảng khoá–giá trị `wrap-anywhere` + `break-normal` (không ngắt giữa chữ) — sửa 2 lỗi thẩm mỹ ghi ở F4 |
| Q-fe-33 | Trả lời cha nhiều ý (`replyTicket`) ghi vào hội thoại thành **một tin người dùng đã che** ("Ý 1: Đã ổn · Ý 2: LAP-0342"), round cũ chuyển chỉ đọc |
| Q-fe-34 | Nhãn ticket cha: "Đang xử lý các ý" / "Cần bạn phản hồi" / "Các ý đã có kết quả — xem từng ý ở trên." |
| Q-fe-35 | Câu lỗi theo **loại khối** của tin tổng hợp; 422 `fields` → lỗi dưới **đúng khối** của `child_id`, không lỗi chung |
| F6 ghi chú | MSW nhiều ý chạy 3 round theo P1 §8.2, chỉ chặn id tiền tố `tkt-demo-multi-`. **Chống duyệt phản xạ** chỉ cho "Đồng ý" (< 5 s xem → hộp "Xem lại"/"Vẫn đồng ý"; đo bằng `performance.now`, đồng hồ bắt đầu khi chi tiết **hiện**); "Từ chối" không bao giờ bị chặn (không đẩy người duyệt bỏ qua nghi ngờ — giảm FN); body quyết định **không đổi** (server tự tính thời gian xem từ `first_viewed_at`). Nút gợi ý chỉ điền ô nhập + focus, **không gửi**. Tách `Sources.tsx`. t44/t45/t51 thêm `viewedLongEnough()`, không đổi assert. Claude chat kiểm độc lập trên bản sao: typecheck/lint/check:style/check:dist PASS, vitest 303/303, 3 đột biến tự cài đều bị bắt. **Đề xuất hợp đồng T20** (`/reply`, `children_progress`) ở PLAN-fe mục 8 → chuyển sang tài liệu Phase 5 |
| Q-fe-36 | Fixture `apv-demo-viewer` trả `role_as:"viewer"` cho mọi người có `approval:decide` (kiểm trạng thái giao diện; phân quyền thật do backend) |
| Q-fe-37 | N4c không dùng test-writer; `security-reviewer` soát một lần trước DỪNG 2 (P4 viewer, P6 mock) — 12/12 PASS |
| Q-fe-38 | Hộp thư đã có dữ liệu mà lần tự tải lại lỗi (kể cả 403) → **giữ danh sách cũ** + dòng `role="status"` "Chưa cập nhật được hộp thư — danh sách dưới đây có thể đã cũ." (`inbox-stale`); đang ở tab khác mà truy vấn `pending` lỗi → "Chưa cập nhật được số phiếu chờ duyệt — con số trên tab có thể đã cũ." (`inbox-count-stale`). Lý do: số đếm là tín hiệu duy nhất về phiếu mới (giảm bỏ sót) |
| N4c ghi chú | **Không `gen:api`**: route 4c trả `JSONResponse` không `response_model` → openapi không sinh kiểu; kiểu ở `contracts-tam.ts`, nguồn `backend/app/api/approvals.py @b457e6e` (nợ API #3). `listApprovals` chặt một hình dạng `{items}`: mảng trần / một phần tử hỏng → 502 `invalid_inbox_body` (không lặng lẽ bỏ phiếu). Trường `null` không ẩn phiếu: `action_type:null` → "Chưa rõ hành động — mở phiếu để xem"; `department:null` → "—"; `risk:null` → "Chưa có đánh giá rủi ro cho phiếu này."; `procedure:null` → "(không có)". `role_as:"viewer"` hoặc giá trị lạ → không thanh quyết định (fail-closed) + câu "…quyền giám sát — không thể quyết định.". Bỏ trang "có từ Phase 4 (4c)". **Mock (dev:mock) = thật + minh hoạ**: handler list gọi backend thật trước, thật không 2xx → trả nguyên; gộp thêm `apv-demo-*`, header `Date` lấy từ thật; xem phiếu chỉ chặn id `apv-demo-`; backend tắt → 503, không trả riêng minh hoạ (**ngoại lệ có chủ đích của checklist 8 #5**). Verify F4-8 chỉ mở phiếu thật đã quyết/hết hạn (mở phiếu `pending` sẽ ghi `first_viewed_at`). Test t79–t87, mutation M38–M47; Claude chat kiểm độc lập 3 lần (vitest + 5 đột biến tự cài). Còn lại: gộp thật + minh hoạ chưa thấy trên stack (ha.lt không có phiếu chờ) — kiểm tay tuỳ chọn; 2 lỗi thẩm mỹ ("đã chuyển l2", dấu `"` rơi dòng ở bảng rủi ro) → sửa ở N4d |
| Q-fe-39 | 201 mà thân JSON hỏng/rỗng (client ném lỗi trước khi đọc được) → **báo lỗi, không báo "đã ghi"**: không chắc đã ghi thì không báo thành công; gửi lại ra 409 `already_overridden` là đúng sự thật, không ghi trùng |
| Q-fe-40 | N4d: `security-reviewer` một lần trước DỪNG 2 — 18/18 PASS, 5 điểm nghi (1 sửa, 1 thành Q-fe-41, 3 giữ) |
| Q-fe-41 | Chỉ **status 201** mới là "đã ghi"; 2xx khác → `ApiError(502,"unexpected_override_status")`, hộp báo lỗi chung |
| N4d ghi chú | `overrideTicket` trả `OverrideRecorded \| null` (201 + thân đọc được nhưng sai dạng → `null` = đã ghi, không hiện chi tiết). Sau 201 hộp hiện "Quyết định ban đầu của hệ thống: <nhãn>" và, khi `notices` ≠ [], câu "Ghi chú đã được ẩn bớt thông tin nhạy cảm" (không hiện nguyên văn notices, không nhắc lại ghi chú). 422 `fields` có `note` (hoặc `body.note`) → lỗi ngay dưới ô ghi chú, giữ dữ liệu đã nhập. 403 `forbidden` → "Bạn không được ghi đè ticket này (không có quyền, hoặc đây là ticket do chính bạn gửi)." (server dùng một mã cho hai nguyên nhân). Câu mô tả hộp thêm "(không gỡ được)". **Mock**: handler ghi đè chỉ chặn id `tkt-demo-`, id khác `passthrough()` ngay — bỏ 201 giả cho ticket thật; ở dev:mock ghi đè ticket thật là ghi thật, vĩnh viễn (README). Bỏ câu "có từ Phase 4 (4d)". Thẩm mỹ: dải chỉ đọc giữ "L2"; bảng khoá–giá trị: giá trị ≤ 24 ký tự xuống dòng nguyên khối (`flex-wrap`, không `nowrap` để không bị cắt đuôi). **Verify không ghi đè ticket thật**: F4-10 gửi tới uuid ngẫu nhiên → 404 `not_found` (route chưa có thì là `Not Found`). Còn lại: 201 thật chưa verify tự động (cố ý — 1 dòng audit vĩnh viễn, làm bẩn chỉ số override của M9) → kiểm tay một lần trước demo. Test t88–t93, mutation M48–M55; Claude chat kiểm độc lập 2 lần (3 đột biến tự cài). Lệch spec: thứ tự kiểm thật là …`same_as_original` → guard 503 → 422 note rỗng sau khi che → 409 `already_overridden` (PLAN-fe mục 7 #36) |
| Hợp đồng `/api/alerts` M9 chốt trước (Q-M9-A3-2, issue #10, 02/10 — thiết kế, chưa có code) | `GET /api/alerts` → 200 **`{"items":[AlertView], "truncated": bool}`** (không phải mảng trần); tham số `status=open\|acked` (trống = tất cả), `audience=dev\|manager\|ops` (tuỳ chọn), `limit` 1–200 (mặc định 200); xếp `created_at` giảm dần. `AlertView` = các trường FE đang dùng + **`audience` (mảng)**. `POST /api/alerts/{id}/ack` (không body) → 200 `AlertView`; 401/403/404 `not_found`/409 `already_acked`/422; 503 `monitor_unavailable` chỉ ở GET. **Lệch với FE F5 (sửa ở chặng "nối A3", không sửa trước):** (1) `listAlerts` đang đòi mảng trần → đổi sang đọc chặt `{items, truncated}`; (2) kiểu `AlertItem` thêm `audience`; (3) khối Tổng quan gọi `?status=open&limit=5` thay vì lấy hết rồi cắt 5; (4) `truncated=true` → hiện dòng "Còn cảnh báo chưa hiển thị" (không lặng lẽ thiếu); (5) mock: `{items}`, bỏ 503 ở ack. Khớp sẵn: `alert_id` số, ack 200 trả cảnh báo, 409 `already_acked`, 404, mặc định "Đang mở". **`audience` (M9 trả lời, Q-M9-A3-1):** không truyền → server trả TẤT CẢ (dev + manager + ops), không lọc theo vai trò; ai có `alert:read` đều thấy hết (hiện chỉ manager). **FE để trống `audience`, KHÔNG mặc định `audience=manager`** (sẽ che cảnh báo dev/ops mà không ai khác xem được). Trường `audience` chỉ để hiện nhãn; nếu sau này thêm bộ lọc theo nhóm thì là lựa chọn của người dùng, mặc định "Tất cả"; giá trị lạ → 422. M9 đồng ý 5 điểm lệch, không đổi gì phía server |
| Nợ test (02/10) | t61 (màn Chính sách, `manager.test.tsx`) nhạy tải máy: đỏ 1 lần vì hết giờ chờ ngay sau build, 5 lượt chạy lại xanh → nới thời gian chờ ở chặng sau (không sửa trong N4d vì ngoài phạm vi) |
| Gửi Phase 4 (từ soát N4d) | Ở `e510a6e`, privacy guard chạy trước bước INSERT quyết định 409 `already_overridden` → gửi lại vẫn ghi thêm sự kiện `privacy_secret_redacted`. Không ảnh hưởng an toàn, làm nhiễu nhật ký; Phase 4 cân nhắc ở 4d DỪNG 2 |
| N-L2Q (06/10) | 3 file `routes/l2/{EscalationQueue.tsx,queue.ts,escalations.test.tsx}` sửa tối 03/10 ngoài quy trình chặng (+218 −24): ô tìm (bỏ dấu, mọi từ phải khớp), thẻ nhóm ưu tiên, thu gọn nhóm, phân trang 10 ca/nhóm. Tuấn Anh chốt GIỮ. **Chốt cho chặng:** không dòng nào bị ẩn mà thiếu con số bên cạnh; không sắp lại thứ tự server; tìm chỉ trên ca đã tải — chạm trần 200 thì nói rõ "chỉ tìm trong 200 ca đã tải"; tự tải lại không làm mất chữ tìm / trang / thu gọn; trạng thái chỉ trong bộ nhớ; verify tìm ticket bằng ô tìm (ca mới nằm cuối nhóm, không còn ở trang 1) + thêm F3-8. Phân trang phía server vẫn là nợ API #10 (Phase 7) |
| N-A3 phần 1 kết quả (07/10) | Chưa commit: 21 file `frontend/` (+1621 −701; xoá 4 file mock/fixture dashboard + alerts). Test t109–t119 (vitest 447 → 522), mutation M79–M95 đều chết; Claude chat kiểm độc lập 2 lần (522/522; 11 đột biến tự cài — 1 cái sống ở lượt đầu: `ackAlert` bỏ điều kiện `status === "acked"` → đã thêm ca t113 + M93). **Q-fe-44 = A:** verify gửi thẳng 3 lời gọi (ack id 2^53−1 → 404; dashboard `from` thiếu múi giờ → 422; `alerts?status=` → 422) bằng Bearer đọc từ header của request mà chính SPA gửi, token vào `secrets` trước mọi log, không refresh/logout (F4-10 thật ra gửi qua giao diện — prompt gốc ghi sai). **Đổi so với prompt:** nhãn `by_group` không ghi con số trọng số (frontend không chép `N3_WEIGHTS`); `ackAlert` trả `AlertItem \| null` (null = 200 mà thân không đọc được / sai id / chưa `acked` → không báo thành công, tải lại); sau ack chỉ sửa cache của bộ lọc đang `success` (không biến query đang lỗi thành dữ liệu cũ); mọi bảng nhãn tra theo khoá server trả ở màn Trưởng BP IT + `AlertRow` + `PolicyTable` dùng `ownEntry`/`labelOf` (`Object.hasOwn`) — khoá `__proto__`/`constructor` không làm vỡ màn; thêm định dạng "< 0,0001" (USD) và "< 1 ms". **t61 (nợ test) đã sửa đúng gốc:** test lấy ô JSON bằng lệnh không chờ trong khi ô chỉ có sau `GET /api/policy` → đổi sang chờ chính ô đó. **Nợ ghi lại (chặng riêng):** tra `X[k]` qua prototype với khoá server trả còn ở `api/errors.ts` (CODE_MESSAGES), `employee/status.ts`, `ChatPage.tsx`, `l1/inbox.ts`, `l1/ApprovalDetail.tsx`, `l1/ApprovalQueue.tsx`, `DigestMessage.tsx`, `employee/multi.ts`, `Sidebar.tsx`. Ở dev:mock, Tổng quan + Cảnh báo nay là dữ liệu thật và "Đã xem" là ghi thật (README). F5-2 đòi `multi_intent_*` còn trong `unavailable` — Phase 5 có nguồn thì bước này đỏ, cố ý |
| Sự cố tc04 + commit phần 1 (08/10) | **Đổi kế hoạch:** PR #30 chưa merge → chốt phần 1 thành commit cục bộ `c063134` sau verify không `VERIFY_MGR` (không push: push sẽ đưa phần 1 vào PR #27; nếu #27 merge trước #30 thì verify có `VERIFY_MGR=1` trên `dev-tuananh` đỏ ở F5-6). Verify 08/10 01:14:15: 44/0/8 (8 BỎ QUA = F5-1…6, F2-3, F3-7), F2-1 19,7 s; F3-8 "phân trang: không đủ dữ liệu" (13 ca / 4 nhóm). Claude chat đọc `summary.txt` trên máy và kiểm commit (21 file đều trong `frontend/`, không file nguồn nào đổi sau giờ verify, thông điệp không dòng AI). **Sự cố stack (không phải frontend):** `make gate3 S="preflight tc04"` đỏ 6/4 hai lần (07/10 ~23:40). Audit: B8 `retrieval_error`, `error_stage: rerank`, `detail: deadline` → `rag_system_error` → L2. Cơ chế: worker gọi ml-service qua HTTP (`ml/client.py`, worker không nạp model), mỗi lần rerank hạn 18 s, thử 3 lần → bị `rag_deadline_s = 50` cắt (B6→B8 = 49,6 s). Embed cùng lượt thành công → URL/token/mạng thông. Log ml-service: rerank 10 đoạn ~6 KB mất 9,3–15,4 s lúc verify xanh 07/10 chiều, 13–62 s lúc đỏ; máy đang chạy pin. Cắm sạc → tc04 10 PASS, verify xanh. Làm nóng của gate3 (1,8 s) gửi 10 bản sao một câu ~90 ký tự nên không so được với lượt thật. **Rủi ro demo:** biên mỏng ngay cả lúc xanh (≤ 15,4 s / 18 s); lối thoát có sẵn `RAG_RERANK_K=5` (`.env.example`) — việc của phiên backend quyết. Luật chạy verify thêm: cắm sạc suốt lượt |
| N-L2Q kết quả (07/10) | Commit `a98d238`, 6 file `frontend/`, +1666 −101. Test t94–t108 (vitest 384 → 447), mutation M56–M78 đều chết; Claude chat kiểm độc lập 2 lần trên bản sao Linux (447/447; 13 đột biến tự cài đều bị bắt) + 1 lượt soát độc lập bằng agent phụ trước khi viết prompt. **Q-fe-42 = A:** chế độ tìm có trạng thái thu gọn/trang riêng, đặt lại khi danh sách từ tìm đổi, xoá ô tìm → về trạng thái đã lưu. **Q-fe-43 = B:** ca mới (so `escalation_id` với lần tải trước) rơi vào nhóm đang thu gọn hoặc khác thẻ đang chọn → dòng `queue-missed` "Có N ca mới ở nhóm đang ẩn hoặc thu gọn: …" + nút "Hiện các nhóm này"; không dùng bảng hạng ở frontend; **chỉ có vitest** (bước verify chỉ đọc không tạo được ca mới). Không dùng `Segmented` (không xuống dòng, khoá chuỗi, thuộc `routes/manager/*`). Verify: F3-1/2/3/5/6 tìm ticket bằng ô tìm; thêm F3-8 (chỉ đọc: đi hết mọi trang mọi nhóm > 10 ca, thu gọn, tìm rồi xoá ô, 0 lời gọi ghi). **Lỗ còn lại:** lượt verify 07/10 hàng đợi chỉ có 9 ca / 4 nhóm → phần **phân trang chưa chạy trên stack thật** (F3-8 ghi "không đủ dữ liệu", chỉ có vitest) — kiểm lại khi một nhóm > 10 ca; nút thanh trang `disabled` làm mất tiêu điểm bàn phím (ghi nhận); gõ "E3" khớp cả mã ticket chứa "e3" (khớp thừa, chấp nhận); nhãn nhóm nay nằm trong `<button>` → nhãn có chữ "duyệt" sẽ làm t34/F3-5 đỏ. Bài học: lượt verify 06/10 16:38 đỏ ở F2-1 (E9 sau 2,8 s) vì bỏ bước kiểm `printenv FAKE_SCENARIO` (stack đang `approval`) |
| N-A3 (03/10) | Nguồn: code `origin/dev-luuduong` @ `3f15afb` (Claude chat đọc trực tiếp `api/alerts.py`, `api/dashboard.py`, `monitor/queries/*`, `monitor/metrics.py`; không đọc được mô tả PR #30). **Lệch so với FE F5:** danh sách cảnh báo là `{items, truncated}` (FE đòi mảng trần) · `AlertView` có `audience` · dashboard lồng `metrics` + `scope` (FE đọc phẳng) · `escalation_rate_weighted` là object `{raw, weighted, by_group, sensitivity}` · `e1_split` `{total, counts, shares}` + khoá `other` · `e3_cases` `{items, truncated}`, `intent`/`kb_version` nullable · AI 14 khoá (2 khoá `multi_intent_*` pending Phase 5), `cost_per_day` `[{day_start, cost_usd}]` (day_start = 00:00 VN viết ở UTC), `latency_p95_by_step` map `node:<tên>` → ms · `override_count` đã ready. **Chốt:** không gửi `audience`/`limit`/tham số rỗng (rỗng → 422); khối 5 cảnh báo ở Tổng quan dùng chung query "open" rồi tự sắp (không `limit=5` — server xếp theo thời gian); `truncated` → băng + "200+"; `scope ≠ all` hoặc `alert_id` không an toàn (> 2^53) → 502 fail-closed; ack 409 → tải lại, không đọc `acked_by`; ack 200 thân hỏng → không báo thành công; 422 dashboard → "Khoảng thời gian không hợp lệ — kiểm tra ngày giờ của máy"; **xoá** handler + fixture mock của dashboard/alerts; verify KHÔNG ack cảnh báo thật (F5-3 chỉ đọc + POST ack id không tồn tại → 404 `not_found`; F5-4 đổi thành kiểm thân 422 thật; 503 chỉ còn vitest); sinh kiểu `gen:api` + so hai chiều ở PHẦN 2. **Lỗ còn lại:** ack thật kiểm tay trước demo; màn L1 `scope=own` và phân trang cảnh báo để sau. `FE-STATE.md` nằm ở gốc worktree, không được git theo dõi |
| Luật dùng máy chung (02/10) | Khi một bên chạy verify/gate: bên kia **không chạy lệnh nặng** (vitest, mutation, build — kể cả không chạm stack) vì tranh CPU làm rerank/gate quá hạn. Chạy verify/gate: **cắm sạc + `caffeinate -i`** (02/10 gate3 của Phase 4 đỏ vì Mac ngủ 418 giây). Claude chat cũng không chạy kiểm độc lập trên máy trong lúc bên kia verify |
| Bài học verify 01/10 | (1) F2-1 đỏ E2 `rag_system_error`, `error_stage=rerank`, `deadline` 50 s (`rag_deadline_s`) ngay sau khi recreate backend — ml-service 7 giờ không ai gọi → rerank "nguội". Chạy `make gate3 S="preflight tc04"` (≈ 22 s, không OTP) làm nóng → lượt sau PASS. **Trước verify FE và trước demo thật: làm nóng bằng lệnh này** (mục 11 bước 6). Không nới `rag_deadline_s` (việc của Phase 4). (2) Hợp đồng route vào sau mốc Bước 0 → verify đỏ ở chặng cũ: ghi FE-STATE, không vá trong chặng đang làm, mở chặng "nối thật" |
| Phase 7 (từ security-reviewer K4) | Caddy **không** mở `/docs`, `/redoc` của FastAPI trên cùng origin với SPA (Swagger tải JS từ CDN, lệch CSP `default-src 'self'` và mở thêm bề mặt). Việc treo F1: token từ refresh không đọc được `sub` → chưa ép hết phiên (backend luôn cấp JWT có `sub`; kênh tab đã kiểm `sub`) |
| F0 ghi chú | Kiểm font: trên Mac `-apple-system` đứng trước nên không có request font là **đúng**; kiểm `@font-face` trỏ `/assets/` bằng `check:dist`. `assetsInlineLimit: 0` vì CSP `default-src 'self'` chặn `data:` |
| Tự quyết | Tailwind 4, token khai `@theme` trong `tokens.css` (không cần `tailwind.config`, xoá palette mặc định); cài một lần cho F0–F6 bằng `--save-exact` (bản ghim trong `package.json` + lock); `engines.node >=20`; eslint chặn `localStorage/sessionStorage/indexedDB`; `check:style` tự động hoá grep mục 7/8; `check:dist` quét tên mọi file + nội dung file văn bản; `VITE_API_MOCK` qua script `dev:mock`, không tạo `frontend/.env*` |

## 13. Nhật ký thay đổi

| Ngày | Thay đổi |
|---|---|
| 29/09/2026 | Tạo file: kiểm route thật ở `6797455`, chặng F0–F6, luật an ninh phía UI, fail-closed cho mock, nợ API |
| 29/09/2026 | v1.1: theo Bản 4 đã duyệt — token 4.5, font tự host (4.1 #7), thanh bên hợp nhất, danh sách artboard; dashboard/alerts chuyển sang M9 A3 (nối thật sớm), kiểu `BusinessDashboard` theo M9 §5.1; nợ API #4 dời Phase 4, thêm #6, #7; mục 12 xây song song (chủ file, hợp đồng, cổng, tải review) |
| 30/09/2026 | Tạm dừng: không làm frontend song song, dời về lịch Phase 7 gốc. Giữ nguyên nội dung để dùng lại |
| 30/09/2026 | v1.2 mở lại: Phase 3 đóng, route thật không đổi; dùng hợp đồng Phase 4 v0.7 (hộp thư, `ApprovalView`, ghi đè) cho MSW + kiểu 3.2; giờ máy chủ từ header `Date`; notifications/lịch sử/danh sách ghi đè → Phase 7; mục 4.6 tinh chỉnh Bản 4; CI frontend sau 4a; cổng 4 không còn phụ thuộc UI; demo thứ Sáu rút về F0–F2 |
| 30/09/2026 | Tuấn Anh tự làm frontend: dựng hết F0–F6 (thật + giả) rồi nối/tinh chỉnh dần; worktree `fe-tuananh` (mục 11); bản sao Bản 4 cho agent ở `docs/spec/claude/ban4/`; cổng 7 do Dương/Duy Anh xác nhận |
| 30/09/2026 | Mục 12b: chốt Q-fe-1…10 + tự quyết của PLAN-fe (Citation thật, reauth ghi đè theo P6, token sidebar/selected, trang đầu theo quyền, Tailwind 4) |
| 30/09/2026 | F0 xong (DỪNG): Vite 8.3, React 19.3, Tailwind 4.3, MSW 3.0, TS 5.9.3; Q-fe-11 Node engines; MSW 3 `onUnhandledFrame` |
| 30/09/2026 | Q-fe-12: `npm run verify` + Playwright — agent tự kiểm, người chỉ gõ 1 lệnh |
| 30/09/2026 | Q-fe-13: BroadcastChannel chia sẻ access token giữa tab (C9-1), không sửa backend |
| 30/09/2026 | F1 DỪNG: Q-fe-14…17; sửa 1.1 (refresh thiếu cookie → 403), 4.1 #9 BroadcastChannel, 7 F1 Đạt khi, 11 bước cài MFA |
| 30/09/2026 | F2 DỪNG: Q-fe-18 (câu yêu cầu đầu), Q-fe-19 (nguồn lặp), nợ API #8, luật 4 check:style |
| 30/09/2026 | F3: Q-fe-20…22, nợ API #9, hàng đợi limit=200, verify dùng lại ticket F2 |
| 30/09/2026 | Q-fe-23: hàng đợi dev > 200 ca; verify F3 kiểm theo điều kiện; nợ API #10 phân trang (ưu tiên cao) |
| 01/10/2026 | **F5 xong `210b158`** (verify lượt 8 xanh 14:22, vitest 246/246, M24–M30 + M23 chạy lại): Q-fe-26…31 + ghi chú F5; nợ API #11 (`/api/policy*` + quay lui append-only); mục 11 bước 4 cách thêm OTP vào app. Bài học: chạy verify khi tài khoản còn khoá → đỏ hàng loạt; dùng giờ máy làm mốc |
| 02/10/2026 | Ghi hợp đồng `/api/alerts` M9 chốt trước (`{items, truncated}`, `audience`, `limit`) + 5 điểm lệch với F5 để sửa ở chặng "nối A3"; trước demo: reset dữ liệu stack (M9) kéo theo enroll lại MFA `quan.tm`, ingest KB, làm nóng RAG |
| 08/10/2026 | **N-A3 phần 1 commit cục bộ `c063134`** (verify 01:14:15 xanh 44/0/8, vitest 522/522; chưa push). Thêm 12b "Sự cố tc04 + commit phần 1": rerank quá hạn khi máy chạy pin, rủi ro biên rerank trước demo; mục 6 dòng 3 và 5 |
| 07/10/2026 | **N-A3 phần 1 xong (chưa commit)**: vitest 522/522, t109–t119, M79–M95; Q-fe-44 + kết quả ở 12b; `a98d238` đã push; phần 2 chờ PR #30 |
| 07/10/2026 | **N-L2Q xong `a98d238`** (verify 20:34:47 xanh 44/0/8, vitest 447/447, t94–t108, M56–M78): Q-fe-42, Q-fe-43 + kết quả ở 12b; mục 6 gạch việc 2; prompt N-A3 đổi mốc HEAD `a98d238`, số bắt đầu t109 / M79, mốc so verify mới |
| 06/10/2026 | **Kế hoạch làm việc frontend** (mục 6): merge PR #27 → N-L2Q → N-A3 phần 1 → CI frontend → N-A3 phần 2 → chờ Phase 5/7. Thêm 12b "N-L2Q"; prompt `claude/prompt-fe-l2q.md`; prompt N-A3 đổi mốc BƯỚC 0 (sau commit N-L2Q) và cách đánh số test/mutation |
| 03/10/2026 | **Mở chặng N-A3** (nối A3 của M9): mục 1.2 dòng dashboard/alerts, mục 6, 12b "N-A3"; prompt `claude/prompt-fe-noi-a3.md`. **Phase 4 đóng** (`12e8e19`; Duy Anh chạy cổng 3 + 4 trên `1455b55`: 78/0, 73/0) → **gỡ lệnh giữ PR #27**; kiểm 03/10 18:20: `origin/dev-tuananh` = `3549daa`, `origin/fe-tuananh` = `66691dc`, hai nhánh không sửa chung file nào, gộp thử 0 xung đột |
| 02/10/2026 | **N4d xong `66691dc`** (verify 21:40:57 xanh 49/0/2; vitest 384/384; t88–t93, M48–M55): Q-fe-39…41 + ghi chú N4d + nợ test t61 + ghi chú gửi Phase 4; mục 1.2 ghi đè "đã nối"; mục 11 bước 7 đổi sang push + PR không rebase (nhánh đã ở remote) |
| 02/10/2026 | **N4c xong `136953c`** (verify 19:33:37 xanh 48/0/2; vitest 346/346; t79–t87, M38–M47): Q-fe-36…38 + ghi chú N4c + luật dùng máy chung; mục 1.2 hộp thư/xem phiếu "đã nối", ghi đè "đã có thật `e510a6e`"; nợ API #12 (phân trang hộp thư); mục 6 trỏ sang N4d |
| 01/10/2026 | **F6 xong `e3e6adc`** (ngoại lệ: verify 23:19:54 có 45 PASS, F4-8 đỏ do 4c vào sau mốc Bước 0, F5-7 chưa chạy): Q-fe-32…35 + ghi chú F6; mục 1.2 hộp thư + xem phiếu chuyển "đã có thật" (4c `b457e6e`, dạng `{items}`); chặng "nối thật 4c" ở mục 6; mục 11 bước 6 thêm làm nóng RAG (`make gate3 S="preflight tc04"`) sau sự cố rerank nguội |
| 30/09/2026 | **F4 xong `75a88fb`** (verify xanh 23:52, vitest 145/145, M19–M23): Q-fe-24, Q-fe-25, ghi chú F4; 1.3 #5 header thiếu → độ lệch 0; `ApprovalViewP4` thêm `procedure`; nợ API #5 thêm tên đăng nhập; mục 11 bước 6 dựng stack gate3 (`.env` có `FAKE_SCENARIO=approval`); đối chiếu 4b DỪNG 1 + spec Phase 4 v1.1 (4c/4d) — không lệch |
