// F5 — Trưởng BP IT: Tổng quan (nghiệp vụ + AI), Cảnh báo + "Đã xem", Chính sách (sửa JSON, lỗi từng dòng, lịch sử, quay
// lui). Không gọi backend: fetch giả trả đúng hình dạng route thật M9 A3 @3f15afb (dashboard/alerts — N-A3) và hợp đồng
// [Đề xuất F5 — Q-fe-26] (policy).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { isAlertItem, parseAlerts } from "../../api/alerts.ts";
import { createClient } from "../../api/client.ts";
import { parseAi, parseBusiness } from "../../api/dashboard.ts";
import { ApiError } from "../../api/errors.ts";
import type { AiDashboard, AiMetrics, AlertItem, AlertList, BusinessDashboard, BusinessMetrics, Me, PolicyVersionItem, PolicyView } from "../../api/types.ts";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { AuthProvider } from "../../auth/AuthProvider.tsx";
import { homePath, STAFF_NAV } from "../../auth/permissions.ts";
import { RequirePerm } from "../../auth/RequireAuth.tsx";
import { useAuth } from "../../auth/useAuth.ts";
import { FlashNotice } from "../../components/FlashNotice.tsx";
import { Sidebar } from "../../components/Sidebar.tsx";
import { Alerts } from "./Alerts.tsx";
import { DashboardPage } from "./DashboardPage.tsx";
import {
  ACK_CONFLICT_TEXT,
  ACK_DONE_TEXT,
  ACK_GONE_TEXT,
  ALERT_LABEL,
  alertLabel,
  audienceLabel,
  DASHBOARD_MISSING_TITLE,
  E1_LABEL,
  EMPTY_NOTE,
  labelOf,
  metricText,
  MONITOR_DOWN_TEXT,
  ownEntry,
  POLICY_MISSING_TITLE,
  severityDot,
  severityLabel,
  sortAlerts,
  UNAVAILABLE_TEXT,
} from "./metrics.ts";
import { PolicyEditor } from "./PolicyEditor.tsx";
import { formatPolicy, restoreConfirmText, TOO_LARGE_TEXT, VERSION_CONFLICT_TEXT } from "./policyText.ts";
import { rangeWindow } from "./range.ts";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
});

// ------------------------------------------------------------------------------------------------ dựng chung

const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
// backend/app/auth/permissions.py (S2).
const MGR: Me = {
  user_id: "it_mgr01",
  role: "manager",
  permissions: [...BASE, "ticket:read:any", "approval:decide", "decision:override", "policy:read", "policy:edit", "dashboard:read:all", "audit:read:all", "kb:edit", "alert:read"],
};
const READER: Me = { ...MGR, permissions: MGR.permissions.filter((p) => p !== "policy:edit") };
const L1: Me = {
  user_id: "l1_01",
  role: "l1",
  permissions: [...BASE, "ticket:read:any", "approval:decide", "decision:override", "escalation:handle", "dashboard:read:own", "audit:read:own"],
};

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

type Call = { method: string; url: string; body: string | null; auth: string | null };
type Handler = (method: string, url: string, init: RequestInit) => Response | Promise<Response | undefined> | undefined;

function stubFetch(route: Handler): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({ method, url, body: typeof init.body === "string" ? init.body : null, auth: new Headers(init.headers).get("Authorization") });
      return (await route(method, url, init)) ?? json(404, { detail: "not_found" });
    }),
  );
  return calls;
}

const signedIn = (me: Me): AuthValue => ({ state: { status: "signedIn", me }, signIn: vi.fn(), signOut: vi.fn(async () => true) });
const SCREENS: Record<string, ReactNode> = { "/dashboard": <DashboardPage />, "/alerts": <Alerts />, "/policy": <PolicyEditor /> };

function renderAt(path: string, me: Me = MGR) {
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthContext value={signedIn(me)}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            {STAFF_NAV.filter((item) => item.to in SCREENS).map((item) => (
              <Route key={item.to} path={item.to} element={<RequirePerm perm={item.perm}>{SCREENS[item.to]}</RequirePerm>} />
            ))}
          </Routes>
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
  return client;
}

const pathOf = (url: string) => new URL(url, "http://x").pathname;
const queryOf = (url: string) => new URL(url, "http://x").searchParams;
const tick = (ms = 20) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------------------------------------ dữ liệu

// Hình dạng THẬT của M9 A3 @3f15afb (backend/app/api/dashboard.py, alerts.py): chỉ số trong `metrics`, `from`/`to` ở UTC.
const METRICS: BusinessMetrics = {
  automation_rate: 0.63,
  escalation_rate_raw: 0.16,
  escalation_rate_weighted: {
    raw: 0.16,
    weighted: 0.142,
    by_group: { routine: 0.1, approval: 0.25, sensitive: null }, // nhóm 0 lá → null → "—"
    sensitivity: { "60/30/10": 0.142, "80/15/5": 0.151 },
  },
  deflection_rate: 0.21,
  approval_expired_count: 0, // 0 thật → "0"
  decided_by_distribution: { rule: 223, llm: 63 },
  top_matched_rules: [{ rule_id: "R20", count: 96 }],
  override_count: 0, // 0 thật → "0" (nguồn có từ 4d)
  e1_split: {
    total: 9,
    counts: { out_of_scope: 6, intent_low_confidence: 0, multi_intent_not_enabled: 0, intent_not_enabled: 1, other: 2 },
    shares: { out_of_scope: 0.667, intent_low_confidence: 0, multi_intent_not_enabled: 0, intent_not_enabled: 0.111, other: 0.222 },
  },
  e3_cases: {
    items: [{ ticket_id: "t-e3", intent: "software", created_at: "2026-09-29T03:00:00Z", kb_version: "v12", request_excerpt: "In lỗi <b>x</b> ở tầng 3" }],
    truncated: false,
  },
};
const BUSINESS: BusinessDashboard = {
  from: "2026-09-24T17:00:00Z",
  to: "2026-10-01T05:05:09.123000Z",
  unavailable: [],
  scope: "all",
  metrics: METRICS,
};
const business = (metrics: Partial<BusinessMetrics> = {}, unavailable: string[] = []): BusinessDashboard => ({
  ...BUSINESS,
  unavailable,
  metrics: { ...METRICS, ...metrics },
});

const AI_METRICS_BODY: AiMetrics = {
  tokens_per_ticket: null,
  cost_per_day: [
    { day_start: "2026-09-29T17:00:00Z", cost_usd: 0.42 }, // 00:00 VN 30/09
    { day_start: "2026-09-30T17:00:00Z", cost_usd: 0 }, // 00:00 VN 01/10 — chưa hết ngày lúc `to`
  ],
  latency_p95_by_step: { B3: 820.4, B10: 2400 },
  cache_hit_rate: 0.31,
  json_invalid_first_try_rate: 0,
  fallback_rate: 0.02,
  e2_llm_count: 1,
  e9_count: 0,
  b2_llm_rate: 0.12,
  intent_filter_fallback_rate: null,
  b3_llm_rate: 1,
  intent_model_version: "intent-clf-2026.09.20",
  multi_intent_first_stop_to_reply_s: null,
  multi_intent_messages_per_turn: null,
};
const AI: AiDashboard = {
  from: BUSINESS.from,
  to: BUSINESS.to,
  unavailable: ["multi_intent_first_stop_to_reply_s", "multi_intent_messages_per_turn"],
  metrics: AI_METRICS_BODY,
};
const ai = (metrics: Partial<AiMetrics> = {}, over: Partial<AiDashboard> = {}): AiDashboard => ({ ...AI, ...over, metrics: { ...AI_METRICS_BODY, ...metrics } });

function alert(alert_id: number, rule_id: string, severity: string, minutesAgo: number, over: Partial<AlertItem> = {}): AlertItem {
  const at = new Date(Date.parse("2026-10-01T05:00:00Z") - minutesAgo * 60_000).toISOString();
  return {
    alert_id,
    rule_id,
    subject: "",
    severity,
    value: null,
    window_start: at,
    status: "open",
    detail: {},
    audience: ["manager"],
    acked_by: null,
    acked_at: null,
    created_at: at,
    ...over,
  };
}
const alertList = (items: AlertItem[], truncated = false): AlertList => ({ items, truncated });

/** Route giả của dashboard + cảnh báo. `state` đổi được giữa chừng (503 sau khi đã có số…). */
function dashboardServer(state: { business?: () => Response; ai?: () => Response; alerts?: () => Response } = {}) {
  return stubFetch((method, url) => {
    const path = pathOf(url);
    if (path === "/api/dashboard/business") return state.business ? state.business() : json(200, BUSINESS);
    if (path === "/api/dashboard/ai") return state.ai ? state.ai() : json(200, AI);
    if (path === "/api/alerts" && method === "GET") return state.alerts ? state.alerts() : json(200, alertList([]));
    return undefined;
  });
}

// ------------------------------------------------------------------------------------------------ t53

