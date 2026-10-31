// t227–t230: logo Trường Đại học FPT (gói fe-logo-fpt) — trang đăng nhập + chân thanh bên; logo AITHA (logo.svg) giữ
// nguyên ở đầu thanh bên và ảnh đại diện trợ lý; tệp ảnh trùng từng byte bản chính thức. Không gọi backend: fetch giả.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createClient } from "../api/client.ts";
import type { Me } from "../api/types.ts";
import { AuthProvider } from "../auth/AuthProvider.tsx";
import { LoginPage } from "../auth/LoginPage.tsx";
import { ROLE_LABEL } from "../auth/permissions.ts";
import { Conversation } from "./Conversation.tsx";
import { normalizeConversation } from "./messages.ts";
import { Sidebar } from "./Sidebar.tsx";

afterEach(cleanup);

const ALT = "Trường Đại học FPT";
/** sha256 bản chính thức (PNG 330×93 RGBA) — đổi byte nào (nén lại, đổi màu, cắt) là đỏ. */
const FPT_LOGO_SHA256 = "93f197aae5453f64c62098f1a717e4655f6133e581b6a870bf55cb61e69ffe2a";

const json = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
const PERMS: Record<Me["role"], string[]> = {
  employee: BASE,
  l1: [...BASE, "ticket:read:any", "approval:decide", "decision:override", "escalation:handle", "dashboard:read:own", "audit:read:own"],
  l2: [...BASE, "ticket:read:any", "escalation:handle", "kb:edit"],
  manager: [...BASE, "ticket:read:any", "approval:decide", "policy:read", "policy:edit", "dashboard:read:all", "audit:read:all", "alert:read"],
};
const ROLES = Object.keys(ROLE_LABEL) as Me["role"][];

function mountSidebar(me: Me) {
  vi.stubGlobal("fetch", vi.fn(async () => json(404, { detail: "Not Found" })));
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <Sidebar me={me} onSignOut={async () => true} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("t227: trang đăng nhập — logo FPT + dòng chữ dưới thẻ đăng nhập", () => {
  it('img alt "Trường Đại học FPT" (330×93, cao theo CSS) + "Đồ án tốt nghiệp · Trường Đại học FPT"; logo AITHA vẫn ở đầu', async () => {
    const fetch = vi.fn(async () => json(401, { detail: "unauthorized" }));
    const client = createClient({ fetch, readCookie: () => null, locks: null, onSessionEnd: vi.fn() });
    const { container } = render(
      <MemoryRouter initialEntries={["/login"]}>
        <AuthProvider client={client} subscribe={() => () => {}}>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>,
    );
    await screen.findByLabelText("Tên đăng nhập");
    const logo = screen.getByRole("img", { name: ALT });
    expect(logo.getAttribute("src")).toMatch(/fpt-university-logo.*\.png/);
    expect([logo.getAttribute("width"), logo.getAttribute("height")]).toEqual(["330", "93"]);
    expect(logo.className).toContain("h-10");
    expect(logo.className).toContain("w-auto");
    const footer = logo.closest("footer");
    expect(footer?.textContent).toContain("Đồ án tốt nghiệp · Trường Đại học FPT");
    // Dưới thẻ đăng nhập: footer đứng sau form trong DOM.
    const form = container.querySelector("form");
    expect(form && footer && form.compareDocumentPosition(footer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("Logo đơn vị")).toBeNull();
    expect(container.querySelector('img[src*="logo.svg"]')).not.toBeNull();
  });
});

describe("t228: thanh bên (mọi vai) — chân có logo FPT + chữ; đầu vẫn logo AITHA", () => {
  it.each(ROLES)("%s", (role) => {
    const { container } = mountSidebar({ user_id: `u-${role}`, role, permissions: PERMS[role] });
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    const logo = within(nav).getByRole("img", { name: ALT });
    expect(logo.getAttribute("src")).toMatch(/fpt-university-logo.*\.png/);
    expect([logo.getAttribute("width"), logo.getAttribute("height")]).toEqual(["330", "93"]);
    expect(logo.className).toContain("h-6");
    expect(logo.className).toContain("w-auto");
    expect(within(screen.getByTestId("sidebar-fpt")).getByText(ALT)).toBeTruthy();
    expect(within(nav).queryByText("Logo đơn vị")).toBeNull();
    // Logo AITHA ở hàng đầu (cạnh "ServiceDesk AI"), không bị thay bằng logo FPT.
    const imgs = [...container.querySelectorAll("img")];
    expect(imgs[0]?.getAttribute("src")).toMatch(/logo\.svg$/);
    expect(imgs.filter((img) => /fpt-university-logo/.test(img.getAttribute("src") ?? ""))).toHaveLength(1);
  });
});

describe("t229: ảnh đại diện trợ lý vẫn là logo AITHA", () => {
  it("Conversation: tin trợ lý dùng logo.svg; không có logo FPT", () => {
    const messages = normalizeConversation([{ role: "assistant", kind: "answer", text: "Chào bạn." }]);
    const { container } = render(<Conversation messages={messages} />);
    const srcs = [...container.querySelectorAll("img")].map((img) => img.getAttribute("src") ?? "");
    expect(srcs.length).toBeGreaterThan(0);
    expect(srcs.every((src) => /logo\.svg$/.test(src))).toBe(true);
  });

  it("DigestMessage, StreamingText vẫn import logo.svg, không import logo FPT (quét tĩnh)", () => {
    const sources = import.meta.glob<string>(["/src/components/DigestMessage.tsx", "/src/routes/employee/StreamingText.tsx"], {
      query: "?raw",
      import: "default",
      eager: true,
    });
    expect(Object.keys(sources)).toHaveLength(2);
    for (const text of Object.values(sources)) {
      expect(text).toMatch(/import logoUrl from "[./]+\/assets\/logo\.svg";/);
      expect(text).not.toContain("fpt-university-logo");
    }
  });
});

describe("t230: tệp src/assets/fpt-university-logo.png trùng từng byte bản chính thức", () => {
  it("sha256 + PNG 330×93", async () => {
    const [uri = ""] = Object.values(
      import.meta.glob<string>("/src/assets/fpt-university-logo.png", { query: "?inline", import: "default", eager: true }),
    );
    expect(uri).toMatch(/^data:image\/png;base64,/);
    const bytes = Uint8Array.from(atob(uri.slice(uri.indexOf(",") + 1)), (c) => c.charCodeAt(0));
    const hex = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");
    expect(hex).toBe(FPT_LOGO_SHA256);
    const view = new DataView(bytes.buffer);
    expect([view.getUint32(16), view.getUint32(20)]).toEqual([330, 93]); // IHDR width, height
  });
});
