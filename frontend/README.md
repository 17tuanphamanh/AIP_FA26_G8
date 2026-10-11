P10 — React + Vite + TS + Tailwind + TanStack Query. Xem docs/spec/build/01-kien-truc-project.md mục 3.
Kế hoạch chốt: `docs/spec/claude/ke-hoach-frontend-khung.md` (KH). Thiết kế: Bản 4 (`docs/spec/claude/ban4/`).

## Lệnh (chạy trong `frontend/`; phiên bản Node: xem `engines` trong `package.json`)

| Lệnh | Việc |
|---|---|
| `npm install` | cài đúng bản đã khoá trong `package-lock.json` |
| `npm run dev` | dev server `http://localhost:5173`, `/api` proxy tới `http://127.0.0.1:8000` — KHÔNG có dữ liệu giả |
| `npm run dev:mock` | như trên + MSW cho route chưa có (nhãn "Dữ liệu minh hoạ" ở góc). Hiện giả: `POST /api/escalations/:id/close` (F3, Phase 7); hộp thư `GET /api/approvals` (route thật 4c) = phiếu của backend THẬT + phiếu minh hoạ `apv-demo-01…08` (lỗi của backend trả nguyên, backend tắt → 503, không bao giờ chỉ có minh hoạ); `GET /api/approvals/:id` + `POST …/decision` CHỈ cho id `apv-demo-*` (`04` = plan_changed, `08` = phòng ban/rủi ro/căn cứ null, `apv-demo-viewer` = người xem giám sát — chỉ mở bằng URL), id khác tới backend thật; `POST /api/tickets/:id/override` (route thật 4d) CHỈ cho id `tkt-demo-*` (`-open` → 409, `-same` → 422 trùng quyết định gốc, `-reauth` → 403 đăng nhập lại ở lần đầu, `-notice` → 201 có `notices`; "Khác" + ghi chú chỉ gồm ký tự vô hình → 422 tại ô ghi chú); ticket thật (không tiền tố minh hoạ) đi backend thật — ghi đè là ghi thật, vĩnh viễn; `GET/PUT /api/policy`, `GET /api/policy/versions`, `POST …/restore` (F5, Phase 7 — 4 phiên bản, bản "4" đang áp dụng); `GET /api/tickets/:id` + `POST /api/tickets/:id/reply` CHỈ cho id `tkt-demo-multi-*` (F6, Phase 5 T20 — yêu cầu nhiều ý: mở `/chat/tkt-demo-multi-1` bằng an.nv; `-422` → 422 tại ý 2, `-409` → 409), id khác tới backend thật |
| ↳ `dev:mock`: Tổng quan + Cảnh báo | dữ liệu THẬT — `/api/dashboard/*`, `/api/alerts*` là route thật M9 A3, không có handler giả (dù góc màn có nhãn "Dữ liệu minh hoạ"); nút "Đã xem" trên Cảnh báo là GHI THẬT, vĩnh viễn (như ghi đè ticket thật ở trên) |
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
