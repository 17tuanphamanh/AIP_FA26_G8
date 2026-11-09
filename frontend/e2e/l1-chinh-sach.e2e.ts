// (b) L1 không có quyền chính sách (hợp đồng thông báo mục 3.2): backend trả 403 cho GET /api/policy bằng chính phiên
// trình duyệt của ha.lt; thanh bên không có "Chính sách"; vào thẳng /policy → trang không có quyền, UI không gọi API.
// Bearer đọc từ header của request GET /api/auth/me mà SPA gửi lúc đăng nhập (như `bearerFrom` của scripts/verify.mjs);
// chỉ nằm trong biến, không in/ghi. 403 (không phải 401) nghĩa là token hợp lệ nhưng thiếu quyền `policy:read`.
import { expect, test } from "@playwright/test";
import {
  ACCOUNTS,
  type Account,
  bearerFrom,
  expectHomeAndNav,
  FORBIDDEN_HEADING,
  missingPassword,
  NAV,
  passwordOf,
  signIn,
} from "./support.ts";

test("L1 ha.lt: GET /api/policy → 403, không có menu Chính sách, /policy → không có quyền", async ({ page }) => {
  const account: Account = ACCOUNTS.l1;
  const password = passwordOf(account);
  test.skip(!password, missingPassword(account));

  const bearer = bearerFrom(page, (url) => url.pathname === "/api/auth/me");
  await signIn(page, account, password as string);
  await expectHomeAndNav(page, account);
  const nav = page.getByRole("navigation", NAV);
  await expect(nav.getByRole("link", { name: "Chính sách", exact: true }), "thanh bên L1 KHÔNG được có Chính sách").toHaveCount(0);

  const token = await bearer.take();
  const response = await page.request.get("/api/policy", { headers: { Authorization: `Bearer ${token}` } });
  expect(response.status(), "GET /api/policy bằng phiên L1 phải bị backend từ chối 403").toBe(403);

  const policyCalls: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/policy")) policyCalls.push(`${request.method()} ${url.pathname}`);
  });
  await page.goto("/policy");
  await expect(page.getByRole("heading", FORBIDDEN_HEADING)).toBeVisible();
  await expect(nav, "vẫn còn đăng nhập sau khi tải lại").toBeVisible();
  await expect(nav.getByRole("link", { name: "Chính sách", exact: true })).toHaveCount(0);
  expect(policyCalls, "trang /policy của L1 không được gọi API chính sách").toEqual([]);
});
