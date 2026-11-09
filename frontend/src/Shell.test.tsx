// Khung sau đăng nhập dựng THẬT (Shell: thanh đầu + ngăn kéo + thanh bên + chuông). Chuông thông báo có đúng MỘT chỗ đứng theo khổ:
// ≥ 1024 px ở hàng logo của thanh bên (như cũ), dưới 1024 px ở thanh đầu và KHÔNG nằm trong ngăn kéo. Không gọi backend: fetch giả.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Me } from "./api/types.ts";
import { Shell } from "./App.tsx";
import { AuthContext } from "./auth/context.ts";
import { NAV_ID } from "./components/useMobileNav.ts";
import { DESKTOP_QUERY } from "./lib/viewport.ts";

const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
const EMP: Me = { user_id: "an.nv", role: "employee", permissions: BASE };
const L2: Me = { user_id: "long.nh", role: "l2", permissions: ["ticket:read:any", "escalation:handle"] };

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const NOTE = {
  id: "appr:1",
  kind: "approval_decided",
  ticket_id: "tkt-1",
  text: "IT đã duyệt yêu cầu của bạn.",
  result: "approved",
  new_ticket_id: null,
  created_at: new Date().toISOString(),
};

/** matchMedia giả: chỉ `DESKTOP_QUERY` đổi được; `setWide` phát sự kiện `change` như khi xoay máy / kéo cửa sổ. */
let wide = false;
let listeners = new Set<() => void>();
function stubViewport(initial: boolean) {
  wide = initial;
  listeners = new Set();
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      return query === DESKTOP_QUERY ? wide : false;
    },
    addEventListener: (_type: string, fn: () => void) => {
      if (query === DESKTOP_QUERY) listeners.add(fn);
    },
    removeEventListener: (_type: string, fn: () => void) => {
      listeners.delete(fn);
    },
  }));
}
const setWide = (value: boolean) =>
  act(() => {
    wide = value;
    listeners.forEach((fn) => fn());
  });

function mount(me: Me = EMP) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => (url.startsWith("/api/me/notifications") ? json(200, { items: [NOTE], next_cursor: null }) : json(404, { detail: "Not Found" }))),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={{ state: { status: "signedIn", me }, signIn: vi.fn(), signOut: vi.fn(async () => true) }}>
        <MemoryRouter initialEntries={["/chat"]}>
          <Routes>
            <Route element={<Shell />}>
              <Route path="/chat" element={<p>Trang chat</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

const topBar = () => document.querySelector("header")!;
const drawer = () => document.getElementById(NAV_ID)!;
const bells = () => screen.queryAllByTestId("tb-bell");

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("chuông thông báo: một chỗ đứng theo khổ", () => {
  it("dưới 1024 px: chuông ở thanh đầu, KHÔNG ở ngăn kéo — kể cả khi mở menu", async () => {
    stubViewport(false);
    mount();
    expect(await within(topBar()).findByTestId("tb-bell")).toBeTruthy();
    expect(bells()).toHaveLength(1);
    expect(within(drawer()).queryByTestId("tb-bell")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    expect(within(drawer()).queryByTestId("tb-bell")).toBeNull();
    expect(bells()).toHaveLength(1);
  });

  it("từ 1024 px: chuông ở hàng logo của thanh bên (như cũ), thanh đầu không có chuông", async () => {
    stubViewport(true);
    mount();
    expect(await within(drawer()).findByTestId("tb-bell")).toBeTruthy();
    expect(within(topBar()).queryByTestId("tb-bell")).toBeNull();
    expect(bells()).toHaveLength(1);
    // đúng hàng logo: cùng hàng với tên ứng dụng trong thanh bên
    const row = screen.getByTestId("tb-bell").closest("div.flex.h-10");
    expect(row?.textContent).toContain("ServiceDesk AI");
  });

  it("chuông ở thanh đầu mở được bảng thông báo, hiện số chưa đọc; Esc đóng bảng", async () => {
    stubViewport(false);
    mount();
    const bell = await within(topBar()).findByTestId("tb-bell");
    expect((await screen.findByTestId("tb-count")).textContent).toBe("1");
    fireEvent.click(bell);
    const panel = await screen.findByRole("dialog", { name: "Thông báo" });
    expect(within(panel).getByText("IT đã duyệt yêu cầu của bạn.")).toBeTruthy();
    fireEvent.keyDown(panel, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Thông báo" })).toBeNull();
  });

  it("qua điểm 1024 px chuông chuyển chỗ nhưng vẫn chỉ một bản, số chưa đọc không đổi", async () => {
    stubViewport(false);
    mount();
    await within(topBar()).findByTestId("tb-bell");
    expect((await screen.findByTestId("tb-count")).textContent).toBe("1");
    await setWide(true);
    expect(await within(drawer()).findByTestId("tb-bell")).toBeTruthy();
    expect(within(topBar()).queryByTestId("tb-bell")).toBeNull();
    expect(bells()).toHaveLength(1);
    expect((await screen.findByTestId("tb-count")).textContent).toBe("1");
    await setWide(false);
    expect(await within(topBar()).findByTestId("tb-bell")).toBeTruthy();
    expect(bells()).toHaveLength(1);
  });

  it("vai không có ticket:read:own (L2): không chuông ở đâu cả, thanh đầu vẫn có nút Menu", async () => {
    stubViewport(false);
    mount(L2);
    expect(screen.getByRole("button", { name: "Menu" })).toBeTruthy();
    await act(async () => {});
    expect(bells()).toHaveLength(0);
  });
});
