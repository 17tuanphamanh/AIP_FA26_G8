import type { HttpHandler } from "msw";
import { escalationCloseHandlers } from "./escalation-close.ts";

// MỖI file trong thư mục này = một nhóm route CHƯA CÓ ở backend (KH mục 1.2, 2). Route đã có thật
// (KH 1.1) KHÔNG được có handler — sẽ che API thật (checklist KH 8 #5). Ngoại lệ duy nhất: `decision`
// cho id tiền tố `apv-demo-` (12b Q-fe-5). Backend ra route → xoá file handler tương ứng.
// Mọi request khác đi thẳng qua proxy tới backend (`onUnhandledFrame: "bypass"`).
export const handlers: HttpHandler[] = [
  ...escalationCloseHandlers, // F3: POST /api/escalations/:id/close (Phase 7, T31)
];
