// TA 14/11 ("khó mở"): lối vào hệ thống giả lập từ app — "Điện thoại của tôi" cho mọi người, "Hệ thống giả lập" cho nhân viên IT,
// link ở trang đăng nhập. Chỉ ở bản demo (lib/demoTools.ts: `npm run dev` hoặc build có VITE_DEMO_TOOLS=1).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createClient } from "../api/client.ts";
import type { Me } from "../api/types.ts";
import { AuthProvider } from "../auth/AuthProvider.tsx";
import { LoginPage } from "../auth/LoginPage.tsx";
import { DEMO_TOOLS, MOCK_CONSOLE_URL, phoneUrl } from "../lib/demoTools.ts";
import { Sidebar } from "./Sidebar.tsx";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const EMP: Me = { user_id: "nv001", role: "employee", permissions: ["ticket:create", "ticket:read:own"] };
const L1: Me = { user_id: "l1_01", role: "l1", permissions: ["approval:decide", "escalation:handle", "dashboard:read:own"] };

function mountSidebar(me: Me) {
  vi.stubGlobal("fetch", vi.fn(async () => json(404, { detail: "Not Found" })));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <Sidebar me={me} onSignOut={async () => true} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Lối vào hệ thống giả lập (bản demo)", () => {
  it("chạy test = bản dev → bật", () => {
    expect(DEMO_TOOLS).toBe(true);
    expect(MOCK_CONSOLE_URL).toBe("http://127.0.0.1:8100/console");
  });

  it("nhân viên: 'Điện thoại của tôi' mở đúng máy của mình ở thẻ mới; không có link cả hệ thống", () => {
    mountSidebar(EMP);
    const phone = screen.getByTestId("nav-demo-phone");
    expect(phone.getAttribute("href")).toBe("http://127.0.0.1:8100/console/phone/nv001");
    expect(phone.getAttribute("target")).toBe("_blank");
    expect(phone.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.queryByTestId("nav-demo-console")).toBeNull();
  });

  it("nhân viên IT: có thêm 'Hệ thống giả lập'", () => {
    mountSidebar(L1);
    expect(screen.getByTestId("nav-demo-phone").getAttribute("href")).toBe(phoneUrl("l1_01"));
    expect(screen.getByTestId("nav-demo-console").getAttribute("href")).toBe(MOCK_CONSOLE_URL);
  });

  it("mã người dùng được mã hoá trong đường dẫn", () => {
    expect(phoneUrl("a b/c")).toBe("http://127.0.0.1:8100/console/phone/a%20b%2Fc");
  });

  it("trang đăng nhập có link mở hệ thống giả lập", async () => {
    const fetch = vi.fn(async () => json(401, { detail: "unauthorized" }));
    const client = createClient({ fetch, readCookie: () => null, locks: null, onSessionEnd: vi.fn() });
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AuthProvider client={client} subscribe={() => () => {}}>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>,
    );
    const box = await screen.findByTestId("login-demo-tools");
    expect(box.querySelector("a")?.getAttribute("href")).toBe(MOCK_CONSOLE_URL);
  });
});
