/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// Q-fe-29 (lớp 1): dữ liệu giả không bao giờ vào bản build. Handler / fixture / worker của MSW chỉ được nạp bằng
// `import()` động trong nhánh DEV của main.tsx (bị loại khi build). Lỡ có module nào của app import thẳng một fixture
// → build LỖI ngay, kể cả fixture không mang chữ đánh dấu nào (check:dist là lớp 2, quét chữ `apv-demo-`, `tkt-demo-`).
// `src/mocks/flag.ts` (cờ MOCK_ENABLED = false ở build) được phép.
const MOCK_MODULE = /\/src\/mocks\/(?:handlers\/|fixtures\/|browser\.ts$)/;
function noMocksInBuild(): Plugin {
  return {
    name: "no-mocks-in-build",
    apply: "build",
    generateBundle(_options, bundle) {
      const leaked = Object.values(bundle).flatMap((chunk) =>
        chunk.type === "chunk" ? chunk.moduleIds.filter((id) => MOCK_MODULE.test(id.replaceAll("\\", "/"))) : [],
      );
      if (leaked.length > 0) this.error(`dữ liệu giả lọt vào bản build: ${leaked.join(", ")}`);
    },
  };
}

// KH mục 2 + 4.3:
// - `/api` đi qua proxy → trình duyệt thấy cùng origin, cookie SameSite=Strict chạy, không cần CORS.
// - Worker của MSW nằm ở `dev-public/`, CHỈ được phục vụ ở mode development. Build (mode production)
//   dùng `public/` — không có worker. `npm run check:dist` chặn nếu worker lọt vào `dist/`.
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), noMocksInBuild()],
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
  // `npm run test`: test hàm thuần + component, KHÔNG gọi backend (fetch giả truyền qua tham số).
  test: {
    environment: "happy-dom",
    // scripts/**: hàm thuần của verify (vd lib/queue-check.mjs — quyết định F3-1, t38).
    include: ["src/**/*.test.{ts,tsx}", "scripts/**/*.test.mjs"],
    restoreMocks: true,
    unstubGlobals: true,
  },
}));
