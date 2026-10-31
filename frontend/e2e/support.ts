// Dùng chung cho các test e2e. Không in, không ghi mật khẩu / OTP / token: giá trị bí mật chỉ đi vào ô nhập qua
// `locator.evaluate` (tiêu đề bước "Evaluate" không chứa tham số — khác `fill`, tiêu đề bước là `Fill "<giá trị>"`).
import { expect, type Locator, type Page } from "@playwright/test";
import { CHAT_NAV, STAFF_NAV } from "../src/auth/permissions.ts";

export const NAV = { name: "Điều hướng chính" } as const;
export const LOGIN_HEADING = { name: "Đăng nhập", level: 1 } as const;
export const OTP_HEADING = { name: "Nhập mã xác thực", level: 1 } as const;
export const FORBIDDEN_HEADING = { name: "Bạn không có quyền xem trang này", level: 1 } as const;

/** Mọi mục thanh bên có thể có (src/auth/permissions.ts) — mục nào không thuộc vai thì phải VẮNG. */
export const ALL_NAV_LABELS: readonly string[] = [...STAFF_NAV.map((item) => item.label), CHAT_NAV.label];

export type Account = {
  username: string;
  title: string;
  passwordVar: string;
  home: string;
  nav: readonly string[];
};

// Kỳ vọng lấy từ code: quyền theo vai ở backend/app/auth/permissions.py (PERMS) → mục thanh bên theo `perm` của
// STAFF_NAV / CHAT_NAV và trang đầu theo homePath() (src/auth/permissions.ts); ba vai đầu khớp ACCOUNTS của
// scripts/verify.mjs (home/has/lacks).
export const ACCOUNTS = {
  employee: { username: "an.nv", title: "nhân viên", passwordVar: "E2E_PASSWORD_AN", home: "/chat", nav: ["Yêu cầu mới"] },
  l1: {
    username: "ha.lt",
    title: "L1",
    passwordVar: "E2E_PASSWORD_HA",
    home: "/approvals",
    nav: ["Chờ tôi duyệt", "Hàng đợi escalate"],
  },
  l2: { username: "long.nh", title: "L2", passwordVar: "E2E_PASSWORD_LONG", home: "/escalations", nav: ["Hàng đợi escalate"] },
  manager: {
    username: "quan.tm",
    title: "quản lý",
    passwordVar: "E2E_PASSWORD_QUAN",
    home: "/dashboard",
    nav: ["Tổng quan", "Cảnh báo", "Chính sách", "Trạng thái LLM", "Chờ tôi duyệt"],
  },
} as const satisfies Record<string, Account>;

/** Mật khẩu riêng của vai, không có thì E2E_PASSWORD chung (tài khoản demo dùng chung một mật khẩu). */
export const passwordOf = (account: Account): string | undefined =>
  process.env[account.passwordVar] || process.env.E2E_PASSWORD || undefined;

export const missingPassword = (account: Account): string =>
  `thiếu biến môi trường ${account.passwordVar} (hoặc E2E_PASSWORD chung) — bỏ qua vai ${account.title} (${account.username})`;

