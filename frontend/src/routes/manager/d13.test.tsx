// D13 bước 4 — số đếm tử/mẫu ở Tổng quan (min_sample, counts của backend 3ec275b) + khối "Cảnh báo đang mở" theo khung
// giờ (`/api/alerts?from&to`) + ghi chú cửa sổ đo của luật 1. Không gọi backend: fetch giả trả đúng hình dạng route thật
// (backend/app/api/dashboard.py `BusinessAll` + `BusinessAllCounts`, api/alerts.py). Mỗi test ghi phép tính tay.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { listAlerts } from "../../api/alerts.ts";
import { parseBusiness } from "../../api/dashboard.ts";
import { ApiError } from "../../api/errors.ts";
import type { AlertItem, AlertList, BusinessCountedTam, BusinessCountsTam, BusinessMetrics, Me } from "../../api/types.ts";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { RequirePerm } from "../../auth/RequireAuth.tsx";
import { Alerts } from "./Alerts.tsx";
import { DashboardPage } from "./DashboardPage.tsx";
import { countedRateText, rule1WindowNote, UNAVAILABLE_TEXT } from "./metrics.ts";

// U+00A0 (NBSP) giữa số và "%" như formatRate in — KHÔNG phải dấu cách thường (bản trước lỡ là U+0020 → 6 test đỏ).
const NBSP = " ";
const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  for (const client of clients.splice(0)) client.clear();
});

// ------------------------------------------------------------------------------------------------ dựng chung

const MGR: Me = {
  user_id: "it_mgr01",
  role: "manager",
  permissions: ["ticket:create", "ticket:read:own", "ticket:read:any", "approval:decide", "policy:read", "dashboard:read:all", "alert:read"],
};

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
type Call = { method: string; url: string };
type Handler = (method: string, url: string) => Response | Promise<Response | undefined> | undefined;

function stubFetch(route: Handler): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({ method, url });
      return (await route(method, url)) ?? json(404, { detail: "not_found" });
    }),
  );
  return calls;
}

const signedIn = (me: Me): AuthValue => ({ state: { status: "signedIn", me }, signIn: vi.fn(), signOut: vi.fn(async () => true) });

function renderAt(path: "/dashboard" | "/alerts") {
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthContext value={signedIn(MGR)}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/dashboard" element={<RequirePerm perm="dashboard:read:all"><DashboardPage /></RequirePerm>} />
            <Route path="/alerts" element={<RequirePerm perm="alert:read"><Alerts /></RequirePerm>} />
          </Routes>
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
  return client;
}

const pathOf = (url: string) => new URL(url, "http://x").pathname;
const queryOf = (url: string) => new URL(url, "http://x").searchParams;
const alertGets = (calls: Call[]) => calls.filter((c) => c.method === "GET" && pathOf(c.url) === "/api/alerts");
const kpi = (name: string) => screen.getAllByTestId("kpi").find((el) => el.dataset.metric === name)!;
const kpiValue = (name: string) => within(kpi(name)).getByTestId("kpi-value").textContent;
const group = (key: string) => screen.getAllByTestId("weighted-group").find((el) => el.dataset.key === key)!;

// ------------------------------------------------------------------------------------------------ dữ liệu

const METRICS: BusinessMetrics = {
  automation_rate: 0.63,
  escalation_rate_raw: 0.16,
  escalation_rate_weighted: { raw: 0.16, weighted: 0.142, by_group: { routine: 0.1, approval: 0.25, sensitive: null }, sensitivity: { "60/30/10": 0.142 } },
  deflection_rate: 0.21,
  approval_expired_count: 0,
  decided_by_distribution: { rule: 10, llm: 3 },
  top_matched_rules: [],
  override_count: 0,
  e1_split: { total: 0, counts: {}, shares: {} },
  e3_cases: { items: [], truncated: false },
};
/** Thân của backend TRƯỚC D13 (không min_sample, không counts). */
const OLD: BusinessCountedTam = { from: "2026-09-24T17:00:00Z", to: "2026-10-01T05:05:09.123000Z", unavailable: [], scope: "all", metrics: METRICS };

