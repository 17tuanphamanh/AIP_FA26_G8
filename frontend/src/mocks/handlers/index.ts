import type { HttpHandler } from "msw";
import { alertHandlers } from "./alerts.ts";
import { approvalHandlers } from "./approvals.ts";
import { dashboardHandlers } from "./dashboard.ts";
import { multiHandlers } from "./employee-multi.ts";
import { escalationCloseHandlers } from "./escalation-close.ts";
import { overrideHandlers } from "./override.ts";
import { policyHandlers } from "./policy.ts";

// MỖI file trong thư mục này = một nhóm route CHƯA CÓ ở backend (KH mục 1.2, 2). Route đã có thật
// (KH 1.1) KHÔNG được có handler — sẽ che API thật (checklist KH 8 #5). Ngoại lệ (chặn THEO TIỀN TỐ id fixture, id khác
// đi thẳng backend): `decision` cho `apv-demo-` (12b Q-fe-5); `GET /api/tickets/:id` cho `tkt-demo-multi-` (F6 P6).
// Backend ra route → xoá file handler tương ứng.
// Mọi request khác đi thẳng qua proxy tới backend (`onUnhandledFrame: "bypass"`). Mọi response giả có header `Date`.
export const handlers: HttpHandler[] = [
  ...escalationCloseHandlers, // F3: POST /api/escalations/:id/close (Phase 7, T31)
  ...approvalHandlers, // F4: GET /api/approvals, GET /api/approvals/:id (4c); decision chỉ id `apv-demo-` (Q-fe-5)
  ...overrideHandlers, // F4: POST /api/tickets/:id/override (4d)
  ...dashboardHandlers, // F5: GET /api/dashboard/business, /ai (M9 A3)
  ...alertHandlers, // F5: GET /api/alerts, POST /api/alerts/:id/ack (M9 A3)
  ...policyHandlers, // F5: GET/PUT /api/policy, GET /api/policy/versions, POST …/restore (Phase 7)
  ...multiHandlers, // F6: GET /api/tickets/:id + POST …/reply chỉ id `tkt-demo-multi-` (Phase 5, T20)
];
