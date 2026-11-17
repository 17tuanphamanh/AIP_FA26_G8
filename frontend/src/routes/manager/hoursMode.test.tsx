// D-97 (demo 14/11) — giả lập giờ hành chính: khối trên trang Chính sách (Trưởng BP đổi chế độ) và dải báo ở khung chung.
// Không gọi backend: fetch giả trả đúng hình dạng route backend/app/api/hours_mode.py.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createClient } from "../../api/client.ts";
import { type HoursModeView, parseHoursModeView } from "../../api/hoursMode.ts";
import type { Me } from "../../api/types.ts";
import { AuthProvider } from "../../auth/AuthProvider.tsx";
import { useAuth } from "../../auth/useAuth.ts";
import { HoursModeBanner } from "../../components/HoursModeBanner.tsx";
import { AD_ADMIN_URL, Sidebar } from "../../components/Sidebar.tsx";
import { HoursModeSection } from "./HoursModeSection.tsx";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const c of clients.splice(0)) c.clear();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const jwt = (sub: string) => `h.${btoa(JSON.stringify({ sub })).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_")}.s`;
const MGR: Me = { user_id: "it_mgr01", role: "manager", permissions: ["policy:read", "policy:edit", "dashboard:read:all"] };
const EMP: Me = { user_id: "nv001", role: "employee", permissions: ["ticket:create", "ticket:read:own"] };
const REAL: HoursModeView = { mode: "real", modes: ["real", "outside", "inside"], changed_by: null, changed_at: null, eval_mode: false };

type Call = { method: string; path: string; body: string | null };

function setup(ui: (client: ReturnType<typeof createClient>) => ReactNode, opts: { me?: Me; view?: HoursModeView; missing?: boolean } = {}) {
  const calls: Call[] = [];
  let view = opts.view ?? REAL;
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const path = new URL(url, "http://x").pathname;
    calls.push({ method, path, body: typeof init.body === "string" ? init.body : null });
    if (path === "/api/auth/refresh") return json(200, { access_token: jwt((opts.me ?? MGR).user_id), token_type: "bearer", expires_in: 900, csrf_token: "c" });
    if (path === "/api/auth/me") return json(200, opts.me ?? MGR);
    if (opts.missing) return json(404, { detail: "Not Found" });
    if (path === "/api/hours-mode") return json(200, view);
    if (path === "/api/admin/hours-mode" && method === "PUT") {
      const mode = (JSON.parse(String(init.body)) as { mode: HoursModeView["mode"] }).mode;
      if (mode === view.mode) return json(409, { detail: "same_as_current" });
      view = { ...view, mode, changed_by: "it_mgr01", changed_at: "2026-11-14T11:00:00Z" };
      return json(200, view);
    }
    return json(404, { detail: "Not Found" });
  });
  const client = createClient({ fetch, readCookie: () => "csrf-1", locks: null, channel: { post: () => {}, subscribe: () => {} }, onSessionEnd: vi.fn() });
  function Gate({ children }: { children: ReactNode }) {
    return useAuth().state.status === "signedIn" ? children : <p>Đang kiểm tra…</p>;
  }
  const queryClient = new QueryClient();
  clients.push(queryClient);
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider client={client} subscribe={() => () => {}}>
        <MemoryRouter initialEntries={["/p"]}>
          <Routes>
            <Route path="/p" element={<Gate>{ui(client)}</Gate>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { calls };
}

describe("parseHoursModeView", () => {
  it("nhận đúng hình dạng, từ chối thân lạ", () => {
    expect(parseHoursModeView(REAL).mode).toBe("real");
    expect(() => parseHoursModeView({ ...REAL, mode: "ngoai" })).toThrow();
    expect(() => parseHoursModeView({ ...REAL, eval_mode: "no" })).toThrow();
  });
});

describe("HoursModeSection — Trưởng BP", () => {
  it("chọn 'Giả lập NGOÀI giờ' rồi Áp dụng → PUT {mode: outside}, hiện chế độ mới và người đổi", async () => {
    const { calls } = setup((client) => <HoursModeSection client={client} />);
    await screen.findByTestId("hours-mode-current");
    expect(screen.getByTestId("hours-mode-current").textContent).toBe("Theo giờ thật");
    fireEvent.click(screen.getAllByTestId("hours-mode-option").find((o) => o.dataset.key === "outside")!);
    fireEvent.click(screen.getByTestId("hours-mode-apply"));
    await waitFor(() => expect(screen.getByTestId("hours-mode-current").textContent).toBe("Giả lập NGOÀI giờ hành chính"));
    const put = calls.filter((c) => c.method === "PUT");
    expect(put).toEqual([{ method: "PUT", path: "/api/admin/hours-mode", body: JSON.stringify({ mode: "outside" }) }]);
    expect(screen.getByTestId("hours-mode-changed-by").textContent).toBe("it_mgr01");
    expect(screen.getByTestId("hours-mode-message").textContent).toContain("Đã chuyển sang");
  });

  it("chưa chọn khác chế độ hiện hành → nút Áp dụng không gửi gì", async () => {
    const { calls } = setup((client) => <HoursModeSection client={client} />);
    await screen.findByTestId("hours-mode-current");
    fireEvent.click(screen.getByTestId("hours-mode-apply"));
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.filter((c) => c.method === "PUT")).toEqual([]);
  });

  it("backend chưa có route (404) → không hiện khối", async () => {
    // Chờ theo SỰ KIỆN (đã gọi route rồi khối ẩn), không chờ cố định 50 ms — CI chậm từng đỏ chập chờn (run 44128085090).
    const { calls } = setup((client) => <HoursModeSection client={client} />, { missing: true });
    await waitFor(() => expect(calls.some((c) => c.path === "/api/hours-mode")).toBe(true));
    await waitFor(() => expect(screen.queryByTestId("hours-mode-section")).toBeNull());
  });
});

describe("HoursModeBanner — mọi vai trò", () => {
  it("theo giờ thật → không có dải báo", async () => {
    const { calls } = setup((client) => <HoursModeBanner client={client} />, { me: EMP });
    await waitFor(() => expect(calls.some((c) => c.path === "/api/hours-mode")).toBe(true));
    await waitFor(() => expect(screen.queryByTestId("hours-mode-banner")).toBeNull());
  });

  it("đang giả lập ngoài giờ → nhân viên cũng thấy dải báo", async () => {
    setup((client) => <HoursModeBanner client={client} />, { me: EMP, view: { ...REAL, mode: "outside" } });
    const banner = await screen.findByTestId("hours-mode-banner");
    expect(banner.textContent).toContain("Giả lập NGOÀI giờ hành chính");
    expect(banner.textContent).toContain("R18");
  });
});

describe("Thanh bên — nút 'Quản trị nhân viên (AD)' (D-97, cách 1)", () => {
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

  it("Trưởng BP thấy link mở trang quản trị AD giả lập ở thẻ mới (noopener)", () => {
    mountSidebar({ ...MGR, permissions: [...MGR.permissions, "alert:read", "approval:decide"] });
    const link = screen.getByTestId("nav-ad-admin");
    expect(link.getAttribute("href")).toBe(AD_ADMIN_URL);
    expect(AD_ADMIN_URL).toBe("http://127.0.0.1:8100/console/nhan-vien");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    vi.unstubAllGlobals();
  });

  it("L1 (không có policy:edit) không thấy", () => {
    mountSidebar({ user_id: "l1_01", role: "l1", permissions: ["approval:decide", "escalation:handle", "dashboard:read:own"] });
    expect(screen.queryByTestId("nav-ad-admin")).toBeNull();
    vi.unstubAllGlobals();
  });
});