/**
 * Thân D13 nhất quán: mọi tỉ lệ chung mẫu số `den` (#lá đã kết thúc), weighted = trung bình trọng số 70/20/10 chuẩn hoá
 * lại trên nhóm có lá (backend `weigh`). `groups`: [tử, mẫu] của routine / approval / sensitive.
 */
function counted(automated: number, escalated: number, deflected: number, groups: Record<string, [number, number]>, weighted: number | null): BusinessCountedTam {
  const W: Record<string, number> = { routine: 0.7, approval: 0.2, sensitive: 0.1 };
  const den = Object.values(groups).reduce((s, [, d]) => s + d, 0);
  const rate = (n: number, d: number) => (d === 0 ? null : n / d);
  const counts: BusinessCountsTam = {
    automation_rate: { num: automated, den },
    escalation_rate_raw: { num: escalated, den },
    escalation_rate_weighted: { den, by_group: Object.fromEntries(Object.entries(groups).map(([g, [num, d]]) => [g, { num, den: d, weight: W[g]! }])) },
    deflection_rate: { num: deflected, den },
  };
  return {
    ...OLD,
    min_sample: 20,
    counts,
    metrics: {
      ...METRICS,
      automation_rate: rate(automated, den),
      escalation_rate_raw: rate(escalated, den),
      escalation_rate_weighted: {
        raw: rate(escalated, den),
        weighted,
        by_group: Object.fromEntries(Object.entries(groups).map(([g, [num, d]]) => [g, rate(num, d)])),
        sensitivity: { "60/30/10": weighted, "80/15/5": weighted },
      },
      deflection_rate: rate(deflected, den),
    },
  };
}

function alert(alert_id: number, rule_id: string, over: Partial<AlertItem> = {}): AlertItem {
  return {
    alert_id,
    rule_id,
    subject: "",
    severity: "warning",
    value: null,
    window_start: "2026-09-30T17:00:00Z",
    status: "open",
    detail: {},
    audience: ["manager"],
    acked_by: null,
    acked_at: null,
    created_at: "2026-09-30T17:05:00Z",
    ...over,
  };
}

function server(business: () => unknown = () => counted(13, 4, 4, { routine: [2, 15], approval: [2, 5], sensitive: [0, 0] }, 0.2), alerts: () => AlertList = () => ({ items: [], truncated: false })) {
  return stubFetch((method, url) => {
    const path = pathOf(url);
    if (path === "/api/dashboard/business") return json(200, business());
    if (path === "/api/alerts" && method === "GET") return json(200, alerts());
    return undefined;
  });
}

// ------------------------------------------------------------------------------------------------ tỉ lệ đơn

