# P10 — Giao diện 4 vai trò (T0, `frontend/`)

*Thuộc bộ `build/`. Phase 7 (chạy song song được với Phase 5–6). Nguồn đã chốt: `huong-dan-xay-dung-he-thong-2.md` mục 16, Phase 7; `NGU-CANH-DAY-DU.md` Phần III mục 2.2 (ma trận quyền); `build/02-cac-tang-he-thong.md` T0; P6 (xác thực).*

---

## 0. Ngữ cảnh nạp sẵn

*File nền tảng này **tự đứng được**: khối ngữ cảnh chung dưới đây giúp người đọc hoặc coding agent hiểu phần này nằm ở đâu trong dự án mà không cần mở tài liệu khác. Phần riêng của thành phần bắt đầu từ mục 1.*

### 0.1. Khối ngữ cảnh chung của dự án

*Khối này giống hệt nhau ở mọi file trong `build/` (phiên bản khối: **CTX-1.1, 25/09/2026**). Khi tài liệu gốc thay đổi, cập nhật khối này ở tất cả các file cùng lúc và tăng số phiên bản.*

**Đề tài:** AI Agent tự động hóa hỗ trợ IT Service Desk cấp 1 với cơ chế Human-in-the-Loop (EN: *Agentic AI for Level-1 IT Service Desk Automation with Human-in-the-Loop*). Đồ án tốt nghiệp, ĐH FPT, chuyên ngành AI, nhóm 4 người.

**Ba mục tiêu đã chốt:**

| Mục tiêu | Trọng số | Nội dung |
|---|---|---|
| Obj 1 | 50–60% | Agent xử lý yêu cầu L1: M1 phân loại + slot, M2 RAG, M3 tool + chẩn đoán chủ động, M4 điều phối, cùng lớp kỹ thuật agent (trace, bộ nhớ, harness, LLMOps, riêng tư) |
| Obj 2 | 30–40% | Human-in-the-Loop: M5 quyết định khi nào cần người (đóng góp chính), M6 phê duyệt, M7 audit |
| Obj 3 | 0–20% | Đánh giá: bộ kịch bản, so sánh 4 phương án, ablation (M8) |

**Nguyên tắc dự án:**

- Objective quyết định xây gì → Phase quyết định xây khi nào → RQ chỉ quyết định đo gì.
- Luôn phân biệt **[Chốt] / [Suy luận] / [Đề xuất]**.
- Ưu tiên thay đổi nhỏ, kiểm chứng được.
- Với an toàn: **giảm False Negative trước**, giảm escalate thừa sau.

**Bốn nguyên tắc thiết kế [Chốt]:**

1. An toàn ưu tiên hơn tự động hóa.
2. Mọi quyết định giải thích được.
3. Luật cứng có quyền phủ quyết LLM.
4. Chủ động chẩn đoán trước khi hỏi.

**Phạm vi:**

- 4 loại yêu cầu: `account`, `vpn`, `software`, `access`.
- Tiếng Việt.
- Hệ thống ngoài giả lập bằng mock FastAPI.

**4 vai trò [Chốt 2.2]:**

| Vai trò | Quyền chính |
|---|---|
| Nhân viên | Gửi yêu cầu, xem ticket của mình |
| L1 | Duyệt, ghi đè, nhận escalate |
| Trưởng BP IT | Sửa policy, dashboard/audit toàn bộ, cập nhật KB |
| L2 | Nhận escalate, cập nhật KB, **không duyệt** |

L1 không được sửa policy.

**Luồng 20 bước [Chốt]:**

B1 xác thực → B2 chặn injection (E0) → B3 intent → B4 trong phạm vi? (E1) → B5 tách ý → B6 chẩn đoán chủ động → B7 lỗi hệ thống ≠ rỗng (E2) → B8 tra KB (E2) → B9 có căn cứ? (E3) → B10 chỉ cần trả lời? → B11 đủ thông tin? (E4) → B12 luật → B13 quyết định theo luật → B14 LLM hiệu chỉnh (E5) → B15 xung đột lợi ích + `action_plan_hash` → B16 chờ duyệt (E6) → B17 thực thi (E7/E5) → B18 thông báo → B19 xác nhận (E8) → B20 audit + `close_reason`.

Mọi node có lớp bọc lỗi chưa lường trước → E9.

**14 trạng thái:**

- Xử lý: `S_NEW`, `S_SCREENING`, `S_CLASSIFYING`, `S_DIAGNOSING`, `S_RETRIEVING`, `S_ASSESSING`, `S_EXECUTING`.
- Chờ người: `S_CLARIFYING` (24h), `S_PENDING_APPROVAL` (30 phút), `S_CONFIRMING` (48h).
- Kết thúc hoặc chuyển giao: `S_ESCALATED`, `S_RESOLVED`, `S_REJECTED`, `S_BLOCKED`.

