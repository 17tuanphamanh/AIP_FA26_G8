// (e) Chuỗi chiều cao của khung ở desktop 1440×900 (sửa lỗi sau commit 0eb24d8): màn dùng `h-full` / `min-h-full` phải đúng
// bằng chiều cao vùng nội dung — chat dính đáy ô nhập, phiếu duyệt dính đáy thanh quyết định, trang chủ chat căn giữa dọc.
// Chỉ đọc, không gửi / duyệt gì. Màn cần dữ liệu (ticket trong "Gần đây", phiếu chờ duyệt) mà stack chưa có thì bỏ qua đoạn đó.
import { expect, type Page, test } from "@playwright/test";
import { ACCOUNTS, missingPassword, passwordOf, signIn } from "./support.ts";

/** Chiều cao: vùng nội dung (`main`), vỏ (`main > div`), gốc của màn (con đầu tiên của vỏ, sau dải flash nếu có). */
async function heights(page: Page) {
  return page.evaluate(() => {
    const main = document.querySelector("main")!;
    const wrapper = main.firstElementChild!;
    const root = wrapper.querySelector(":scope > section, :scope > div")!;
    return { main: main.clientHeight, wrapper: wrapper.getBoundingClientRect().height, root: root.getBoundingClientRect().height, overflow: wrapper.scrollHeight - wrapper.clientHeight };
  });
}

test("nhân viên: vỏ nội dung cao bằng vùng nội dung; trang chủ chat căn giữa dọc; chat dính đáy", async ({ page }) => {
  const account = ACCOUNTS.employee;
  const password = passwordOf(account);
  test.skip(!password, missingPassword(account));
  await signIn(page, account, password as string);

  await expect(page.getByRole("textbox", { name: "Mô tả vấn đề" })).toBeVisible();
  const home = await heights(page);
  expect(Math.abs(home.wrapper - home.main), "vỏ nội dung không cao bằng main — chuỗi h-full đứt").toBeLessThanOrEqual(1);
  expect(home.root, "trang chủ chat không phủ hết chiều cao (min-h-full không tác dụng)").toBeGreaterThanOrEqual(home.main - 1);

  const recent = page.getByRole("navigation", { name: "Điều hướng chính" }).getByRole("list", { name: "Yêu cầu gần đây" }).getByRole("link").first();
  test.skip((await recent.count()) === 0, "chưa có ticket nào trong 'Gần đây' — bỏ qua phần chat");
  await recent.click();
  await expect(page).toHaveURL(/\/chat\/.+/);
  await expect(page.getByTestId("ticket-id")).toBeVisible();
  const chat = await heights(page);
  expect(Math.abs(chat.root - chat.main), "màn chat không cao bằng vùng nội dung — ô nhập không dính đáy").toBeLessThanOrEqual(1);
  expect(chat.overflow, "cả trang chat cuộn (lẽ ra chỉ vùng tin nhắn cuộn)").toBeLessThanOrEqual(1);
});

test("L1: phiếu duyệt cao bằng vùng nội dung, thanh quyết định dính đáy", async ({ page }) => {
  const account = ACCOUNTS.l1;
  const password = passwordOf(account);
  test.skip(!password, missingPassword(account));
  await signIn(page, account, password as string);

  const row = page.getByTestId("inbox-row").first();
  test.skip((await row.count()) === 0, "không có phiếu nào trong hộp thư — bỏ qua");
  await row.click();
  const bar = page.getByTestId("decision-bar");
  test.skip((await bar.count()) === 0, "phiếu đầu tiên không có thanh quyết định (chỉ đọc) — bỏ qua");
  const detail = await heights(page);
  expect(Math.abs(detail.root - detail.main), "phiếu duyệt không cao bằng vùng nội dung").toBeLessThanOrEqual(1);
  expect(detail.overflow, "cả trang phiếu cuộn (lẽ ra chỉ vùng chi tiết cuộn)").toBeLessThanOrEqual(1);
  const main = (await page.locator("main").boundingBox())!;
  const barBox = (await bar.boundingBox())!;
  expect(Math.abs(barBox.y + barBox.height - (main.y + main.height)), "thanh quyết định không nằm sát đáy vùng nội dung").toBeLessThanOrEqual(1);
});
