// (d) Điện thoại 390×844 — luồng chat của nhân viên (an.nv) trên stack thật: đăng nhập → trang chat → menu thu gọn → ô chat.
// Kiểm bố cục THẬT (happy-dom của vitest không có bố cục): không cuộn ngang cả trang, nút/ô nhập cao ≥ 44 px, chữ ≥ 14 px,
// menu mở/đóng (Esc, nút Đóng menu, chạm liên kết), chuông thông báo và ô chat nằm trọn trong màn.
// KHÔNG gửi tin nào: gửi = tạo ticket thật trên stack, mà e2e ở đây chỉ đọc (xem README.md). Bàn phím ảo của máy thật
// (iOS Safari / Chrome Android) Playwright không giả lập được — phần đó người kiểm bằng điện thoại thật.
import { expect, type Page, test } from "@playwright/test";
import { ACCOUNTS, missingPassword, NAV, passwordOf, submitPassword } from "./support.ts";

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

const MIN_TARGET = 44;
const MIN_FONT = 14;

type Audit = { overflowX: number; wide: string[]; small: string[]; tiny: string[] };

/** Đo trên trang đang hiện (bỏ phần tử ẩn / inert): tràn ngang, phần tử vượt mép phải, nút–ô nhập thấp hơn 44 px, chữ nhỏ hơn 14 px. */
async function audit(page: Page): Promise<Audit> {
  return page.evaluate(
    ([minTarget, minFont]) => {
      const shown = (el: Element) => {
        const box = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return box.width > 0 && box.height > 0 && style.visibility !== "hidden" && !el.closest("[inert], .sr-only");
      };
      const name = (el: Element) => `${el.tagName.toLowerCase()} "${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 28)}"`;
      const root = document.documentElement;
      const wide = Array.from(document.querySelectorAll("body *"))
        .filter((el) => shown(el) && el.getBoundingClientRect().right > root.clientWidth + 1 && !el.closest("pre, table, [class*='overflow-x']"))
        .slice(0, 6)
        .map(name);
      const small = Array.from(document.querySelectorAll("button, input:not([type=checkbox]):not([type=radio]), textarea, select, [role=tab], [role=radio], nav a"))
        .filter((el) => shown(el) && el.getBoundingClientRect().height < minTarget - 0.01)
        .map((el) => `${name(el)} ${Math.round(el.getBoundingClientRect().height)}px`);
      const tiny: string[] = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const el = node.parentElement;
        if (!el || !(node.textContent ?? "").trim() || !shown(el) || el.closest("script, style, noscript")) continue;
        if (parseFloat(getComputedStyle(el).fontSize) < minFont) tiny.push(`${name(el)} ${getComputedStyle(el).fontSize}`);
      }
      return { overflowX: root.scrollWidth - root.clientWidth, wide, small, tiny: tiny.slice(0, 8) };
    },
    [MIN_TARGET, MIN_FONT],
  );
}

async function expectClean(page: Page, where: string) {
  const result = await audit(page);
  expect(result.overflowX, `${where}: trang cuộn ngang ${result.overflowX}px; vượt mép phải: ${result.wide.join(", ")}`).toBeLessThanOrEqual(0);
  expect(result.small, `${where}: nút / ô nhập thấp hơn ${MIN_TARGET}px`).toEqual([]);
  expect(result.tiny, `${where}: chữ nhỏ hơn ${MIN_FONT}px`).toEqual([]);
}

test("điện thoại 390×844: nhân viên đăng nhập, menu thu gọn, ô chat — bố cục không tràn, nút ≥ 44 px, chữ ≥ 14 px", async ({ page }) => {
  const account = ACCOUNTS.employee;
  const password = passwordOf(account);
  test.skip(!password, missingPassword(account));
  const status = await submitPassword(page, account, password as string);

  // Thanh bên đã thu vào nút menu: ở khổ này "navigation" chưa hiện, nút Menu ở thanh đầu thì có.
  const menu = page.getByRole("button", { name: "Menu", exact: true });
  await expect(menu, `${account.username}: không vào được (POST /api/auth/login → ${status})`).toBeVisible();
  await expect(page).toHaveURL((url) => url.pathname === account.home);
  const nav = page.getByRole("navigation", NAV);
  await expect(nav).toBeHidden();
  await expect(menu).toHaveAttribute("aria-expanded", "false");

  // Trang chat: ô nhập nằm trọn trong màn, đủ cao; nút gửi (khoá tới khi có chữ) cũng ≥ 44 px.
  const box = page.getByRole("textbox", { name: "Mô tả vấn đề" });
  await expect(box).toBeVisible();
  const send = page.getByRole("button", { name: "Gửi", exact: true });
  for (const [what, target] of [["ô nhập", box], ["nút gửi", send]] as const) {
    const rect = (await target.boundingBox())!;
    expect(rect.height, `${what} cao ${rect.height}px`).toBeGreaterThanOrEqual(MIN_TARGET);
    expect(rect.x, `${what} lọt mép trái`).toBeGreaterThanOrEqual(0);
    expect(rect.x + rect.width, `${what} lọt mép phải`).toBeLessThanOrEqual(390);
    expect(rect.y + rect.height, `${what} lọt mép dưới`).toBeLessThanOrEqual(844);
  }
  await expectClean(page, "trang chat (menu đóng)");

  // Mở menu: tiêu điểm vào trong, nội dung phía sau inert, liên kết cao ≥ 44 px.
  await menu.click();
  await expect(nav).toBeVisible();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("main")).toHaveAttribute("inert", "");
  await expectClean(page, "menu mở");

  // Chuông thông báo (route có thể chưa có → không chuông): bảng thông báo phải nằm trọn trong màn.
  const bell = page.getByTestId("tb-bell");
  if (await bell.count()) {
    await bell.click();
    const panel = page.getByRole("dialog", { name: "Thông báo" });
    await expect(panel).toBeVisible();
    const rect = (await panel.boundingBox())!;
    expect(rect.x, "bảng thông báo lọt mép trái").toBeGreaterThanOrEqual(0);
    expect(rect.x + rect.width, "bảng thông báo lọt mép phải").toBeLessThanOrEqual(390);
    expect(rect.y + rect.height, "bảng thông báo lọt mép dưới").toBeLessThanOrEqual(844);
    await expectClean(page, "bảng thông báo");
    await page.keyboard.press("Escape"); // Esc trong bảng chỉ đóng bảng, ngăn kéo vẫn mở
    await expect(panel).toBeHidden();
    await expect(nav).toBeVisible();
  }

  // Esc đóng menu, tiêu điểm về nút Menu.
  await page.keyboard.press("Escape");
  await expect(nav).toBeHidden();
  await expect(menu).toBeFocused();
  await expect(menu).toHaveAttribute("aria-expanded", "false");

  // Nút "Đóng menu" và chạm vào liên kết cũng đóng.
  await menu.click();
  await page.getByRole("button", { name: "Đóng menu" }).click();
  await expect(nav).toBeHidden();
  await menu.click();
  await nav.getByRole("link", { name: "Yêu cầu mới", exact: true }).click();
  await expect(nav).toBeHidden();
  await expect(page).toHaveURL((url) => url.pathname === account.home);

  // Gõ vào ô chat (không gửi): nút gửi mở khoá, ô và nút vẫn nằm trong màn.
  await box.fill("Thử bố cục trên điện thoại — không gửi");
  await expect(send).toBeEnabled();
  const typed = (await send.boundingBox())!;
  expect(typed.y + typed.height, "nút gửi lọt mép dưới sau khi gõ").toBeLessThanOrEqual(844);
  await expectClean(page, "trang chat (đã gõ)");
});
