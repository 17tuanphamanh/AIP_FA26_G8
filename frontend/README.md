P10 — React + Vite + TS + Tailwind + TanStack Query. Xem docs/spec/build/01-kien-truc-project.md mục 3.
Kế hoạch chốt: `docs/spec/claude/ke-hoach-frontend-khung.md` (KH). Thiết kế: Bản 4 (`docs/spec/claude/ban4/`).

## Lệnh (chạy trong `frontend/`; phiên bản Node: xem `engines` trong `package.json`)

| Lệnh | Việc |
|---|---|
| `npm install` | cài đúng bản đã khoá trong `package-lock.json` |
| `npm run dev` | dev server `http://localhost:5173`, `/api` proxy tới `http://127.0.0.1:8000` — KHÔNG có dữ liệu giả |
| `npm run dev:mock` | như trên + MSW cho route chưa có (nhãn "Dữ liệu minh hoạ" ở góc). Hiện giả: `POST /api/escalations/:id/close` (F3, Phase 7); `GET /api/approvals`, `GET /api/approvals/:id` (F4, 4c — phiếu `apv-demo-01…07`, `04` = plan_changed); `POST /api/tickets/:id/override` (F4, 4d — `tkt-demo-open` / `-same` / `-reauth`); `POST …/decision` CHỈ cho id `apv-demo-*`, id khác tới backend thật; `GET /api/dashboard/business`, `/ai`, `GET /api/alerts`, `POST /api/alerts/:id/ack` (F5, M9 A3 — ack id `9409` → 409, `9404` → 404; cookie `mock_monitor=unavailable` → 503 `monitor_unavailable`); `GET/PUT /api/policy`, `GET /api/policy/versions`, `POST …/restore` (F5, Phase 7 — 4 phiên bản, bản "4" đang áp dụng) |
| `npm run lint` · `npm run typecheck` · `npm run build` | eslint · tsc · vite build |
| `npm run check:dist` | build rồi quét `dist/`: không có msw/mockServiceWorker, không tải ngoài origin |
| `npm run check:style` | không mã màu ngoài token, không Storage / `dangerouslySetInnerHTML`, không CDN |
| `npm run test` | vitest (từ F1) |
| `npm run verify` | toàn bộ bước trên + Playwright (đăng nhập, chat, L2 thật khi backend chạy); kết quả ở `.verify/summary.txt`. `VERIFY_MGR=1 npm run verify` thêm các bước Trưởng BP IT (quan.tm): mở Chromium CÓ giao diện ngay sau kiểm tĩnh, người nhập mã OTP trong 120 giây (verify không đọc/chụp ô OTP) |
| `npm run gen:api` | sinh `src/api/schema.gen.ts` từ `http://127.0.0.1:8000/openapi.json` (backend phải chạy) |

## Luật (KH mục 4)

- Dữ liệu giả CHỈ khi `import.meta.env.DEV && VITE_API_MOCK === "1"`. Worker MSW ở `dev-public/`
  (chỉ phục vụ ở mode development); **không** chép vào `public/`, không `msw init public`.
- Cờ mock đặt qua `npm run dev:mock` (hoặc `VITE_API_MOCK=1 npm run dev`) — không tạo `frontend/.env*`.
- `src/mocks/handlers/` chỉ chứa route CHƯA CÓ ở backend; backend ra route → xoá handler.
- Màu, cỡ chữ, font: chỉ token ở `src/styles/tokens.css`. Component import kiểu API từ `src/api/types.ts`.
- Token chỉ trong bộ nhớ; cấm Local/SessionStorage/IndexedDB, `dangerouslySetInnerHTML`, `console.*`
  (trừ `console.error` không kèm dữ liệu) — eslint chặn.
