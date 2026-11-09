import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

// Luật bắt buộc KH mục 4.1 (Chốt P10 §4, P6) — lint đỏ thay vì chờ người review grep.
const noStorage = "Cấm lưu trữ trình duyệt: token chỉ nằm trong bộ nhớ (KH 4.1 #1).";

export default defineConfig([
  globalIgnores(["dist", "dev-public", "src/api/schema.gen.ts"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: { globals: globals.browser },
    rules: {
      // 4.1 #6: không log nội dung tin nhắn; chỉ cho console.error (không kèm dữ liệu — soát khi review).
      "no-console": ["error", { allow: ["error"] }],
      // 4.1 #5: nội dung từ LLM/agent chỉ hiện qua Markdown đã lọc HTML.
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: "Cấm dangerouslySetInnerHTML (KH 4.1 #5) — dùng react-markdown, không bật HTML thô.",
        },
      ],
      // 4.1 #1: cấm localStorage/sessionStorage/IndexedDB (cả dạng window.x, globalThis.x).
      "no-restricted-globals": [
        "error",
        { name: "localStorage", message: noStorage },
        { name: "sessionStorage", message: noStorage },
        { name: "indexedDB", message: noStorage },
      ],
      "no-restricted-properties": [
        "error",
        ...["window", "globalThis", "self"].flatMap((object) =>
          ["localStorage", "sessionStorage", "indexedDB"].map((property) => ({ object, property, message: noStorage })),
        ),
      ],
    },
  },
  {
    // Test phải nhắc tới Storage/IndexedDB để gài spy chứng minh code KHÔNG dùng chúng (t5).
    files: ["src/**/*.test.{ts,tsx}"],
    rules: { "no-restricted-globals": "off", "no-restricted-properties": "off" },
  },
  {
    // NGOẠI LỆ DUY NHẤT của luật cấm Storage (ĐP 26/10 N-TB P3): mốc `last_seen_at` của chuông thông báo — hợp đồng
    // thông báo §1 giữ trạng thái đọc ở trình duyệt. Giá trị CHỈ là chuỗi ISO, không token (lý do + giới hạn: đầu file đó).
    // Không thêm file nào khác vào đây; check:style miễn đúng file này.
    files: ["src/lib/lastSeen.ts"],
    rules: { "no-restricted-globals": "off", "no-restricted-properties": "off" },
  },
  {
    // Cấu hình + script chạy bằng Node (không vào bundle): được in ra terminal.
    files: ["*.{js,ts}", "scripts/**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
    rules: { "no-console": "off" },
  },
]);
