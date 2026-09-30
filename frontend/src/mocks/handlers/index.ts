import type { HttpHandler } from "msw";

// MỖI file trong thư mục này = một nhóm route CHƯA CÓ ở backend (KH mục 1.2, 2). Route đã có thật
// (KH 1.1) KHÔNG được có handler — sẽ che API thật (checklist KH 8 #5). Ngoại lệ duy nhất: `decision`
// cho id tiền tố `apv-demo-` (12b Q-fe-5). Backend ra route → xoá file handler tương ứng.
// F0: chưa có handler nào — mọi request đi thẳng qua proxy (`onUnhandledFrame: "bypass"`).
export const handlers: HttpHandler[] = [];