**Mã thoát và ưu tiên hàng đợi L2:**

| Mã | Tình huống | Ưu tiên |
|---|---|---|
| E0 | Prompt injection | An ninh |
| E1 | Ngoài phạm vi | Thường |
| E2 | Tool/RAG lỗi hệ thống sau retry | Hạ tầng |
| E3 | Không có căn cứ (`NO_EVIDENCE`) | Thường, kèm cờ bổ sung KB |
| E4 | Hỏi 3 lần vẫn thiếu | Thường |
| E5 | Rủi ro cao / `deny` / hash lệch | Cao |
| E6 | Hết hạn duyệt (fail-safe) | Có SLA |
| E7 | Thực thi lỗi | Rất cao |
| E8 | Người dùng báo chưa xong | Thường |
| E9 | Lỗi chưa lường trước | Ngang E2 |

**`block_reason`:** `invalid_credentials` (không phải sự cố an ninh), `repeated_auth_failure`, `injection_detected`.

**`close_reason` (8 giá trị):** `resolved_user_confirmed`, `resolved_auto_timeout_48h`, `resolved_after_escalation`, `resolved_after_deny_review`, `rejected_by_approver`, `blocked_invalid_credentials`, `blocked_repeated_auth_failure`, `blocked_injection_detected`.

**8 điểm log bắt buộc:**

| Điểm | Bước | Nội dung |
|---|---|---|
| 1 | B3 | intent |
| 2 | B6 | chẩn đoán |
| 3 | B8 | tra cứu |
| 4 | B12–14 | quyết định rủi ro — quan trọng nhất |
| 5 | B15 | vào hàng đợi duyệt |
| 6 | B16 | kết quả duyệt |
| 7 | B17 | thực thi |
| 8 | B20 | kết thúc |

**Hằng số trong `policy.json`:**

| Hằng số | Giá trị |
|---|---|
| `MAX_LOOPS` | 5 |
| `MAX_CLARIFICATION_TURNS` | 3 |
| `TOOL_RETRY` | 2 (backoff 1s, 2s) |
| `MAX_AUTH_FAILURES` | 5 trong 10 phút |
| `SLA_MINUTES` | 30 |
| `THRESHOLD_LOW` / `THRESHOLD_HIGH` | 0,25 / 0,75 (sẽ chọn lại trên tập calibration) |
| `RETRIEVAL_THRESHOLD` | 0,6 |
| `CLARIFY_TIMEOUT` | 24h |
| `CONFIRM_TIMEOUT` | 48h |

**Công nghệ [Chốt + Đề xuất]:**

- Python 3.12, FastAPI, Pydantic v2.
- LangGraph + checkpoint Postgres.
- PostgreSQL 16 + SQLAlchemy 2 + Alembic.
- Qdrant + bge-m3 + bge-reranker-v2-m3 + BM25/RRF.
- LLM gateway fast/strong, API hoặc local.
- httpx, APScheduler.
- React + Vite + TS.
- Docker Compose, Caddy, GitHub Actions.
- Kiến trúc modular monolith + ml-service + mock (D-13).
- DB 22 bảng (P7).

**Bất biến toàn cục (không nhánh nào được phá):**

1. M5 không bao giờ đọc câu người dùng. `policy_engine.evaluate(action, ctx)` chỉ nhận hai tham số đó.
2. B17 là điểm ghi duy nhất ra hệ thống ngoài; chỉ `svc_executor` có credential ghi.
3. Mọi đổi trạng thái đi qua `goto()` (kiểm chuyển hợp lệ + ghi audit).
4. Mọi nhánh kết thúc ở B20.
5. Hết hạn duyệt không bao giờ tự thực thi.
6. Lỗi hệ thống ≠ kết quả rỗng.
7. Luật `deny` không bao giờ vào hàng đợi duyệt, và L2 không thực hiện lại hành động bị `deny`.
8. Việc cần làm trước khi chờ người nằm ở node đứng trước; sự kiện đến muộn bị bỏ qua (409). Ngoại lệ: tín hiệu `wake_parent` từ ticket con chỉ để đánh thức ticket cha, không bị 409 (D-17).
9. M9 chỉ đọc.
10. Ngưỡng và calibrator chỉ được fit trên tập calibration.
11. Role của người gửi chỉ lấy từ AD, không từ lời người dùng.
12. Một lượt người dùng — một tin trả lời: ticket con không tự nhắn, ticket cha gom (D-31).
13. Mọi chỉ số M8/M9 tính trên ticket lá (`is_parent = false`) (D-30).

**Mã quyết định mới (đã chốt theo đặc tả 25/09/2026):** D-01…D-33 — danh sách đầy đủ, trạng thái và các quyết định Q1–Q14 ở `build/decisions.md`. Các mã mà file này dùng được liệt kê ở mục 0.5 (file nền tảng: trong thân bài).

