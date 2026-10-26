// (a) vai quản lý: quan.tm bắt buộc OTP → đúng trang đầu + đúng menu thanh bên (hợp đồng thông báo mục 3.1).
// Mã OTP do test TỰ SINH (TOTP RFC 6238, e2e/totp.ts) từ E2E_MANAGER_TOTP_SECRET (base32, secret đã enroll MFA của
// quan.tm). Không có biến → BỎ QUA. Backend KHÔNG có cờ bỏ MFA và test này không thêm cờ nào.
// Tối đa 2 lần OTP mỗi lượt (backend khoá ở 5 lần sai / 10 phút): mã của bước hiện tại; bị từ chối (401 — đồng hồ máy
// lệch) → mã của bước KẾ TIẾP một lần; vẫn bị từ chối → đỏ, không thử nữa. retries = 0 (playwright.config.ts).
import { expect, test } from "@playwright/test";
import {
  ACCOUNTS,
  type Account,
  afterSubmit,
  expectHomeAndNav,
  missingPassword,
  passwordOf,
  submitOtp,
  submitPassword,
} from "./support.ts";
import { base32Decode, TOTP_STEP_SECONDS, totpAt, totpCounter } from "./totp.ts";

/** Tối đa số lần gửi OTP mỗi lượt chạy. */
const MAX_OTP_ATTEMPTS = 2;
/** Còn ít hơn chừng này giây trong bước 30 s thì chờ sang bước mới rồi mới sinh mã (tránh mã hết hạn giữa đường). */
const MIN_SECONDS_LEFT = 5;

// Ô OTP hiện chữ số (không phải type=password) → không chụp ảnh kể cả khi đỏ.
test.use({ screenshot: "off" });

test(`quản lý ${ACCOUNTS.manager.username} (OTP) → ${ACCOUNTS.manager.home}`, async ({ page }) => {
  const account: Account = ACCOUNTS.manager;
  const password = passwordOf(account);
  test.skip(!password, missingPassword(account));
  const secret = process.env.E2E_MANAGER_TOTP_SECRET?.trim();
  test.skip(
    !secret,
    "thiếu E2E_MANAGER_TOTP_SECRET — quản lý bắt buộc OTP; đặt secret base32 đã enroll MFA của quan.tm (xem e2e/README.md)",
  );
  const totpSecret = secret as string;
  base32Decode(totpSecret); // secret hỏng → ném lỗi rõ ràng (thông báo không chứa secret) TRƯỚC khi đăng nhập

  const status = await submitPassword(page, account, password as string);
  const step = await afterSubmit(page);
  expect(step, `${account.username}: không sang bước OTP (POST /api/auth/login → ${status}; cần 401 mfa_required)`).toBe("otp");

  const secondsLeft = TOTP_STEP_SECONDS - ((Date.now() / 1000) % TOTP_STEP_SECONDS);
  if (secondsLeft < MIN_SECONDS_LEFT) await page.waitForTimeout(Math.ceil((secondsLeft + 0.5) * 1000));
  const counter = totpCounter(Date.now() / 1000);

  const statuses: number[] = [];
  let state = "";
  for (let attempt = 0; attempt < MAX_OTP_ATTEMPTS; attempt += 1) {
    const otpStatus = await submitOtp(page, totpAt(totpSecret, counter + attempt));
    statuses.push(otpStatus);
    state = await afterSubmit(page, { fromOtp: true });
    if (state === "signedIn" || otpStatus !== 401) break; // khác 401 (vd bị khoá, 5xx) → không thử mã kế tiếp
  }
  expect(
    state,
    `${account.username}: OTP tự sinh không được nhận sau ${statuses.length} lần (POST /api/auth/login → ${statuses.join(", ")}). ` +
      "Kiểm đồng hồ máy (phải đúng giờ, tự đồng bộ) và E2E_MANAGER_TOTP_SECRET (đúng secret đã enroll). " +
      "Đừng chạy lặp liên tục: backend khoá ở 5 lần sai / 10 phút.",
  ).toBe("signedIn");
  await expectHomeAndNav(page, account);
});
