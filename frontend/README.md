P10 — React + Vite + TS + Tailwind + TanStack Query. Xem docs/spec/build/01-kien-truc-project.md mục 3.
Kế hoạch chốt: `docs/spec/claude/ke-hoach-frontend-khung.md` (KH). Thiết kế: Bản 4 (`docs/spec/claude/ban4/`).

## Lệnh (chạy trong `frontend/`; phiên bản Node: xem `engines` trong `package.json`)

| Lệnh | Việc |
|---|---|
| `npm install` | cài đúng bản đã khoá trong `package-lock.json` |
| `npm run dev` | dev server `http://localhost:5173`, `/api` proxy tới `http://127.0.0.1:8000` — KHÔNG có dữ liệu giả |
| `npm run dev:mock` | như trên + MSW cho route chưa có (nhãn "Dữ liệu minh hoạ" ở góc) |
| `npm run lint` · `npm run typecheck` · `npm run build` | eslint · tsc · vite build |
| `npm run check:dist` | build rồi quét `dist/`: không có msw/mockServiceWorker, không tải ngoài origin |
| `npm run check:style` | không mã màu ngoài token, không Storage / `dangerouslySetInnerHTML`, không CDN |
| `npm run test` | vitest (từ F1) |
| `npm run gen:api` | sinh `src/api/schema.gen.ts` từ `http://127.0.0.1:8000/openapi.json` (backend phải chạy) |

## Luật (KH mục 4)

- Dữ liệu giả CHỈ khi `import.meta.env.DEV && VITE_API_MOCK === "1"`. Worker MSW ở `dev-public/`
  (chỉ phục vụ ở mode development); **không** chép vào `public/`, không `msw init public`.
- Cờ mock đặt qua `npm run dev:mock` (hoặc `VITE_API_MOCK=1 npm run dev`) — không tạo `frontend/.env*`.
- `src/mocks/handlers/` chỉ chứa route CHƯA CÓ ở backend; backend ra route → xoá handler.
- Màu, cỡ chữ, font: chỉ token ở `src/styles/tokens.css`. Component import kiểu API từ `src/api/types.ts`.
- Token chỉ trong bộ nhớ; cấm Local/SessionStorage/IndexedDB, `dangerouslySetInnerHTML`, `console.*`
  (trừ `console.error` không kèm dữ liệu) — eslint chặn.