describe("t53 (P4): from/to theo giờ Việt Nam, luôn kèm +07:00", () => {
  const NOW = Date.parse("2026-10-01T05:05:09.123Z"); // 12:05:09 giờ VN, 01/10

  it("Hôm nay / 7 ngày (mặc định) / 30 ngày: from = 00:00 +07:00 của ngày đầu (ngày lịch, tính cả hôm nay), to = bây giờ", () => {
    expect(rangeWindow("today", NOW)).toStrictEqual({ from: "2026-10-01T00:00:00.000+07:00", to: "2026-10-01T12:05:09.123+07:00" });
    expect(rangeWindow("7d", NOW)).toStrictEqual({ from: "2026-09-25T00:00:00.000+07:00", to: "2026-10-01T12:05:09.123+07:00" });
    expect(rangeWindow("30d", NOW)).toStrictEqual({ from: "2026-09-02T00:00:00.000+07:00", to: "2026-10-01T12:05:09.123+07:00" });
  });

  it("ranh giới ngày VN khi máy khách ở UTC: 16:59:59.999Z = 23:59 VN 30/09 → 'hôm nay' là 30/09; 17:00Z = 00:00 VN 01/10 → 01/10", () => {
    expect(rangeWindow("today", Date.parse("2026-09-30T16:59:59.999Z")).from).toBe("2026-09-30T00:00:00.000+07:00");
    expect(rangeWindow("today", Date.parse("2026-09-30T16:59:59.999Z")).to).toBe("2026-09-30T23:59:59.999+07:00");
    expect(rangeWindow("today", Date.parse("2026-09-30T17:00:00.000Z")).from).toBe("2026-10-01T00:00:00.000+07:00");
    // Đúng 00:00:00.000 VN → `to` đẩy thêm 1 ms để from < to (backend 422 khi from ≥ to).
    const midnight = rangeWindow("today", Date.parse("2026-09-30T17:00:00.000Z"));
    expect(Date.parse(midnight.to)).toBeGreaterThan(Date.parse(midnight.from));
  });

  it("không phụ thuộc múi giờ của máy (TZ=America/New_York cho cùng kết quả)", () => {
    // vitest chạy trên Node: đổi TZ lúc chạy có hiệu lực ngay với Date (tsconfig của app không có kiểu Node → ép kiểu).
    const env = (globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env;
    const old = env.TZ;
    env.TZ = "America/New_York";
    try {
      expect(new Date(NOW).getHours()).toBe(1); // 05:05Z = 01:05 New York (EDT) — chứng minh TZ đã đổi
      expect(rangeWindow("7d", NOW)).toStrictEqual({ from: "2026-09-25T00:00:00.000+07:00", to: "2026-10-01T12:05:09.123+07:00" });
    } finally {
      env.TZ = old;
    }
  });

  it("màn Tổng quan: mặc định 7 ngày; đổi Hôm nay / 30 ngày → mỗi request có from/to kết thúc '+07:00', from lúc 00:00", async () => {
    const calls = dashboardServer();
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    fireEvent.click(screen.getByRole("tab", { name: "Hôm nay" }));
    await waitFor(() => expect(calls.filter((c) => pathOf(c.url) === "/api/dashboard/business")).toHaveLength(2));
    fireEvent.click(screen.getByRole("tab", { name: "30 ngày" }));
    await waitFor(() => expect(calls.filter((c) => pathOf(c.url) === "/api/dashboard/business")).toHaveLength(3));
    const windows = calls.filter((c) => pathOf(c.url) === "/api/dashboard/business").map((c) => [queryOf(c.url).get("from") ?? "", queryOf(c.url).get("to") ?? ""] as const);
    for (const [from, to] of windows) {
      expect(from).toMatch(/T00:00:00\.000\+07:00$/);
      expect(to).toMatch(/\+07:00$/);
      expect(Date.parse(from)).toBeLessThan(Date.parse(to));
    }
    const days = windows.map(([from, to]) => Math.ceil((Date.parse(to) - Date.parse(from)) / 86_400_000));
    expect(days).toStrictEqual([7, 1, 30]);
  });
});

// ------------------------------------------------------------------------------------------------ t54

describe("t54 (P3): unavailable → 'Chưa có dữ liệu', null → '—', 0 thật → '0' — KHÔNG BAO GIỜ 0 thay cho null", () => {
  it("metricText: thứ tự unavailable → thiếu trường → null → số", () => {
    // override_count đã có nguồn thật (4d) → hết chú thích "Nguồn có từ Phase 4"; tên trong unavailable vẫn thắng.
    expect(metricText("override_count", null, ["override_count"], "count")).toStrictEqual({ state: "unavailable", text: UNAVAILABLE_TEXT, note: null });
    // Tên trong unavailable thắng cả khi server lỡ trả 0.
    expect(metricText("override_count", 0, ["override_count"], "count").text).toBe(UNAVAILABLE_TEXT);
    expect(metricText("deflection_rate", undefined, [], "rate").text).toBe(UNAVAILABLE_TEXT);
    expect(metricText("deflection_rate", null, [], "rate")).toStrictEqual({ state: "empty", text: "—", note: EMPTY_NOTE });
    expect(EMPTY_NOTE).toBe("Không có ticket trong khoảng này");
    expect(metricText("deflection_rate", 0, [], "rate").text).toMatch(/^0\s%$/);
    expect(metricText("approval_expired_count", 0, [], "count").text).toBe("0");
    expect(metricText("automation_rate", 0.63, [], "rate").text).toMatch(/^63\s%$/);
    expect(metricText("automation_rate", 0.125, [], "rate").text).toMatch(/^12,5\s%$/);
    // Khác 0 mà làm tròn ra 0 → không hiện "0 %".
    expect(metricText("fallback_rate", 0.0004, [], "rate").text).toMatch(/^<\s0,1\s%$/);
  });

  it("màn Tổng quan: override_count 'Chưa có dữ liệu', tỉ lệ null '—', số 0 thật '0'; hai ô đầu không có chữ '0'", async () => {
    const weightedNull = { raw: 0.16, weighted: null, by_group: { routine: null, approval: null, sensitive: null }, sensitivity: { "60/30/10": null } };
    const body = business({ escalation_rate_weighted: weightedNull, override_count: null }, ["override_count"]);
    dashboardServer({ business: () => json(200, body) });
    renderAt("/dashboard");
    const tiles = await screen.findAllByTestId("kpi");
    const tile = (name: string) => tiles.find((t) => t.dataset.metric === name)!;
    const weighted = tile("escalation_rate_weighted");
    expect(within(weighted).getByTestId("kpi-value").textContent).toBe("—");
    expect(weighted.dataset.state).toBe("empty");
    expect(weighted.textContent).toContain(EMPTY_NOTE);
    const override = screen.getByTestId("metric-override_count");
    expect(within(override).getByTestId("metric-value").textContent).toBe(UNAVAILABLE_TEXT);
    expect(override.dataset.state).toBe("unavailable");
    for (const el of [within(weighted).getByTestId("kpi-value"), within(override).getByTestId("metric-value")]) {
      expect(el.textContent).not.toMatch(/0/);
    }
    expect(within(tile("approval_expired_count")).getByTestId("kpi-value").textContent).toBe("0");
    expect(within(tile("automation_rate")).getByTestId("kpi-value").textContent).toMatch(/^63\s%$/);
    expect(weighted.textContent).toMatch(/thô 16\s%/); // số thô vẫn hiện ở dòng phụ
  });
});

// ------------------------------------------------------------------------------------------------ t55

describe("t55: tab AI — 14 chỉ số đúng thứ tự backend; tỉ lệ, 0 thật, null, unavailable, chuỗi phiên bản", () => {
  it("14 dòng = khoá của AiMetrics; mỗi dòng có data-state; from kèm +07:00", async () => {
    const calls = dashboardServer();
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    fireEvent.click(screen.getByRole("tab", { name: "AI" }));
    const rows = await screen.findAllByTestId("ai-metric");
    expect(rows.map((r) => r.dataset.metric)).toStrictEqual(Object.keys(AI_METRICS_BODY));
    expect(rows).toHaveLength(14);
    const row = (name: string) => rows.find((r) => r.dataset.metric === name)!;
    const value = (name: string) => row(name).lastElementChild!.textContent;
    expect(value("cache_hit_rate")).toMatch(/^31\s%$/);
    expect(value("json_invalid_first_try_rate")).toMatch(/^0\s%$/);
    expect(value("e9_count")).toBe("0");
    expect(value("e2_llm_count")).toBe("1");
    expect([row("intent_filter_fallback_rate").dataset.state, value("intent_filter_fallback_rate")]).toStrictEqual(["empty", `—${EMPTY_NOTE}`]);
    expect([row("tokens_per_ticket").dataset.state, value("tokens_per_ticket")]).toStrictEqual(["empty", `—${EMPTY_NOTE}`]);
    expect(row("multi_intent_messages_per_turn").dataset.state).toBe("unavailable");
    expect(value("intent_model_version")).toBe("intent-clf-2026.09.20");
    expect(row("intent_model_version").dataset.state).toBe("value");
    const aiCall = calls.find((c) => pathOf(c.url) === "/api/dashboard/ai")!;
    expect(queryOf(aiCall.url).get("from")).toMatch(/\+07:00$/);
  });
});

// ------------------------------------------------------------------------------------------------ t56

describe("t56 (P5): 503 → 'Số liệu tạm thời không có', KHÔNG số cũ; 404 route → trang A3; 403 → không có quyền", () => {
  it("đã có số → tải lại CÙNG khoảng gặp 503 monitor_unavailable → chỉ còn câu lỗi, không ô số / thanh / ca E3 cũ", async () => {
    let down = false;
    dashboardServer({ business: () => (down ? json(503, { detail: "monitor_unavailable" }) : json(200, BUSINESS)) });
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect(screen.getAllByTestId("bar-row").length).toBeGreaterThan(0);
    down = true;
    fireEvent.click(screen.getByRole("button", { name: "Tải lại" }));
    const error = await screen.findByTestId("load-error");
    expect(error.textContent).toContain(MONITOR_DOWN_TEXT);
    expect(MONITOR_DOWN_TEXT).toBe("Số liệu tạm thời không có");
    expect(screen.queryAllByTestId("kpi")).toHaveLength(0);
    expect(screen.queryAllByTestId("bar-row")).toHaveLength(0);
    expect(screen.queryAllByTestId("weighted-group")).toHaveLength(0);
    expect(screen.queryAllByTestId("e3-case")).toHaveLength(0);
    expect(screen.queryByTestId("metric-override_count")).toBeNull();
    expect(document.body.textContent).not.toMatch(/63\s%|223/);
    expect(screen.getByTestId("dashboard-window").textContent).not.toContain("Từ");
  });

  it("tab AI 503 → cùng câu, không bảng chỉ số", async () => {
    dashboardServer({ ai: () => json(503, { detail: "monitor_unavailable" }) });
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    fireEvent.click(screen.getByRole("tab", { name: "AI" }));
    expect((await screen.findByTestId("load-error")).textContent).toContain(MONITOR_DOWN_TEXT);
    expect(screen.queryAllByTestId("ai-metric")).toHaveLength(0);
  });

  it("404 'Not Found' của Starlette (route chưa có) → 'Tổng quan có từ M9 (chặng A3)', không khối lỗi đỏ, không ô chọn", async () => {
    dashboardServer({ business: () => json(404, { detail: "Not Found" }) });
    renderAt("/dashboard");
    const box = await screen.findByTestId("dashboard-missing");
    expect(within(box).getByRole("heading").textContent).toBe(DASHBOARD_MISSING_TITLE);
    expect(DASHBOARD_MISSING_TITLE).toBe("Tổng quan có từ M9 (chặng A3)");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("tablist")).toBeNull();
  });

  it("403 từ backend → trang không có quyền", async () => {
    dashboardServer({ business: () => json(403, { detail: "forbidden" }) });
    renderAt("/dashboard");
    expect(await screen.findByRole("heading", { name: "Bạn không có quyền xem trang này" })).toBeTruthy();
  });
});

// ------------------------------------------------------------------------------------------------ t57

