// B1 (12/11): Tổng quan — tab Nghiệp vụ / AI mặc định chỉ ticket thật (`source=real`); ô "Gồm dữ liệu thử" gửi `source=all`.
// Dòng "Đang xem" theo `source` backend trả về; thân có `source` khác nguồn đã gửi → 502 (không hiện số của nguồn khác).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseAi, parseBusiness } from "../../api/dashboard.ts";
import { ApiError } from "../../api/errors.ts";
import type { AiDashboard, BusinessCountedTam, Me } from "../../api/types.ts";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { DashboardPage } from "./DashboardPage.tsx";
import { DASH_SOURCES, sourceViewText } from "./metrics.ts";

const ME: Me = { user_id: "it_mgr01", role: "manager", permissions: ["dashboard:read:all", "alert:read"] };
const signedIn: AuthValue = { state: { status: "signedIn", me: ME }, signIn: vi.fn(), signOut: vi.fn(async () => true) };

const BUSINESS: BusinessCountedTam = {
  from: "2026-11-05T17:00:00Z",
  to: "2026-11-12T05:00:00Z",
  unavailable: [],
  scope: "all",
  metrics: {
    automation_rate: 0.5,
    escalation_rate_raw: 0.25,
    escalation_rate_weighted: null,
    deflection_rate: 0,
    approval_expired_count: 0,
    decided_by_distribution: {},
    top_matched_rules: [],
    override_count: 0,
    e1_split: null,
    e3_cases: null,
  },
};
const AI: AiDashboard = {
  from: BUSINESS.from,
  to: BUSINESS.to,
  unavailable: [],
  metrics: {
    tokens_per_ticket: null,
    cost_per_day: null,
    latency_p95_by_step: null,
    cache_hit_rate: null,
    json_invalid_first_try_rate: null,
    fallback_rate: null,
    e2_llm_count: 0,
    e9_count: 0,
    b2_llm_rate: null,
    intent_filter_fallback_rate: null,
    b3_llm_rate: null,
    intent_model_version: null,
    multi_intent_first_stop_to_reply_s: null,
    multi_intent_messages_per_turn: null,
  },
};

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  for (const c of clients.splice(0)) c.clear();
});

/** Backend giả: trả lại `source` đã nhận (hoặc `echo` ép giá trị khác / bỏ hẳn). */
function server(echo?: (sent: string | null) => string | undefined): string[] {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(url);
      const u = new URL(url, "http://x");
      const sent = u.searchParams.get("source");
      const source = echo ? echo(sent) : (sent ?? undefined);
      if (u.pathname === "/api/dashboard/business") return json(200, { ...BUSINESS, source });
      if (u.pathname === "/api/dashboard/ai") return json(200, { ...AI, source });
      if (u.pathname === "/api/alerts") return json(200, { items: [], truncated: false });
      return json(404, { detail: "not_found" });
    }),
  );
  return urls;
}

function renderPage() {
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthContext value={signedIn}>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <DashboardPage />
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
}

const sources = (urls: string[], path: string) =>
  urls.filter((u) => new URL(u, "http://x").pathname === path).map((u) => new URL(u, "http://x").searchParams.get("source"));

describe("B1: nguồn ticket của Tổng quan", () => {
  it("mặc định gửi source=real và ghi 'Đang xem: ticket thật'", async () => {
    const urls = server();
    renderPage();
    expect((await screen.findByTestId("dashboard-source")).textContent).toBe(sourceViewText("real"));
    expect(sources(urls, "/api/dashboard/business")).toStrictEqual(["real"]);
    expect(screen.getByRole("tab", { name: "Ticket thật" }).getAttribute("aria-selected")).toBe("true");
  });

  it("chọn 'Gồm dữ liệu thử' → gửi source=all, dòng 'Đang xem' đổi theo thân", async () => {
    const urls = server();
    renderPage();
    await screen.findByTestId("dashboard-source");
    fireEvent.click(screen.getByRole("tab", { name: "Gồm dữ liệu thử" }));
    await waitFor(() => expect(screen.getByTestId("dashboard-source").textContent).toBe(sourceViewText("all")));
    expect(sources(urls, "/api/dashboard/business")).toStrictEqual(["real", "all"]);
  });

  it("tab AI dùng cùng ô nguồn; tab So sánh không có ô này (có nguồn real|sim riêng)", async () => {
    const urls = server();
    renderPage();
    await screen.findByTestId("dashboard-source");
    fireEvent.click(screen.getByRole("tab", { name: "AI" }));
    await waitFor(() => expect(sources(urls, "/api/dashboard/ai")).toStrictEqual(["real"]));
    fireEvent.click(screen.getByRole("tab", { name: "So sánh phương án" }));
    await waitFor(() => expect(screen.queryByRole("tab", { name: "Gồm dữ liệu thử" })).toBeNull());
    expect(screen.queryByTestId("dashboard-source")).toBeNull();
  });

  it("thân không có source (backend trước B1) → không ghi 'Đang xem'", async () => {
    server(() => undefined);
    renderPage();
    await screen.findAllByTestId("kpi");
    expect(screen.queryByTestId("dashboard-source")).toBeNull();
  });

  it("thân có source khác nguồn đã gửi → 502, không dựng màn từ số của nguồn khác", () => {
    expect(() => parseBusiness({ ...BUSINESS, source: "all" }, "real")).toThrow(ApiError);
    expect(() => parseAi({ ...AI, source: "real" }, "all")).toThrow(ApiError);
    expect(parseBusiness({ ...BUSINESS, source: "all" }, "all").source).toBe("all");
    expect(parseAi({ ...AI }, "real").source).toBeUndefined();
  });

  it("nhãn ô chọn và dòng 'Đang xem'", () => {
    expect(DASH_SOURCES.map((s) => s.key)).toStrictEqual(["real", "all"]);
    expect(sourceViewText(undefined)).toBeNull();
    expect(sourceViewText("real")).toMatch(/ticket thật/);
    expect(sourceViewText("all")).toMatch(/sim\/eval/);
  });
});