---

## 1. Mục đích

Giao diện cho 4 vai trò, đủ để demo 12 ca và chạy cổng 7 **[Chốt Phase 7, mục 16]**. Giao diện **không tự quyết quyền**: nút bị ẩn chỉ để tiện dùng, quyền thật luôn do backend kiểm (T1) **[Chốt]**. Quy tắc làm: chỉ làm "Nên có" sau khi "Phải có" của phase đã qua cổng **[Chốt 16]**.

## 2. Sơ đồ cấu tạo

```
frontend/ (React + Vite + TypeScript + Tailwind + TanStack Query) — build tĩnh, Caddy phục vụ
 src/
  api/client.ts        fetch + access token trong BỘ NHỚ; 401 → /api/auth/refresh (cookie HttpOnly + X-CSRF-Token)
  auth/                LoginPage (MFA cho manager), useMe() ← GET /api/auth/me → role + permissions
  routes/
    employee/          ChatPage, TicketHistory
    l1/                ApprovalQueue, ApprovalDetail, OverrideDialog, MyDashboard
    manager/           PolicyEditor, PolicyHistory, BusinessDashboard, AiDashboard, Alerts
    l2/                EscalationQueue, EscalationDetail
  components/          DigestMessage (D-31), ProgressPanel, Countdown, Citation, ActionView, ReasonPicker
  demo/                DemoBar (SLA 2 phút, đặt lại mock) — chỉ hiện khi DEMO_MODE
```

Điều hướng theo `permissions` từ `/api/auth/me`, không theo tên role viết cứng.

## 3. Màn hình và tính năng

### 3.1. Nhân viên [Chốt 16.1]

| Tính năng | Ưu tiên | API |
|---|---|---|
| Chat gửi yêu cầu; trạng thái dễ hiểu; đồng hồ khi đang chờ | Phải có | `POST /api/tickets`, `POST /api/tickets/{id}/messages`, `GET /api/tickets/{id}` (polling 2 giây khi đang xử lý, 10 giây khi chờ người) |
| Xác nhận "Đã ổn / Chưa ổn" (B19) | Phải có | `POST /api/tickets/{id}/confirm` |
| **Yêu cầu nhiều ý:** một tin tổng hợp mỗi lượt, mỗi ý một khối có nút Đã ổn/Chưa ổn hoặc ô trả lời; một nút gửi cho tất cả | Phải có (D-31) | `POST /api/tickets/{cha}/reply`; thiếu ý → hiển thị lỗi 422 tại đúng khối |
| **Khung tiến độ từng ý** ("Đang xử lý", "Chờ IT duyệt", "Đã có kết quả — chờ tổng hợp") — không phải tin nhắn | Phải có (D-31) | `GET /api/tickets/{cha}` trả `children_progress` |
| Hiện nguồn tài liệu đã trích | Phải có | trong nội dung tin |
| Thông báo trong app khi có kết quả duyệt hoặc L2 đóng ticket | Phải có | `GET /api/me/notifications` |
| Nút gợi ý nhanh (quên mật khẩu, lỗi VPN, cài phần mềm, xin quyền) | Nên có | — |
| Lịch sử ticket; tạo yêu cầu mới liên kết ticket cũ đã đóng | Nên có | không mở lại ticket cũ **[Chốt 8.3]** |
| Chấm hài lòng 1–5 | Có thể | `ConfirmIn.satisfaction` |

Thông báo E0 luôn trung tính; giao diện không hiện gì gợi ý "phát hiện tấn công" **[Chốt 7.1]**.

### 3.2. L1 [Chốt 16.2]

| Tính năng | Ưu tiên | API |
|---|---|---|
| Hàng đợi duyệt sắp theo hạn; đồng hồ đỏ khi còn < 20% | Phải có | `GET /api/approvals?status=pending&mine=1` |
| Chi tiết duyệt: yêu cầu (đã che), **Action đúng như đã băm** (JSON đọc được + `action_plan_hash`), luật khớp hoặc p, chẩn đoán | Phải có | `GET /api/approvals/{id}`; hiển thị đúng object đã băm, không tóm tắt khác **[Chốt 5.2.1]** |
| Đồng ý / Từ chối (lý do bắt buộc) | Phải có | `POST /api/approvals/{id}/decision` |
| Ghi đè quyết định kèm lý do | Phải có | `POST /api/tickets/{id}/override` (xác nhận lại đăng nhập ≤ 10 phút) |
| Mẫu lý do từ chối chọn nhanh + ô tự do bắt buộc | Nên có | |
| Chống duyệt theo phản xạ: xem < 5 giây thì hỏi xác nhận lại | Nên có | gửi `view_duration` cùng quyết định |
| Dashboard phần của mình | Nên có | `GET /api/dashboard/business` (L1 → `:own`) |

