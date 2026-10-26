// `npm run e2e` (N-E2E, hợp đồng thông báo mục 3): Playwright tối thiểu chạy trên dev server KHÔNG mock
// (`npm run dev`, proxy /api → backend thật 127.0.0.1:8000). Hướng dẫn chạy: e2e/README.md.
// - Không ghi bí mật ra đĩa: trace/video tắt; ảnh chụp CHỈ khi test đỏ (ô mật khẩu là type=password; test quản lý tắt
//   hẳn ảnh vì ô OTP hiện chữ số). Không có báo cáo HTML (tiêu đề bước của Playwright có thể chứa giá trị gõ vào).
// - retries = 0: mỗi lượt đăng nhập sai được backend đếm (khoá 5 lần / 10 phút) và OTP chỉ dùng được một lần.
import { defineConfig, devices } from "@playwright/test";

// Test đỏ → Playwright mặc định ghi ảnh chụp cây truy cập (aria snapshot) của trang vào error-context.md, gồm cả GIÁ TRỊ
// ô nhập (ô OTP). Tắt hẳn; thông báo lỗi của test vẫn đủ để đọc.
process.env.PLAYWRIGHT_NO_COPY_PROMPT = "1";

const baseURL = process.env.E2E_BASE_URL || "http://localhost:5173";
// Máy không có Chromium của Playwright (vd Windows dùng Chrome cài sẵn): trỏ E2E_CHROMIUM_PATH tới tệp chạy.
const executablePath = process.env.E2E_CHROMIUM_PATH || undefined;

export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.e2e.ts",
  // .verify/ đã gitignore (frontend/.gitignore) — kết quả e2e không lọt vào git.
  outputDir: ".verify/e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["./e2e/skip-reporter.ts"]],
  use: {
    baseURL,
    viewport: { width: 1440, height: 900 },
    trace: "off",
    video: "off",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, launchOptions: { executablePath } },
    },
  ],
  // Dev server đang chạy ở baseURL thì dùng lại; chưa chạy thì tự bật `npm run dev` (KHÔNG phải dev:mock).
  webServer: {
    command: "npm run dev",
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
