import type { HttpHandler } from "msw";
import { approvalHandlers } from "./approvals.ts";
import { multiHandlers } from "./employee-multi.ts";
import { escalationCloseHandlers } from "./escalation-close.ts";
import { escalationQueueHandlers } from "./escalation-queue.ts";
import { strategyCompareHandlers } from "./strategy-compare.ts";
import { strategyHandlers } from "./strategy.ts";
import { overrideHandlers } from "./override.ts";

// MỖI file trong thư mục này = một nhóm route CHƯA CÓ ở backend (KH mục 1.2, 2). Route đã có thật
// (KH 1.1) KHÔNG được có handler — sẽ che API thật (checklist KH 8 #5). Ngoại lệ (chặn THEO TIỀN TỐ id fixture, id khác
// đi thẳng backend): xem phiếu + `decision` cho `apv-demo-` (12b Q-fe-5, N4c P6b); ghi đè (route thật 4d) cho `tkt-demo-`
// (N4d P7); `GET /api/tickets/:id` + `/reply` (route thật T20b) cho `tkt-demo-multi-` — chỉ để minh hoạ ca lỗi 422/409 khó
// tạo trên stack (N-T20 P5). Hộp thư duyệt (route thật 4c): handler GỌI THẬT trước,
// chỉ gộp thêm phiếu minh hoạ khi thật trả 2xx hợp lệ — lỗi thật trả nguyên (N4c P6a). Backend ra route → xoá file handler
// tương ứng (đã xoá: Tổng quan `/api/dashboard/*` + Cảnh báo `/api/alerts*` — route thật M9 A3, N-A3). Chính sách
// `/api/policy*` là route thật F7 (N-POL1): gỡ khỏi danh sách này; file policy.ts còn lại CHỈ cho test (hình dạng thật).
// Mọi request khác đi thẳng qua proxy tới backend (`onUnhandledFrame: "bypass"`). Mọi response giả có header `Date`.
export const handlers: HttpHandler[] = [
  ...escalationQueueHandlers, // N-PA: GET /api/escalations/queue dạng mới {items, next_cursor} (be-tuan8 chưa merge — Q-fe-N8)
  ...escalationCloseHandlers, // POST /api/escalations/:id/close — route thật đã có; chỉ chặn id ca MINH HOẠ của escalation-queue.ts
  ...strategyHandlers, // N-PA: GET/PUT /api/admin/strategy, GET …/history (D-67, be-tuan8 chưa merge)
  ...strategyCompareHandlers, // N-PA: GET /api/dashboard/strategies (be-tuan8 chưa merge) — business/ai vẫn route thật
  ...approvalHandlers, // F4/N4c: hộp thư = thật + minh hoạ; xem phiếu + decision chỉ id `apv-demo-` (Q-fe-5, P6)
  ...overrideHandlers, // F4/N4d: POST /api/tickets/:id/override (route thật 4d) chỉ id `tkt-demo-`
  ...multiHandlers, // F6: GET /api/tickets/:id + POST …/reply (route thật T20b) chỉ id `tkt-demo-multi-` (minh hoạ 422/409)
];
