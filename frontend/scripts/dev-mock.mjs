// `npm run dev:mock`: dev server CÓ MSW (KH 4.3). Cờ đặt vào biến môi trường của chính tiến trình này — Vite
// ưu tiên `process.env.VITE_*` hơn tệp `.env*` — nên không tạo `frontend/.env*` (.gitignore gốc chặn, luật cấm
// đụng .env) và chạy được cả Windows. MSW vẫn chỉ bật ở dev: `main.tsx` kiểm `import.meta.env.DEV`.
import { createServer } from "vite";

process.env.VITE_API_MOCK = "1";

const server = await createServer({ mode: "development" });
await server.listen();
server.printUrls();
server.bindCLIShortcuts({ print: true });