### 3.3. Trưởng bộ phận IT [Chốt 16.3]

| Tính năng | Ưu tiên | API |
|---|---|---|
| Sửa policy JSON: kiểm tra hợp lệ, báo lỗi **từng dòng**, lịch sử phiên bản, quay lui | Phải có | `GET/PUT /api/policy`, `GET /api/policy/versions`, `POST /api/policy/versions/{id}/restore` (MFA + xác nhận lại ≤ 10 phút) |
| Dashboard nghiệp vụ + dashboard AI | Phải có | P9 mục 7 |
| Cảnh báo (an ninh, escalation > 40%, …) và xác nhận đã xem | Phải có | `GET /api/alerts`, `POST /api/alerts/{id}/ack` |
| Mô phỏng tác động trước khi lưu policy (N ticket gần nhất, số ca đổi route) | Nên có | `POST /api/policy/simulate` — chỉ đọc |
| Danh sách lỗ hổng KB (ca E3) | Nên có | từ dashboard nghiệp vụ |
| Xuất CSV | Có thể | |

### 3.4. L2 [Chốt 16.4]

| Tính năng | Ưu tiên | API |
|---|---|---|
| Hàng đợi escalate theo ưu tiên (E9 ngang E2) | Phải có | `GET /api/escalations/queue` |
| Ghi chú bàn giao 4 phần + hội thoại của ticket | Phải có | `GET /api/escalations/{id}` |
| Đóng với 3 kết quả (`completed`, `confirmed_denial`, `reopened_as_new`); ca deny chọn `completed` → 422 hiển thị rõ lý do | Phải có | `POST /api/escalations/{id}/close` |
| Soạn tài liệu KB từ ca E3 | Nên có | `kb:edit` |

L2 không có nút duyệt ở bất kỳ màn hình nào; gọi thẳng API duyệt → 403 **[Chốt 2.2]**.

### 3.5. Chế độ demo [Chốt 16.5, Nên có]

Thanh demo (chỉ khi `DEMO_MODE=true`, ẩn ở môi trường khác): SLA 2 phút, đặt lại mock bằng một nút, 4 tài khoản demo đăng nhập nhanh.

## 4. Bảo mật phía giao diện [Chốt P6]

- Access token chỉ trong bộ nhớ; **cấm** localStorage/sessionStorage cho token.
- Refresh token trong cookie `HttpOnly; Secure; SameSite=Strict`; gọi refresh kèm `X-CSRF-Token`.
- CSP `default-src 'self'` (Caddy): không tải script ngoài; không `dangerouslySetInnerHTML` cho nội dung từ LLM — hiển thị Markdown qua trình render đã lọc HTML.
- Không log nội dung tin nhắn ra console ở bản build.

## 5. Giao diện và khả năng đọc

- **Theme sáng**, cỡ chữ gốc ≥ 16 px, tương phản đủ để đọc trên máy chiếu **[Chốt 11.3]**.
- Trạng thái ticket dùng chữ tiếng Việt dễ hiểu, không hiện mã `S_*` cho nhân viên (L1/L2 thấy cả hai).
- Đồng hồ đếm ngược dùng giờ máy chủ (`server_now` trong response) để không lệch khi đồng hồ máy khách sai.

## 6. Kiểm thử và tiêu chí đạt (cổng 7)

| Loại | Test | Đạt khi |
|---|---|---|
| Tự động | `eslint`, `tsc --noEmit`, `vite build` | Sạch **[Chốt]** |
| Tự động | Playwright: đăng nhập 4 vai trò; L1 không thấy menu policy; gọi thẳng `/api/policy` bằng token L1 → 403 | Xanh **[Chốt]** |
| Tự động | Playwright: TC34 (một tin tổng hợp, một lần xác nhận) | Đúng 1 tin mỗi lượt |
| Tự động | Ca deny: L2 chọn "hoàn tất" → 422 hiển thị; "mở ticket mới" tạo ticket liên kết | **[Chốt cổng 7]** |
| Thủ công (người không làm giao diện) | TC02, TC06, TC07, TC08, TC20 (SLA 2 phút), 1 ca L2; lưu policy sai → lỗi từng dòng; đọc được trên máy chiếu | Biên bản **[Chốt cổng 7]** |

## 7. Phase

- **Phase 4:** màn hình tối thiểu cho L1 duyệt (để chạy TC07/TC08 bằng tay).
- **Phase 7:** đủ 4 vai trò, Phải có của mục 16 (T31 → T25 → T30 **[Chốt]**).
- Chạy song song Phase 5–6 được; không để giao diện ngốn thời gian của luồng chính **[Chốt]**.

## 8. Nhật ký thay đổi

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file: màn hình 4 vai trò theo mục 16, API, D-31 (tin tổng hợp + khung tiến độ), bảo mật phía giao diện, cổng 7 |
