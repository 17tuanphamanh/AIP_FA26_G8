// (a) vai quản lý: quan.tm bắt buộc OTP → đúng trang đầu + đúng menu thanh bên (hợp đồng thông báo mục 3.1).
// Mã OTP do test TỰ SINH (TOTP RFC 6238, e2e/totp.ts) từ E2E_MANAGER_TOTP_SECRET (base32, secret đã enroll MFA của
// quan.tm). Không có biến → BỎ QUA. Backend KHÔNG có cờ bỏ MFA và test này không thêm cờ nào.
// Hạn chế OTP sai (ĐP 27/10 — sai cộng dồn có thể bắn cảnh báo an ninh / khoá quan.tm; backend khoá 5 lần / 10 phút):
// - Trước lần đầu: cửa sổ 30 s hiện tại còn < 5 s → chờ sang cửa sổ mới rồi mới sinh mã.
// - 401 lần đầu → DỪNG NGAY, trừ đúng một trường hợp: mã rơi sát ranh giới cửa sổ (lúc nhận 401 đồng hồ đã sang cửa
//   sổ sau, hoặc lúc gửi còn ≤ 3 s). Khi đó chờ sang cửa sổ mới, sinh lại mã TỪ THỜI GIAN HIỆN TẠI (không đoán mã bước
//   kế tiếp), gửi lần 2. Sai lần 2 → dừng. Thường chỉ 1 mã, tối đa 2 mã mỗi lượt. retries = 0 (playwright.config.ts).
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

/** Còn ít hơn chừng này giây trong cửa sổ 30 s thì chờ sang cửa sổ mới rồi mới sinh mã lần đầu. */
const MIN_SECONDS_LEFT = 5;
/** Lúc gửi mà cửa sổ còn ≤ chừng này giây → coi là sát ranh giới (được thử lại một lần). */
const NEAR_BOUNDARY_SECONDS = 3;
const OTP_REJECTED = "OTP bị từ chối — kiểm E2E_MANAGER_TOTP_SECRET và giờ máy (đồng bộ thời gian)";

const nowSeconds = () => Date.now() / 1000;
const secondsLeftInWindow = () => TOTP_STEP_SECONDS - (nowSeconds() % TOTP_STEP_SECONDS);

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

  if (secondsLeftInWindow() < MIN_SECONDS_LEFT) await page.waitForTimeout(Math.ceil((secondsLeftInWindow() + 0.5) * 1000));

  /** Sinh mã từ thời gian HIỆN TẠI, gửi, chờ kết quả. Mã chỉ nằm trong biến, không in. */
  const sendOtp = async () => {
    const counter = totpCounter(nowSeconds());
    const leftAtSend = secondsLeftInWindow();
    const status = await submitOtp(page, totpAt(totpSecret, counter));
    // Ngay lúc nhận phản hồi: đồng hồ đã sang cửa sổ sau, hoặc lúc gửi đã sát ranh giới.
    const nearBoundary = totpCounter(nowSeconds()) !== counter || leftAtSend <= NEAR_BOUNDARY_SECONDS;
    const state = await afterSubmit(page, { fromOtp: true });
    return { counter, status, state, nearBoundary };
  };

  const statuses: number[] = [];
  const first = await sendOtp();
  statuses.push(first.status);
  let state = first.state;
  if (state !== "signedIn" && first.status === 401 && first.nearBoundary) {
    // Mã có thể đã hết hạn giữa đường: chờ tới khi đã sang cửa sổ SAU cửa sổ của mã đầu (+0,5 s; đã sang rồi thì không
    // chờ), rồi sinh lại từ thời gian hiện tại — đúng MỘT lần.
    const nextWindowAt = (first.counter + 1) * TOTP_STEP_SECONDS + 0.5;
    await page.waitForTimeout(Math.max(0, Math.ceil((nextWindowAt - nowSeconds()) * 1000)));
    const second = await sendOtp();
    statuses.push(second.status);
    state = second.state;
  }
  expect(
    state,
    `${account.username}: ${OTP_REJECTED}. Đã gửi ${statuses.length} mã (POST /api/auth/login → ${statuses.join(", ")}). ` +
      "KHÔNG chạy lại liên tục — báo Tuấn Anh (backend khoá ở 5 lần sai / 10 phút).",
  ).toBe("signedIn");
  await expectHomeAndNav(page, account);
});
