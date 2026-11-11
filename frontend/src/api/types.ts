// ĐIỂM IMPORT DUY NHẤT về kiểu API cho component (KH mục 2, 3).
// Chuyển giả → thật: xoá kiểu ở `contracts-tam.ts`, re-export kiểu tương ứng từ `schema.gen.ts` (sinh bằng
// `npm run gen:api`) ngay tại file này — component không phải sửa.
// F0: chưa có `schema.gen.ts` (gen:api cần backend chạy — 12b Q-fe-1).
import type { TicketViewBase } from "./contracts-tam.ts";
import type { components } from "./schema.gen.ts";

export type * from "./contracts-tam.ts";

type S = components["schemas"];

// ---------------------------------------------------------------- Chính sách (F7, route thật — N-POL1)
// backend/app/api/policy.py: GET /api/policy (`PolicyView`), GET /api/policy/versions (MẢNG TRẦN `PolicyVersionItem`),
// POST /api/policy/validate (200 `ValidateOk`; 422 `InvalidPolicy` | `InvalidRequestBody`). Nối tên schema với ĐÚNG
// route: src/api/schema.check.ts. Thân gửi đi của validate: `PolicyValidateIn` (contracts-tam.ts — route tự đọc thân).
export type PolicyView = S["PolicyView"];
export type PolicyVersionItem = S["PolicyVersionItem"];
export type PolicyValidateOk = S["ValidateOk"];
export type PolicyInvalid = S["InvalidPolicy"];

// ---------------------------------------------------------------- Lỗi dùng chung (route thật)
// backend/app/api/alerts.py — một schema cho mọi route khai `responses`: 401/403/404/409/503 `ErrorDetail` {detail},
// 422 `InvalidRequestBody` {error:"invalid_request", fields} (chỉ vị trí trường). Đọc lúc chạy ở api/errors.ts.
export type ErrorDetail = S["ErrorDetail"];
export type InvalidRequestBody = S["InvalidRequestBody"];

// ---------------------------------------------------------------- Thông báo (N-TB, route thật be-thong-bao 56ea4d9)
// backend/app/api/notifications.py: GET /api/me/notifications (quyền `ticket:read:own`) → `NotificationPage`. Đọc CHẶT lúc
// chạy ở api/notifications.ts `parseNotificationPage`; nối tên schema với ĐÚNG route: schema.check.ts `NotificationOk`.
export type NotificationView = S["NotificationView"];
export type NotificationPage = S["NotificationPage"];
export type NotificationKind = S["Kind"];
export type NotificationResult = S["Result"];

// ---------------------------------------------------------------- Ticket (route thật)
// Phần viết tay (`TicketViewBase`, contracts-tam.ts) + `deadline`/`server_now` từ openapi. Hai khoá này backend ghi BẮT
// BUỘC (`deadline` có thể null) nhưng ở đây để TUỲ CHỌN có chủ ý: thân của backend cũ / fixture thiếu khoá vẫn đúng kiểu
// và màn đọc thiếu = không có (không đồng hồ; độ lệch rơi về header `Date`) — routes/employee/approvalClock.ts.
// `request_text` (Nợ API #8): câu yêu cầu đầu ĐÃ CHE, ≤ 500 ký tự; thiếu khoá (backend cũ) = null.
// `can_follow_up` (Q13b, D-79): ô "Hỏi tiếp về yêu cầu này" trên ticket đã kết thúc; thiếu khoá (backend cũ / cờ tắt) = không có ô.
export type TicketView = TicketViewBase &
  Partial<Pick<S["TicketView"], "deadline" | "server_now" | "request_text" | "can_follow_up">>;
// P3 "Gần đây": GET /api/tickets (quyền `ticket:read:own`) → `TicketList` {items} — ticket gốc của CHÍNH người gọi, mới
// nhất trước; `request_text` ĐÃ CHE. Đọc CHẶT lúc chạy ở api/tickets.ts `parseTicketList`; nối với route: schema.check.ts.
export type TicketListItem = S["TicketListItem"];
export type TicketList = S["TicketList"];
