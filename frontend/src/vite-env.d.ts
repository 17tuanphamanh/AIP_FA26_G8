/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" → bật MSW (CHỈ khi dev). Đặt qua `npm run dev:mock`, không qua file `.env*` (KH 4.3, 12b). */
  readonly VITE_API_MOCK?: "0" | "1";
  /** "1" → hiện lối vào hệ thống giả lập ở bản build (gói nộp). `npm run dev` luôn hiện (lib/demoTools.ts). */
  readonly VITE_DEMO_TOOLS?: "0" | "1";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
