// Điện thoại (dưới 1024 px): thanh bên thu vào nút menu. Logic ở MobileNav.tsx — mở/đóng, Esc, aria, tiêu điểm, đóng khi đổi
// màn / bấm liên kết / kéo rộng tới ≥ 1024 px. CSS (ẩn/hiện theo khổ) không chạy trong happy-dom: ở đây kiểm trạng thái và
// thuộc tính; phần bố cục thật do ca Playwright 390×844 (e2e/chat-dien-thoai.e2e.ts) và verify trên máy có trình duyệt.
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { Link, MemoryRouter, useLocation, useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MobileNavBar, NavDrawer } from "./MobileNav.tsx";
import { DESKTOP_QUERY } from "../lib/viewport.ts";
import { NAV_ID, useMobileNav } from "./useMobileNav.ts";

type Listener = () => void;
let listeners: Set<Listener>;
let wide: { matches: boolean; addEventListener: (type: string, fn: Listener) => void; removeEventListener: (type: string, fn: Listener) => void };

/** matchMedia giả: chỉ truy vấn `DESKTOP_QUERY` có phản ứng; `widen()` giả lập kéo rộng tới ≥ 1024 px. */
function stubViewport() {
  listeners = new Set();
  wide = {
    matches: false,
    addEventListener: (_type, fn) => listeners.add(fn),
    removeEventListener: (_type, fn) => listeners.delete(fn),
  };
  vi.stubGlobal("matchMedia", (query: string) => (query === DESKTOP_QUERY ? wide : { ...wide, matches: false }));
}
const widen = () =>
  act(() => {
    wide.matches = true;
    listeners.forEach((fn) => fn());
  });

function Harness() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { open, toggle, close, buttonRef, drawerRef } = useMobileNav(pathname);
  return (
    <>
      <MobileNavBar open={open} onToggle={toggle} buttonRef={buttonRef} />
      <NavDrawer open={open} onClose={close} drawerRef={drawerRef}>
        <nav aria-label="Điều hướng chính">
          <Link to="/">Trang đầu</Link>
          <Link to="/approvals">Chờ tôi duyệt</Link>
        </nav>
      </NavDrawer>
      <main inert={open}>
        <button type="button" onClick={() => void navigate("/escalations")}>
          Đi nơi khác
        </button>
        <output data-testid="path">{pathname}</output>
      </main>
    </>
  );
}

const mount = (path = "/") =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Harness />
    </MemoryRouter>,
  );

const toggle = () => screen.getByRole("button", { name: "Menu" });
const drawer = () => document.getElementById(NAV_ID)!;
const isOpen = () => toggle().getAttribute("aria-expanded") === "true";

beforeEach(stubViewport);
afterEach(cleanup);

describe("menu thu gọn trên điện thoại", () => {
  it("mặc định đóng; nút menu có aria-expanded=false và aria-controls trỏ đúng vỏ ngăn kéo", () => {
    mount();
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(toggle().getAttribute("aria-controls")).toBe(NAV_ID);
    expect(drawer().dataset.open).toBe("false");
    expect(drawer().className).toContain("hidden"); // dưới 1024 px: không hiện, không vào cây truy cập
    expect(drawer().className).toContain("lg:contents"); // từ 1024 px: không sinh hộp — thanh bên ở chỗ cũ
    expect(document.querySelector("main")!.hasAttribute("inert")).toBe(false);
  });

  it("bấm nút menu: mở, tiêu điểm vào ngăn kéo, vùng nội dung và thanh đầu thành inert; bấm lại thì đóng", () => {
    mount();
    fireEvent.click(toggle());
    expect(isOpen()).toBe(true);
    expect(drawer().dataset.open).toBe("true");
    expect(drawer().className).toContain("fixed");
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "Trang đầu" }));
    expect(document.querySelector("main")!.hasAttribute("inert")).toBe(true);
    expect(document.querySelector("header")!.hasAttribute("inert")).toBe(true);
    fireEvent.click(toggle());
    expect(isOpen()).toBe(false);
    expect(document.querySelector("main")!.hasAttribute("inert")).toBe(false);
  });

  it("Esc đóng và trả tiêu điểm về nút menu", () => {
    mount();
    fireEvent.click(toggle());
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(isOpen()).toBe(false);
    expect(document.activeElement).toBe(toggle());
  });

  it("Esc khi đang đóng không làm gì (không cướp tiêu điểm)", () => {
    mount();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(isOpen()).toBe(false);
    expect(document.activeElement).not.toBe(toggle());
  });

  it("phím khác Esc không đóng", () => {
    mount();
    fireEvent.click(toggle());
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    expect(isOpen()).toBe(true);
  });

  it("chạm vùng mờ hoặc nút Đóng menu: đóng, tiêu điểm về nút menu", () => {
    mount();
    fireEvent.click(toggle());
    fireEvent.click(drawer().querySelector('div[aria-hidden="true"]')!);
    expect(isOpen()).toBe(false);
    expect(document.activeElement).toBe(toggle());

    fireEvent.click(toggle());
    fireEvent.click(within(drawer()).getByRole("button", { name: "Đóng menu" }));
    expect(isOpen()).toBe(false);
    expect(document.activeElement).toBe(toggle());
  });

  it("bấm liên kết trong ngăn kéo: đi tới màn đó và đóng", () => {
    mount();
    fireEvent.click(toggle());
    fireEvent.click(screen.getByRole("link", { name: "Chờ tôi duyệt" }));
    expect(screen.getByTestId("path").textContent).toBe("/approvals");
    expect(isOpen()).toBe(false);
  });

  it("bấm liên kết tới chính trang đang mở (đường dẫn không đổi) vẫn đóng", () => {
    mount("/approvals");
    fireEvent.click(toggle());
    fireEvent.click(screen.getByRole("link", { name: "Chờ tôi duyệt" }));
    expect(screen.getByTestId("path").textContent).toBe("/approvals");
    expect(isOpen()).toBe(false);
  });

  it("đổi đường dẫn bằng cách khác (chuyển hướng, nút Back) cũng đóng", () => {
    mount();
    fireEvent.click(toggle());
    fireEvent.click(screen.getByRole("button", { name: "Đi nơi khác" }));
    expect(screen.getByTestId("path").textContent).toBe("/escalations");
    expect(isOpen()).toBe(false);
  });

  it("kéo rộng tới ≥ 1024 px khi đang mở: tự đóng", () => {
    mount();
    fireEvent.click(toggle());
    widen();
    expect(isOpen()).toBe(false);
  });

  it("đóng thì gỡ hết trình nghe (Esc, đổi khổ)", () => {
    const { unmount } = mount();
    fireEvent.click(toggle());
    expect(listeners.size).toBe(1);
    fireEvent.click(toggle());
    expect(listeners.size).toBe(0);
    unmount();
  });
});