describe("D13: tỉ lệ đơn 'x % (a/b)', mẫu < min_sample → 'chưa đủ dữ liệu (n=b)'", () => {
  it("biên den 20 / 19 với min_sample 20", () => {
    // 13/20 = 0,65 → "65 %"; den 20 ≥ 20 → hiện %.
    expect(countedRateText("automation_rate", 0.65, { num: 13, den: 20 }, 20, [])).toStrictEqual({ state: "value", text: `65${NBSP}% (13 trên 20 ca)`, note: null });
    // 13/19 ≈ 0,684 nhưng den 19 < 20 → KHÔNG hiện %.
    const small = countedRateText("automation_rate", 13 / 19, { num: 13, den: 19 }, 20, []);
    expect(small).toStrictEqual({ state: "insufficient", text: "chưa đủ dữ liệu (mới có 19 ca)", note: null });
  });

  it("mẫu 0 → tỉ lệ null: 'chưa đủ dữ liệu (mới có 0 ca)', không '0 %', không '—'", () => {
    // 0/0: backend trả tỉ lệ null; den 0 < 20.
    const m = countedRateText("deflection_rate", null, { num: 0, den: 0 }, 20, []);
    expect(m.text).toBe("chưa đủ dữ liệu (mới có 0 ca)");
    expect(m.text).not.toContain("%");
    expect(m.text).not.toContain("—");
  });

  it("thiếu counts hoặc min_sample (backend cũ) → như trước: chỉ %; unavailable thắng", () => {
    // 0,65 → "65 %", không "(a/b)".
    expect(countedRateText("automation_rate", 0.65, undefined, 20, []).text).toBe(`65${NBSP}%`);
    expect(countedRateText("automation_rate", 0.65, { num: 13, den: 20 }, undefined, []).text).toBe(`65${NBSP}%`);
    expect(countedRateText("automation_rate", undefined, null, 20, ["automation_rate"]).text).toBe(UNAVAILABLE_TEXT);
  });

  it("màn Tổng quan: den 20 → '% (a/b)'; den 19 → 'chưa đủ dữ liệu (mới có 19 ca)' ở cả 3 ô tỉ lệ đơn", async () => {
    // den = 15 + 5 + 0 = 20. Tự xử lý 13/20 = 0,65; trả lời tài liệu 4/20 = 0,2; thô 4/20 = 0,2.
    server(() => counted(13, 4, 4, { routine: [3, 15], approval: [1, 5], sensitive: [0, 0] }, 0.2));
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect(kpiValue("automation_rate")).toBe(`65${NBSP}% (13 trên 20 ca)`);
    expect(kpiValue("deflection_rate")).toBe(`20${NBSP}% (4 trên 20 ca)`);
    expect(kpi("escalation_rate_weighted").textContent).toContain(`chưa trọng số 20${NBSP}% (4 trên 20 ca)`);
    cleanup();
    // den = 14 + 5 + 0 = 19 < 20.
    server(() => counted(13, 3, 4, { routine: [2, 14], approval: [1, 5], sensitive: [0, 0] }, 0.15));
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect(kpiValue("automation_rate")).toBe("chưa đủ dữ liệu (mới có 19 ca)");
    expect(kpiValue("deflection_rate")).toBe("chưa đủ dữ liệu (mới có 19 ca)");
    expect(kpi("escalation_rate_weighted").textContent).toContain("chưa trọng số chưa đủ dữ liệu (mới có 19 ca)");
    expect(kpi("automation_rate").dataset.state).toBe("insufficient");
  });

  it("backend cũ (không min_sample/counts) → màn chạy như trước: '63 %', không '(a/b)'", async () => {
    server(() => OLD);
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect(kpiValue("automation_rate")).toBe(`63${NBSP}%`);
    expect(kpiValue("escalation_rate_weighted")).toBe(`14,2${NBSP}%`);
    // Không "(a/b)" ở ô nào. Không soi mọi dấu "/": gợi ý trọng số (sr-only, N-NGU) có "70/20/10".
    expect(screen.getAllByTestId("kpi").map((el) => el.textContent).join(" ")).not.toMatch(/\(\d[\d.]*\/\d[\d.]*\)/);
    expect(group("routine").textContent).toContain(`10${NBSP}%`);
  });
});

// ------------------------------------------------------------------------------------------------ weighted

