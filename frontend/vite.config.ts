import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// KH mục 2 + 4.3:
// - `/api` đi qua proxy → trình duyệt thấy cùng origin, cookie SameSite=Strict chạy, không cần CORS.
// - Worker của MSW nằm ở `dev-public/`, CHỈ được phục vụ ở mode development. Build (mode production)
//   dùng `public/` — không có worker. `npm run check:dist` chặn nếu worker lọt vào `dist/`.
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  publicDir: mode === "development" ? "dev-public" : "public",
  // CSP `default-src 'self'` (Caddy, P6 §7) chặn URI `data:` → không nhúng font/ảnh dạng base64,
  // mọi tệp tĩnh ra `/assets/` cùng origin (KH 4.1 #7).
  build: { assetsInlineLimit: 0 },
  server: {
    host: "localhost",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000" },
    },
  },
}));