describe("t57 (P6): nhãn 16 luật; 'Đã xem' chỉ gỡ SAU 200; 409 / 404 câu riêng + tải lại; không gửi 2 lần", () => {
  it("bảng nhãn đúng 16 rule_id của kế hoạch M9 mục 6; rule_id lạ → hiện nguyên", () => {
    expect(Object.keys(ALERT_LABEL)).toStrictEqual([
      "escalation_rate_high", "injection_detected", "password_bruteforce", "e9_spike", "breaker_open", "e6_spike",
      "reflex_approval", "drift", "refresh_reuse", "permission_denied_burst", "policy_saved", "b2_degraded",
      "b3_degraded", "llm_budget", "finalize_failed", "execution_failed",
    ]);
    expect(alertLabel("custom_rule_x")).toBe("custom_rule_x");
  });

  it("sắp: critical → warning → info → lạ, rồi window_start giảm dần (Q-fe-27)", () => {
    const sorted = sortAlerts([
      alert(1, "drift", "info", 1),
      alert(2, "e9_spike", "warning", 50),
      alert(3, "x", "weird", 0),
      alert(4, "password_bruteforce", "critical", 90),
      alert(5, "e6_spike", "warning", 5),
      alert(6, "refresh_reuse", "critical", 10),
    ]);
    expect(sorted.map((a) => a.alert_id)).toStrictEqual([6, 4, 5, 2, 1, 3]);
  });

  function alertsServer() {
    const open = [
      alert(1001, "password_bruteforce", "critical", 25, { subject: "nv004", detail: { note: "<b>x</b>", failures: 5 } }),
      alert(9409, "refresh_reuse", "critical", 40, { subject: "nv002" }),
      alert(9404, "permission_denied_burst", "warning", 180, { subject: "nv005" }),
    ];
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const calls = stubFetch(async (method, url) => {
      const path = pathOf(url);
      if (path === "/api/alerts" && method === "GET") return json(200, alertList(open));
      const id = /^\/api\/alerts\/(\d+)\/ack$/.exec(path)?.[1];
      if (method === "POST" && id === "1001") {
        await gate;
        const i = open.findIndex((a) => a.alert_id === 1001);
        const [acked] = open.splice(i, 1);
        return json(200, { ...acked, status: "acked", acked_by: "it_mgr01", acked_at: new Date().toISOString() });
      }
      if (method === "POST" && id === "9409") {
        open.splice(open.findIndex((a) => a.alert_id === 9409), 1);
        return json(409, { detail: "already_acked" });
      }
      if (method === "POST" && id === "9404") {
        open.splice(open.findIndex((a) => a.alert_id === 9404), 1);
        return json(404, { detail: "not_found" });
      }
      return undefined;
    });
    return { calls, release };
  }

  const row = (id: number) => document.querySelector<HTMLElement>(`[data-testid="alert-row"][data-alert-id="${id}"]`);
  const ackPosts = (calls: Call[], id: number) => calls.filter((c) => c.method === "POST" && pathOf(c.url) === `/api/alerts/${id}/ack`);
  const listGets = (calls: Call[]) => calls.filter((c) => c.method === "GET" && pathOf(c.url) === "/api/alerts");

  it("bấm 'Đã xem' 2 lần cùng nhịp → 1 POST; cảnh báo VẪN còn trong 'Đang mở' khi chưa có 200; có 200 → mới biến mất", async () => {
    const { calls, release } = alertsServer();
    renderAt("/alerts");
    await waitFor(() => expect(row(1001)).not.toBeNull());
    const button = within(row(1001)!).getByRole("button", { name: "Đã xem" });
    fireEvent.click(button);
    fireEvent.click(button);
    await tick(30);
    expect(ackPosts(calls, 1001)).toHaveLength(1);
    expect(row(1001)).not.toBeNull(); // chưa có 200 → chưa gỡ
    expect(within(row(1001)!).getByRole("button", { name: "Đang gửi…" }).hasAttribute("disabled")).toBe(true);
    release();
    await waitFor(() => expect(row(1001)).toBeNull());
    expect(screen.getByTestId("ack-notice").textContent).toBe(ACK_DONE_TEXT);
    expect(ackPosts(calls, 1001)).toHaveLength(1);
  });

  it("409 → 'Cảnh báo này đã được xác nhận trước đó' + tải lại; 404 → 'Cảnh báo không còn' + tải lại", async () => {
    const { calls } = alertsServer();
    renderAt("/alerts");
    await waitFor(() => expect(row(9409)).not.toBeNull());
    const before = listGets(calls).length;
    fireEvent.click(within(row(9409)!).getByRole("button", { name: "Đã xem" }));
    expect((await screen.findByRole("alert")).textContent).toBe(ACK_CONFLICT_TEXT);
    await waitFor(() => expect(listGets(calls).length).toBe(before + 1));
    await waitFor(() => expect(row(9409)).toBeNull()); // danh sách tải lại từ server
    fireEvent.click(within(row(9404)!).getByRole("button", { name: "Đã xem" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(ACK_GONE_TEXT));
    await waitFor(() => expect(listGets(calls).length).toBe(before + 2));
  });

  it("detail có HTML → hiện NGUYÊN VĂN trong bảng khoá–giá trị (không dựng thẻ); nhãn tiếng Việt + subject nguyên mã", async () => {
    alertsServer();
    renderAt("/alerts");
    await waitFor(() => expect(row(1001)).not.toBeNull());
    expect(row(1001)!.textContent).toContain("Dò mật khẩu — tài khoản bị khoá");
    expect(row(1001)!.textContent).toContain("nv004");
    fireEvent.click(within(row(1001)!).getByRole("button", { name: "Chi tiết" }));
    const detail = within(row(1001)!).getByTestId("alert-detail");
    const note = within(detail).getAllByTestId("alert-detail-row").find((r) => r.dataset.key === "note")!;
    expect(note.textContent).toContain('"<b>x</b>"');
    expect(detail.querySelector("b")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t58

describe("t58: khối 'Cảnh báo đang mở' trên Tổng quan — tối đa 5, link /alerts; ca E3 chữ thô", () => {
  it("7 cảnh báo mở → 5 dòng, nghiêm trọng trước; 'Tất cả' → /alerts", async () => {
    const open = [
      alert(1, "drift", "info", 1),
      alert(2, "e9_spike", "warning", 2),
      alert(3, "password_bruteforce", "critical", 300),
      alert(4, "e6_spike", "warning", 3),
      alert(5, "policy_saved", "info", 4),
      alert(6, "injection_detected", "critical", 5),
      alert(7, "escalation_rate_high", "warning", 6),
    ];
    dashboardServer({ alerts: () => json(200, alertList(open)) });
    renderAt("/dashboard");
    const block = await screen.findByTestId("open-alerts");
    await waitFor(() => expect(within(block).getAllByTestId("alert-row")).toHaveLength(5));
    expect(within(block).getAllByTestId("alert-row").map((r) => r.dataset.severity)).toStrictEqual(["critical", "critical", "warning", "warning", "warning"]);
    expect(within(block).getByRole("link", { name: "Tất cả" }).getAttribute("href")).toBe("/alerts");
    expect(within(block).queryByRole("button", { name: "Chi tiết" })).toBeNull(); // khối gọn
  });

  it("request_excerpt chứa '<b>x</b>' → hiện nguyên văn, không in đậm", async () => {
    dashboardServer();
    renderAt("/dashboard");
    const excerpt = await screen.findByTestId("e3-excerpt");
    expect(excerpt.textContent).toContain("In lỗi <b>x</b> ở tầng 3");
    expect(excerpt.querySelector("b")).toBeNull();
  });

  it("/api/alerts chưa có route (404 'Not Found') → câu trung tính trong khối, không role=alert", async () => {
    dashboardServer({ alerts: () => json(404, { detail: "Not Found" }) });
    renderAt("/dashboard");
    const block = await screen.findByTestId("open-alerts");
    await waitFor(() => expect(block.textContent).toContain("Cảnh báo có từ M9 (chặng A3)."));
    expect(within(block).queryByRole("alert")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t60–t63 chính sách

const POLICY = {
  constants: { SLA_MINUTES: 30, THRESHOLD_LOW: 0.25, THRESHOLD_HIGH: 0.75 },
  rules: [
    { id: "R17", type: "approval_required", description: "Thiết bị chưa đăng ký" },
    { id: "R20", type: "allow", description: "Cấp lại cho thiết bị đã đăng ký" },
  ],
};
const view = (over: Partial<PolicyView> = {}): PolicyView => ({
  version_id: 14,
  version: "4",
  content: POLICY,
  updated_by: "it_mgr01",
  updated_at: "2026-09-30T03:00:00Z",
  is_current: true,
  ...over,
});
const VERSIONS: PolicyVersionItem[] = [
  { version_id: 14, version: "4", updated_by: "it_mgr01", updated_at: "2026-09-30T03:00:00Z", is_current: true, restored_from: null },
  { version_id: 13, version: "3", updated_by: "it_mgr01", updated_at: "2026-09-28T03:00:00Z", is_current: false, restored_from: "1" },
  { version_id: 12, version: "2", updated_by: "it_mgr01", updated_at: "2026-09-27T03:00:00Z", is_current: false, restored_from: null },
  { version_id: 11, version: "1", updated_by: null, updated_at: "2026-09-25T03:00:00Z", is_current: false, restored_from: null },
];

type PolicyState = { current: () => PolicyView; put?: (body: unknown, auth: string | null) => Response; restore?: (id: string, auth: string | null) => Response };

function policyRoutes(state: PolicyState): Handler {
  return (method, url, init) => {
    const path = pathOf(url);
    const auth = new Headers(init.headers).get("Authorization");
    if (path === "/api/policy" && method === "GET") return json(200, state.current());
    if (path === "/api/policy/versions") return json(200, VERSIONS);
    if (path === "/api/policy" && method === "PUT") return state.put ? state.put(JSON.parse(String(init.body)), auth) : json(201, { version_id: 15, version: "5" });
    const id = /^\/api\/policy\/versions\/(\d+)\/restore$/.exec(path)?.[1];
    if (id && method === "POST") return state.restore ? state.restore(id, auth) : json(201, { version_id: 15, version: "5" });
    return undefined;
  };
}

const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT" && pathOf(c.url) === "/api/policy");
const restores = (calls: Call[]) => calls.filter((c) => c.method === "POST" && /\/restore$/.test(pathOf(c.url)));

/**
 * Tab "JSON" có ngay khi màn mount, còn ô JSON chỉ có SAU khi GET /api/policy về (nháp nạp từ server) → chờ chính ô đó.
 * Lấy đồng bộ (`getBy…`) là đua với response: t61 "người khác" từng đỏ 1/6 lượt dưới tải (N4d) — làm chậm GET 5 ms thì
 * mọi test dùng hàm này đỏ ngay bằng "Unable to find a label".
 */
async function openJson() {
  fireEvent.click(await screen.findByRole("tab", { name: "JSON" }));
  return screen.findByLabelText<HTMLTextAreaElement>("Nội dung chính sách (JSON)");
}
const saveButton = () => screen.getByRole("button", { name: /^Lưu/ });
const lineOf = (text: string, needle: string) => text.split("\n").findIndex((l) => l.includes(needle)) + 1;
const gutterMark = (line: number) => document.querySelector<HTMLElement>(`[data-testid="gutter-line"][data-line="${line}"]`)?.dataset.mark;

describe("t60 (P7): lỗi cú pháp khoá Lưu; 422 đúng dòng; base_version_id + 409; > 64 KB byte; chấm bản nháp", () => {
  it("JSON sai cú pháp → 'Dòng N, cột M · …', số dòng đỏ, nút 'Lưu · còn 1 lỗi' khoá, bấm → 0 PUT; Bảng không hiện bản cũ", async () => {
    const calls = stubFetch(policyRoutes({ current: () => view() }));
    renderAt("/policy");
    const area = await openJson();
    const broken = formatPolicy(POLICY).replace('"SLA_MINUTES": 30,', '"SLA_MINUTES": 30');
    fireEvent.change(area, { target: { value: broken } });
    const line = lineOf(broken, '"THRESHOLD_LOW"');
    const problem = await screen.findByTestId("policy-problem");
    expect(problem.textContent).toMatch(new RegExp(`^Dòng ${line}, cột \\d+ · Thiếu dấu phẩy`));
    expect(gutterMark(line)).toBe("error");
    expect(saveButton().textContent).toBe("Lưu · còn 1 lỗi");
    expect(saveButton().hasAttribute("disabled")).toBe(true);
    fireEvent.click(saveButton());
    await tick();
    expect(puts(calls)).toHaveLength(0);
    fireEvent.click(screen.getByRole("tab", { name: "Bảng" }));
    expect(screen.getByTestId("table-invalid")).toBeTruthy();
    expect(screen.queryAllByTestId("constant-row")).toHaveLength(0);
  });

  it("422 invalid_policy → lỗi hiện ở ĐÚNG dòng theo loc (+ 'Toàn tệp' khi loc rỗng); body có base_version_id của bản đã tải", async () => {
    const calls = stubFetch(
      policyRoutes({
        current: () => view(),
        put: () =>
          json(422, {
            error: "invalid_policy",
            errors: [
              { loc: ["constants", "THRESHOLD_LOW"], msg: "Ngưỡng dưới 0.9 phải nhỏ hơn ngưỡng trên 0.75" },
              { loc: ["rules", 1, "type"], msg: "type không hợp lệ" },
              { loc: [], msg: "Thiếu khối business_hours" },
            ],
          }),
      }),
    );
    renderAt("/policy");
    const area = await openJson();
    const text = formatPolicy(POLICY).replace('"THRESHOLD_LOW": 0.25', '"THRESHOLD_LOW": 0.9').replace('"type": "allow"', '"type": "alow"');
    fireEvent.change(area, { target: { value: text } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(screen.getAllByTestId("policy-problem")).toHaveLength(3));
    const low = lineOf(text, '"THRESHOLD_LOW"');
    const type = lineOf(text, '"type": "alow"');
    const texts = screen.getAllByTestId("policy-problem").map((p) => p.textContent);
    expect(texts).toStrictEqual([
      `Dòng ${low} · Ngưỡng dưới 0.9 phải nhỏ hơn ngưỡng trên 0.75`,
      `Dòng ${type} · type không hợp lệ`,
      "Toàn tệp · Thiếu khối business_hours",
    ]);
    expect(gutterMark(low)).toBe("error");
    expect(gutterMark(type)).toBe("error");
    expect(gutterMark(low - 1)).toBeUndefined();
    const body = JSON.parse(puts(calls)[0]!.body!) as { content: unknown; base_version_id: number };
    expect(Object.keys(body).sort()).toStrictEqual(["base_version_id", "content"]);
    expect(body.base_version_id).toBe(14);
    expect(body.content).toStrictEqual(JSON.parse(text));
    // Tab Bảng đánh dấu đúng hàng theo loc.
    fireEvent.click(screen.getByRole("tab", { name: "Bảng" }));
    const flagged = screen.getAllByTestId("constant-row").filter((r) => r.dataset.flagged === "true").map((r) => r.dataset.key);
    expect(flagged).toStrictEqual(["THRESHOLD_LOW"]);
  });

  it("server có bản mới trong lúc đang sửa → base GIỮ bản cũ → 409 version_conflict: câu báo, đúng 1 PUT, không ghi đè; 'Tải bản mới nhất' thay nháp", async () => {
    let current = view();
    const calls = stubFetch(policyRoutes({ current: () => current, put: () => json(409, { detail: "version_conflict" }) }));
    const client = renderAt("/policy");
    const area = await openJson();
    const draftText = formatPolicy(POLICY).replace('"SLA_MINUTES": 30', '"SLA_MINUTES": 25');
    fireEvent.change(area, { target: { value: draftText } });
    current = view({ version_id: 15, version: "5", content: { ...POLICY, constants: { ...POLICY.constants, SLA_MINUTES: 40 } } });
    await client.invalidateQueries({ queryKey: ["policy"] }); // tải lại ngầm (vd quay lại tab) thấy bản 5
    expect(screen.getByLabelText<HTMLTextAreaElement>("Nội dung chính sách (JSON)").value).toBe(draftText); // nháp giữ nguyên
    fireEvent.click(saveButton());
    expect((await screen.findByTestId("policy-message")).textContent).toBe(VERSION_CONFLICT_TEXT);
    await tick();
    expect(puts(calls)).toHaveLength(1);
    expect((JSON.parse(puts(calls)[0]!.body!) as { base_version_id: number }).base_version_id).toBe(14);
    fireEvent.click(screen.getByRole("button", { name: "Tải bản mới nhất (bỏ bản nháp)" }));
    await waitFor(() =>
      expect(screen.getByLabelText<HTMLTextAreaElement>("Nội dung chính sách (JSON)").value).toBe(formatPolicy(current.content)),
    );
    expect(puts(calls)).toHaveLength(1);
  });

  it("vượt 64 KB tính bằng BYTE UTF-8 (chữ có dấu) dù dưới 64 K ký tự → 'Nội dung quá dài', Lưu khoá, 0 PUT", async () => {
    const calls = stubFetch(policyRoutes({ current: () => view() }));
    renderAt("/policy");
    const area = await openJson();
    const big = formatPolicy({ ...POLICY, ghi_chu: "ệ".repeat(22_000) }); // "ệ" = 3 byte UTF-8
    expect(big.length).toBeLessThan(64 * 1024);
    expect(new TextEncoder().encode(big).length).toBeGreaterThan(64 * 1024);
    fireEvent.change(area, { target: { value: big } });
    const problem = await screen.findByTestId("policy-problem");
    expect(problem.textContent).toMatch(new RegExp(`^${TOO_LARGE_TEXT}`));
    expect(saveButton().hasAttribute("disabled")).toBe(true);
    fireEvent.click(saveButton());
    await tick();
    expect(puts(calls)).toHaveLength(0);
  });

  it("khoá trùng → cảnh báo vàng, KHÔNG khoá Lưu; sửa → chấm 'Bản nháp chưa lưu'; 201 → 'Đã lưu thành bản 5', hết chấm", async () => {
    let current = view();
    const calls = stubFetch(
      policyRoutes({
        current: () => current,
        put: (body) => {
          current = view({ version_id: 15, version: "5", content: (body as { content: Record<string, unknown> }).content });
          return json(201, { version_id: 15, version: "5" });
        },
      }),
    );
    renderAt("/policy");
    const area = await openJson();
    expect(screen.queryByTestId("draft-mark")).toBeNull();
    const dup = formatPolicy(POLICY).replace('"SLA_MINUTES": 30,', '"SLA_MINUTES": 30,\n    "SLA_MINUTES": 45,');
    fireEvent.change(area, { target: { value: dup } });
    expect(screen.getByTestId("draft-mark").textContent).toContain("Bản nháp chưa lưu");
    const warning = screen.getByTestId("policy-warning");
    expect(warning.textContent).toMatch(/^Khoá "SLA_MINUTES" lặp ở dòng \d+ và \d+ — hệ thống dùng giá trị sau cùng/);
    expect(gutterMark(Number(warning.dataset.line))).toBe("warn");
    expect(screen.queryByTestId("policy-problem")).toBeNull();
    expect(saveButton().textContent).toBe("Lưu");
    fireEvent.click(saveButton());
    expect((await screen.findByTestId("policy-message")).textContent).toBe("Đã lưu thành bản 5.");
    await waitFor(() => expect(screen.queryByTestId("draft-mark")).toBeNull());
    expect((JSON.parse(puts(calls)[0]!.body!) as { content: { constants: { SLA_MINUTES: number } } }).content.constants.SLA_MINUTES).toBe(45);
    fireEvent.click(screen.getByRole("tab", { name: "Bảng" }));
    const sla = screen.getAllByTestId("constant-row").find((r) => r.dataset.key === "SLA_MINUTES")!;
    expect(sla.textContent).toContain("45"); // Bảng = giá trị sau cùng, như server
  });

  it("route chưa có (404 'Not Found') → 'Chính sách có từ Phase 7', không khối lỗi đỏ", async () => {
    stubFetch((_m, url) => (pathOf(url).startsWith("/api/policy") ? json(404, { detail: "Not Found" }) : undefined));
    renderAt("/policy");
    const box = await screen.findByTestId("policy-missing");
    expect(within(box).getByRole("heading").textContent).toBe(POLICY_MISSING_TITLE);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t61

/** JWT dạng thật (3 đoạn base64url) — client đọc `sub` để so danh tính, không kiểm chữ ký. */
const jwt = (sub: string, n: string) => `h.${btoa(JSON.stringify({ sub, n })).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_")}.s`;
const OLD = jwt("it_mgr01", "old");
const NEW = jwt("it_mgr01", "new");
const tokenBody = (token: string) => json(200, { access_token: token, token_type: "bearer", expires_in: 900, csrf_token: "c" });
const EMPLOYEE: Me = { user_id: "nv001", role: "employee", permissions: BASE };
const OTHER = jwt("nv001", "x");

function reauthSetup({ login, meAfterLogin = MGR }: { login: () => Response; meAfterLogin?: Me }) {
  const calls: Call[] = [];
  let loggedIn = false;
  const routes = policyRoutes({
    current: () => view(),
    put: (_b, auth) => (auth === `Bearer ${NEW}` ? json(201, { version_id: 15, version: "5" }) : json(403, { detail: "reauth_required" })),
    restore: (_id, auth) => (auth === `Bearer ${NEW}` ? json(201, { version_id: 15, version: "5" }) : json(403, { detail: "reauth_required" })),
  });
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    calls.push({ method, url, body: typeof init.body === "string" ? init.body : null, auth: new Headers(init.headers).get("Authorization") });
    if (url === "/api/auth/refresh") return tokenBody(OLD); // tải trang: khôi phục phiên (đăng nhập đã lâu)
    if (url === "/api/auth/login") {
      const res = login();
      loggedIn = res.ok;
      return res;
    }
    if (url === "/api/auth/me") return json(200, loggedIn ? meAfterLogin : MGR);
    // Như backend: người không có policy:read (nhân viên) → 403 cho mọi route chính sách.
    if (url.startsWith("/api/policy") && new Headers(init.headers).get("Authorization") === `Bearer ${OTHER}`) return json(403, { detail: "forbidden" });
    return (await routes(method, url, init)) ?? json(404, { detail: "not_found" });
  });
  const client = createClient({ fetch, readCookie: () => "csrf-1", locks: null, channel: null, onSessionEnd: vi.fn() });

  function Gate({ children }: { children: ReactNode }) {
    return useAuth().state.status === "signedIn" ? children : <p>Đang kiểm tra…</p>;
  }
  function Landing() {
    return (
      <>
        <p data-testid="landing">{useLocation().pathname}</p>
        <FlashNotice />
      </>
    );
  }
  const queryClient = new QueryClient();
  clients.push(queryClient);
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider client={client} subscribe={() => () => {}}>
        <MemoryRouter initialEntries={["/policy"]}>
          <Routes>
            <Route
              path="/policy"
              element={
                <Gate>
                  <PolicyEditor client={client} />
                </Gate>
              }
            />
            <Route path="/chat" element={<Landing />} />
            <Route path="/dashboard" element={<Landing />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { calls, queryClient };
}

async function reauthWith(password: string) {
  const dialog = await screen.findByRole("dialog", { name: "Xác nhận lại đăng nhập" });
  fireEvent.change(within(dialog).getByLabelText("Tên đăng nhập"), { target: { value: "quan.tm" } });
  fireEvent.change(within(dialog).getByLabelText("Mật khẩu"), { target: { value: password } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Đăng nhập lại" }));
}

describe("t61: Lưu / quay lui gặp 403 reauth_required → đăng nhập lại (luồng F1) → gửi lại ĐÚNG 1 lần", () => {
  it("Lưu, cùng người: PUT gửi 2 lần (token cũ → mới), body lần 2 = lần 1; 'Đã lưu thành bản 5'", async () => {
    const { calls } = reauthSetup({ login: () => tokenBody(NEW) });
    const area = await openJson();
    fireEvent.change(area, { target: { value: formatPolicy(POLICY).replace('"SLA_MINUTES": 30', '"SLA_MINUTES": 35') } });
    fireEvent.click(saveButton());
    await reauthWith("pw");
    expect((await screen.findByTestId("policy-message")).textContent).toBe("Đã lưu thành bản 5.");
    const sent = puts(calls);
    expect(sent.map((c) => c.auth)).toStrictEqual([`Bearer ${OLD}`, `Bearer ${NEW}`]);
    expect(JSON.parse(sent[1]!.body!)).toStrictEqual(JSON.parse(sent[0]!.body!));
    await tick(30);
    expect(puts(calls)).toHaveLength(2);
    expect(screen.queryByRole("dialog", { name: "Xác nhận lại đăng nhập" })).toBeNull();
  });

  it("Lưu, đăng nhập lại bằng NGƯỜI KHÁC → không gửi lại, xoá cache, về trang đầu người mới + câu báo huỷ", async () => {
    const { calls, queryClient } = reauthSetup({ login: () => tokenBody(OTHER), meAfterLogin: EMPLOYEE });
    const area = await openJson();
    fireEvent.change(area, { target: { value: formatPolicy(POLICY).replace('"SLA_MINUTES": 30', '"SLA_MINUTES": 35') } });
    fireEvent.click(saveButton());
    await reauthWith("pw");
    expect((await screen.findByTestId("landing")).textContent).toBe(homePath(EMPLOYEE));
    expect(screen.getByTestId("flash").textContent).toBe("Bạn đã đăng nhập bằng tài khoản khác — thao tác trên chính sách đã huỷ.");
    // Không còn dữ liệu nào của người cũ. (Router chuyển trang trong startTransition → màn cũ kịp render lại sau
    // `clear()` và dựng lại truy vấn bằng token NGƯỜI MỚI — backend trả 403, không có dữ liệu.)
    await tick(30);
    expect(queryClient.getQueryCache().getAll().filter((q) => q.state.data !== undefined)).toHaveLength(0);
    expect(calls.filter((c) => c.method === "GET" && c.url.startsWith("/api/policy") && c.auth === `Bearer ${OLD}` && c.url === "/api/policy")).toHaveLength(1);
    expect(puts(calls)).toHaveLength(1);
  });

  it("Quay lui, cùng người: POST restore gửi 2 lần (cũ → mới) rồi dừng", async () => {
    const { calls } = reauthSetup({ login: () => tokenBody(NEW) });
    fireEvent.click(await screen.findByRole("button", { name: "Quay lui bản 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Áp dụng lại" }));
    await reauthWith("pw");
    expect((await screen.findByTestId("policy-message")).textContent).toBe("Đã áp dụng lại nội dung bản 2 thành bản 5.");
    expect(restores(calls).map((c) => [pathOf(c.url), c.auth])).toStrictEqual([
      ["/api/policy/versions/12/restore", `Bearer ${OLD}`],
      ["/api/policy/versions/12/restore", `Bearer ${NEW}`],
    ]);
    await tick(30);
    expect(restores(calls)).toHaveLength(2);
  });
});

// ------------------------------------------------------------------------------------------------ t62, t63

describe("t62: chỉ có policy:read → chỉ xem (không Lưu, không Quay lui, ô JSON chỉ đọc)", () => {
  it("không nút Lưu / Quay lui; textarea readOnly; lịch sử vẫn hiện", async () => {
    stubFetch(policyRoutes({ current: () => view() }));
    renderAt("/policy", READER);
    const area = await openJson();
    expect(area.readOnly).toBe(true);
    expect(screen.queryByRole("button", { name: /^Lưu/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Quay lui/ })).toBeNull();
    expect(await screen.findAllByTestId("version-row")).toHaveLength(4);
    expect(screen.getByText("Bạn chỉ có quyền xem chính sách.")).toBeTruthy();
  });
});

describe("t63: quay lui — hộp xác nhận nêu rõ tạo phiên bản mới; Huỷ → 0 POST; Áp dụng lại → 1 POST", () => {
  it("câu xác nhận; Huỷ; xác nhận → POST /restore của đúng version_id → 201 → câu báo + tải lại lịch sử", async () => {
    const calls = stubFetch(policyRoutes({ current: () => view() }));
    renderAt("/policy");
    const rows = await screen.findAllByTestId("version-row");
    expect(rows.map((r) => r.dataset.version)).toStrictEqual(["4", "3", "2", "1"]);
    expect(rows[1]!.textContent).toContain("khôi phục từ bản 1");
    expect(within(rows[0]!).queryByRole("button", { name: /Quay lui/ })).toBeNull(); // bản đang áp dụng
    fireEvent.click(screen.getByRole("button", { name: "Quay lui bản 2" }));
    expect(screen.getByTestId("restore-confirm-text").textContent).toBe("Nội dung bản 2 sẽ được áp dụng lại thành một phiên bản mới.");
    expect(restoreConfirmText("2")).toBe("Nội dung bản 2 sẽ được áp dụng lại thành một phiên bản mới.");
    fireEvent.click(screen.getByRole("button", { name: "Huỷ" }));
    await tick();
    expect(restores(calls)).toHaveLength(0);
    const versionsBefore = calls.filter((c) => pathOf(c.url) === "/api/policy/versions").length;
    fireEvent.click(screen.getByRole("button", { name: "Quay lui bản 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Áp dụng lại" }));
    expect((await screen.findByTestId("policy-message")).textContent).toBe("Đã áp dụng lại nội dung bản 2 thành bản 5.");
    expect(restores(calls).map((c) => pathOf(c.url))).toStrictEqual(["/api/policy/versions/12/restore"]);
    await waitFor(() => expect(calls.filter((c) => pathOf(c.url) === "/api/policy/versions").length).toBe(versionsBefore + 1));
  });
});

// ------------------------------------------------------------------------------------------------ t64

describe("t64: L1 (ha.lt) không vào được 3 màn Trưởng BP IT — 0 lời gọi API; thanh bên không có 3 mục", () => {
  it.each(["/dashboard", "/alerts", "/policy"])("%s → trang không có quyền, 0 request", async (path) => {
    const calls = stubFetch(() => undefined);
    renderAt(path, L1);
    expect(screen.getByRole("heading", { name: "Bạn không có quyền xem trang này" })).toBeTruthy();
    await tick();
    expect(calls).toHaveLength(0);
  });

  it("thanh bên: L1 không có Tổng quan/Cảnh báo/Chính sách; Trưởng BP IT có cả 3 + 'Chờ tôi duyệt'; trang đầu /dashboard", () => {
    const labels = (me: Me) => {
      const view = render(
        <MemoryRouter>
          <Sidebar me={me} onSignOut={async () => true} />
        </MemoryRouter>,
      );
      const names = within(view.container).getAllByRole("link").map((a) => a.textContent);
      view.unmount();
      return names;
    };
    const l1 = labels(L1);
    for (const name of ["Tổng quan", "Cảnh báo", "Chính sách"]) expect(l1).not.toContain(name);
    const mgr = labels(MGR);
    for (const name of ["Tổng quan", "Cảnh báo", "Chính sách", "Chờ tôi duyệt"]) expect(mgr).toContain(name);
    expect(homePath(MGR)).toBe("/dashboard");
  });
});

// ================================================================================================ N-A3 — route thật M9 A3

/** Chữ của phần tử, NBSP (giữa số và "%"/"ms") → dấu cách thường để so chuỗi. */
const text = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\u00a0/g, " ");
const alertRow = (id: number) => document.querySelector<HTMLElement>(`[data-testid="alert-row"][data-alert-id="${id}"]`);
const alertGets = (calls: Call[]) => calls.filter((c) => c.method === "GET" && pathOf(c.url) === "/api/alerts");
const apiErrorOf = (fn: () => unknown): ApiError | null => {
  try {
    fn();
  } catch (e) {
    return e instanceof ApiError ? e : null;
  }
  return null;
};
const without = <T extends object>(value: T, key: keyof T) => Object.fromEntries(Object.entries(value).filter(([k]) => k !== key));

// ------------------------------------------------------------------------------------------------ t109

describe("t109 (P2): parseAlerts / isAlertItem — MỘT hình dạng {items, truncated}; sai một chỗ → 502 invalid_alerts_body", () => {
  const ok = alert(1, "drift", "info", 0, { audience: ["manager", "ops"], detail: { n: 1 }, value: 3.5 });
  const is502 = (body: unknown) => {
    const e = apiErrorOf(() => parseAlerts(body));
    return e !== null && e.status === 502 && e.code === "invalid_alerts_body";
  };

  it("đúng hình dạng → trả nguyên items + truncated; audience lạ / rỗng, cảnh báo đã ack vẫn hợp lệ", () => {
    expect(parseAlerts({ items: [ok], truncated: true })).toStrictEqual({ items: [ok], truncated: true });
    expect(parseAlerts({ items: [], truncated: false })).toStrictEqual({ items: [], truncated: false });
    expect(isAlertItem({ ...ok, status: "acked", acked_by: "it_mgr01", acked_at: "2026-10-01T05:00:00Z", audience: [] })).toBe(true);
    expect(isAlertItem({ ...ok, audience: ["pager"] })).toBe(true);
    expect(isAlertItem({ ...ok, alert_id: Number.MAX_SAFE_INTEGER })).toBe(true);
  });

  it.each([
    ["mảng trần (hình dạng cũ)", [ok]],
    ["thiếu truncated", { items: [ok] }],
    ["truncated là chuỗi", { items: [ok], truncated: "false" }],
    ["items là object", { items: { 0: ok }, truncated: false }],
    ["null", null],
  ])("thân %s → 502", (_name, body) => {
    expect(is502(body)).toBe(true);
  });

  it.each([
    ["alert_id 2^53 (không an toàn — JS đã làm tròn)", { alert_id: 2 ** 53 }],
    ["alert_id 0", { alert_id: 0 }],
    ["alert_id 1.5", { alert_id: 1.5 }],
    ["alert_id chuỗi", { alert_id: "2" }],
    ["status lạ", { status: "closed" }],
    ["value chuỗi", { value: "3" }],
    ["detail null", { detail: null }],
    ["detail mảng", { detail: [] }],
    ["audience không phải mảng", { audience: "manager" }],
    ["audience có số", { audience: ["manager", 1] }],
    ["acked_by là số", { acked_by: 7 }],
    ["thiếu created_at", { created_at: undefined }],
  ])("MỘT cảnh báo có %s → cả danh sách 502 (không lặng lẽ bỏ dòng)", (_name, over) => {
    const bad = { ...ok, alert_id: 2, ...over };
    expect(isAlertItem(bad)).toBe(false);
    expect(is502({ items: [ok, bad], truncated: false })).toBe(true);
  });

  it("màn Cảnh báo: thân mảng trần → khối lỗi, 0 dòng cảnh báo", async () => {
    stubFetch((method, url) => (method === "GET" && pathOf(url) === "/api/alerts" ? json(200, [ok]) : undefined));
    renderAt("/alerts");
    expect(text(await screen.findByTestId("load-error"))).toContain("Chưa tải được cảnh báo");
    expect(screen.queryAllByTestId("alert-row")).toHaveLength(0);
  });
});

// ------------------------------------------------------------------------------------------------ t110

describe("t110 (P3): 'Đang mở' = /api/alerts?status=open, 'Tất cả' = /api/alerts — không audience, limit, tham số rỗng", () => {
  it("màn Cảnh báo (2 bộ lọc) + khối Tổng quan: đúng 2 URL, chỉ GET", async () => {
    const calls = dashboardServer({ alerts: () => json(200, alertList([alert(1, "drift", "info", 0)])) });
    renderAt("/alerts");
    await waitFor(() => expect(alertRow(1)).not.toBeNull());
    fireEvent.click(screen.getByRole("tab", { name: "Tất cả" }));
    await waitFor(() => expect(alertGets(calls).some((c) => c.url === "/api/alerts")).toBe(true));
    await waitFor(() => expect(alertRow(1)).not.toBeNull());
    cleanup();
    renderAt("/dashboard");
    const block = await screen.findByTestId("open-alerts");
    await waitFor(() => expect(within(block).getAllByTestId("alert-row")).toHaveLength(1));
    const urls = calls.filter((c) => pathOf(c.url).startsWith("/api/alerts")).map((c) => `${c.method} ${c.url}`);
    expect(new Set(urls)).toStrictEqual(new Set(["GET /api/alerts?status=open", "GET /api/alerts"]));
    expect(urls.filter((u) => u === "GET /api/alerts?status=open").length).toBeGreaterThanOrEqual(2); // màn Cảnh báo + khối Tổng quan
  });
});

// ------------------------------------------------------------------------------------------------ t111

describe("t111 (P4): truncated → băng 'Chỉ hiện 200 cảnh báo mới nhất…' (cả 2 bộ lọc); khối Tổng quan đếm '200+'", () => {
  const BANNER = "Chỉ hiện 200 cảnh báo mới nhất — còn cảnh báo cũ hơn chưa hiện.";
  const many = Array.from({ length: 200 }, (_, i) => alert(i + 1, "drift", "info", i));

  it("màn Cảnh báo: truncated → băng role=status ở 'Đang mở' và 'Tất cả'", async () => {
    const calls = dashboardServer({ alerts: () => json(200, alertList(many.slice(0, 3), true)) });
    renderAt("/alerts");
    const banner = await screen.findByTestId("alerts-truncated");
    expect([banner.getAttribute("role"), banner.textContent]).toStrictEqual(["status", BANNER]);
    fireEvent.click(screen.getByRole("tab", { name: "Tất cả" }));
    await waitFor(() => expect(alertGets(calls).some((c) => c.url === "/api/alerts")).toBe(true));
    expect((await screen.findByTestId("alerts-truncated")).textContent).toBe(BANNER);
    expect(screen.getAllByTestId("alert-row")).toHaveLength(3);
  });

  it("màn Cảnh báo: truncated false → không băng", async () => {
    dashboardServer({ alerts: () => json(200, alertList(many.slice(0, 3), false)) });
    renderAt("/alerts");
    await waitFor(() => expect(screen.getAllByTestId("alert-row")).toHaveLength(3));
    expect(screen.queryByTestId("alerts-truncated")).toBeNull();
  });

  it("khối Tổng quan: 200 cảnh báo + truncated → '· 200+', 5 dòng; 3 cảnh báo không truncated → '· 3'", async () => {
    dashboardServer({ alerts: () => json(200, alertList(many, true)) });
    renderAt("/dashboard");
    let block = await screen.findByTestId("open-alerts");
    await waitFor(() => expect(within(block).getAllByTestId("alert-row")).toHaveLength(5));
    expect(within(block).getByRole("heading").textContent).toBe("Cảnh báo đang mở · 200+");
    cleanup();
    dashboardServer({ alerts: () => json(200, alertList(many.slice(0, 3), false)) });
    renderAt("/dashboard");
    block = await screen.findByTestId("open-alerts");
    await waitFor(() => expect(within(block).getAllByTestId("alert-row")).toHaveLength(3));
    expect(within(block).getByRole("heading").textContent).toBe("Cảnh báo đang mở · 3");
  });
});

// ------------------------------------------------------------------------------------------------ t112

describe("t112 (P5): audience → nhãn người nhận (chỉ bản đầy đủ); giá trị lạ hiện nguyên; KHÔNG lọc theo audience", () => {
  it("5 cảnh báo đủ loại audience → đủ 5 dòng, nhãn đúng; khối gọn của Tổng quan không có nhãn", async () => {
    const items = [
      alert(1, "password_bruteforce", "critical", 1, { audience: ["manager"] }),
      alert(2, "finalize_failed", "critical", 2, { audience: ["dev"] }),
      alert(3, "execution_failed", "warning", 3, { audience: ["manager", "ops"] }),
      alert(4, "x_rule", "info", 4, { audience: ["pager"] as unknown as AlertItem["audience"] }),
      alert(5, "y_rule", "info", 5, { audience: [] }),
    ];
    dashboardServer({ alerts: () => json(200, alertList(items)) });
    renderAt("/alerts");
    await waitFor(() => expect(screen.getAllByTestId("alert-row")).toHaveLength(5));
    const audience = (id: number) => alertRow(id)?.querySelector('[data-testid="alert-audience"]')?.textContent ?? null;
    expect([1, 2, 3, 4, 5].map(audience)).toStrictEqual([
      "Người nhận: Trưởng BP IT",
      "Người nhận: Dev",
      "Người nhận: Trưởng BP IT, Vận hành",
      "Người nhận: pager",
      null,
    ]);
    cleanup();
    renderAt("/dashboard");
    const block = await screen.findByTestId("open-alerts");
    await waitFor(() => expect(within(block).getAllByTestId("alert-row")).toHaveLength(5));
    expect(within(block).queryAllByTestId("alert-audience")).toHaveLength(0);
  });
});

// ------------------------------------------------------------------------------------------------ t113

describe("t113 (P6): ack — 200 đọc được mới gỡ; 200 không đọc được / 409 / 404 → câu riêng + ĐÚNG 1 lần tải lại", () => {
  /** Server giả: danh sách theo `status`; POST theo id. `hold` chặn GET tải lại sau ack (soi cache trước khi server trả). */
  function ackServer() {
    const items = [
      alert(1001, "password_bruteforce", "critical", 1, { subject: "nv004" }),
      alert(1002, "e9_spike", "warning", 2),
      alert(1003, "e6_spike", "warning", 3),
      alert(1004, "drift", "info", 4),
      alert(1005, "b2_degraded", "info", 5),
      alert(9409, "refresh_reuse", "critical", 5),
      alert(9404, "permission_denied_burst", "warning", 6),
      alert(9405, "policy_saved", "info", 7),
    ];
    const state = { hold: null as Promise<void> | null, acks: 0, allDown: false };
    const ackedNow = (a: AlertItem): AlertItem => ({ ...a, status: "acked", acked_by: "it_mgr01", acked_at: "2026-10-01T05:10:00Z" });
    const calls = stubFetch(async (method, url) => {
      const path = pathOf(url);
      if (path === "/api/alerts" && method === "GET") {
        if (state.hold) await state.hold;
        const status = queryOf(url).get("status");
        if (status !== "open" && state.allDown) return json(503, { detail: "monitor_unavailable" });
        return json(200, alertList(status === "open" ? items.filter((a) => a.status === "open") : items, true));
      }
      const id = Number(/^\/api\/alerts\/(\d+)\/ack$/.exec(path)?.[1]);
      if (method !== "POST" || !id) return undefined;
      state.acks += 1;
      const i = items.findIndex((a) => a.alert_id === id);
      const target = items[i]!;
      if (id === 9409) {
        items[i] = { ...target, status: "acked", acked_by: "it_mgr02" }; // người khác xác nhận trước
        return json(409, { detail: "already_acked" });
      }
      if (id === 9404) {
        items.splice(i, 1);
        return json(404, { detail: "not_found" });
      }
      if (id === 9405) return json(404, { detail: "Not Found" });
      if (id === 1005) return json(200, target); // đúng hình dạng, đúng id nhưng status vẫn "open" — server KHÔNG ghi
      items[i] = ackedNow(target); // 1001–1004: server ĐÃ ghi
      if (id === 1002) return new Response("{", { status: 200, headers: { "Content-Type": "application/json" } }); // JSON hỏng
      if (id === 1003) return json(200, { status: "acked" }); // sai hình dạng
      if (id === 1004) return json(200, ackedNow({ ...target, alert_id: 77 })); // khác id
      return json(200, items[i]);
    });
    return { calls, state };
  }
  const clickAck = (id: number) => fireEvent.click(within(alertRow(id)!).getByRole("button", { name: "Đã xem" }));
  const notice = () => screen.getByTestId("ack-notice");

  it("200 đọc được → rời 'Đang mở' NGAY bằng cache (giữ truncated) trước khi tải lại về; 'Tất cả' hiện 'Đã xem · it_mgr01'", async () => {
    const { calls, state } = ackServer();
    const client = renderAt("/alerts");
    await waitFor(() => expect(alertRow(1001)).not.toBeNull());
    let release: () => void = () => {};
    state.hold = new Promise<void>((r) => (release = r));
    const before = alertGets(calls).length;
    clickAck(1001);
    await waitFor(() => expect(notice().textContent).toBe("Đã xác nhận cảnh báo"));
    expect(notice().getAttribute("role")).toBe("status");
    expect(alertRow(1001)).toBeNull();
    const cached = client.getQueryData<AlertList>(["alerts", "open"])!;
    expect([cached.truncated, cached.items.some((a) => a.alert_id === 1001)]).toStrictEqual([true, false]);
    expect(screen.getByTestId("alerts-truncated")).toBeTruthy();
    await waitFor(() => expect(alertGets(calls).length).toBe(before + 1));
    state.hold = null;
    release();
    fireEvent.click(screen.getByRole("tab", { name: "Tất cả" }));
    await waitFor(() => expect(alertRow(1001)?.dataset.status).toBe("acked"));
    expect(text(within(alertRow(1001)!).getByTestId("alert-acked"))).toMatch(/^Đã xem · it_mgr01 · /);
  });

  it.each([
    [1002, "JSON hỏng", true],
    [1003, "sai hình dạng", true],
    [1004, "khác id", true],
    [1005, "status vẫn 'open'", false],
  ])("200 thân %s (%s) → KHÔNG báo thành công, KHÔNG sửa cache, câu role=alert + ĐÚNG 1 lần tải lại", async (id, _name, serverAcked) => {
    const { calls, state } = ackServer();
    const client = renderAt("/alerts");
    await waitFor(() => expect(alertRow(id)).not.toBeNull());
    let release: () => void = () => {};
    state.hold = new Promise<void>((r) => (release = r));
    const before = alertGets(calls).length;
    clickAck(id);
    await waitFor(() => expect(notice().textContent).toBe("Đã gửi xác nhận nhưng không đọc được phản hồi — danh sách đã tải lại."));
    expect(notice().getAttribute("role")).toBe("alert");
    // Trước khi lần tải lại về: cache "Đang mở" còn nguyên cảnh báo (không đoán là đã ack).
    expect(client.getQueryData<AlertList>(["alerts", "open"])!.items.some((a) => a.alert_id === id)).toBe(true);
    expect(alertRow(id)).not.toBeNull();
    await waitFor(() => expect(alertGets(calls).length).toBe(before + 1));
    state.hold = null;
    release();
    // Lần tải lại cho thấy sự thật của server: đã ghi → rời "Đang mở"; chưa ghi → vẫn còn.
    if (serverAcked) await waitFor(() => expect(alertRow(id)).toBeNull());
    else await waitFor(() => expect(alertGets(calls).length).toBe(before + 1));
    await tick(30);
    if (!serverAcked) expect(alertRow(id)?.dataset.status).toBe("open");
    expect(alertGets(calls).length).toBe(before + 1);
    expect(screen.queryByText("Đã xác nhận cảnh báo")).toBeNull();
  });

  it("409 → 'đã được xác nhận trước đó' + ĐÚNG 1 GET tải lại (không đọc acked_by); 404 not_found → 'không còn' + 1 GET", async () => {
    const { calls } = ackServer();
    renderAt("/alerts");
    await waitFor(() => expect(alertRow(9409)).not.toBeNull());
    let before = alertGets(calls).length;
    clickAck(9409);
    await waitFor(() => expect(notice().textContent).toBe("Cảnh báo này đã được xác nhận trước đó"));
    await waitFor(() => expect(alertGets(calls).length).toBe(before + 1));
    await waitFor(() => expect(alertRow(9409)).toBeNull());
    await tick(30);
    expect(alertGets(calls).length).toBe(before + 1);
    expect(document.body.textContent).not.toContain("it_mgr02");
    before = alertGets(calls).length;
    clickAck(9404);
    await waitFor(() => expect(notice().textContent).toBe("Cảnh báo không còn"));
    await waitFor(() => expect(alertGets(calls).length).toBe(before + 1));
    await tick(30);
    expect(alertGets(calls).length).toBe(before + 1);
  });

  it("'Tất cả' đang LỖI → ack 200 ở 'Đang mở' KHÔNG biến nó thành danh sách cũ trước lỗi (security-reviewer 3b)", async () => {
    const { state } = ackServer();
    const client = renderAt("/alerts");
    await waitFor(() => expect(alertRow(1001)).not.toBeNull());
    fireEvent.click(screen.getByRole("tab", { name: "Tất cả" }));
    await waitFor(() => expect(screen.getAllByTestId("alert-row")).toHaveLength(8));
    state.allDown = true;
    await client.invalidateQueries({ queryKey: ["alerts", "all"] }); // lần tải lại của "Tất cả" gặp 503
    expect(text(await screen.findByTestId("load-error"))).toContain(MONITOR_DOWN_TEXT);
    fireEvent.click(screen.getByRole("tab", { name: "Đang mở" }));
    await waitFor(() => expect(alertRow(1001)).not.toBeNull());
    clickAck(1001);
    await waitFor(() => expect(notice().textContent).toBe("Đã xác nhận cảnh báo"));
    expect(client.getQueryState(["alerts", "all"])?.status).toBe("error");
    fireEvent.click(screen.getByRole("tab", { name: "Tất cả" }));
    expect(screen.queryAllByTestId("alert-row")).toHaveLength(0);
    expect(text(await screen.findByTestId("load-error"))).toContain(MONITOR_DOWN_TEXT);
    await tick(30);
    expect(screen.queryAllByTestId("alert-row")).toHaveLength(0);
  });

  it("404 'Not Found' của Starlette (route ack chưa có) → câu 'có từ A3', KHÔNG tải lại; bấm 2 lần cùng nhịp → 1 POST", async () => {
    const { calls, state } = ackServer();
    renderAt("/alerts");
    await waitFor(() => expect(alertRow(9405)).not.toBeNull());
    const before = alertGets(calls).length;
    const button = within(alertRow(9405)!).getByRole("button", { name: "Đã xem" });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(notice().textContent).toBe("Cảnh báo có từ M9 (chặng A3) — máy chủ chưa có chức năng này."));
    await tick(30);
    expect([state.acks, alertGets(calls).length]).toStrictEqual([1, before]);
  });
});

// ------------------------------------------------------------------------------------------------ t114

describe("t114 (P7): parseBusiness / parseAi — khung + scope 'all' + hình dạng lồng; khoá chỉ số THIẾU không làm 502", () => {
  const is502 = (fn: () => unknown) => {
    const e = apiErrorOf(fn);
    return e !== null && e.status === 502 && e.code === "invalid_dashboard_body";
  };
  const withMetric = (name: string, value: unknown) => ({ ...BUSINESS, metrics: { ...METRICS, [name]: value } });
  const withAiMetric = (name: string, value: unknown) => ({ ...AI, metrics: { ...AI_METRICS_BODY, [name]: value } });

  it("đúng → trả nguyên; mọi chỉ số null → nhận; khoá thiếu / metrics rỗng → vẫn nhận", () => {
    expect(parseBusiness(BUSINESS)).toStrictEqual(BUSINESS);
    expect(parseAi(AI)).toStrictEqual(AI);
    const allNull = Object.fromEntries(Object.keys(METRICS).map((k) => [k, null]));
    expect(parseBusiness({ ...BUSINESS, metrics: allNull }).metrics).toStrictEqual(allNull);
    expect(parseBusiness({ ...BUSINESS, metrics: without(METRICS, "deflection_rate") }).metrics.deflection_rate).toBeUndefined();
    expect(parseBusiness({ ...BUSINESS, metrics: {} }).metrics).toStrictEqual({});
    expect(parseAi({ ...AI, metrics: without(AI_METRICS_BODY, "cost_per_day") }).metrics.cost_per_day).toBeUndefined();
  });

  it.each([
    ["scope 'own' (L1)", { ...BUSINESS, scope: "own" }],
    ["thiếu scope", without(BUSINESS, "scope")],
    ["hình dạng phẳng cũ (chỉ số ở gốc, không metrics)", { ...without(BUSINESS, "metrics"), ...METRICS }],
    ["metrics null", { ...BUSINESS, metrics: null }],
    ["metrics mảng", { ...BUSINESS, metrics: [] }],
    ["thiếu unavailable", without(BUSINESS, "unavailable")],
    ["unavailable có số", { ...BUSINESS, unavailable: [1] }],
    ["from là số", { ...BUSINESS, from: 0 }],
    ["thân là mảng", [BUSINESS]],
    ["escalation_rate_weighted là số (cũ)", withMetric("escalation_rate_weighted", 0.14)],
    ["weighted thiếu by_group", withMetric("escalation_rate_weighted", without(METRICS.escalation_rate_weighted!, "by_group"))],
    ["by_group có giá trị chuỗi", withMetric("escalation_rate_weighted", { ...METRICS.escalation_rate_weighted!, by_group: { routine: "10%" } })],
    ["sensitivity null", withMetric("escalation_rate_weighted", { ...METRICS.escalation_rate_weighted!, sensitivity: null })],
    ["weighted.weighted chuỗi", withMetric("escalation_rate_weighted", { ...METRICS.escalation_rate_weighted!, weighted: "0.1" })],
    ["decided_by_distribution là mảng", withMetric("decided_by_distribution", [223, 63])],
    ["top_matched_rules là object", withMetric("top_matched_rules", { R20: 96 })],
    ["top_matched_rules count chuỗi", withMetric("top_matched_rules", [{ rule_id: "R20", count: "96" }])],
    ["e1_split phẳng cũ (không total/counts)", withMetric("e1_split", { out_of_scope: 9 })],
    ["e1_split counts có chuỗi", withMetric("e1_split", { ...METRICS.e1_split!, counts: { other: "2" } })],
    ["e3_cases là mảng (cũ)", withMetric("e3_cases", METRICS.e3_cases!.items)],
    ["e3_cases thiếu truncated", withMetric("e3_cases", { items: [] })],
    ["e3 ca có request_excerpt số", withMetric("e3_cases", { items: [{ ...METRICS.e3_cases!.items[0]!, request_excerpt: 1 }], truncated: false })],
  ])("business: %s → 502", (_name, body) => {
    expect(is502(() => parseBusiness(body))).toBe(true);
  });

  it.each([
    ["hình dạng phẳng cũ (không metrics)", { ...without(AI, "metrics"), ...AI_METRICS_BODY }],
    ["thiếu unavailable", without(AI, "unavailable")],
    ["to là null", { ...AI, to: null }],
    ["cost_per_day kiểu cũ {day, cost_usd}", withAiMetric("cost_per_day", [{ day: "2026-09-30", cost_usd: 0.42 }])],
    ["cost_per_day cost chuỗi", withAiMetric("cost_per_day", [{ day_start: "2026-09-29T17:00:00Z", cost_usd: "0.42" }])],
    ["cost_per_day là object", withAiMetric("cost_per_day", { "2026-09-30": 0.42 })],
    ["latency_p95_by_step có chuỗi", withAiMetric("latency_p95_by_step", { B3: "820" })],
    ["latency_p95_by_step là mảng", withAiMetric("latency_p95_by_step", [820])],
  ])("ai: %s → 502", (_name, body) => {
    expect(is502(() => parseAi(body))).toBe(true);
  });
});

// ------------------------------------------------------------------------------------------------ t115

describe("t115 (P8): màn Nghiệp vụ đọc data.metrics — KPI có trọng số = .weighted, nhóm rủi ro, độ nhạy, E1 'other', E3 truncated", () => {
  const kpi = (name: string) => document.querySelector<HTMLElement>(`[data-testid="kpi"][data-metric="${name}"]`)!;
  const kpiValue = (name: string) => text(within(kpi(name)).getByTestId("kpi-value"));

  it("ô số + khối mới với dữ liệu thật đầy đủ", async () => {
    dashboardServer();
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect(text(screen.getByTestId("dashboard-window"))).toBe("Từ 25/09 00:00 đến 01/10 12:05 (giờ Việt Nam) · chỉ tính ticket lá.");
    expect([kpiValue("automation_rate"), kpiValue("escalation_rate_weighted"), kpiValue("deflection_rate"), kpiValue("approval_expired_count")]).toStrictEqual([
      "63 %",
      "14,2 %",
      "21 %",
      "0",
    ]);
    expect(text(kpi("escalation_rate_weighted"))).toContain("thô 16 %");
    const groups = screen.getAllByTestId("weighted-group");
    expect(groups.map((g) => [g.dataset.key, text(g.firstElementChild), text(g.lastElementChild)])).toStrictEqual([
      ["routine", "Thường", "10 %"],
      ["approval", "Cần duyệt", "25 %"],
      ["sensitive", "Nhạy cảm", "—"], // nhóm 0 lá → null → "—", KHÔNG "0 %"
    ]);
    expect(text(screen.getByTestId("weighted-sensitivity"))).toBe("Độ nhạy trọng số: 60/30/10: 14,2 % · 80/15/5: 15,1 %");
    const e1 = within(screen.getByRole("region", { name: /Ca không xác định được ý định/ })).getAllByTestId("bar-row");
    expect(e1.map((r) => r.dataset.key)).toStrictEqual(["out_of_scope", "intent_low_confidence", "multi_intent_not_enabled", "intent_not_enabled", "other"]);
    expect(text(e1[4]!.firstElementChild)).toBe("Lý do khác");
    expect(screen.getAllByTestId("rule-row")).toHaveLength(1);
    const override = screen.getByTestId("metric-override_count");
    expect([override.dataset.state, text(override)]).toStrictEqual(["value", "Số lần L1 ghi đè: 0"]);
    expect(screen.getAllByTestId("e3-case")).toHaveLength(1);
    expect(text(screen.getByTestId("e3-case"))).toContain("software · 29/09 · KB v12 · t-e3");
    expect(screen.queryByTestId("e3-truncated")).toBeNull();
  });

  it("nhóm lạ hiện nguyên khoá; độ nhạy null → '—'; E3 truncated → băng; ý định / KB null → 'chưa rõ ý định', không 'KB'", async () => {
    const body = business({
      escalation_rate_weighted: { raw: 0.16, weighted: null, by_group: { routine: 0.1, experimental: 0.5 }, sensitivity: { "60/30/10": null } },
      e3_cases: {
        items: [{ ticket_id: "t-e3b", intent: null, created_at: "2026-09-29T17:30:00Z", kb_version: null, request_excerpt: "Không thấy tài liệu" }],
        truncated: true,
      },
    });
    dashboardServer({ business: () => json(200, body) });
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect([kpi("escalation_rate_weighted").dataset.state, kpiValue("escalation_rate_weighted")]).toStrictEqual(["empty", "—"]);
    expect(screen.getAllByTestId("weighted-group").map((g) => text(g))).toStrictEqual(["Thường10 %", "experimental50 %"]);
    expect(text(screen.getByTestId("weighted-sensitivity"))).toBe("Độ nhạy trọng số: 60/30/10: —");
    const banner = screen.getByTestId("e3-truncated");
    expect([banner.getAttribute("role"), banner.textContent]).toStrictEqual(["status", "Chỉ hiện 100 ca mới nhất."]);
    const e3 = text(screen.getByTestId("e3-case"));
    expect(e3).toContain("chưa rõ ý định · 30/09 · t-e3b");
    expect(e3).not.toContain("KB");
  });

  it("cửa sổ rỗng (0 ticket): tỉ lệ '—', nhóm '—', không thanh, không luật, không ca E3 — không chữ '0 %' nào", async () => {
    const body = business({
      automation_rate: null,
      escalation_rate_raw: null,
      escalation_rate_weighted: { raw: null, weighted: null, by_group: { routine: null, approval: null, sensitive: null }, sensitivity: { "60/30/10": null, "80/15/5": null } },
      deflection_rate: null,
      approval_expired_count: 0,
      decided_by_distribution: {},
      top_matched_rules: [],
      override_count: 0,
      e1_split: { total: 0, counts: { out_of_scope: 0, intent_low_confidence: 0, multi_intent_not_enabled: 0, intent_not_enabled: 0, other: 0 }, shares: {} },
      e3_cases: { items: [], truncated: false },
    });
    dashboardServer({ business: () => json(200, body) });
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect(["automation_rate", "escalation_rate_weighted", "deflection_rate"].map(kpiValue)).toStrictEqual(["—", "—", "—"]);
    expect(text(kpi("escalation_rate_weighted"))).toContain("thô —");
    expect(screen.getAllByTestId("weighted-group").map((g) => text(g.lastElementChild))).toStrictEqual(["—", "—", "—"]);
    expect(screen.queryAllByTestId("bar-row")).toHaveLength(0);
    expect(screen.getAllByText("Không có ticket trong khoảng này.")).toHaveLength(2); // decided_by + E1
    expect(screen.getByText("Không có luật nào khớp trong khoảng này.")).toBeTruthy();
    expect(screen.getByText("Không có ca E3 trong khoảng này.")).toBeTruthy();
    expect(text(document.querySelector("main") ?? document.body)).not.toMatch(/\b0 %/);
  });

  it("khoá chỉ số thiếu → 'Chưa có dữ liệu' + 'Máy chủ không trả chỉ số này' (không 0); tên trong unavailable → 'Chưa có dữ liệu'", async () => {
    const body = { ...business({}, ["override_count"]), metrics: without({ ...METRICS, override_count: null }, "deflection_rate") };
    dashboardServer({ business: () => json(200, body) });
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect([kpi("deflection_rate").dataset.state, kpiValue("deflection_rate")]).toStrictEqual(["unavailable", "Chưa có dữ liệu"]);
    expect(text(kpi("deflection_rate"))).toContain("Máy chủ không trả chỉ số này");
    const override = screen.getByTestId("metric-override_count");
    expect([override.dataset.state, text(override)]).toStrictEqual(["unavailable", "Số lần L1 ghi đè: Chưa có dữ liệu"]);
  });
});

// ------------------------------------------------------------------------------------------------ t116

describe("t116 (P9): tab AI — cost_per_day theo ngày VN (T17:00Z → hôm sau), mọi điểm, 'chưa hết ngày'; latency; null; Phase 5", () => {
  const openAi = async () => {
    await screen.findAllByTestId("kpi");
    fireEvent.click(screen.getByRole("tab", { name: "AI" }));
    return screen.findAllByTestId("ai-metric");
  };
  const row = (name: string) => document.querySelector<HTMLElement>(`[data-testid="ai-metric"][data-metric="${name}"]`)!;
  const value = (name: string) => text(row(name).lastElementChild);
  const days = Array.from({ length: 8 }, (_, i) => new Date(Date.parse("2026-09-23T17:00:00Z") + i * 86_400_000).toISOString().replace(".000Z", "Z"));
  const costs = [0.1, 0.123456, 0, 1.5, 0.00004, 2, 0.3, 0];

  it("8 điểm → 8 dòng 'dd/MM · USD' theo giờ VN; chỉ điểm cuối 'chưa hết ngày'; latency làm tròn ms", async () => {
    const body = ai({ cost_per_day: days.map((day_start, i) => ({ day_start, cost_usd: costs[i]! })) });
    dashboardServer({ ai: () => json(200, body) });
    renderAt("/dashboard");
    await openAi();
    expect(screen.getAllByTestId("ai-cost-day").map((li) => text(li))).toStrictEqual([
      "24/09 · 0,1",
      "25/09 · 0,1235",
      "26/09 · 0",
      "27/09 · 1,5",
      "28/09 · < 0,0001",
      "29/09 · 2",
      "30/09 · 0,3",
      "01/10 · 0 · chưa hết ngày",
    ]);
    expect(row("cost_per_day").dataset.state).toBe("value");
    expect(screen.getAllByTestId("ai-latency-step").map((li) => text(li))).toStrictEqual(["B3 · 820 ms", "B10 · 2.400 ms"]);
  });

  it("latency {} và cost [] → 'Không có dữ liệu trong khoảng này.'; cost null → '—'; intent null → '—' + 'Chưa ghi nhận phiên bản model'", async () => {
    dashboardServer({ ai: () => json(200, ai({ latency_p95_by_step: {}, cost_per_day: [], intent_model_version: null })) });
    renderAt("/dashboard");
    await openAi();
    expect([row("latency_p95_by_step").dataset.state, value("latency_p95_by_step")]).toStrictEqual(["value", "Không có dữ liệu trong khoảng này."]);
    expect(value("cost_per_day")).toBe("Không có dữ liệu trong khoảng này.");
    expect([row("intent_model_version").dataset.state, value("intent_model_version")]).toStrictEqual(["empty", "—Chưa ghi nhận phiên bản model"]);
    cleanup();
    dashboardServer({ ai: () => json(200, ai({ cost_per_day: null })) });
    renderAt("/dashboard");
    await openAi();
    expect([row("cost_per_day").dataset.state, value("cost_per_day")]).toStrictEqual(["empty", `—${EMPTY_NOTE}`]);
  });

  it("multi_intent (pending, trong unavailable) → 'Chưa có dữ liệu' + 'Nguồn có từ Phase 5', không số 0", async () => {
    dashboardServer();
    renderAt("/dashboard");
    await openAi();
    for (const name of ["multi_intent_first_stop_to_reply_s", "multi_intent_messages_per_turn"]) {
      expect([row(name).dataset.state, value(name)]).toStrictEqual(["unavailable", "Chưa có dữ liệuNguồn có từ Phase 5"]);
    }
    expect(text(row("multi_intent_first_stop_to_reply_s").firstElementChild)).toContain("Nhiều ý: từ lúc dừng đầu tới câu trả lời (giây)");
    expect(text(row("multi_intent_messages_per_turn").firstElementChild)).toContain("Nhiều ý: số tin mỗi lượt");
  });
});

// ------------------------------------------------------------------------------------------------ t117

describe("t117 (P10): lỗi tải — 422 cửa sổ, 500 không phải JSON, 502 thân sai, 503 monitor; không số nào hiện kèm", () => {
  const WINDOW_INVALID = "Khoảng thời gian không hợp lệ — kiểm tra ngày giờ của máy rồi tải lại.";
  const GENERIC = "Có lỗi xảy ra, vui lòng thử lại.";
  const invalid = () => json(422, { error: "invalid_request", fields: ["query.from"] });
  const crash = () => new Response("Internal Server Error", { status: 500, headers: { "Content-Type": "text/plain" } });

  it.each([
    ["422 invalid_request (query.from)", invalid, WINDOW_INVALID],
    ["500 text/plain", crash, GENERIC],
    ["200 hình dạng phẳng cũ → 502", () => json(200, { ...without(BUSINESS, "metrics"), ...METRICS }), GENERIC],
  ])("Nghiệp vụ %s → khối lỗi đúng câu, 0 ô số", async (_name, response, expected) => {
    dashboardServer({ business: response });
    renderAt("/dashboard");
    const error = await screen.findByTestId("load-error");
    expect(text(error)).toBe(`Chưa tải được số liệu${expected}`);
    expect(screen.queryAllByTestId("kpi")).toHaveLength(0);
    expect(screen.queryAllByTestId("weighted-group")).toHaveLength(0);
  });

  it("tab AI: 422 → câu cửa sổ; 500 → câu chung", async () => {
    dashboardServer({ ai: invalid });
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    fireEvent.click(screen.getByRole("tab", { name: "AI" }));
    expect(text(await screen.findByTestId("load-error"))).toBe(`Chưa tải được số liệu AI${WINDOW_INVALID}`);
    cleanup();
    dashboardServer({ ai: crash });
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    fireEvent.click(screen.getByRole("tab", { name: "AI" }));
    expect(text(await screen.findByTestId("load-error"))).toBe(`Chưa tải được số liệu AI${GENERIC}`);
    expect(screen.queryAllByTestId("ai-metric")).toHaveLength(0);
  });

  it("màn Cảnh báo: 503 monitor_unavailable → 'Số liệu tạm thời không có'; 500 text/plain → câu chung; khối Tổng quan 503 → role=alert", async () => {
    dashboardServer({ alerts: () => json(503, { detail: "monitor_unavailable" }) });
    renderAt("/alerts");
    expect(text(await screen.findByTestId("load-error"))).toContain(MONITOR_DOWN_TEXT);
    cleanup();
    dashboardServer({ alerts: crash });
    renderAt("/alerts");
    expect(text(await screen.findByTestId("load-error"))).toBe(`Chưa tải được cảnh báo${GENERIC}`);
    cleanup();
    dashboardServer({ alerts: () => json(503, { detail: "monitor_unavailable" }) });
    renderAt("/dashboard");
    const block = await screen.findByTestId("open-alerts");
    await waitFor(() => expect(within(block).getByRole("alert").textContent).toBe(MONITOR_DOWN_TEXT));
  });
});

// ------------------------------------------------------------------------------------------------ t119

describe("t119 (2b): bảng nhãn tra theo khoá RIÊNG — '__proto__' / 'constructor' / 'toString' từ server hiện nguyên, màn không vỡ", () => {
  /** Object có khoá RIÊNG "__proto__" (viết `{"__proto__": …}` trong mã JS là đổi prototype, không phải tạo khoá). */
  const ownKeys = (raw: string) => JSON.parse(raw) as Record<string, number>;
  const noLeak = () => {
    expect(document.body.textContent).not.toMatch(/function |\[object /);
  };

  it("labelOf / ownEntry / alertLabel / severityLabel / severityDot / audienceLabel; sắp xếp coi mức lạ là cuối", () => {
    expect([alertLabel("constructor"), alertLabel("injection_detected")]).toStrictEqual(["constructor", "Yêu cầu bị chặn vì nghi chèn lệnh (E0)"]);
    expect([severityLabel("__proto__"), severityLabel("toString"), severityLabel("critical")]).toStrictEqual(["__proto__", "toString", "Nghiêm trọng"]);
    expect([severityDot("__proto__"), severityDot("constructor"), severityDot("critical")]).toStrictEqual(["bg-ink-3", "bg-ink-3", "bg-danger"]);
    expect([audienceLabel("toString"), audienceLabel("manager")]).toStrictEqual(["toString", "Trưởng BP IT"]);
    expect(labelOf(E1_LABEL, "hasOwnProperty")).toBe("hasOwnProperty");
    expect(ownEntry<number>({ a: 1 }, "valueOf", 3)).toBe(3);
    const sorted = sortAlerts([alert(1, "x", "__proto__", 0), alert(2, "x", "info", 5), alert(3, "x", "constructor", 1), alert(4, "x", "critical", 9)]);
    expect(sorted.map((a) => a.alert_id)).toStrictEqual([4, 2, 1, 3]);
  });

  it("màn Cảnh báo: severity '__proto__', rule_id 'constructor', audience ['toString'] → hiện nguyên chuỗi, không vỡ", async () => {
    const items = [
      alert(1, "constructor", "__proto__", 0, { audience: ["toString"] as unknown as AlertItem["audience"], subject: "valueOf" }),
      alert(2, "toString", "critical", 1),
    ];
    dashboardServer({ alerts: () => json(200, alertList(items)) });
    renderAt("/alerts");
    await waitFor(() => expect(screen.getAllByTestId("alert-row")).toHaveLength(2));
    expect(screen.getAllByTestId("alert-row").map((r) => r.dataset.alertId)).toStrictEqual(["2", "1"]);
    const row = alertRow(1)!;
    expect(row.dataset.severity).toBe("__proto__");
    expect(text(row)).toContain("constructor — mức __proto__");
    expect(text(within(row).getByTestId("alert-audience"))).toBe("Người nhận: toString");
    expect(row.querySelector('[aria-hidden="true"]')!.className).toContain("bg-ink-3");
    expect(text(alertRow(2))).toContain("toString — mức Nghiêm trọng");
    noLeak();
  });

  it("màn Tổng quan: khoá '__proto__' / 'constructor' / 'toString' trong by_group, decided_by, e1 counts → hiện nguyên khoá", async () => {
    const body = business({
      escalation_rate_weighted: { raw: 0.16, weighted: 0.142, by_group: ownKeys('{"__proto__": 0.5, "routine": 0.1}'), sensitivity: { "60/30/10": 0.142 } },
      decided_by_distribution: ownKeys('{"__proto__": 3, "constructor": 2}'),
      e1_split: { total: 1, counts: ownKeys('{"toString": 1, "other": 0}'), shares: {} },
    });
    expect(JSON.stringify(body)).toContain('"__proto__":0.5'); // khoá thật sự đi qua dây
    dashboardServer({ business: () => json(200, body) });
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect(screen.getAllByTestId("weighted-group").map((g) => [g.dataset.key, text(g.firstElementChild)])).toStrictEqual([
      ["__proto__", "__proto__"],
      ["routine", "Thường"],
    ]);
    const bars = (section: string) =>
      [...document.querySelectorAll<HTMLElement>(`section[aria-labelledby="${section}"] [data-testid="bar-row"]`)].map((r) => text(r.firstElementChild));
    expect(bars("decided-by")).toStrictEqual(["__proto__", "constructor"]);
    expect(bars("e1-split")).toStrictEqual(["toString", "Lý do khác"]);
    noLeak();
  });

  it("Chính sách (tab Bảng): hằng số khoá '__proto__' / 'constructor' → nhãn là chính khoá; luật type 'constructor' / '__proto__' → 'Không hợp lệ'", async () => {
    const content = JSON.parse(
      '{"constants": {"__proto__": 1, "constructor": 2, "SLA_MINUTES": 30}, "rules": [' +
        '{"id": "R1", "type": "constructor"}, {"id": "R2", "type": "__proto__"}, {"id": "R3", "type": "toString"}, {"id": "R4", "type": "allow"}]}',
    ) as Record<string, unknown>;
    stubFetch(policyRoutes({ current: () => view({ content }) }));
    renderAt("/policy");
    await waitFor(() => expect(screen.getAllByTestId("constant-row")).toHaveLength(3));
    const rows = screen.getAllByTestId("constant-row");
    expect(rows.map((r) => [r.dataset.key, text(r.querySelector("span > span"))])).toStrictEqual([
      ["__proto__", "__proto__"],
      ["constructor", "constructor"],
      ["SLA_MINUTES", "Hạn duyệt (phút)"],
    ]);
    const rules = screen.getAllByTestId("rule-row").map((r) => text(r.lastElementChild));
    expect(rules).toStrictEqual(["Không hợp lệ (constructor)", "Không hợp lệ (__proto__)", "Không hợp lệ (toString)", "Cho phép"]);
    for (const r of screen.getAllByTestId("rule-row").slice(0, 3)) expect(r.lastElementChild!.className).toContain("text-danger");
    noLeak();
  });
});