/** Gõ giá trị bí mật vào ô React có điều khiển, không để giá trị lọt vào tiêu đề bước / thông báo lỗi. */
async function typeSecret(input: Locator, value: string): Promise<void> {
  await input.waitFor();
  await input.evaluate((el, v) => {
    const field = el as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(field, v);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
}

const isLoginCall = (url: string, method: string) => method === "POST" && new URL(url).pathname === "/api/auth/login";

/**
 * Mở /login qua dev server, kiểm backend sống + KHÔNG phải dev:mock, điền tên + mật khẩu, bấm "Đăng nhập".
 * Trả mã HTTP của POST /api/auth/login (không đọc thân).
 */
export async function submitPassword(page: Page, account: Account, password: string): Promise<number> {
  const health = await page.request.get("/api/health");
  expect(
    health.status(),
    "GET /api/health qua dev server ≠ 200 — backend chưa chạy ở 127.0.0.1:8000 (hoặc dev server không proxy được)",
  ).toBe(200);
  await page.goto("/login");
  await expect(page.getByRole("heading", LOGIN_HEADING)).toBeVisible();
  const workers = await page.evaluate(async () =>
    "serviceWorker" in navigator ? (await navigator.serviceWorker.getRegistrations()).length : 0,
  );
  expect(workers, "trang có service worker — dev server đang chạy `npm run dev:mock` (MSW). Tắt nó, chạy lại.").toBe(0);
  await page.getByLabel("Tên đăng nhập", { exact: true }).fill(account.username);
  await typeSecret(page.getByLabel("Mật khẩu", { exact: true }), password);
  const [response] = await Promise.all([
    page.waitForResponse((r) => isLoginCall(r.url(), r.request().method())),
    page.getByRole("button", { name: "Đăng nhập", exact: true }).click(),
  ]);
  return response.status();
}

/**
 * Sau khi bấm: đã vào (thanh bên) / màn OTP / thông báo lỗi CỦA FORM đăng nhập (câu chung, không chứa bí mật).
 * Sau bước OTP (`fromOtp`) tiêu đề "Nhập mã xác thực" vẫn còn trong lúc chờ /me → chỉ chờ thanh bên hoặc lỗi.
 */
export async function afterSubmit(page: Page, { fromOtp = false } = {}): Promise<"signedIn" | "otp" | string> {
  const nav = page.getByRole("navigation", NAV);
  const otp = page.getByRole("heading", OTP_HEADING);
  const alert = page.locator("form").getByRole("alert");
  const settled = fromOtp ? nav.or(alert) : nav.or(otp).or(alert);
  await expect(settled.first()).toBeVisible();
  if (await nav.isVisible()) return "signedIn";
  if (!fromOtp && (await otp.isVisible())) return "otp";
  return `lỗi trên màn: "${(await alert.first().textContent())?.trim()}"`;
}

/** Nhập mã OTP 6 số (dán vào ô đầu, giao diện tự rải ra 6 ô) rồi bấm "Xác nhận". */
export async function submitOtp(page: Page, otp: string): Promise<number> {
  await typeSecret(page.getByLabel("Chữ số 1", { exact: true }), otp);
  const [response] = await Promise.all([
    page.waitForResponse((r) => isLoginCall(r.url(), r.request().method())),
    page.getByRole("button", { name: "Xác nhận", exact: true }).click(),
  ]);
  return response.status();
}

export async function signIn(page: Page, account: Account, password: string): Promise<void> {
  const status = await submitPassword(page, account, password);
  const state = await afterSubmit(page);
  expect(state, `${account.username}: không vào được (POST /api/auth/login → ${status})`).toBe("signedIn");
}

/** Đúng trang đầu và thanh bên có ĐÚNG các mục của vai — mục ngoài vai phải vắng. */
export async function expectHomeAndNav(page: Page, account: Account): Promise<void> {
  await expect(page, `${account.username}: trang đầu`).toHaveURL((url) => url.pathname === account.home);
  const nav = page.getByRole("navigation", NAV);
  await expect(nav).toBeVisible();
  for (const label of ALL_NAV_LABELS) {
    const expected = account.nav.includes(label) ? 1 : 0;
    await expect(
      nav.getByRole("link", { name: label, exact: true }),
      `${account.username}: mục thanh bên "${label}" ${expected ? "phải có" : "KHÔNG được có"}`,
    ).toHaveCount(expected);
  }
}

/**
 * Bearer của phiên trình duyệt: đọc header Authorization của request GET mà CHÍNH SPA gửi (vd /api/auth/me khi đăng
 * nhập) — như `bearerFrom` của scripts/verify.mjs. Gọi TRƯỚC khi đăng nhập. Token chỉ nằm trong biến, không in/ghi.
 */
export function bearerFrom(page: Page, match: (url: URL) => boolean) {
  let token: string | null = null;
  const reads: Promise<void>[] = [];
  const onRequest = (request: import("@playwright/test").Request) => {
    if (token !== null || request.method() !== "GET" || !match(new URL(request.url()))) return;
    reads.push(
      request.headerValue("authorization").then(
        (value) => {
          const found = /^Bearer (\S+)$/.exec(value ?? "")?.[1];
          if (found && token === null) token = found;
        },
        () => {},
      ),
    );
  };
  page.on("request", onRequest);
  return {
    async take(): Promise<string> {
      page.off("request", onRequest);
      await Promise.all(reads);
      expect(token !== null, "không đọc được header Authorization (Bearer) từ request GET nào của SPA").toBe(true);
      return token as unknown as string;
    },
  };
}
