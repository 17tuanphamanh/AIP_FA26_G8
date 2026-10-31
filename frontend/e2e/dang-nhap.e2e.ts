// (a) Đăng nhập 3 vai không OTP → đúng trang đầu + đúng menu thanh bên (hợp đồng thông báo mục 3.1).
// Vai thứ tư (quản lý, bắt buộc OTP) ở dang-nhap-quan-ly.e2e.ts.
import { test } from "@playwright/test";
import { ACCOUNTS, type Account, expectHomeAndNav, missingPassword, passwordOf, signIn } from "./support.ts";

test.describe("đăng nhập nhân viên / L1 / L2: trang đầu + thanh bên", () => {
  for (const account of [ACCOUNTS.employee, ACCOUNTS.l1, ACCOUNTS.l2] satisfies Account[]) {
    test(`${account.title} ${account.username} → ${account.home}`, async ({ page }) => {
      const password = passwordOf(account);
      test.skip(!password, missingPassword(account));
      await signIn(page, account, password as string);
      await expectHomeAndNav(page, account);
    });
  }
});