describe("D13: weighted — 'chưa đủ dữ liệu' theo den TỔNG; từng nhóm a/b, nhóm den < min_sample không %", () => {
  it("den tổng 19 → KPI 'chưa đủ dữ liệu (mới có 19 ca)', độ nhạy không số; nhóm chỉ a/b", async () => {
    // den = 14 + 5 + 0 = 19 < 20.
    server(() => counted(10, 3, 2, { routine: [2, 14], approval: [1, 5], sensitive: [0, 0] }, 0.15));
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect(kpiValue("escalation_rate_weighted")).toBe("chưa đủ dữ liệu (mới có 19 ca)");
    expect(screen.getByTestId("weighted-sensitivity").textContent).toBe("Nếu đổi tỉ lệ trọng số: chưa đủ dữ liệu");
    expect(group("routine").textContent).toBe("Thường2 trên 14 ca");
    expect(group("approval").textContent).toBe("Cần duyệt1 trên 5 ca");
    expect(group("sensitive").textContent).toBe("Nhạy cảm0 trên 0 ca");
  });

  it("den tổng 20 → KPI hiện % weighted + n=20; nhóm 15 và 5 lá vẫn < 20 → chỉ a/b", async () => {
    // routine 3/15 = 0,2; approval 1/5 = 0,2; sensitive 0 lá (bỏ khỏi chuẩn hoá).
    // weighted = (0,7·0,2 + 0,2·0,2) / (0,7 + 0,2) = 0,2 → "20 %". den = 15 + 5 + 0 = 20 ≥ 20.
    server(() => counted(13, 4, 4, { routine: [3, 15], approval: [1, 5], sensitive: [0, 0] }, 0.2));
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect(kpiValue("escalation_rate_weighted")).toBe(`20${NBSP}%`);
    expect(kpi("escalation_rate_weighted").textContent).toContain("trên 20 ca");
    expect(screen.getByTestId("weighted-sensitivity").textContent).toContain(`60/30/10 → 20${NBSP}%`);
    expect(group("routine").textContent).toBe("Thường3 trên 15 ca");
    expect(group("approval").textContent).toBe("Cần duyệt1 trên 5 ca");
  });

  it("nhóm đủ mẫu (20 lá) → '% (a/b)'; nhóm 5 lá → a/b; nhóm 0 lá (by_group null) → '0/0', không %", async () => {
    // den = 20 + 5 + 0 = 25. routine 5/20 = 0,25 → "25 % (5 trên 20 ca)"; approval 0/5 = 0 nhưng 5 < 20 → "0/5".
    // weighted = (0,7·0,25 + 0,2·0) / 0,9 ≈ 0,1944 → "19,4 %".
    server(() => counted(15, 5, 5, { routine: [5, 20], approval: [0, 5], sensitive: [0, 0] }, 0.7 * 0.25 / 0.9));
    renderAt("/dashboard");
    await screen.findAllByTestId("kpi");
    expect(kpiValue("escalation_rate_weighted")).toBe(`19,4${NBSP}%`);
    expect(group("routine").textContent).toBe(`Thường25${NBSP}% (5 trên 20 ca)`);
    expect(group("approval").textContent).toBe("Cần duyệt0 trên 5 ca");
    expect(group("sensitive").textContent).toBe("Nhạy cảm0 trên 0 ca");
    expect(group("sensitive").textContent).not.toContain("%");
  });
});

// ------------------------------------------------------------------------------------------------ parseBusiness

describe("D13: parseBusiness kiểm min_sample / counts KHI CÓ MẶT; thiếu → vẫn qua (backend cũ)", () => {
  const GOOD = counted(13, 4, 4, { routine: [3, 15], approval: [1, 5], sensitive: [0, 0] }, 0.2);
  const is502 = (body: unknown) => {
    try {
      parseBusiness(body);
      return false;
    } catch (e) {
      return e instanceof ApiError && e.status === 502 && e.code === "invalid_dashboard_body";
    }
  };
  const withCount = (key: string, value: unknown) => ({ ...GOOD, counts: { ...GOOD.counts, [key]: value } });

  it("thân đúng → trả nguyên; counts khoá null (pending) → qua; thiếu min_sample/counts → qua", () => {
    expect(parseBusiness(GOOD)).toStrictEqual(GOOD);
    expect(parseBusiness(withCount("deflection_rate", null)).counts?.deflection_rate).toBeNull();
    expect(parseBusiness(OLD)).toStrictEqual(OLD);
  });

  it.each([
    ["num > den (5 trên 4 ca)", withCount("automation_rate", { num: 5, den: 4 })],
    ["den âm", withCount("automation_rate", { num: 0, den: -1 })],
    ["den lẻ 2.5", withCount("deflection_rate", { num: 1, den: 2.5 })],
    ["thiếu num", withCount("escalation_rate_raw", { den: 20 })],
    ["min_sample là chuỗi", { ...GOOD, min_sample: "20" }],
    ["min_sample 0", { ...GOOD, min_sample: 0 }],
    ["min_sample null", { ...GOOD, min_sample: null }],
    ["counts là mảng", { ...GOOD, counts: [] }],
    ["counts null", { ...GOOD, counts: null }],
    ["weighted thiếu den", withCount("escalation_rate_weighted", { by_group: {} })],
    ["by_group thiếu weight", withCount("escalation_rate_weighted", { den: 5, by_group: { routine: { num: 1, den: 5 } } })],
    ["by_group num > den", withCount("escalation_rate_weighted", { den: 5, by_group: { routine: { num: 6, den: 5, weight: 0.7 } } })],
  ])("%s → 502 invalid_dashboard_body", (_name, body) => {
    expect(is502(body)).toBe(true);
  });
});

