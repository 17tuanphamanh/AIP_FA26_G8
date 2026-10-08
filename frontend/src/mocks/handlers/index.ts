import type { HttpHandler } from "msw";
import { approvalHandlers } from "./approvals.ts";
import { multiHandlers } from "./employee-multi.ts";
import { escalationCloseHandlers } from "./escalation-close.ts";
import { overrideHandlers } from "./override.ts";
import { policyHandlers } from "./policy.ts";

// MỖI file trong thư mục này = một nhóm route CHƯA CÓ ở backend (KH mục 1.2, 2). Route đã có thật
// (KH 1.1) KHÔNG được có handler — sẽ che API thật (checklist KH 8 #5). Ngoại lệ (chặn THEO TIỀN TỐ id fixture, id khác
// đi thẳng backend): xem phiếu + `decision` cho `apv-demo-` (12b Q-fe-5, N4c P6b); ghi đè (route thật 4d) cho `tkt-demo-`
// (N4d P7); `GET /api/tickets/:id` cho `tkt-demo-multi-` (F6 P6). Hộp thư duyệt (route thật 4c): handler GỌI THẬT trước,
// chỉ gộp thêm phiếu minh hoạ khi thật trả 2xx hợp lệ — lỗi thật trả nguyên (N4c P6a). Backend ra route → xoá file handler
// tương ứng (đã xoá: Tổng quan `/api/dashboard/*` + Cảnh báo `/api/alerts*` — route thật M9 A3, N-A3).
// Mọi request khác đi thẳng qua proxy tới backend (`onUnhandledFrame: "bypass"`). Mọi response giả có header `Date`.
export const handlers: HttpHandler[] = [
  ...escalationCloseHandlers, // F3: POST /api/escalations/:id/close (Phase 7, T31)
  ...approvalHandlers, // F4/N4c: hộp thư = thật + minh hoạ; xem phiếu + decision chỉ id `apv-demo-` (Q-fe-5, P6)
  ...overrideHandlers, // F4/N4d: POST /api/tickets/:id/override (route thật 4d) chỉ id `tkt-demo-`
  ...policyHandlers, // F5: GET/PUT /api/policy, GET /api/policy/versions, POST …/restore (Phase 7)
  ...multiHandlers, // F6: GET /api/tickets/:id + POST …/reply chỉ id `tkt-demo-multi-` (Phase 5, T20)
];