// ------------------------------------------------------------------------------------------------ cảnh báo theo khung

describe("D13: khối 'Cảnh báo đang mở' gọi /api/alerts với from/to của khung đang chọn", () => {
  const NOW = new Date("2026-10-01T05:05:09.123Z"); // 12:05:09 giờ VN 01/10

  it("listAlerts: có khung → status=open&from&to (đã encode); không khung → URL như cũ", async () => {
    const calls = stubFetch(() => json(200, { items: [], truncated: false }));
    await listAlerts("open", { from: "2026-10-01T00:00:00.000+07:00", to: "2026-10-01T12:05:09.123+07:00" });
    await listAlerts("open");
    await listAlerts("all");
    // ":" → %3A, "+" → %2B (không encode thì "+" thành dấu cách ở server → 422).
    expect(calls.map((c) => c.url)).toStrictEqual([
      "/api/alerts?status=open&from=2026-10-01T00%3A00%3A00.000%2B07%3A00&to=2026-10-01T12%3A05%3A09.123%2B07%3A00",
      "/api/alerts?status=open",
      "/api/alerts",
    ]);
  });

  it("Tổng quan: 7 ngày → from 25/09 00:00 VN, to = bây giờ; đổi 'Hôm nay' → request mới from 01/10 00:00 VN", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const calls = server();
    renderAt("/dashboard");
    await screen.findByTestId("open-alerts");
    await waitFor(() => expect(alertGets(calls)).toHaveLength(1));
    // 7 ngày: 00:00 VN của 01/10 − 6 ngày = 25/09; to = 05:05:09.123Z + 7 giờ = 12:05:09.123 VN.
    const first = queryOf(alertGets(calls)[0]!.url);
    expect([...first.keys()]).toStrictEqual(["status", "from", "to"]);
    expect([first.get("status"), first.get("from"), first.get("to")]).toStrictEqual(["open", "2026-09-25T00:00:00.000+07:00", "2026-10-01T12:05:09.123+07:00"]);
    fireEvent.click(screen.getByRole("tab", { name: "Hôm nay" }));
    await waitFor(() => expect(alertGets(calls)).toHaveLength(2));
    // Hôm nay: from = 00:00 VN 01/10.
    expect(queryOf(alertGets(calls)[1]!.url).get("from")).toBe("2026-10-01T00:00:00.000+07:00");
  });

  it("màn /alerts không đổi: không gửi from/to", async () => {
    const calls = server();
    renderAt("/alerts");
    await waitFor(() => expect(alertGets(calls)).toHaveLength(1));
    expect(alertGets(calls)[0]!.url).toBe("/api/alerts?status=open");
  });

  it("'Đã xem' trong khối → cảnh báo rời khối NGAY bằng cache ['alerts','open','7d'] (trước khi tải lại về)", async () => {
    const items = [alert(11, "drift"), alert(12, "e9_spike")];
    let hold: Promise<void> | null = null;
    let release: () => void = () => {};
    stubFetch(async (method, url) => {
      const path = pathOf(url);
      if (path === "/api/dashboard/business") return json(200, OLD);
      if (path === "/api/alerts" && method === "GET") {
        if (hold) await hold;
        return json(200, { items, truncated: false });
      }
      if (path === "/api/alerts/11/ack" && method === "POST") return json(200, { ...items[0]!, status: "acked", acked_by: "it_mgr01", acked_at: "2026-10-01T05:10:00Z" });
      return undefined;
    });
    const client = renderAt("/dashboard");
    const block = await screen.findByTestId("open-alerts");
    await waitFor(() => expect(within(block).getAllByTestId("alert-row")).toHaveLength(2));
    hold = new Promise<void>((r) => (release = r)); // GET tải lại sau ack bị giữ → chỉ cache mới gỡ được dòng
    const row11 = within(block).getAllByTestId("alert-row").find((r) => r.dataset.alertId === "11")!;
    fireEvent.click(within(row11).getByRole("button", { name: "Đã xem" }));
    await waitFor(() => expect(within(block).getAllByTestId("alert-row").map((r) => r.dataset.alertId)).toStrictEqual(["12"]));
    expect(client.getQueryData<AlertList>(["alerts", "open", "7d"])!.items.map((a) => a.alert_id)).toStrictEqual([12]);
    release();
  });
});

// ------------------------------------------------------------------------------------------------ luật 1

describe("D13: ghi chú cửa sổ đo của luật 1 (rules.py rolling_7d_window: [window_start − days, window_start))", () => {
  it("window_start 30/09 17:00Z (= 00:00 VN 01/10), days 7 → 24/09–30/09", () => {
    // đầu = 30/09 17:00Z − 7 ngày = 23/09 17:00Z = 00:00 VN 24/09; cuối = 01/10 00:00 VN − 1 ms = 30/09 23:59 VN.
    expect(rule1WindowNote(alert(1, "escalation_rate_high", { detail: { weighted: 0.45, raw: 0.3, threshold: 0.4, days: 7 } }))).toBe(
      "Đo trên 7 ngày trọn 24/09–30/09 (giờ VN), không theo khoảng đang chọn.",
    );
  });

  it("luật khác → không ghi chú; thiếu / sai days → câu chung không ngày", () => {
    expect(rule1WindowNote(alert(2, "drift", { detail: { days: 7 } }))).toBeNull();
    const generic = rule1WindowNote(alert(3, "escalation_rate_high"));
    // N-NGU: không hiện số hiệu nội bộ "Luật 1" — dòng ghi chú nằm ngay dưới cảnh báo đó.
    expect(generic).toBe("Đo trên các ngày trọn (giờ VN) trước ngày ghi cảnh báo, không theo khoảng đang chọn.");
    expect(rule1WindowNote(alert(4, "escalation_rate_high", { detail: { days: "7" } }))).toBe(generic);
    expect(rule1WindowNote(alert(5, "escalation_rate_high", { detail: { days: 0 } }))).toBe(generic);
    expect(rule1WindowNote(alert(6, "escalation_rate_high", { detail: { days: 1e15 } }))).toBe(generic); // ngoài miền Date
  });

  it("khối Tổng quan: dòng ghi chú nằm ngay sau cảnh báo luật 1, cảnh báo khác không có", async () => {
    server(undefined, () => ({ items: [alert(21, "escalation_rate_high", { detail: { days: 7 } }), alert(22, "drift", { severity: "info" })], truncated: false }));
    renderAt("/dashboard");
    const block = await screen.findByTestId("open-alerts");
    const note = await within(block).findByTestId("rule1-window-note");
    expect(within(block).getAllByTestId("rule1-window-note")).toHaveLength(1);
    expect((note.previousElementSibling as HTMLElement).dataset.alertId).toBe("21");
    expect(note.textContent).toContain("24/09–30/09");
  });
});
