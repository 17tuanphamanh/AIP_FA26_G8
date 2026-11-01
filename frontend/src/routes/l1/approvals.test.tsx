// F4 — L1: hộp thư duyệt, chi tiết phiếu, quyết định, ghi đè. Không gọi backend: fetch giả trả đúng dạng spec
// (phase4-thiet-ke-chi-tiet.md 1.0: 4c P5 hộp thư, P6 xem phiếu, 4d P1–P4 ghi đè; backend/app/api/approvals.py decision).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { INBOX_REFRESH_MS, inboxRefetchInterval, listApprovals, overrideTicket } from "../../api/approvals.ts";
import { type AuthChannel, createClient } from "../../api/client.ts";
import { errorMessage, ApiError, GENERIC_LOGIN_ERROR } from "../../api/errors.ts";
import { offsetFrom, recordServerDate, serverNow } from "../../api/serverClock.ts";
import type {
  ApprovalAffected,
  ApprovalListItem,
  ApprovalRiskView,
  ApprovalStatus,
  ApprovalViewP4,
  Me,
  OverrideIn,
} from "../../api/types.ts";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { AuthProvider } from "../../auth/AuthProvider.tsx";
import { RequirePerm } from "../../auth/RequireAuth.tsx";
import { useAuth } from "../../auth/useAuth.ts";
import { ActionView, FlatTable, RAW_NOTE, SHOW_RAW_TEXT } from "../../components/ActionView.tsx";
import { FlashNotice } from "../../components/FlashNotice.tsx";
import { OverrideDialog } from "../../components/OverrideDialog.tsx";
import { ApprovalDetailRoute } from "./ApprovalDetail.tsx";
import { ApprovalQueue } from "./ApprovalQueue.tsx";
import {
  ACTION_UNKNOWN,
  actionLabel,
  BACKUP_TEXT,
  DECISION_SENT,
  decisionRole,
  deadlineText,
  INBOX_COUNT_STALE_TEXT,
  INBOX_STALE_TEXT,
  isShortValue,
  isUrgent,
  managerText,
  MANAGER_UNKNOWN_TEXT,
  NOTICES_TEXT,
  OVERRIDE_DONE,
  OVERRIDE_FORBIDDEN,
  OVERRIDE_NOT_FOUND,
  OVERRIDE_NOTE_INVALID,
  overrideBody,
  overrideErrorMessage,
  PLAN_CHANGED_TEXT,
  isReflex,
  readonlyText,
  REFLEX_MIN_SECONDS,
  reflexText,
  remainingShort,
  RISK_MISSING_TEXT,
  riskSummary,
  UNCALIBRATED_TEXT,
  SHORT_VALUE_MAX,
  sortByDeadline,
  TICKET_UNAVAILABLE,
  VIEW_NOT_FOUND_TEXT,
  viewedSeconds,
  VIEWER_TEXT,
} from "./inbox.ts";
import { TicketOverrideRoute } from "./TicketOverride.tsx";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear(); // dừng nhịp tự tải lại trước khi gỡ fetch giả
  vi.useRealTimers();
  recordServerDate(new Headers()); // độ lệch giờ máy chủ về 0 cho test sau
});

const MIN = 60_000;
const T0 = Date.parse("2026-09-30T14:00:00Z");
const at = (minutes: number) => new Date(T0 + minutes * MIN).toISOString();

const L1: Me = {
  user_id: "l1_01",
  role: "l1",
  permissions: ["approval:decide", "decision:override", "escalation:handle", "ticket:create", "ticket:read:any"],
};
const L2: Me = { user_id: "l2_01", role: "l2", permissions: ["escalation:handle", "ticket:create", "ticket:read:any", "kb:edit"] };

function listItem(id: string, over: Partial<ApprovalListItem> = {}): ApprovalListItem {
  return {
    approval_id: id,
    ticket_id: `0f4e2a6c-9b1d-4c7e-8a3f-${id.padStart(12, "0")}`,
    status: "pending",
    created_at: at(-10),
    deadline: at(20),
    reminder_1_at: null,
    reminder_2_at: null,
    role_as: "primary",
    action_type: "renew_vpn_cert",
    device_id: "LAP-0342",
    ...over,
  };
}

// Action lồng nhiều tầng (object trong object, mảng, object/mảng rỗng, null) — Bảng phải trải ĐỦ mọi khoá.
const NESTED_ACTION = {
  type: "renew_vpn_cert",
  target: "device:LAP-0342",
  requested_for: "nv001",
  reversible: true,
  params: { device_id: "LAP-0342", window: { from: "22:00", to: null }, tags: ["vpn", { level: 2 }], empty: {} },
  facts: { device_registered: true, cert_days_to_expiry: -3, history: [] },
};

// F6 #76: người bị tác động (chính người gửi, sếp có tên) + RiskDecision của luật + 2 cờ suy ra.
const AFFECTED: ApprovalAffected = {
  user_id: "nv001",
  is_requester: true,
  department: "Finance",
  manager: { status: "known", user_id: "mgr01", full_name: "Lê Thị Hạnh" },
};
const RISK_VIEW: ApprovalRiskView = {
  decided_by: "rule",
  policy_decision: "approval_required",
  matched_rule_id: "R18",
  raw_prob: null,
  calibrated_prob: null,
  p_method: null,
  risk_level: "medium",
  route: "HITL",
  reason: "Ngoài giờ hành chính",
  thresholds: null,
  calibrated: false,
  auto_allowed: false,
};

function viewOf(id: string, over: Partial<ApprovalViewP4> = {}): ApprovalViewP4 {
  return {
    approval_id: id,
    ticket_id: `0f4e2a6c-9b1d-4c7e-8a3f-${id.padStart(12, "0")}`,
    status: "pending",
    deadline: at(20),
    requester: { role: "employee", department: "Finance" },
    request_summary: "VPN báo chứng chỉ hết hạn trên máy LAP-0342.",
    action: NESTED_ACTION,
    action_plan_hash: "9f2c7e5d1b8a4c3e6f0d2a9b7c5e1f3a8d6b4c2e0f9a7b5c3d1e8f6a4b2c0e41",
    risk: { decided_by: "rule", matched_rule_id: "R18", reason: "Ngoài giờ hành chính", thresholds: null },
    facts: { cert_status: "expired" },
    role_as: "primary",
    procedure: { doc_id: "KB-VPN-004", title: "Gia hạn và cấp lại chứng chỉ VPN" },
    affected: AFFECTED,
    risk_view: RISK_VIEW,
    ...over,
  };
}

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
/** Thân hộp thư THẬT (4c `b457e6e`): `{items: [...]}`, không phải mảng trần. */
const inbox = (items: ApprovalListItem[], headers: Record<string, string> = {}) => json(200, { items }, headers);

type Call = { method: string; url: string; body: string | null; auth: string | null };
type Route = (method: string, url: string) => Response | Promise<Response> | undefined;

function stubFetch(route: Route): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({ method, url, body: typeof init.body === "string" ? init.body : null, auth: new Headers(init.headers).get("Authorization") });
      return (await route(method, url)) ?? json(404, { detail: "not_found" });
    }),
  );
  return calls;
}

const posts = (calls: Call[], suffix: string) => calls.filter((c) => c.method === "POST" && c.url.endsWith(suffix));

/** F6 P3: xem phiếu dưới REFLEX_MIN_SECONDS mà bấm "Đồng ý" → hộp hỏi lại. Test của luồng gửi (F4) mô phỏng người duyệt
 *  ĐÃ xem đủ lâu: dời `performance.now` (đồng hồ chống phản xạ) lên trước, vẫn đơn điệu. Gỡ sau mỗi test (restoreMocks). */
function viewedLongEnough(seconds = REFLEX_MIN_SECONDS) {
  const real = performance.now.bind(performance);
  vi.spyOn(performance, "now").mockImplementation(() => real() + seconds * 1000);
}

const signedIn = (me: Me): AuthValue => ({
  state: { status: "signedIn", me },
  signIn: vi.fn(),
  signOut: vi.fn(async () => true),
});

function renderAt(path: string, me: Me = L1) {
  const client = new QueryClient();
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <AuthContext value={signedIn(me)}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/approvals" element={<ApprovalQueue />} />
            <Route path="/approvals/ticket/:ticketId" element={<TicketOverrideRoute />} />
            <Route path="/approvals/:approvalId" element={<ApprovalDetailRoute />} />
          </Routes>
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
}

const rowIds = () => [...document.querySelectorAll<HTMLElement>('[data-testid="inbox-row"]')].map((r) => r.dataset.approvalId);

// ------------------------------------------------------------------------------------------------ t39

describe("t39: hộp thư sắp theo deadline tăng dần ở client", () => {
  const a = listItem("a", { deadline: at(5), created_at: at(-25) });
  const b = listItem("b", { deadline: at(12), role_as: "backup", reminder_1_at: at(-3), reminder_2_at: at(-1) });
  const c = listItem("c", { deadline: at(30), created_at: at(0), reminder_1_at: at(-2) });

  it("sortByDeadline: hạn gần nhất trước; hạn hỏng xuống cuối; không đổi mảng gốc", () => {
    const server = [c, a, b, listItem("x", { deadline: "không phải ngày" })];
    expect(sortByDeadline(server).map((i) => i.approval_id)).toStrictEqual(["a", "b", "c", "x"]);
    expect(server.map((i) => i.approval_id)).toStrictEqual(["c", "a", "b", "x"]);
  });

  it("màn hộp thư: server trả lộn thứ tự → dòng theo hạn; 'Chờ duyệt · 3'; dự phòng có huy hiệu; có dấu nhắc", async () => {
    const calls = stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? inbox([c, a, b]) : undefined));
    renderAt("/approvals");
    await screen.findAllByTestId("inbox-row");
    expect(rowIds()).toStrictEqual(["a", "b", "c"]);
    expect(screen.getByRole("tab", { name: /^Chờ duyệt/ }).textContent).toBe("Chờ duyệt · 3");
    const rows = screen.getAllByTestId("inbox-row");
    expect(within(rows[1]!).getByTestId("backup-badge").textContent).toBe("Dự phòng");
    expect(within(rows[0]!).queryByTestId("backup-badge")).toBeNull();
    expect(within(rows[1]!).getByTestId("reminder-mark").textContent).toContain("Đã nhắc 2");
    expect(within(rows[2]!).getByTestId("reminder-mark").textContent).toContain("Đã nhắc 1");
    expect(within(rows[0]!).queryByTestId("reminder-mark")).toBeNull();
    expect(rows[0]!.textContent).toContain("Cấp lại chứng chỉ VPN");
    expect(rows[0]!.textContent).toContain("LAP-0342");
    expect(calls.map((c) => c.url)).toContain("/api/approvals?mine=1&status=pending");
    // Không nút duyệt nào ở danh sách — chỉ ở chi tiết phiếu.
    expect(screen.queryByRole("button", { name: /Đồng ý|Từ chối/ })).toBeNull();
  });

  it("tab Đã quyết = approved + rejected (2 lời gọi), vẫn sắp theo hạn", async () => {
    const approved = listItem("p", { status: "approved", deadline: at(-60) });
    const rejected = listItem("q", { status: "rejected", deadline: at(-90) });
    const calls = stubFetch((_method, url) => {
      if (url.endsWith("status=pending")) return inbox([]);
      if (url.endsWith("status=approved")) return inbox([approved]);
      if (url.endsWith("status=rejected")) return inbox([rejected]);
      return undefined;
    });
    renderAt("/approvals");
    await screen.findByText("Không có phiếu nào chờ bạn duyệt");
    fireEvent.click(screen.getByRole("tab", { name: "Đã quyết" }));
    await waitFor(() => expect(rowIds()).toStrictEqual(["q", "p"]));
    expect(screen.getAllByTestId("inbox-time").map((t) => t.textContent)).toStrictEqual(["Đã từ chối", "Đã đồng ý"]);
    expect(calls.map((c) => c.url)).toEqual(
      expect.arrayContaining(["/api/approvals?mine=1&status=approved", "/api/approvals?mine=1&status=rejected"]),
    );
  });
});

// ------------------------------------------------------------------------------------------------ t40

describe("t40: đồng hồ dùng giờ máy chủ = giờ máy + độ lệch từ header Date", () => {
  it("offsetFrom / recordServerDate / serverNow", () => {
    const server = new Date(T0).toUTCString();
    expect(offsetFrom(server, T0 + 10 * MIN)).toBe(-10 * MIN);
    expect(offsetFrom(null, T0)).toBe(0);
    expect(offsetFrom("không phải ngày", T0)).toBe(0);
    recordServerDate(new Headers({ Date: server }), T0 + 10 * MIN);
    expect(serverNow(T0 + 10 * MIN)).toBe(T0);
    recordServerDate(new Headers(), T0 + 10 * MIN); // response gần nhất thiếu Date → độ lệch 0
    expect(serverNow(T0 + 10 * MIN)).toBe(T0 + 10 * MIN);
  });

  const item = listItem("d", { created_at: at(-25), deadline: at(5) });

  it("giờ máy nhanh 10 phút + header Date đúng giờ máy chủ → vẫn 'còn 5 phút', đỏ (còn 5/30)", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: T0 + 10 * MIN });
    stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? inbox([item], { Date: new Date(T0).toUTCString() }) : undefined));
    renderAt("/approvals");
    const time = await screen.findByTestId("inbox-time");
    expect(time.textContent).toBe("còn 5 phút");
    expect(screen.getByTestId("inbox-row").dataset.urgent).toBe("true");
  });

  it("thiếu header Date → độ lệch 0: giờ máy nhanh 10 phút thì thấy đã quá hạn", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: T0 + 10 * MIN });
    stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? inbox([item]) : undefined));
    renderAt("/approvals");
    expect((await screen.findByTestId("inbox-time")).textContent).toBe("đã quá hạn");
  });

  it("chi tiết: đồng hồ 'Còn mm:ss / 30 phút' theo giờ máy chủ", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: T0 - 7 * MIN });
    const date = { Date: new Date(T0).toUTCString() };
    stubFetch((_method, url) => {
      if (url === "/api/approvals/d") return json(200, viewOf("d", { deadline: at(5) }), date);
      if (url.startsWith("/api/approvals?")) return inbox([item], date);
      return undefined;
    });
    renderAt("/approvals/d");
    const pill = await screen.findByTestId("approval-deadline");
    await waitFor(() => expect(pill.textContent).toBe("Còn 05:00 / 30 phút"));
    expect(pill.dataset.urgent).toBe("true");
    expect(remainingShort(at(5), serverNow())).toBe("còn 5 phút");
  });
});

// ------------------------------------------------------------------------------------------------ t41

describe("t41: ngưỡng đỏ 20% của (deadline − created_at)", () => {
  const created = at(0);
  const deadline = at(30); // tổng 30 phút → ngưỡng 6 phút
  it.each([
    ["dưới 20% (còn 5:59)", T0 + 24 * MIN + 1000, true],
    ["bằng 20% (còn đúng 6:00)", T0 + 24 * MIN, false],
    ["trên 20% (còn 7:00)", T0 + 23 * MIN, false],
    ["quá hạn", T0 + 31 * MIN, true],
  ])("%s", (_name, now, urgent) => {
    expect(isUrgent(created, deadline, now)).toBe(urgent);
  });
  it("không biết created_at / tổng ≤ 0 → không đỏ", () => {
    expect(isUrgent(null, deadline, T0 + 29 * MIN)).toBe(false);
    expect(isUrgent(deadline, created, T0)).toBe(false);
  });
});

// ------------------------------------------------------------------------------------------------ t42

/** Tập khoá của một giá trị JSON — viết RIÊNG ở test (không dùng flattenEntries của code) để so độc lập. */
function jsonKeyPaths(value: unknown, prefix = ""): string[] {
  if (Array.isArray(value)) return value.length ? value.flatMap((v, i) => jsonKeyPaths(v, `${prefix}[${i}]`)) : [prefix];
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value);
    return entries.length ? entries.flatMap(([k, v]) => jsonKeyPaths(v, prefix ? `${prefix}.${k}` : k)) : [prefix];
  }
  return [prefix];
}

describe("t42: Bảng và JSON cùng ĐỦ khoá của một action lồng nhau + mã băm đủ", () => {
  const EXPECTED = [
    "type",
    "target",
    "requested_for",
    "reversible",
    "params.device_id",
    "params.window.from",
    "params.window.to",
    "params.tags[0]",
    "params.tags[1].level",
    "params.empty",
    "facts.device_registered",
    "facts.cert_days_to_expiry",
    "facts.history",
  ];
  const HASH = viewOf("h").action_plan_hash;

  it("ActionView: tập khoá Bảng = tập khoá JSON = tập khoá object; JSON đúng JSON.stringify của object", () => {
    render(<ActionView action={NESTED_ACTION} hash={HASH} title="Cấp lại chứng chỉ VPN" />);
    const table = [...document.querySelectorAll<HTMLElement>('[data-testid="action-row"]')].map((r) => r.dataset.key);
    expect(new Set(table)).toStrictEqual(new Set(EXPECTED));
    expect(table).toHaveLength(EXPECTED.length); // không trùng, không thiếu
    const row = document.querySelector('[data-key="params.window.to"]')!;
    expect(row.querySelector("dd")?.textContent).toBe("null");
    expect(document.querySelector('[data-key="type"] [data-testid="raw-value"]')?.textContent).toBe('"renew_vpn_cert"');

    fireEvent.click(screen.getByRole("tab", { name: "JSON" }));
    const text = screen.getByTestId("action-json").textContent ?? "";
    expect(text).toBe(JSON.stringify(NESTED_ACTION, null, 2));
    expect(new Set(jsonKeyPaths(JSON.parse(text)))).toStrictEqual(new Set(table));
    expect(screen.getByTestId("action-hash").textContent).toBe(HASH);
    expect(HASH).toHaveLength(64);
  });

  it("màn chi tiết: đủ khối — yêu cầu, người gửi, căn cứ quy trình, rủi ro (khoá–giá trị), dữ kiện, hành động, hash", async () => {
    stubFetch((_method, url) => {
      if (url === "/api/approvals/h") return json(200, viewOf("h"));
      if (url.startsWith("/api/approvals?")) return inbox([listItem("h")]);
      return undefined;
    });
    renderAt("/approvals/h");
    expect((await screen.findByTestId("request-summary")).textContent).toBe("VPN báo chứng chỉ hết hạn trên máy LAP-0342.");
    expect(screen.getByTestId("procedure").textContent).toContain("Gia hạn và cấp lại chứng chỉ VPN");
    expect(screen.getAllByTestId("risk-row").map((r) => r.dataset.key)).toStrictEqual(["decided_by", "matched_rule_id", "reason", "thresholds"]);
    expect(screen.getAllByTestId("fact-row").map((r) => r.dataset.key)).toStrictEqual(["cert_status"]);
    expect(screen.getAllByTestId("action-row")).toHaveLength(EXPECTED.length);
    expect(screen.getByTestId("action-hash").textContent).toBe(HASH);
    expect(screen.getAllByText("Finance")).toHaveLength(2); // người gửi + người bị ảnh hưởng (cùng phòng ban)
    expect(screen.queryByTestId("backup-banner")).toBeNull();
    expect(screen.getByRole("button", { name: /^Đồng ý/ })).toBeTruthy();
  });

  it("không có tiêu đề quy trình → hiện doc_id; dự phòng → dải 'Bạn duyệt với vai trò dự phòng'", async () => {
    stubFetch((_method, url) => {
      if (url === "/api/approvals/k") return json(200, viewOf("k", { procedure: { doc_id: "KB-VPN-004", title: null }, role_as: "backup" }));
      if (url.startsWith("/api/approvals?")) return inbox([listItem("k", { role_as: "backup" })]);
      return undefined;
    });
    renderAt("/approvals/k");
    expect((await screen.findByTestId("procedure")).textContent).toBe("KB-VPN-004");
    expect(screen.getByTestId("backup-banner").textContent).toContain(BACKUP_TEXT);
  });
});

// ------------------------------------------------------------------------------------------------ t43

describe("t43: 409 plan_changed → chỉ một câu, không object, không nút", () => {
  it("không Bảng/JSON/hash, không nút nào, không tab; không hiện chữ nào của action", async () => {
    stubFetch((_method, url) => (url === "/api/approvals/pc" ? json(409, { detail: "plan_changed" }) : undefined));
    renderAt("/approvals/pc");
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe(PLAN_CHANGED_TEXT);
    expect(PLAN_CHANGED_TEXT).toBe("Hành động đã thay đổi sau khi tạo phiếu — không thể duyệt");
    expect(document.querySelectorAll("button")).toHaveLength(0);
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.queryByTestId("action-row")).toBeNull();
    expect(screen.queryByTestId("action-json")).toBeNull();
    expect(screen.queryByTestId("action-hash")).toBeNull();
    expect(document.body.textContent).not.toMatch(/renew_vpn_cert|LAP-0342|Mã băm/);
  });

  it("404 → 'Không tìm thấy phiếu hoặc phiếu không giao cho bạn', không nút", async () => {
    stubFetch(() => undefined); // mọi đường → 404 not_found
    renderAt("/approvals/khac");
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe(VIEW_NOT_FOUND_TEXT);
    expect(document.querySelectorAll("button")).toHaveLength(0);
  });

  it("phiếu không còn pending → chỉ đọc: không nút Đồng ý / Từ chối, hiện kết quả", async () => {
    stubFetch((_method, url) => {
      if (url === "/api/approvals/ok") return json(200, viewOf("ok", { status: "approved" }));
      if (url.startsWith("/api/approvals?")) return inbox([listItem("ok", { status: "approved" })]);
      return undefined;
    });
    renderAt("/approvals/ok");
    expect((await screen.findByTestId("approval-readonly")).textContent).toContain("đã đồng ý");
    expect(screen.getByTestId("approval-status").textContent).toBe("Đã đồng ý");
    expect(screen.queryByRole("button", { name: /Đồng ý|Từ chối/ })).toBeNull();
    expect(screen.getAllByTestId("action-row").length).toBeGreaterThan(0); // vẫn xem được đúng object
  });
});

// ------------------------------------------------------------------------------------------------ t44, t45

function detailApi(decision: () => Response | Promise<Response>) {
  return stubFetch((method, url) => {
    if (method === "POST" && url === "/api/approvals/r/decision") return decision();
    if (url === "/api/approvals/r") return json(200, viewOf("r"));
    if (url.startsWith("/api/approvals?")) return inbox([listItem("r")]);
    return undefined;
  });
}

describe("t44: từ chối thiếu lý do hoặc thiếu ghi chú → không gửi; đủ → body đúng dạng", () => {
  it("thiếu reason_code / note rỗng / note chỉ khoảng trắng → 0 request; đủ → 1 request đúng 4 khoá", async () => {
    const calls = detailApi(() => json(202, { approval_id: "r", ticket_id: "t", status: "accepted", notices: [] }));
    renderAt("/approvals/r");
    fireEvent.click(await screen.findByRole("button", { name: "Từ chối" }));
    const dialog = screen.getByRole("dialog", { name: "Từ chối yêu cầu" });
    const send = within(dialog).getByRole("button", { name: "Gửi từ chối" });
    const reason = within(dialog).getByLabelText("Lý do") as HTMLSelectElement;
    const note = within(dialog).getByLabelText("Lý do gửi người dùng") as HTMLTextAreaElement;
    expect([...reason.options].map((o) => o.value).filter(Boolean)).toStrictEqual([
      "missing_info",
      "not_authorized",
      "policy_violation",
      "duplicate",
      "wrong_device",
      "security_concern",
      "other",
    ]);

    fireEvent.change(note, { target: { value: "Sai máy" } }); // có ghi chú, chưa chọn lý do
    fireEvent.click(send);
    expect(within(dialog).getByRole("alert").textContent).toBe("Chọn lý do từ chối.");

    fireEvent.change(reason, { target: { value: "wrong_device" } });
    for (const value of ["", "   ", "\n\t "]) {
      fireEvent.change(note, { target: { value } });
      fireEvent.click(send);
      expect(within(dialog).getByRole("alert").textContent).toBe("Nhập lý do gửi người dùng (bắt buộc).");
    }
    await new Promise((r) => setTimeout(r, 20));
    expect(posts(calls, "/decision")).toHaveLength(0);

    fireEvent.change(note, { target: { value: "  Máy LAP-0342 không phải của bạn.  " } });
    fireEvent.click(send);
    expect((await screen.findByTestId("decision-sent")).textContent).toBe(DECISION_SENT);
    const sent = posts(calls, "/decision");
    expect(sent).toHaveLength(1);
    const body = JSON.parse(sent[0]!.body!) as Record<string, unknown>;
    expect(Object.keys(body).sort()).toStrictEqual(["decision", "note", "reason_code", "view_started_at"]);
    expect(body).toMatchObject({ decision: "rejected", reason_code: "wrong_device", note: "Máy LAP-0342 không phải của bạn." });
    expect(Number.isNaN(Date.parse(body.view_started_at as string))).toBe(false);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Đồng ý/ })).toBeNull(); // đã gửi → thanh quyết định ẩn
  });

  it("202 có notices → thêm câu chung, KHÔNG hiện nội dung notices", async () => {
    detailApi(() => json(202, { approval_id: "r", ticket_id: "t", status: "accepted", notices: ["NOI-DUNG-NOTICE"] }));
    renderAt("/approvals/r");
    fireEvent.click(await screen.findByRole("button", { name: "Từ chối" }));
    fireEvent.change(screen.getByLabelText("Lý do"), { target: { value: "other" } });
    fireEvent.change(screen.getByLabelText("Lý do gửi người dùng"), { target: { value: "ghi chú" } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi từ chối" }));
    const done = await screen.findByTestId("decision-sent");
    expect(done.textContent).toBe(`${DECISION_SENT} · ${NOTICES_TEXT}`);
    expect(document.body.textContent).not.toContain("NOI-DUNG-NOTICE");
  });

  it("409 → hiện câu của server + tải lại phiếu", async () => {
    let views = 0;
    const calls = stubFetch((method, url) => {
      if (method === "POST") return json(409, { detail: "Yêu cầu đã chuyển sang bước khác" });
      if (url === "/api/approvals/r") {
        views += 1;
        return json(200, viewOf("r"));
      }
      if (url.startsWith("/api/approvals?")) return inbox([listItem("r")]);
      return undefined;
    });
    renderAt("/approvals/r");
    const approve = await screen.findByRole("button", { name: /^Đồng ý/ });
    viewedLongEnough();
    fireEvent.click(approve);
    expect((await screen.findByRole("alert")).textContent).toBe("Yêu cầu đã chuyển sang bước khác");
    await waitFor(() => expect(views).toBeGreaterThanOrEqual(2));
    expect(posts(calls, "/decision")).toHaveLength(1);
  });
});

describe("t45: bấm Đồng ý 2 lần nhanh → đúng 1 request", () => {
  it("click ×2 cùng một nhịp (state chưa kịp khoá nút) → 1 POST, body {decision:'approved', view_started_at}", async () => {
    const calls = detailApi(
      () => new Promise((resolve) => setTimeout(() => resolve(json(202, { approval_id: "r", ticket_id: "t", status: "accepted", notices: [] })), 30)),
    );
    renderAt("/approvals/r");
    const approve = await screen.findByRole("button", { name: /^Đồng ý/ });
    viewedLongEnough();
    fireEvent.click(approve);
    fireEvent.click(approve);
    fireEvent.click(approve);
    await screen.findByTestId("decision-sent");
    await new Promise((r) => setTimeout(r, 50));
    const sent = posts(calls, "/decision");
    expect(sent).toHaveLength(1);
    const body = JSON.parse(sent[0]!.body!) as Record<string, unknown>;
    expect(Object.keys(body).sort()).toStrictEqual(["decision", "view_started_at"]);
    expect(body.decision).toBe("approved");
  });
});

// ------------------------------------------------------------------------------------------------ t46 (+ P9)

describe("t46: hộp thư 404 → đường lỗi chung (N4c P5: route 4c đã có, 404 là lỗi thật)", () => {
  it("404 'Not Found' → 'Chưa tải được hộp thư: Không tìm thấy.' (role=alert); không trang Phase 4; tab vẫn có; ô mã ticket vẫn dùng được", async () => {
    const calls = stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? json(404, { detail: "Not Found" }) : undefined));
    renderAt("/approvals");
    expect((await screen.findByRole("alert")).textContent).toBe("Chưa tải được hộp thư: Không tìm thấy.");
    expect(screen.queryByTestId("inbox-missing")).toBeNull();
    expect(document.body.textContent).not.toContain("Phase 4 (4c)");
    expect(screen.getByRole("tablist")).toBeTruthy();
    expect(screen.getByLabelText("Mã yêu cầu")).toBeTruthy();
    expect(calls[0]?.url).toBe("/api/approvals?mine=1&status=pending");
  });

  it("P9: không có approval:decide (L2) → trang không có quyền, không gọi API", async () => {
    const calls = stubFetch(() => undefined);
    const client = new QueryClient();
    clients.push(client);
    render(
      <QueryClientProvider client={client}>
        <AuthContext value={signedIn(L2)}>
          <MemoryRouter>
            <RequirePerm perm="approval:decide">
              <ApprovalQueue />
            </RequirePerm>
          </MemoryRouter>
        </AuthContext>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("heading", { name: "Bạn không có quyền xem trang này" })).toBeTruthy();
    await new Promise((r) => setTimeout(r, 20));
    expect(calls).toHaveLength(0);
  });
});

// ------------------------------------------------------------------------------------------------ t47

async function openOverride(ticketId: string) {
  renderAt(`/approvals/ticket/${ticketId}`);
  fireEvent.click(await screen.findByRole("button", { name: "Ghi đè…" }));
  return screen.getByRole("dialog", { name: "Ghi đè quyết định" });
}

function fillOverride(dialog: HTMLElement, decision: string, reason: string, note: string) {
  fireEvent.click(within(dialog).getByRole("radio", { name: new RegExp(`^${decision}`) }));
  fireEvent.change(within(dialog).getByLabelText("Lý do"), { target: { value: reason } });
  fireEvent.change(within(dialog).getByLabelText("Ghi chú ghi đè"), { target: { value: note } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Gửi ghi đè" }));
}

describe("t47: ghi đè — 'Khác' thiếu ghi chú → không gửi; 409/422 → câu riêng", () => {
  it("4 lựa chọn + 6 lý do; 'Khác' không ghi chú → 0 request; lý do khác không ghi chú → body KHÔNG có khoá note", async () => {
    const calls = stubFetch((method) => (method === "POST" ? json(201, { status: "recorded" }) : undefined));
    const dialog = await openOverride("tkt-x");
    expect(within(dialog).getAllByRole("radio").map((r) => r.dataset.value)).toStrictEqual(["AUTO", "HITL", "L2", "ANSWER"]);
    const reasons = [...(within(dialog).getByLabelText("Lý do") as HTMLSelectElement).options].map((o) => o.value).filter(Boolean);
    expect(reasons).toStrictEqual(["too_risky_for_auto", "approval_unnecessary", "should_not_escalate", "wrong_answer", "policy_gap", "other"]);

    fillOverride(dialog, "Chuyển L2", "other", "   ");
    expect(within(dialog).getByRole("alert").textContent).toBe("Lý do “Khác” cần ghi chú.");
    await new Promise((r) => setTimeout(r, 20));
    expect(posts(calls, "/override")).toHaveLength(0);

    fillOverride(dialog, "Chuyển L2", "too_risky_for_auto", "  ");
    await within(dialog).findByText(/Đã ghi nhận ghi đè/);
    const sent = posts(calls, "/override");
    expect(sent).toHaveLength(1);
    expect(sent[0]!.url).toBe("/api/tickets/tkt-x/override");
    expect(JSON.parse(sent[0]!.body!)).toStrictEqual({ override_decision: "L2", reason_code: "too_risky_for_auto" });
  });

  it.each([
    ["409 ticket_open", 409, "ticket_open"],
    ["409 already_overridden", 409, "already_overridden"],
    ["422 same_as_original", 422, "same_as_original"],
  ])("%s → câu tiếng Việt riêng, giữ form để sửa", async (_name, status, code) => {
    stubFetch((method) => (method === "POST" ? json(status, { detail: code }) : undefined));
    const dialog = await openOverride("tkt-y");
    fillOverride(dialog, "Tự xử lý", "other", "Ca này lẽ ra tự làm được.");
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(new ApiError(status, code)));
    expect(alert.textContent).not.toBe(code);
    expect(alert.textContent).not.toMatch(/Có lỗi xảy ra|Yêu cầu đã chuyển sang bước khác/);
    expect((within(dialog).getByLabelText("Ghi chú ghi đè") as HTMLTextAreaElement).value).toBe("Ca này lẽ ra tự làm được.");
  });

  // N4d P6: route 4d đã có → bỏ câu "có từ Phase 4"; 404 "Not Found" (không có route) đi đường không tìm thấy chung.
  it("404 'Not Found' → câu không tìm thấy chung, không còn chữ 'Phase 4'", async () => {
    stubFetch((method) => (method === "POST" ? json(404, { detail: "Not Found" }) : undefined));
    const dialog = await openOverride("tkt-z");
    fillOverride(dialog, "Cần người duyệt", "policy_gap", "");
    expect((await within(dialog).findByRole("alert")).textContent).toBe(OVERRIDE_NOT_FOUND);
    expect(dialog.textContent).not.toMatch(/Phase 4/);
  });
});

// ------------------------------------------------------------------------------------------------ t48

/** JWT dạng thật (3 đoạn base64url) — client đọc `sub` để kiểm danh tính, không kiểm chữ ký. */
const jwt = (sub: string, n: string) => `h.${btoa(JSON.stringify({ sub, n })).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_")}.s`;
const OLD = jwt("l1_01", "old");
const NEW = jwt("l1_01", "new");
const tokenBody = (token: string) => json(200, { access_token: token, token_type: "bearer", expires_in: 900, csrf_token: "c" });

function reauthSetup({ login, meAfterLogin = L1 }: { login: () => Response; meAfterLogin?: Me }) {
  const calls: Call[] = [];
  let loggedIn = false;
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    calls.push({ method, url, body: typeof init.body === "string" ? init.body : null, auth: new Headers(init.headers).get("Authorization") });
    if (url === "/api/auth/refresh") return tokenBody(OLD); // tải trang: khôi phục phiên (token cũ — đăng nhập đã lâu)
    if (url === "/api/auth/login") {
      const res = login();
      loggedIn = res.ok;
      return res;
    }
    if (url === "/api/auth/me") return json(200, loggedIn ? meAfterLogin : L1);
    if (url.endsWith("/override")) {
      return new Headers(init.headers).get("Authorization") === `Bearer ${NEW}`
        ? json(201, { status: "recorded" })
        : json(403, { detail: "reauth_required" });
    }
    return json(404, { detail: "not_found" });
  });
  const posted: unknown[] = [];
  const channel: AuthChannel = { post: (m) => posted.push(m), subscribe: () => {} };
  const client = createClient({ fetch, readCookie: () => "csrf-1", locks: null, channel, onSessionEnd: vi.fn() });

  function Gate({ children }: { children: ReactNode }) {
    return useAuth().state.status === "signedIn" ? children : <p>Đang kiểm tra…</p>;
  }
  /** Trang đầu sau khi đổi người: đường dẫn + dải flash (như Shell). */
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
  // Dữ liệu đã tải của người cũ — đổi người thì phải bị xoá.
  queryClient.setQueryData(["approvals", "list", "pending"], [listItem("cu")]);
  queryClient.setQueryData(["ticket", "tkt-cu"], { ticket_id: "tkt-cu" });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider client={client} subscribe={() => () => {}}>
        <MemoryRouter initialEntries={["/approvals/ticket/tkt-demo-reauth"]}>
          <Routes>
            <Route
              path="/approvals/ticket/:ticketId"
              element={
                <Gate>
                  <OverrideDialog ticketId="tkt-demo-reauth" onClose={() => {}} submit={(id, body) => overrideTicket(id, body, client)} />
                </Gate>
              }
            />
            <Route path="/approvals" element={<Landing />} />
            <Route path="/chat" element={<Landing />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { calls, posted, queryClient };
}

async function submitOverrideThenReauth(password: string) {
  const dialog = await screen.findByRole("dialog", { name: "Ghi đè quyết định" });
  fillOverride(dialog, "Cần người duyệt", "too_risky_for_auto", "");
  const reauth = await screen.findByRole("dialog", { name: "Xác nhận lại đăng nhập" });
  fireEvent.change(within(reauth).getByLabelText("Tên đăng nhập"), { target: { value: "ha.lt" } });
  fireEvent.change(within(reauth).getByLabelText("Mật khẩu"), { target: { value: password } });
  fireEvent.click(within(reauth).getByRole("button", { name: "Đăng nhập lại" }));
  return reauth;
}

const passwordLeft = (value: string) =>
  [...document.querySelectorAll("input")].some((i) => i.type === "password" || (value !== "" && i.value === value));

describe("t48: 403 reauth_required → đăng nhập lại (đường F1) → gửi lại ĐÚNG 1 lần", () => {
  it("cùng người (sub = user_id cũ): login đúng body, token mới chỉ qua client.login + phát qua kênh tab; override gửi 2 lần (cũ → mới)", async () => {
    const { calls, posted } = reauthSetup({ login: () => tokenBody(NEW) });
    await submitOverrideThenReauth("pw");
    await screen.findByText(/Đã ghi nhận ghi đè/);
    const overrides = posts(calls, "/override");
    expect(overrides.map((c) => c.auth)).toStrictEqual([`Bearer ${OLD}`, `Bearer ${NEW}`]);
    expect(JSON.parse(overrides[1]!.body!)).toStrictEqual(JSON.parse(overrides[0]!.body!)); // gửi lại đúng body cũ
    const logins = posts(calls, "/api/auth/login");
    expect(logins).toHaveLength(1);
    expect(JSON.parse(logins[0]!.body!)).toStrictEqual({ username: "ha.lt", password: "pw" });
    expect(posted).toContainEqual(expect.objectContaining({ type: "token", user_id: "l1_01", token: NEW }));
    expect(screen.queryByRole("dialog", { name: "Xác nhận lại đăng nhập" })).toBeNull();
    expect(passwordLeft("pw")).toBe(false); // hộp đóng → mật khẩu không còn ở đâu trên màn
    await new Promise((r) => setTimeout(r, 30));
    expect(posts(calls, "/override")).toHaveLength(2);
  });

  it("đăng nhập lại thất bại → câu lỗi chung, KHÔNG gửi lại; huỷ → vẫn không gửi, mật khẩu bị xoá khỏi màn", async () => {
    const { calls } = reauthSetup({ login: () => json(401, { detail: "unauthorized" }) });
    const reauth = await submitOverrideThenReauth("sai-mat-khau");
    expect((await within(reauth).findByRole("alert")).textContent).toBe(GENERIC_LOGIN_ERROR);
    await new Promise((r) => setTimeout(r, 30));
    expect(posts(calls, "/override")).toHaveLength(1);
    fireEvent.click(within(reauth).getByRole("button", { name: "Huỷ" }));
    const dialog = await screen.findByRole("dialog", { name: "Ghi đè quyết định" });
    expect(within(dialog).getByRole("alert").textContent).toContain("Chưa gửi ghi đè");
    expect(passwordLeft("sai-mat-khau")).toBe(false);
    expect(posts(calls, "/override")).toHaveLength(1);
  });

  it("đăng nhập lại bằng NGƯỜI KHÁC (sub ≠ user_id cũ) → không gửi lại, xoá cache, về trang đầu người mới + câu báo huỷ", async () => {
    const employee: Me = { user_id: "nv001", role: "employee", permissions: ["ticket:create", "ticket:read:own"] };
    const { calls, queryClient } = reauthSetup({ login: () => tokenBody(jwt("nv001", "x")), meAfterLogin: employee });
    expect(queryClient.getQueryCache().getAll()).toHaveLength(2);
    await submitOverrideThenReauth("pw");
    expect((await screen.findByTestId("landing")).textContent).toBe("/chat"); // homePath của nhân viên
    expect(screen.getByTestId("flash").textContent).toBe("Bạn đã đăng nhập bằng tài khoản khác — thao tác ghi đè đã huỷ.");
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(passwordLeft("pw")).toBe(false);
    await new Promise((r) => setTimeout(r, 30));
    expect(posts(calls, "/override")).toHaveLength(1);
  });

  it("token mới không đọc được sub → coi là người khác (fail-closed): không gửi lại, xoá cache", async () => {
    const { calls, queryClient } = reauthSetup({ login: () => tokenBody("khong-phai-jwt"), meAfterLogin: L1 });
    await submitOverrideThenReauth("pw");
    expect((await screen.findByTestId("landing")).textContent).toBe("/approvals");
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    await new Promise((r) => setTimeout(r, 30));
    expect(posts(calls, "/override")).toHaveLength(1);
  });
});

// ------------------------------------------------------------------------------------------------ t50 (Q-fe-24)

describe("t50: GET ticket 404 → câu trung tính, nút ghi đè vẫn có theo quyền (Q-fe-24)", () => {
  it("404 → 'Chưa tải được chi tiết yêu cầu.' (không alert, không mã lỗi); vẫn có nút 'Ghi đè…' và mở được hộp", async () => {
    const calls = stubFetch(() => undefined); // GET /api/tickets/tkt-khong-co → 404 not_found
    renderAt("/approvals/ticket/tkt-khong-co");
    expect((await screen.findByTestId("ticket-unavailable")).textContent).toBe(TICKET_UNAVAILABLE);
    expect(TICKET_UNAVAILABLE).toBe("Chưa tải được chi tiết yêu cầu.");
    expect(calls.map((c) => c.url)).toContain("/api/tickets/tkt-khong-co");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.body.textContent).not.toMatch(/404|not_found|Không tìm thấy/);
    fireEvent.click(screen.getByRole("button", { name: "Ghi đè…" }));
    expect(screen.getByRole("dialog", { name: "Ghi đè quyết định" })).toBeTruthy();
  });

  it("không có decision:override → không có nút (câu trung tính vẫn hiện)", async () => {
    stubFetch(() => undefined);
    renderAt("/approvals/ticket/tkt-khong-co", { ...L1, permissions: L1.permissions.filter((p) => p !== "decision:override") });
    await screen.findByTestId("ticket-unavailable");
    expect(screen.queryByRole("button", { name: "Ghi đè…" })).toBeNull();
  });

  it("theo dữ liệu phiếu: phiếu đã quyết + có quyền → lối vào ghi đè đúng ticket_id; phiếu đang chờ → không có", async () => {
    const decided = viewOf("dq", { status: "approved" });
    stubFetch((_method, url) => {
      if (url === "/api/approvals/dq") return json(200, decided);
      if (url === "/api/approvals/pq") return json(200, viewOf("pq"));
      if (url.startsWith("/api/approvals?")) return inbox([listItem("dq", { status: "approved" }), listItem("pq")]);
      return undefined;
    });
    renderAt("/approvals/dq");
    const link = await screen.findByTestId("override-link");
    expect(link.getAttribute("href")).toBe(`/approvals/ticket/${decided.ticket_id}`);
    cleanup();
    renderAt("/approvals/pq");
    await screen.findByRole("button", { name: /^Đồng ý/ });
    expect(screen.queryByTestId("override-link")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t51 (kiểm chéo 4b)

describe("t51: decision 403 (xung đột lợi ích theo chuỗi quản lý — may_decide_as sai) → câu 403 trung tính", () => {
  it("Đồng ý → 403 forbidden → 'Bạn không có quyền…', không lộ lý do; thanh quyết định vẫn còn, không báo đã gửi", async () => {
    const calls = detailApi(() => json(403, { detail: "forbidden" }));
    renderAt("/approvals/r");
    const approve = await screen.findByRole("button", { name: /^Đồng ý/ });
    viewedLongEnough();
    fireEvent.click(approve);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(new ApiError(403, "forbidden")));
    expect(alert.textContent).toBe("Bạn không có quyền thực hiện thao tác này.");
    // "Quản lý" là nhãn dòng của khối "Người bị ảnh hưởng" (F6) → chỉ chặn chữ của LÝ DO xung đột ("chuỗi quản lý").
    expect(document.body.textContent).not.toMatch(/xung đột|chuỗi quản lý|forbidden|permission_denied/i);
    expect(screen.queryByTestId("decision-sent")).toBeNull();
    expect((screen.getByRole("button", { name: /^Đồng ý/ }) as HTMLButtonElement).disabled).toBe(false);
    expect(posts(calls, "/decision")).toHaveLength(1);
  });
});

// ------------------------------------------------------------------------------------------------ t75 (F6 P3)

/** Đồng hồ chống phản xạ giả: `performance.now` = giờ thật + độ dời; `elapse(s)` = người duyệt đã nhìn thêm s giây. */
function reflexClock() {
  const real = performance.now.bind(performance);
  let offset = 0;
  vi.spyOn(performance, "now").mockImplementation(() => real() + offset);
  return (seconds: number) => {
    offset += seconds * 1000;
  };
}

describe("t75: chống duyệt theo phản xạ — Đồng ý khi mới xem < 5 giây → hỏi lại; Từ chối không hỏi", () => {
  it("hàm thuần: ngưỡng 5 giây là hằng một chỗ; đo bằng mốc performance.now; chưa có mốc → 0 (hỏi lại)", () => {
    expect(REFLEX_MIN_SECONDS).toBe(5);
    expect(isReflex(0)).toBe(true);
    expect(isReflex(4.999)).toBe(true);
    expect(isReflex(5)).toBe(false);
    expect(isReflex(60)).toBe(false);
    expect(viewedSeconds(null, 99_000)).toBe(0);
    expect(viewedSeconds(1_000, 4_200)).toBeCloseTo(3.2);
    expect(viewedSeconds(5_000, 1_000)).toBe(0); // không âm
    expect(reflexText(3.7)).toBe("Bạn mới xem phiếu này 3 giây. Đã kiểm tra hành động, đối tượng và mã băm chưa?");
    expect(reflexText(0.2)).toContain("1 giây");
  });

  it("< 5 s → hộp xác nhận, focus 'Xem lại'; 'Xem lại' → đóng, 0 POST; bấm lại → 'Vẫn đồng ý' → đúng 1 POST, body không thêm trường", async () => {
    const elapse = reflexClock();
    const calls = detailApi(() => json(202, { approval_id: "r", ticket_id: "t", status: "accepted", notices: [] }));
    renderAt("/approvals/r");
    const approve = await screen.findByRole("button", { name: /^Đồng ý/ });
    elapse(3.2);
    fireEvent.click(approve);
    const dialog = screen.getByRole("dialog", { name: "Xác nhận đồng ý" });
    expect(within(dialog).getByTestId("reflex-text").textContent).toBe(
      "Bạn mới xem phiếu này 3 giây. Đã kiểm tra hành động, đối tượng và mã băm chưa?",
    );
    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Xem lại" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Xem lại" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await new Promise((r) => setTimeout(r, 20));
    expect(posts(calls, "/decision")).toHaveLength(0);
    expect(screen.getByTestId("decision-bar")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^Đồng ý/ })); // vẫn < 5 s → hỏi lại
    fireEvent.click(within(screen.getByRole("dialog", { name: "Xác nhận đồng ý" })).getByRole("button", { name: "Vẫn đồng ý" }));
    await screen.findByTestId("decision-sent");
    const sent = posts(calls, "/decision");
    expect(sent).toHaveLength(1);
    expect(Object.keys(JSON.parse(sent[0]!.body!) as object).sort()).toStrictEqual(["decision", "view_started_at"]);
  });

  it("≥ 5 s → không hộp, gửi ngay đúng 1 POST", async () => {
    const elapse = reflexClock();
    const calls = detailApi(() => json(202, { approval_id: "r", ticket_id: "t", status: "accepted", notices: [] }));
    renderAt("/approvals/r");
    const approve = await screen.findByRole("button", { name: /^Đồng ý/ });
    elapse(REFLEX_MIN_SECONDS);
    fireEvent.click(approve);
    expect(screen.queryByRole("dialog")).toBeNull();
    await screen.findByTestId("decision-sent");
    expect(posts(calls, "/decision")).toHaveLength(1);
  });

  it("đồng hồ bắt đầu khi chi tiết HIỆN (GET 200), không tính thời gian chờ tải: tải 30 s rồi bấm ngay → vẫn hỏi lại", async () => {
    const elapse = reflexClock();
    let release: () => void = () => {};
    const loaded = new Promise<void>((resolve) => {
      release = resolve;
    });
    stubFetch(async (method, url) => {
      if (url === "/api/approvals/r") {
        await loaded;
        return json(200, viewOf("r"));
      }
      if (url.startsWith("/api/approvals?")) return inbox([listItem("r")]);
      return method === "POST" ? json(202, {}) : json(404, { detail: "not_found" });
    });
    renderAt("/approvals/r");
    await screen.findByText("Đang tải phiếu…");
    elapse(30); // phiếu tải chậm 30 giây
    release();
    fireEvent.click(await screen.findByRole("button", { name: /^Đồng ý/ }));
    expect(screen.getByRole("dialog", { name: "Xác nhận đồng ý" })).toBeTruthy();
  });

  it("Từ chối ngay khi vừa mở phiếu (đủ lý do + ghi chú) → KHÔNG hỏi lại, đúng 1 POST rejected", async () => {
    reflexClock(); // 0 giây
    const calls = detailApi(() => json(202, { approval_id: "r", ticket_id: "t", status: "accepted", notices: [] }));
    renderAt("/approvals/r");
    fireEvent.click(await screen.findByRole("button", { name: "Từ chối" }));
    const sheet = screen.getByRole("dialog", { name: "Từ chối yêu cầu" });
    fireEvent.change(within(sheet).getByLabelText("Lý do"), { target: { value: "wrong_device" } });
    fireEvent.change(within(sheet).getByLabelText("Lý do gửi người dùng"), { target: { value: "Sai máy" } });
    fireEvent.click(within(sheet).getByRole("button", { name: "Gửi từ chối" }));
    await screen.findByTestId("decision-sent");
    expect(screen.queryByRole("dialog", { name: "Xác nhận đồng ý" })).toBeNull();
    const sent = posts(calls, "/decision");
    expect(sent).toHaveLength(1);
    expect((JSON.parse(sent[0]!.body!) as { decision: string }).decision).toBe("rejected");
  });
});

// ------------------------------------------------------------------------------------------------ t77 (F6 P5)

describe("t77: thẩm mỹ F4 — bảng khoá–giá trị không ngắt giữa chữ; thanh quyết định nền đặc, ngoài vùng cuộn (Q-fe-32)", () => {
  it("dd của bảng: wrap-anywhere + break-normal, không break-all; thanh: bg-white đặc + border-t + shrink-0, không sticky, KHÔNG nằm trong vùng cuộn", async () => {
    detailApi(() => json(202, {}));
    renderAt("/approvals/r");
    const bar = await screen.findByTestId("decision-bar");
    const values = [...document.querySelectorAll('[data-testid="risk-row"] dd, [data-testid="action-row"] dd, [data-testid="fact-row"] dd')];
    expect(values.length).toBeGreaterThanOrEqual(3); // đủ 3 bảng: hành động, rủi ro, dữ kiện
    for (const dd of values) {
      const cls = dd.className.split(/\s+/);
      expect(cls).toContain("wrap-anywhere");
      expect(cls).toContain("break-normal");
      expect(cls).not.toContain("break-all");
    }
    const barCls = bar.className.split(/\s+/);
    expect(barCls).toEqual(expect.arrayContaining(["bg-white", "border-t", "shrink-0"]));
    expect(barCls.some((c) => c.startsWith("bg-white/"))).toBe(false); // không nền trong suốt
    expect(barCls).not.toContain("sticky");
    const scroll = screen.getByTestId("approval-scroll");
    expect(scroll.className.split(/\s+/)).toEqual(expect.arrayContaining(["overflow-y-auto", "min-h-0", "grow"]));
    expect(scroll.contains(bar)).toBe(false);
    expect(scroll.parentElement).toBe(bar.parentElement);
    expect(scroll.querySelector("section")?.className.split(/\s+/)).toContain("pb-6");
  });
});

// ================================================================================================ N4c — nối thật 4c
// Hợp đồng: backend/app/api/approvals.py @b457e6e — hộp thư `{items: [...]}` (InboxItem 10 khoá, `action_type` /
// `device_id` có thể null), xem phiếu `ApprovalView` (`department`, `risk`, `procedure` có thể null; `role_as` có `viewer`),
// 202 decision thêm `decided_as`.

// ------------------------------------------------------------------------------------------------ t79

describe("t79: listApprovals nhận ĐÚNG MỘT hình dạng {items: [...]}; sai dạng → 502 invalid_inbox_body", () => {
  it("{items:[…]} → trả mảng phần tử (giữ cả trường null); URL có mine=1&status=…", async () => {
    const a = listItem("a");
    const n = listItem("n", { action_type: null, device_id: null });
    const calls = stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? inbox([a, n]) : undefined));
    expect(await listApprovals("timeout")).toStrictEqual([a, n]);
    expect(await listApprovals("pending")).toStrictEqual([a, n]);
    expect(calls.map((c) => c.url)).toStrictEqual(["/api/approvals?mine=1&status=timeout", "/api/approvals?mine=1&status=pending"]);
  });

  const noDeadline: Partial<ApprovalListItem> = { ...listItem("b") };
  delete noDeadline.deadline;
  it.each([
    ["mảng trần (dạng cũ của F4)", [listItem("a")]],
    ["object rỗng {}", {}],
    ["{items: null}", { items: null }],
    ["items là object", { items: { a: listItem("a") } }],
    ["thân null", null],
    ["một phần tử thiếu deadline", { items: [listItem("a"), noDeadline] }],
    ["deadline không phải chuỗi", { items: [{ ...listItem("a"), deadline: 1_700_000_000 }] }],
    ["approval_id không phải chuỗi", { items: [{ ...listItem("a"), approval_id: 412 }] }],
    ["một phần tử không phải object", { items: [listItem("a"), "b"] }],
    ["phần tử null", { items: [null] }],
  ])("%s → ApiError(502, invalid_inbox_body) — không đoán, không bỏ lặng phần tử", async (_name, body) => {
    stubFetch(() => json(200, body));
    const error = await listApprovals("pending").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect([(error as ApiError).status, (error as ApiError).code]).toStrictEqual([502, "invalid_inbox_body"]);
  });

  it("màn: thân mảng trần → câu lỗi chung, 0 dòng (không hiện dữ liệu đoán dạng)", async () => {
    stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? json(200, [listItem("a")]) : undefined));
    renderAt("/approvals");
    expect((await screen.findByRole("alert")).textContent).toBe("Chưa tải được hộp thư: Có lỗi xảy ra, vui lòng thử lại.");
    expect(screen.queryAllByTestId("inbox-row")).toHaveLength(0);
  });
});

// ------------------------------------------------------------------------------------------------ t80

describe("t80: dòng action_type null + device_id null — vẫn hiện, vẫn là link, vẫn sắp theo hạn và tô đỏ", () => {
  it("actionLabel: null → câu P3; mã đã biết → nhãn; mã lạ → nguyên mã", () => {
    expect(actionLabel(null)).toBe(ACTION_UNKNOWN);
    expect(ACTION_UNKNOWN).toBe("Chưa rõ hành động — mở phiếu để xem");
    expect(actionLabel("renew_vpn_cert")).toBe("Cấp lại chứng chỉ VPN");
    expect(actionLabel("hanh_dong_la")).toBe("Khác · hanh_dong_la"); // N-NGU: mã lạ → "Khác · mã"
  });

  it("màn: dòng null đứng đúng chỗ theo hạn, đỏ khi < 20%, nhãn P3 + '(không có)', bấm → mở phiếu", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: T0 });
    const unknownUrgent = listItem("u", { action_type: null, device_id: null, created_at: at(-25), deadline: at(4) });
    const unknownCalm = listItem("v", { action_type: null, device_id: null, created_at: at(-2), deadline: at(28) });
    const normal = listItem("a", { created_at: at(-10), deadline: at(20) });
    const calls = stubFetch((_method, url) => {
      if (url === "/api/approvals/u") return json(200, viewOf("u"));
      if (url.startsWith("/api/approvals?")) return inbox([unknownCalm, normal, unknownUrgent]);
      return undefined;
    });
    renderAt("/approvals");
    await screen.findAllByTestId("inbox-row");
    expect(rowIds()).toStrictEqual(["u", "a", "v"]);
    expect(screen.getByRole("tab", { name: /^Chờ duyệt/ }).textContent).toBe("Chờ duyệt · 3");
    const [rowU, , rowV] = screen.getAllByTestId("inbox-row");
    expect(rowU!.dataset.urgent).toBe("true");
    expect(rowV!.dataset.urgent).toBe("false");
    for (const row of [rowU!, rowV!]) {
      expect(row.textContent).toContain(ACTION_UNKNOWN);
      expect(row.textContent).toContain("Máy (không có)");
    }
    expect(rowU!.tagName).toBe("A");
    expect(rowU!.getAttribute("href")).toBe("/approvals/u");
    fireEvent.click(rowU!);
    expect((await screen.findByTestId("request-summary")).textContent).toBe(viewOf("u").request_summary);
    expect(calls.map((c) => c.url)).toContain("/api/approvals/u");
  });
});

// ------------------------------------------------------------------------------------------------ t81

const NULL_VIEW: Partial<ApprovalViewP4> = { requester: { role: "employee", department: null }, risk: null, risk_view: null, procedure: null };

describe("t81: phiếu có phòng ban / rủi ro / căn cứ null → '—', câu rủi ro, '(không có)'; thanh quyết định VẪN có", () => {
  // Khối "Người gửi" (khối "Người bị ảnh hưởng" cũng có dòng "Phòng ban") — tra trong khối đúng.
  const dd = (label: string) =>
    within(screen.getByText("Người gửi", { selector: "h2" }).parentElement!).getByText(label, { selector: "dt" }).nextElementSibling?.textContent;

  it("hiện thay thế đúng chỗ, không dựng bảng rỗng; Đồng ý gửi đúng body cũ", async () => {
    const calls = stubFetch((method, url) => {
      if (method === "POST" && url === "/api/approvals/z/decision") {
        return json(202, { approval_id: "z", ticket_id: "t", status: "accepted", notices: [], decided_as: "primary" });
      }
      if (url === "/api/approvals/z") return json(200, viewOf("z", NULL_VIEW));
      if (url.startsWith("/api/approvals?")) return inbox([listItem("z", { action_type: null, device_id: null })]);
      return undefined;
    });
    renderAt("/approvals/z");
    expect((await screen.findByTestId("risk-missing")).textContent).toBe(RISK_MISSING_TEXT);
    expect(RISK_MISSING_TEXT).toBe("Chưa có đánh giá rủi ro cho phiếu này.");
    expect(screen.queryAllByTestId("risk-row")).toHaveLength(0);
    expect(screen.getByTestId("procedure").textContent).toBe("(không có)");
    expect(dd("Phòng ban")).toBe("—");
    expect(dd("Vai trò")).toBe("Nhân viên");
    expect(screen.getByTestId("action-hash").textContent).toBe(viewOf("z").action_plan_hash); // căn cứ duyệt vẫn đủ
    expect(screen.getAllByTestId("fact-row").length).toBeGreaterThan(0);
    expect(screen.getByTestId("decision-bar")).toBeTruthy();
    viewedLongEnough();
    fireEvent.click(screen.getByRole("button", { name: /^Đồng ý/ }));
    expect((await screen.findByTestId("decision-sent")).textContent).toBe(DECISION_SENT);
    const sent = posts(calls, "/decision");
    expect(sent).toHaveLength(1);
    const body = JSON.parse(sent[0]!.body!) as Record<string, unknown>;
    expect(Object.keys(body).sort()).toStrictEqual(["decision", "view_started_at"]);
    expect(body.decision).toBe("approved");
  });

  it("vai trò người gửi rỗng (thiếu requester_context) → '—'", async () => {
    stubFetch((_method, url) => {
      if (url === "/api/approvals/y") return json(200, viewOf("y", { requester: { role: "", department: "Finance" } }));
      if (url.startsWith("/api/approvals?")) return inbox([listItem("y")]);
      return undefined;
    });
    renderAt("/approvals/y");
    await screen.findByTestId("request-summary");
    expect(dd("Vai trò")).toBe("—");
    expect(dd("Phòng ban")).toBe("Finance");
  });
});

// ------------------------------------------------------------------------------------------------ t82

describe("t82: role_as viewer (hoặc giá trị lạ) → không đường quyết định nào; câu giám sát", () => {
  it("decisionRole: chỉ primary/backup giữ nguyên; viewer và mọi giá trị lạ → viewer", () => {
    expect(decisionRole("primary")).toBe("primary");
    expect(decisionRole("backup")).toBe("backup");
    for (const odd of ["viewer", "owner", "PRIMARY", "", null, undefined, 1, {}]) expect(decisionRole(odd)).toBe("viewer");
  });

  it.each([
    ["viewer", "viewer"],
    ["giá trị lạ 'owner' → như viewer", "owner"],
  ])("%s: phiếu pending → câu giám sát, 0 thanh quyết định, 0 nút, 0 hộp, 0 POST", async (_name, roleAs) => {
    const calls = stubFetch((method, url) => {
      if (method === "POST") return json(202, { approval_id: "w", ticket_id: "t", status: "accepted", notices: [] });
      if (url === "/api/approvals/w") return json(200, viewOf("w", { role_as: roleAs as ApprovalViewP4["role_as"] }));
      if (url.startsWith("/api/approvals?")) return inbox([]);
      return undefined;
    });
    renderAt("/approvals/w");
    const note = await screen.findByTestId("viewer-note");
    expect(note.textContent).toBe(VIEWER_TEXT);
    expect(VIEWER_TEXT).toBe("Bạn đang xem phiếu này với quyền giám sát — không thể quyết định.");
    expect(screen.getByTestId("action-hash").textContent).toBe(viewOf("w").action_plan_hash); // vẫn xem được đúng object
    expect(screen.queryByTestId("decision-bar")).toBeNull();
    expect(screen.queryByRole("button", { name: /Đồng ý|Từ chối|Vẫn đồng ý|Gửi từ chối/ })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByTestId("backup-banner")).toBeNull();
    fireEvent.keyDown(document.body, { key: "Enter" });
    await new Promise((r) => setTimeout(r, 20));
    expect(posts(calls, "/decision")).toHaveLength(0);
  });

  it("backup vẫn như cũ: dải dự phòng + thanh quyết định, không câu giám sát", async () => {
    stubFetch((_method, url) => {
      if (url === "/api/approvals/b") return json(200, viewOf("b", { role_as: "backup" }));
      if (url.startsWith("/api/approvals?")) return inbox([listItem("b", { role_as: "backup" })]);
      return undefined;
    });
    renderAt("/approvals/b");
    expect((await screen.findByTestId("backup-banner")).textContent).toContain(BACKUP_TEXT);
    expect(screen.getByTestId("decision-bar")).toBeTruthy();
    expect(screen.queryByTestId("viewer-note")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t83

describe("t83: hộp thư 404 → đường lỗi chung; tự tải lại: 403 dừng, lỗi khác vẫn theo nhịp", () => {
  it("inboxRefetchInterval: chỉ 403 dừng; 404 (cả 'Not Found'), 502, lỗi mạng, không lỗi → 30 s", () => {
    expect(inboxRefetchInterval(new ApiError(403, "forbidden"))).toBe(false);
    for (const error of [new ApiError(404, "Not Found"), new ApiError(404, "not_found"), new ApiError(502, "invalid_inbox_body"), new TypeError("mạng"), null]) {
      expect(inboxRefetchInterval(error)).toBe(INBOX_REFRESH_MS);
    }
    expect(INBOX_REFRESH_MS).toBe(30_000);
  });

  async function inboxCallsAfter30s(status: number, code: string): Promise<[number, number, string]> {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? json(status, { detail: code }) : undefined));
    renderAt("/approvals");
    const alert = (await screen.findByRole("alert")).textContent ?? "";
    const before = calls.length;
    await vi.advanceTimersByTimeAsync(INBOX_REFRESH_MS + 1_000);
    return [before, calls.length, alert];
  }

  it("404 → 'Chưa tải được hộp thư: Không tìm thấy.', không trang Phase 4; 30 s sau gọi lại", async () => {
    const [before, after, alert] = await inboxCallsAfter30s(404, "Not Found");
    expect(alert).toBe("Chưa tải được hộp thư: Không tìm thấy.");
    expect(document.body.textContent).not.toMatch(/Phase 4 \(4c\)|chưa có danh sách phiếu duyệt/);
    expect(after).toBeGreaterThan(before);
  });

  it("403 → câu không có quyền; 30 s sau KHÔNG gọi lại", async () => {
    const [before, after, alert] = await inboxCallsAfter30s(403, "forbidden");
    expect(alert).toBe("Chưa tải được hộp thư: Bạn không có quyền thực hiện thao tác này.");
    expect(after).toBe(before);
  });
});

// ------------------------------------------------------------------------------------------------ t86

describe("t86: 202 có / thiếu decided_as → màn như cũ, không hiện decided_as", () => {
  it.each([
    ["có decided_as (4c)", { approval_id: "r", ticket_id: "t", status: "accepted", notices: [], decided_as: "backup" }],
    ["thiếu decided_as (backend cũ)", { approval_id: "r", ticket_id: "t", status: "accepted", notices: [] }],
  ])("%s → 'Đã gửi quyết định', thanh quyết định ẩn", async (_name, accepted) => {
    detailApi(() => json(202, accepted));
    renderAt("/approvals/r");
    const approve = await screen.findByRole("button", { name: /^Đồng ý/ });
    viewedLongEnough();
    fireEvent.click(approve);
    expect((await screen.findByTestId("decision-sent")).textContent).toBe(DECISION_SENT);
    expect(screen.queryByTestId("decision-bar")).toBeNull();
    expect(document.body.textContent).not.toMatch(/decided_as|backup/);
  });
});

// ------------------------------------------------------------------------------------------------ t87 (Q-fe-38)

describe("t87: đã có dữ liệu mà tải lại lỗi → GIỮ danh sách cũ + cảnh báo 'có thể đã cũ' (role=status); tải lại thành công → mất", () => {
  it("200 [A] → 500 (dòng A còn + cảnh báo) → 200 (mất) → 403 (cảnh báo còn, dừng tự tải lại)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const a = listItem("a");
    const replies = [inbox([a]), json(500, { detail: "internal" }), inbox([a]), json(403, { detail: "forbidden" })];
    const calls = stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? (replies.shift() ?? inbox([a])) : undefined));
    const inboxCalls = () => calls.filter((c) => c.url.startsWith("/api/approvals?")).length;
    const tick = async () => {
      const before = inboxCalls();
      await vi.advanceTimersByTimeAsync(INBOX_REFRESH_MS + 1_000);
      return inboxCalls() - before;
    };
    const stale = () => screen.queryByTestId("inbox-stale");
    renderAt("/approvals");
    await screen.findByTestId("inbox-row");
    expect(stale()).toBeNull();

    expect(await tick()).toBe(1); // tải lại → 500
    await waitFor(() => expect(stale()).not.toBeNull());
    expect(stale()!.getAttribute("role")).toBe("status");
    expect(stale()!.textContent).toBe(`${INBOX_STALE_TEXT} Có lỗi xảy ra, vui lòng thử lại.`);
    expect(INBOX_STALE_TEXT).toBe("Chưa cập nhật được hộp thư — danh sách dưới đây có thể đã cũ.");
    expect(rowIds()).toStrictEqual(["a"]); // phiếu đang chờ không bị ẩn
    expect(screen.getByTestId("inbox-row").getAttribute("href")).toBe("/approvals/a"); // vẫn mở được
    expect(screen.getByRole("tab", { name: /^Chờ duyệt/ }).textContent).toBe("Chờ duyệt · 1");
    expect(screen.queryByRole("alert")).toBeNull(); // không lẫn với khối "Chưa tải được hộp thư"
    expect(screen.queryByTestId("inbox-count-stale")).toBeNull(); // đang ở tab "Chờ duyệt": một lỗi → một dòng

    expect(await tick()).toBe(1); // tải lại → 200
    await waitFor(() => expect(stale()).toBeNull());
    expect(rowIds()).toStrictEqual(["a"]);

    expect(await tick()).toBe(1); // tải lại → 403
    await waitFor(() => expect(stale()?.textContent).toBe(`${INBOX_STALE_TEXT} Bạn không có quyền thực hiện thao tác này.`));
    expect(rowIds()).toStrictEqual(["a"]);
    expect(await tick()).toBe(0); // 403 → nhịp tự tải lại dừng
    expect(stale()).not.toBeNull();
  });

  it("đang ở tab 'Đã quyết': pending tải lại 500 → 'inbox-count-stale', số đếm cũ còn; tải lại 200 → mất", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const a = listItem("a");
    const pendingReplies = [inbox([a]), json(500, { detail: "internal" }), inbox([a])];
    const calls = stubFetch((_method, url) => {
      if (url.endsWith("status=pending")) return pendingReplies.shift() ?? inbox([a]);
      if (url.startsWith("/api/approvals?")) return inbox([]);
      return undefined;
    });
    const pendingCalls = () => calls.filter((c) => c.url.endsWith("status=pending")).length;
    const countStale = () => screen.queryByTestId("inbox-count-stale");
    renderAt("/approvals");
    await screen.findByTestId("inbox-row");
    fireEvent.click(screen.getByRole("tab", { name: "Đã quyết" }));
    await screen.findByText("Chưa có phiếu nào đã quyết");
    expect(countStale()).toBeNull();

    const before = pendingCalls();
    await vi.advanceTimersByTimeAsync(INBOX_REFRESH_MS + 1_000); // pending tải lại → 500
    expect(pendingCalls() - before).toBe(1);
    await waitFor(() => expect(countStale()).not.toBeNull());
    expect(countStale()!.getAttribute("role")).toBe("status");
    expect(countStale()!.textContent).toBe(`${INBOX_COUNT_STALE_TEXT} Có lỗi xảy ra, vui lòng thử lại.`);
    expect(INBOX_COUNT_STALE_TEXT).toBe("Chưa cập nhật được số phiếu chờ duyệt — con số trên tab có thể đã cũ.");
    expect(screen.getByRole("tab", { name: /^Chờ duyệt/ }).textContent).toBe("Chờ duyệt · 1"); // số đếm cũ còn
    expect(screen.queryByTestId("inbox-stale")).toBeNull(); // danh sách tab đang xem vẫn mới
    expect(screen.queryByRole("alert")).toBeNull();

    await vi.advanceTimersByTimeAsync(INBOX_REFRESH_MS + 1_000); // pending tải lại → 200
    await waitFor(() => expect(countStale()).toBeNull());
    expect(screen.getByRole("tab", { name: /^Chờ duyệt/ }).textContent).toBe("Chờ duyệt · 1");
  });
});

// ================================================================================================ N4d — nối thật 4d (ghi đè)
// Hợp đồng: backend/app/api/tickets.py @e510a6e — 201 `{ticket_id, original_decision, override_decision, reason_code, notices}`;
// lỗi 403 `forbidden` / `reauth_required`, 404, 409 `ticket_open` / `already_overridden`, 422 `invalid_request` (`fields`
// KHÔNG có tiền tố `body.`) / `same_as_original`, 503 `privacy_guard_unavailable`.

const RECORDED = {
  ticket_id: "6a1c2e4f-0b3d-4e5f-8a7b-9c0d1e2f3a4b",
  original_decision: "HITL",
  override_decision: "L2",
  reason_code: "should_not_escalate",
  notices: [],
};
const OVERRIDE_BODY: OverrideIn = { override_decision: "L2", reason_code: "should_not_escalate" };

// ------------------------------------------------------------------------------------------------ t88

describe("t88: overrideTicket đọc CHẶT thân 201 — server đã trả 201 thì luôn là ĐÃ GHI (2xx khác → lỗi)", () => {
  it("201 đủ thân → trả đúng OverrideRecorded; 1 POST đúng URL (mã hoá id), body đúng OverrideIn", async () => {
    const calls = stubFetch((method) => (method === "POST" ? json(201, RECORDED) : undefined));
    expect(await overrideTicket("tkt 1/x", OVERRIDE_BODY)).toStrictEqual(RECORDED);
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "POST", url: "/api/tickets/tkt%201%2Fx/override" });
    expect(JSON.parse(calls[0]!.body!)).toStrictEqual(OVERRIDE_BODY);
  });

  it.each([
    ["{status:'recorded'} (thiếu ticket_id)", () => json(201, { status: "recorded" })],
    ["ticket_id là số", () => json(201, { ...RECORDED, ticket_id: 7 })],
    ["thiếu notices", () => json(201, { ticket_id: "t", original_decision: "HITL" })],
    ["notices là chuỗi", () => json(201, { ...RECORDED, notices: "đã che" })],
    ["mảng", () => json(201, [RECORDED])],
    ["null", () => json(201, null)],
    ["thân rỗng, không Content-Type", () => new Response(null, { status: 201 })],
    ["text/plain", () => new Response("ok", { status: 201, headers: { "Content-Type": "text/plain" } })],
  ])("201 %s → resolve null (đã ghi, không đọc được chi tiết) — KHÔNG ném", async (_name, response) => {
    stubFetch((method) => (method === "POST" ? response() : undefined));
    await expect(overrideTicket("t", OVERRIDE_BODY)).resolves.toBeNull();
  });

  // Q-fe-39 = A (chốt DỪNG 1 N4d): thân 201 mang Content-Type JSON mà rỗng/hỏng → client.ts ném khi đọc thân, KHÔNG phân
  // biệt được với refresh hỏng (khi đó ghi đè CHƯA được ghi) → KHÔNG được bắt để báo "đã ghi". Gửi lại → 409
  // already_overridden là đúng sự thật, không ghi trùng. Đừng "sửa" thành bắt SyntaxError.
  it("Q-fe-39 = A: 201 Content-Type JSON mà thân rỗng → client ném → hộp hiện lỗi chung, KHÔNG 'Đã ghi nhận ghi đè'", async () => {
    const empty = () => new Response("", { status: 201, headers: { "Content-Type": "application/json" } });
    stubFetch((method) => (method === "POST" ? empty() : undefined));
    await expect(overrideTicket("t", OVERRIDE_BODY)).rejects.toMatchObject({ name: "SyntaxError" });
    const dialog = await openOverride("tkt-q39");
    fillOverride(dialog, "Tự xử lý", "policy_gap", "");
    expect((await within(dialog).findByRole("alert")).textContent).toBe(errorMessage(null));
    expect(within(dialog).queryByRole("status")).toBeNull();
    expect(dialog.textContent).not.toContain("Đã ghi nhận ghi đè");
  });

  // Q-fe-41 = A (chốt DỪNG 2 N4d): route chỉ trả 201 khi ghi; 2xx khác (proxy sai…) = không chắc đã ghi → báo lỗi.
  it("Q-fe-41 = A: 200 + thân ĐÚNG dạng → ApiError 502 → hộp hiện lỗi chung, KHÔNG 'Đã ghi nhận ghi đè'; 202 / 204 cũng vậy", async () => {
    stubFetch((method) => (method === "POST" ? json(200, RECORDED) : undefined));
    await expect(overrideTicket("t", OVERRIDE_BODY)).rejects.toMatchObject({ status: 502, code: "unexpected_override_status" });
    const dialog = await openOverride("tkt-q41");
    fillOverride(dialog, "Tự xử lý", "policy_gap", "");
    expect((await within(dialog).findByRole("alert")).textContent).toBe(errorMessage(new ApiError(502, "unexpected_override_status")));
    expect(within(dialog).queryByRole("status")).toBeNull();
    expect(dialog.textContent).not.toContain("Đã ghi nhận ghi đè");
    for (const response of [() => json(202, RECORDED), () => new Response(null, { status: 204 })]) {
      stubFetch((method) => (method === "POST" ? response() : undefined));
      await expect(overrideTicket("t", OVERRIDE_BODY)).rejects.toBeInstanceOf(ApiError);
    }
  });

  it("overrideBody: ghi chú rỗng / chỉ khoảng trắng → KHÔNG khoá note; có → note đã cắt khoảng trắng", () => {
    expect(overrideBody("HITL", "policy_gap", "")).toStrictEqual({ override_decision: "HITL", reason_code: "policy_gap" });
    expect(overrideBody("HITL", "policy_gap", " \n\t ")).toStrictEqual({ override_decision: "HITL", reason_code: "policy_gap" });
    expect(overrideBody("L2", "other", "  Ca này nên chuyển L2.  ")).toStrictEqual({
      override_decision: "L2",
      reason_code: "other",
      note: "Ca này nên chuyển L2.",
    });
  });
});

// ------------------------------------------------------------------------------------------------ t89

describe("t89: sau 201 — câu xác nhận + quyết định ban đầu (server suy) + câu chung khi ghi chú bị che", () => {
  const NOTE = "Ca này lẽ ra phải chuyển L2.";

  async function sendWith(response: () => Response) {
    stubFetch((method) => (method === "POST" ? response() : undefined));
    const dialog = await openOverride("tkt-89");
    fillOverride(dialog, "Chuyển L2", "should_not_escalate", NOTE);
    const done = await within(dialog).findByTestId("override-done");
    expect(done.getAttribute("role")).toBe("status");
    expect(within(done).getByText(OVERRIDE_DONE)).toBeTruthy();
    expect(done.textContent).not.toContain(NOTE); // không nhắc lại ghi chú
    return done;
  }

  it("gốc HITL, notices [] → 'Quyết định ban đầu của hệ thống: Cần người duyệt'; KHÔNG câu notices", async () => {
    const done = await sendWith(() => json(201, RECORDED));
    expect(within(done).getByTestId("override-original").textContent).toBe("Quyết định ban đầu của hệ thống: Cần người duyệt");
    expect(within(done).queryByTestId("override-notices")).toBeNull();
    expect(done.textContent).not.toContain(NOTICES_TEXT);
  });

  it("notices ≠ [] → NOTICES_TEXT, KHÔNG nguyên văn notices; gốc AUTO → 'Tự xử lý'", async () => {
    const done = await sendWith(() => json(201, { ...RECORDED, original_decision: "AUTO", notices: ["NGUYEN-VAN-NOTICE"] }));
    expect(within(done).getByTestId("override-notices").textContent).toBe(NOTICES_TEXT);
    expect(within(done).getByTestId("override-original").textContent).toBe("Quyết định ban đầu của hệ thống: Tự xử lý");
    expect(document.body.textContent).not.toContain("NGUYEN-VAN-NOTICE");
  });

  it.each([
    ["gốc lạ (mã route nội bộ)", { original_decision: "ESCALATE_L2" }],
    ["gốc null", { original_decision: null }],
    ["thiếu khoá gốc", { original_decision: undefined }],
  ])("%s → chỉ câu xác nhận, KHÔNG dòng quyết định gốc, KHÔNG câu notices", async (_name, over) => {
    const done = await sendWith(() => json(201, { ...RECORDED, ...over }));
    expect(within(done).queryByTestId("override-original")).toBeNull();
    expect(within(done).queryByTestId("override-notices")).toBeNull();
    expect(done.textContent).toBe(OVERRIDE_DONE);
  });

  it("thân lạ ({status:'recorded'}) → vẫn 'Đã ghi nhận ghi đè.' (không báo lỗi giả), không chi tiết", async () => {
    const done = await sendWith(() => json(201, { status: "recorded" }));
    expect(done.textContent).toBe(OVERRIDE_DONE);
    expect(within(screen.getByRole("dialog", { name: "Ghi đè quyết định" })).queryByRole("alert")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t90

describe("t90: 422 invalid_request vì ghi chú → câu lỗi TẠI ô ghi chú; hộp không đóng, giữ dữ liệu đã nhập", () => {
  it.each([["note"], ["body.note"]])("fields ['%s'] → câu P4 dưới ô ghi chú (aria-invalid, aria-describedby); không alert chung; sửa ghi chú → mất lỗi", async (field) => {
    stubFetch((method) => (method === "POST" ? json(422, { error: "invalid_request", fields: [field] }) : undefined));
    const dialog = await openOverride("tkt-90");
    fillOverride(dialog, "Chỉ trả lời", "other", "​​"); // ký tự vô hình: qua kiểm ở client, server che xong rỗng
    const error = await within(dialog).findByTestId("override-note-error");
    expect(error.textContent).toBe(OVERRIDE_NOTE_INVALID);
    expect(OVERRIDE_NOTE_INVALID).toBe("Ghi chú không hợp lệ hoặc trống sau khi ẩn thông tin nhạy cảm — hãy viết lại ghi chú.");
    expect(error.getAttribute("role")).toBe("alert");
    const note = within(dialog).getByLabelText("Ghi chú ghi đè") as HTMLTextAreaElement;
    expect(note.getAttribute("aria-invalid")).toBe("true");
    expect(note.getAttribute("aria-describedby")).toBe(error.id);
    expect(within(dialog).getAllByRole("alert")).toHaveLength(1); // không thêm dòng lỗi chung
    expect(screen.getByRole("dialog", { name: "Ghi đè quyết định" })).toBe(dialog); // hộp không đóng
    expect(within(dialog).getByRole("radio", { name: /^Chỉ trả lời/ }).getAttribute("aria-checked")).toBe("true");
    expect((within(dialog).getByLabelText("Lý do") as HTMLSelectElement).value).toBe("other");
    expect(note.value).toBe("​​");
    expect(within(dialog).queryByRole("status")).toBeNull();
    fireEvent.change(note, { target: { value: "Ghi chú mới" } });
    expect(within(dialog).queryByTestId("override-note-error")).toBeNull();
    expect(note.getAttribute("aria-invalid")).toBeNull();
    expect(note.getAttribute("aria-describedby")).toBeNull();
  });

  it("fields ['override_decision'] → câu 422 chung, KHÔNG gắn ô ghi chú", async () => {
    stubFetch((method) => (method === "POST" ? json(422, { error: "invalid_request", fields: ["override_decision"] }) : undefined));
    const dialog = await openOverride("tkt-90b");
    fillOverride(dialog, "Tự xử lý", "policy_gap", "ghi chú");
    expect((await within(dialog).findByRole("alert")).textContent).toBe(errorMessage(new ApiError(422, "invalid_request")));
    expect(within(dialog).queryByTestId("override-note-error")).toBeNull();
    expect(within(dialog).getByLabelText("Ghi chú ghi đè").getAttribute("aria-invalid")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t91

describe("t91: câu lỗi của hộp ghi đè — 403 forbidden riêng; 404 (kể cả 'Not Found'); mã 4d → câu errors.ts", () => {
  it.each([
    ["403 forbidden (không quyền / tự ghi đè ticket của mình)", 403, { detail: "forbidden" }, OVERRIDE_FORBIDDEN],
    ["404 not_found", 404, { detail: "not_found" }, OVERRIDE_NOT_FOUND],
    ["404 'Not Found' (không có route)", 404, { detail: "Not Found" }, OVERRIDE_NOT_FOUND],
    ["409 ticket_open", 409, { detail: "ticket_open" }, errorMessage(new ApiError(409, "ticket_open"))],
    ["409 already_overridden", 409, { detail: "already_overridden" }, errorMessage(new ApiError(409, "already_overridden"))],
    ["422 same_as_original", 422, { detail: "same_as_original" }, errorMessage(new ApiError(422, "same_as_original"))],
    ["503 privacy_guard_unavailable", 503, { error: "privacy_guard_unavailable" }, errorMessage(new ApiError(503, "privacy_guard_unavailable"))],
  ])("%s → đúng câu, không lỗi ô ghi chú, không báo đã ghi", async (_name, status, body, text) => {
    stubFetch((method) => (method === "POST" ? json(status, body) : undefined));
    const dialog = await openOverride("tkt-91");
    fillOverride(dialog, "Tự xử lý", "approval_unnecessary", "");
    expect((await within(dialog).findByRole("alert")).textContent).toBe(text);
    expect(within(dialog).queryByTestId("override-note-error")).toBeNull();
    expect(within(dialog).queryByRole("status")).toBeNull();
    expect(document.body.textContent).not.toMatch(/có từ Phase 4/);
  });

  it("hằng câu + overrideErrorMessage thuần: P5 đúng chữ; 403 mã khác → câu 403 chung; lỗi không phải ApiError → câu mất kết nối", () => {
    expect(OVERRIDE_FORBIDDEN).toBe("Bạn không được ghi đè yêu cầu này (không có quyền, hoặc đây là yêu cầu do chính bạn gửi).");
    expect(OVERRIDE_NOT_FOUND).toBe("Không tìm thấy yêu cầu hoặc bạn không được xem yêu cầu này.");
    expect(overrideErrorMessage(new ApiError(403, null))).toBe(errorMessage(new ApiError(403, null)));
    expect(overrideErrorMessage(new ApiError(403, "reauth_required"))).toBe(errorMessage(new ApiError(403, "reauth_required")));
    expect(overrideErrorMessage(new TypeError("Failed to fetch"))).toBe(errorMessage(null));
  });
});

// ------------------------------------------------------------------------------------------------ t93

describe("t93: thẩm mỹ — dải chỉ đọc giữ 'L2' viết hoa; bảng khoá–giá trị: giá trị ngắn không ngắt dòng", () => {
  it("phiếu timeout → 'Phiếu hết hạn, đã chuyển L2 — …' (có 'L2', không 'l2'); câu từng trạng thái", async () => {
    stubFetch((_method, url) => {
      if (url === "/api/approvals/to") return json(200, viewOf("to", { status: "timeout" }));
      if (url.startsWith("/api/approvals?")) return inbox([listItem("to", { status: "timeout" })]);
      return undefined;
    });
    renderAt("/approvals/to");
    const strip = await screen.findByTestId("approval-readonly");
    expect(strip.textContent).toBe("Phiếu hết hạn, đã chuyển L2 — chỉ xem, không quyết định được nữa.");
    expect(strip.textContent).not.toMatch(/l2/);
    expect(screen.getByTestId("approval-status").textContent).toBe("Hết hạn — đã chuyển L2");
    expect(readonlyText("approved")).toBe("Phiếu đã đồng ý — chỉ xem, không quyết định được nữa.");
    expect(readonlyText("rejected")).toBe("Phiếu đã từ chối — chỉ xem, không quyết định được nữa.");
    expect(readonlyText("trạng_thái_lạ" as ApprovalStatus)).toBe("Phiếu không còn chờ duyệt — chỉ xem, không quyết định được nữa.");
  });

  // Không `whitespace-nowrap`: ô nằm trong khung `overflow-hidden` — nowrap + ký tự rộng sẽ bị cắt đuôi không dấu hiệu
  // (security-reviewer N4d NGHI-1). Ngắn = dòng flex-wrap: không vừa cạnh khoá thì cả giá trị xuống dòng dưới.
  it("FlatTable: ≤ 24 ký tự hiển thị → dòng flex-wrap, ô ml-auto max-w-full; 25 → cạnh khoá như cũ; KHÔNG ô nào nowrap; MỌI ô giữ min-w-0 wrap-anywhere break-normal; chữ = JSON", () => {
    const value = {
      policy_decision: "approval_required", // "approval_required" có ngoặc = 19 — ca lỗi F4
      exact: "x".repeat(22), // có ngoặc = đúng 24
      over: "y".repeat(23), // có ngoặc = 25
      prob: 0.5,
      reason: "Nhân viên chưa qua thử việc", // có ngoặc = 29, có khoảng trắng
    };
    render(<FlatTable value={value} testId="kv" />);
    const row = (key: string) => document.querySelector<HTMLElement>(`[data-testid="kv"][data-key="${key}"]`)!;
    const cls = (el: Element) => el.className.split(/\s+/);
    for (const key of ["policy_decision", "exact", "prob"]) {
      expect(cls(row(key))).toContain("flex-wrap");
      expect(cls(row(key).querySelector("dd")!)).toEqual(expect.arrayContaining(["ml-auto", "max-w-full"]));
    }
    for (const key of ["over", "reason"]) {
      expect(cls(row(key))).not.toContain("flex-wrap");
      expect(cls(row(key).querySelector("dd")!)).not.toContain("ml-auto");
    }
    for (const [key, raw] of Object.entries(value)) {
      const dd = row(key).querySelector("dd")!;
      expect(cls(dd)).toEqual(expect.arrayContaining(["min-w-0", "wrap-anywhere", "break-normal"]));
      expect(cls(dd)).not.toContain("break-all");
      expect(cls(dd).some((c) => c.startsWith("whitespace-") || c === "shrink-0")).toBe(false); // không bao giờ bị cắt
      expect(dd.textContent).toBe(JSON.stringify(raw));
    }
    expect(SHORT_VALUE_MAX).toBe(24);
    expect(isShortValue(`"${"x".repeat(22)}"`)).toBe(true);
    expect(isShortValue(`"${"x".repeat(23)}"`)).toBe(false);
    expect(isShortValue('"Ngoài giờ hành chính"')).toBe(true); // đếm theo ký tự, không theo byte
  });
});

// ------------------------------------------------------------------------------------------------ t124 (N-PROTO)

describe("t124: L1 — status / action_type / vai trò người gửi '__proto__' / 'constructor' / 'toString' → dự phòng, màn không vỡ", () => {
  const PROTO_KEYS = ["__proto__", "constructor", "toString"];
  const childErrors = () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    return () => spy.mock.calls.filter((args) => args.some((a) => String(a).includes("React child")));
  };
  const noLeak = () => expect(document.body.textContent).not.toMatch(/function |\[object /);

  it("readonlyText / actionLabel: khoá prototype → câu 'không còn chờ duyệt' / hiện nguyên mã; khoá hợp lệ giữ nhãn cũ", () => {
    for (const key of PROTO_KEYS) {
      expect(readonlyText(key as ApprovalStatus)).toBe("Phiếu không còn chờ duyệt — chỉ xem, không quyết định được nữa.");
      expect(actionLabel(key)).toBe(`Khác · ${key}`); // N-NGU: mã lạ → "Khác · mã"
    }
    expect(readonlyText("rejected")).toBe("Phiếu đã từ chối — chỉ xem, không quyết định được nữa.");
    expect(actionLabel("renew_vpn_cert")).toBe("Cấp lại chứng chỉ VPN");
  });

  it.each(PROTO_KEYS)("chi tiết phiếu: status %j → nhãn trạng thái trống + dải chỉ đọc chung; vai trò người gửi cùng khoá → hiện nguyên", async (key) => {
    const errors = childErrors();
    stubFetch((_method, url) =>
      url === "/api/approvals/p"
        ? json(200, viewOf("p", { status: key as ApprovalStatus, requester: { role: key, department: null }, action: { ...NESTED_ACTION, type: key } }))
        : undefined,
    );
    renderAt("/approvals/p");
    expect((await screen.findByTestId("approval-status")).textContent).toBe("");
    expect(screen.getByTestId("approval-readonly").textContent).toBe("Phiếu không còn chờ duyệt — chỉ xem, không quyết định được nữa.");
    expect(screen.getByText("Vai trò", { selector: "dt" }).nextElementSibling?.textContent).toBe(key);
    expect(screen.getByText(`Khác · ${key}`, { selector: "p.text-heading" })).toBeTruthy(); // N-NGU: tiêu đề hành động lạ = "Khác · mã"
    expect(errors()).toHaveLength(0);
    noLeak();
  });

  it("chi tiết phiếu: status + vai trò hợp lệ vẫn ra nhãn cũ", async () => {
    stubFetch((_method, url) =>
      url === "/api/approvals/q" ? json(200, viewOf("q", { status: "approved", requester: { role: "l2", department: null } })) : undefined,
    );
    renderAt("/approvals/q");
    expect((await screen.findByTestId("approval-status")).textContent).toBe("Đã đồng ý");
    expect(screen.getByText("Vai trò", { selector: "dt" }).nextElementSibling?.textContent).toBe("Kỹ thuật viên L2");
  });

  it("hộp thư tab 'Đã quyết': status prototype → ô thời gian trống, action_type → nguyên mã; status hợp lệ giữ nhãn", async () => {
    const errors = childErrors();
    const odd = PROTO_KEYS.map((key, i) => listItem(`o${i}`, { status: key as ApprovalStatus, action_type: key, deadline: at(i) }));
    stubFetch((_method, url) => {
      if (url.endsWith("status=approved")) return inbox([...odd, listItem("ok", { status: "approved", deadline: at(9) })]);
      if (url.startsWith("/api/approvals?")) return inbox([]);
      return undefined;
    });
    renderAt("/approvals");
    fireEvent.click(await screen.findByRole("tab", { name: "Đã quyết" }));
    await waitFor(() => expect(rowIds()).toStrictEqual(["o0", "o1", "o2", "ok"]));
    const rows = screen.getAllByTestId("inbox-row");
    PROTO_KEYS.forEach((key, i) => {
      expect(within(rows[i]!).getByTestId("inbox-time").textContent).toBe("");
      expect(rows[i]!.textContent).toContain(key);
    });
    expect(within(rows[3]!).getByTestId("inbox-time").textContent).toBe("Đã đồng ý");
    expect(errors()).toHaveLength(0);
    noLeak();
  });
});

// ------------------------------------------------------------------------------------------------ t142 (F6 #76, R3 #76)

describe("t142: hàm thuần — nhãn rủi ro, quản lý, hạn tuyệt đối", () => {
  it("riskSummary: nhãn theo bảng; giá trị lạ → nguyên mã; LLM chưa hiệu chỉnh mới có câu 'chưa hiệu chỉnh'", () => {
    // N-NGU: hướng xử lý / bên quyết định / luật = cặp "Nhãn · mã" (bảng ĐP 23:10); luật kèm mô tả từ matched_rules.
    expect(riskSummary(RISK_VIEW)).toMatchObject({
      level: "Trung bình",
      route: { nhan: "Chờ IT duyệt", ma: "HITL" },
      rule: { nhan: "Luật chưa có mô tả", ma: "R18" },
      source: { nhan: "Theo luật", ma: "rule" },
      note: null,
    });
    expect(riskSummary(RISK_VIEW, [{ rule_id: "R18", description: "Ngoài giờ cần duyệt", decision: "approval_required", applied: true }]).rule).toStrictEqual({
      nhan: "Ngoài giờ cần duyệt",
      ma: "R18",
    });
    expect(riskSummary({ ...RISK_VIEW, risk_level: "low", route: "AUTO" })).toMatchObject({ level: "Thấp", route: { nhan: "Tự xử lý", ma: "AUTO" } });
    expect(riskSummary({ ...RISK_VIEW, risk_level: "high", route: "ESCALATE_L2" })).toMatchObject({ level: "Cao", route: { nhan: "Chuyển kỹ thuật viên L2" } });
    expect(riskSummary({ ...RISK_VIEW, risk_level: "toString" as never, route: "constructor" as never })).toMatchObject({
      level: "toString",
      route: { nhan: "Khác", ma: "constructor" },
    });
    const llm = { ...RISK_VIEW, decided_by: "llm" as const, matched_rule_id: null, policy_decision: null };
    expect(riskSummary(llm).note).toBe(UNCALIBRATED_TEXT);
    expect(UNCALIBRATED_TEXT).toBe("Chưa hiệu chỉnh, không tự xử lý");
    expect(riskSummary({ ...llm, calibrated_prob: 0.4, calibrated: true }).note).toBeNull(); // đã hiệu chỉnh → không câu
    expect(riskSummary({ ...RISK_VIEW, calibrated: false }).note).toBeNull(); // luật (rule) không bao giờ có câu này
  });

  it("managerText: known có tên / không tên; unknown → 'Chưa rõ quản lý', KHÔNG 'không có quản lý'", () => {
    expect(managerText({ status: "known", user_id: "m-1", full_name: "Lê Thị Hạnh" })).toBe("Lê Thị Hạnh (m-1)");
    expect(managerText({ status: "known", user_id: "m-1", full_name: null })).toBe("m-1 (chưa có tên)");
    expect(managerText({ status: "unknown", user_id: null, full_name: null })).toBe(MANAGER_UNKNOWN_TEXT);
    expect(MANAGER_UNKNOWN_TEXT).not.toMatch(/không có quản lý/i);
  });

  it("deadlineText: giờ Việt Nam; null / không phải chuỗi / không phải thời điểm → null", () => {
    expect(deadlineText("2026-09-30T14:30:00Z")).toBe("21:30 30/09/2026");
    expect(deadlineText("2026-09-30T17:05:00+00:00")).toBe("00:05 01/10/2026"); // qua nửa đêm giờ VN
    for (const bad of [null, undefined, "", "không phải ngày", 0, 1.7e12, {}, []]) expect(deadlineText(bad)).toBeNull();
  });
});

describe("t143: màn chi tiết phiếu — người bị ảnh hưởng, mức rủi ro, hạn duyệt", () => {
  const txt = (id: string) => screen.getByTestId(id).textContent;

  function open(over: Partial<ApprovalViewP4>, path = "/approvals/f6") {
    stubFetch((_method, url) => {
      if (url === "/api/approvals/f6") return json(200, viewOf("f6", over));
      if (url.startsWith("/api/approvals?")) return inbox([listItem("f6")]);
      return undefined;
    });
    renderAt(path);
  }

  it("người bị ảnh hưởng = người gửi: tài khoản, phòng ban, quản lý có tên; KHÔNG có dải 'khác người gửi'", async () => {
    open({});
    await screen.findByTestId("affected");
    expect(txt("affected-user")).toBe("nv001");
    expect(txt("affected-relation")).toBe("Chính người gửi yêu cầu");
    expect(txt("affected-department")).toBe("Finance");
    expect(txt("affected-manager")).toBe("Lê Thị Hạnh (mgr01)");
    expect(screen.queryByTestId("affected-other")).toBeNull();
  });

  it("khác người gửi → dải cảnh báo 'Khác người gửi yêu cầu'; quản lý chưa rõ; phòng ban null → '—'", async () => {
    open({
      affected: { user_id: "nv006", is_requester: false, department: null, manager: { status: "unknown", user_id: null, full_name: null } },
    });
    await screen.findByTestId("affected");
    expect(txt("affected-user")).toBe("nv006");
    expect(screen.getByTestId("affected-other").textContent).toContain("Khác người gửi yêu cầu");
    expect(txt("affected-relation")).toBe("Khác người gửi yêu cầu");
    expect(txt("affected-department")).toBe("—");
    expect(txt("affected-manager")).toBe("Chưa rõ quản lý");
    expect(txt("affected-manager")).not.toMatch(/không có quản lý/i);
    expect(screen.getByTestId("affected-manager").dataset.known).toBe("false");
  });

  it("quản lý known mà sếp chưa có tên → 'id (chưa có tên)'", async () => {
    open({ affected: { ...AFFECTED, manager: { status: "known", user_id: "mgr02", full_name: null } } });
    await screen.findByTestId("affected");
    expect(txt("affected-manager")).toBe("mgr02 (chưa có tên)");
  });

  it("mức rủi ro: nhãn Việt, hướng xử lý, lý do, luật khớp, nguồn; bảng gốc vẫn còn; luật không có câu 'chưa hiệu chỉnh'", async () => {
    open({});
    await screen.findByTestId("risk-summary");
    expect(txt("risk-level")).toBe("Trung bình");
    expect(screen.getByTestId("risk-level").dataset.level).toBe("medium");
    expect(txt("risk-route")).toBe("Chờ IT duyệt · HITL"); // N-NGU: "Nhãn · mã"
    expect(txt("risk-reason")).toBe("Ngoài giờ hành chính");
    expect(txt("risk-rule")).toBe(`${txt("risk-rule").split(" · ")[0]} · R18`); // N-NGU: "Mô tả · R18"
    expect(txt("risk-rule")).not.toBe("R18");
    expect(txt("risk-source")).toBe("Theo luật · rule");
    expect(screen.queryByTestId("risk-uncalibrated")).toBeNull();
    expect(screen.getAllByTestId("risk-row").length).toBeGreaterThan(0);
  });

  it("mức Cao + LLM chưa hiệu chỉnh → nhãn 'Cao' và câu 'Chưa hiệu chỉnh, không tự xử lý'; luật khớp '—'", async () => {
    open({
      risk: { decided_by: "llm", matched_rule_id: null, reason: "x", thresholds: null },
      risk_view: { ...RISK_VIEW, decided_by: "llm", policy_decision: null, matched_rule_id: null, raw_prob: 0.6, p_method: "self_report", risk_level: "high" },
    });
    await screen.findByTestId("risk-summary");
    expect(txt("risk-level")).toBe("Cao");
    expect(txt("risk-rule")).toBe("—");
    expect(txt("risk-source")).toBe("Theo đánh giá của AI · llm"); // N-NGU
    expect(txt("risk-uncalibrated")).toBe(UNCALIBRATED_TEXT);
  });

  it("LLM đã hiệu chỉnh → không có câu 'chưa hiệu chỉnh'", async () => {
    open({
      risk_view: { ...RISK_VIEW, decided_by: "llm", policy_decision: null, matched_rule_id: null, calibrated_prob: 0.4, calibrated: true, thresholds: [0.3, 0.7] },
    });
    await screen.findByTestId("risk-summary");
    expect(screen.queryByTestId("risk-uncalibrated")).toBeNull();
  });

  it("risk null (và risk_view null) → câu 'chưa có đánh giá', không bảng tóm tắt, thanh quyết định vẫn có", async () => {
    open({ risk: null, risk_view: null });
    await screen.findByTestId("risk-missing");
    expect(screen.queryByTestId("risk-summary")).toBeNull();
    expect(screen.queryByTestId("risk-uncalibrated")).toBeNull();
    expect(screen.getByTestId("decision-bar")).toBeTruthy();
  });

  it("hạn duyệt: đồng hồ đếm ngược VÀ mốc tuyệt đối giờ Việt Nam", async () => {
    open({ deadline: "2099-09-30T14:30:00Z" });
    await screen.findByTestId("approval-deadline");
    expect(txt("approval-deadline-at")).toBe("21:30 30/09/2099");
  });

  it("hạn hỏng (không phải thời điểm) → không hiện mốc tuyệt đối, màn không vỡ", async () => {
    open({ deadline: "không phải ngày" });
    await screen.findByTestId("request-summary");
    expect(screen.queryByTestId("approval-deadline-at")).toBeNull();
  });

  it("viewer: vẫn thấy người bị ảnh hưởng + rủi ro, KHÔNG có thanh quyết định", async () => {
    open({ role_as: "viewer" });
    await screen.findByTestId("viewer-note");
    expect(txt("affected-user")).toBe("nv001");
    expect(txt("risk-level")).toBe("Trung bình");
    expect(screen.queryByTestId("decision-bar")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Đồng ý/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Từ chối/ })).toBeNull();
  });

  it("primary: có thanh quyết định (đối chứng của ca viewer)", async () => {
    open({});
    await screen.findByTestId("affected");
    expect(screen.getByTestId("decision-bar")).toBeTruthy();
  });
});

describe("t144: fail-closed — phiếu thiếu / sai kiểu người bị ảnh hưởng hoặc rủi ro → không hiện phiếu, KHÔNG thanh quyết định", () => {
  async function expectBlocked(over: Record<string, unknown>) {
    stubFetch((_method, url) => {
      if (url === "/api/approvals/bad") return json(200, { ...viewOf("bad"), ...over });
      if (url.startsWith("/api/approvals?")) return inbox([listItem("bad")]);
      return undefined;
    });
    renderAt("/approvals/bad");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(new ApiError(502, "invalid_approval_body")));
    expect(alert.textContent).not.toContain("invalid_approval_body");
    expect(screen.queryByTestId("decision-bar")).toBeNull();
    expect(screen.queryByTestId("affected")).toBeNull();
    expect(screen.queryByTestId("action-hash")).toBeNull(); // không hiện nửa phiếu
    expect(screen.queryByRole("button", { name: /^Đồng ý/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Từ chối/ })).toBeNull();
  }

  it("thiếu affected", () => expectBlocked({ affected: undefined }));
  it("affected sai kiểu (user_id số)", () => expectBlocked({ affected: { ...AFFECTED, user_id: 5 } }));
  it("manager.status lạ", () => expectBlocked({ affected: { ...AFFECTED, manager: { status: "none", user_id: null, full_name: null } } }));
  it("risk_view sai enum (risk_level 'critical')", () => expectBlocked({ risk_view: { ...RISK_VIEW, risk_level: "critical" } }));
  it("risk_view null mà risk có", () => expectBlocked({ risk_view: null }));
});

describe("t145: màn xem ticket (ghi đè) — hạn của lần chờ hiện tại", () => {
  const T = "tkt-145";
  const ticket = (over: Record<string, unknown>) => ({
    ticket_id: T,
    status: "S_PENDING_APPROVAL",
    waiting_for: "approval",
    conversation: [],
    exit_code: null,
    close_reason: null,
    final_state: null,
    created_at: "2026-09-30T13:00:00Z",
    closed_at: null,
    deadline: null,
    ...over,
  });

  async function show(over: Record<string, unknown>) {
    stubFetch((_method, url) => (url === `/api/tickets/${T}` ? json(200, ticket(over)) : undefined));
    renderAt(`/approvals/ticket/${T}`);
    await screen.findByTestId("ticket-state");
  }

  it("deadline là mốc → 'Hạn của lần chờ hiện tại 21:30 30/09/2026'", async () => {
    await show({ deadline: "2026-09-30T14:30:00Z" });
    expect(screen.getByTestId("ticket-deadline").textContent).toBe("21:30 30/09/2026");
    expect(screen.getByTestId("ticket-state").textContent).toContain("Hạn của lần chờ hiện tại");
  });

  it("deadline null → không hiện gì (không '—', không 'Hạn')", async () => {
    await show({ deadline: null });
    expect(screen.queryByTestId("ticket-deadline")).toBeNull();
    expect(screen.getByTestId("ticket-state").textContent).not.toMatch(/Hạn/);
  });

  it("thiếu khoá deadline (backend/fixture cũ) hoặc sai kiểu → không hiện, màn không vỡ", async () => {
    await show({ deadline: undefined });
    expect(screen.queryByTestId("ticket-deadline")).toBeNull();
    cleanup();
    await show({ deadline: 1234 });
    expect(screen.queryByTestId("ticket-deadline")).toBeNull();
    cleanup();
    await show({ deadline: "không phải ngày" });
    expect(screen.queryByTestId("ticket-deadline")).toBeNull();
  });

  it("ticket đã kết thúc → không hiện hạn dù thân có chuỗi (không còn lần chờ)", async () => {
    await show({ final_state: "S_CLOSED", deadline: "2026-09-30T14:30:00Z" });
    expect(screen.queryByTestId("ticket-deadline")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t231 (đợt 2 tên gọi, B1)

describe("t231: B1 — tiêu đề phiếu là tên hành động; mã phiếu + mã yêu cầu ở dòng dưới", () => {
  it("h1 = 'Cấp lại chứng chỉ VPN'; dòng dưới có 'Phiếu r' và 'Mã yêu cầu'; không còn 'Mã ticket'", async () => {
    detailApi(() => json(202, {}));
    renderAt("/approvals/r");
    await screen.findByTestId("decision-bar");
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toBe("Cấp lại chứng chỉ VPN");
    const meta = h1.nextElementSibling?.textContent ?? "";
    expect(meta).toContain("Phiếu r");
    expect(meta).toContain("Mã yêu cầu");
    expect(document.body.textContent).not.toContain("Mã ticket");
  });
});

// ------------------------------------------------------------------------------------------------ t232 (đợt 2 tên gọi, B2 — phương án (b))

describe("t232: B2 (b) — nhãn 1-1, công tắc 'Hiện giá trị gốc' mặc định tắt; gốc luôn trong DOM; danh tính luôn hiện gốc", () => {
  // Object có khoá đã biết, khoá lạ, giá trị lạ, giá trị trùng tên thuộc tính prototype, mảng, null.
  const ACTION = {
    type: "grant_permission",
    target: "folder:finance/Q3",
    requested_for: "nv001",
    scope: "single_account",
    privilege_level: "elevated",
    reversible: false,
    reversibility: "none",
    data_sensitivity: "constructor",
    params: { resource_path: "finance/Q3", permission_level: "write", duration_days: 30, account_type: "__proto__", software_name: "Visio" },
    facts: { cert_status: "expired", device_registered: true, cert_days_to_expiry: -3, khoa_moi: "gia_tri_moi" },
    khoa_la: { x: null, y: [1, "a"] },
  };
  /** Giá trị tại đường dẫn — viết RIÊNG ở test, không dùng flattenEntries. */
  const at = (path: string): unknown =>
    path.split(/\.|\[(\d+)\]/).filter(Boolean).reduce<unknown>((v, k) => (v as Record<string, unknown>)[k], ACTION);
  const LABELED: Record<string, string> = {
    type: "Cấp quyền truy cập",
    target: "Thư mục finance/Q3",
    scope: "Một tài khoản",
    privilege_level: "Quyền nâng cao",
    reversible: "Không",
    reversibility: "Không hoàn tác được",
    "params.permission_level": "Đọc và ghi",
    "params.duration_days": "30 ngày",
    "facts.cert_status": "Đã hết hạn",
    "facts.device_registered": "Có",
  };
  /** Điều kiện 2: trường danh tính luôn hiện gốc (phần sau ":" của target nằm nguyên trong nhãn). */
  const IDENTITY = ["requested_for", "params.resource_path", "params.software_name"];
  const raw = (row: HTMLElement) => within(row).getByTestId("raw-value");

  it("mặc định TẮT: dòng có nhãn → nhãn hiện, gốc vẫn trong DOM nhưng hidden; dòng không nhãn → gốc hiện; đủ khoá, đúng thứ tự", () => {
    render(<ActionView action={ACTION} hash={"a".repeat(64)} title="Cấp quyền truy cập" />);
    const toggle = screen.getByRole("button", { name: SHOW_RAW_TEXT });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    const rows = screen.getAllByTestId("action-row");
    expect(rows.map((r) => r.dataset.key)).toStrictEqual(jsonKeyPaths(ACTION)); // đủ, không trùng, không sắp lại
    for (const row of rows) {
      const key = row.dataset.key!;
      expect(raw(row).textContent).toBe(JSON.stringify(at(key))); // gốc KHÔNG bị bỏ, kể cả khi ẩn
      const label = within(row).queryByTestId("value-label");
      if (Object.hasOwn(LABELED, key)) {
        expect(label?.textContent).toBe(LABELED[key]);
        expect(raw(row).hidden).toBe(true);
      } else {
        expect(label).toBeNull(); // requested_for, "constructor", "__proto__", khoá lạ, null, mảng → không đoán
        expect(raw(row).hidden).toBe(false);
      }
    }
    for (const key of IDENTITY) expect(raw(rows.find((r) => r.dataset.key === key)!).hidden).toBe(false);
    // Điều kiện 4: mã băm rút gọn + câu chú thích ở đầu bảng; mã đủ ở chân.
    expect(screen.getByTestId("action-hash-short").textContent).toBe(`${"a".repeat(12)}…`);
    expect(screen.getByTestId("raw-note").textContent).toBe(RAW_NOTE);
    expect(screen.getByTestId("action-hash").textContent).toBe("a".repeat(64));
    // nhãn khoá: params/facts riêng; khoá lạ chỉ hiện khoá
    const dt = (key: string) => rows.find((r) => r.dataset.key === key)!.querySelector("dt")!.textContent;
    expect(dt("params.permission_level")).toBe("Mức quyền xin cấp · params.permission_level");
    expect(dt("facts.cert_status")).toBe("Trạng thái chứng chỉ · facts.cert_status");
    expect(dt("facts.khoa_moi")).toBe("Dữ kiện · facts.khoa_moi");
    expect(dt("khoa_la.x")).toBe("khoa_la.x");
  });

  it("BẬT: mọi dòng hiện gốc, textContent === JSON.stringify từng ký tự; tab JSON === JSON.stringify(action, null, 2)", () => {
    render(<ActionView action={ACTION} hash={"b".repeat(64)} title="Cấp quyền truy cập" />);
    fireEvent.click(screen.getByRole("button", { name: SHOW_RAW_TEXT }));
    expect(screen.getByRole("button", { name: SHOW_RAW_TEXT }).getAttribute("aria-pressed")).toBe("true");
    for (const row of screen.getAllByTestId("action-row")) {
      expect(raw(row).hidden).toBe(false);
      expect(raw(row).textContent).toBe(JSON.stringify(at(row.dataset.key!)));
    }
    fireEvent.click(screen.getByRole("tab", { name: "JSON" }));
    expect(screen.getByTestId("action-json").textContent).toBe(JSON.stringify(ACTION, null, 2));
    expect(screen.getByTestId("action-hash").textContent).toBe("b".repeat(64));
  });

  it("điều kiện 6: không nhớ sang phiếu khác — bật ở phiếu này, mở phiếu khác (dựng lại) → TẮT", () => {
    const { rerender } = render(<ActionView key="p1" action={ACTION} hash={"c".repeat(64)} title="x" />);
    fireEvent.click(screen.getByRole("button", { name: SHOW_RAW_TEXT }));
    expect(screen.getByRole("button", { name: SHOW_RAW_TEXT }).getAttribute("aria-pressed")).toBe("true");
    rerender(<ActionView key="p2" action={ACTION} hash={"c".repeat(64)} title="x" />);
    expect(screen.getByRole("button", { name: SHOW_RAW_TEXT }).getAttribute("aria-pressed")).toBe("false");
  });

  it("bảng khác (rủi ro, dữ kiện, chính sách) không nhận nhãn giá trị: FlatTable mặc định không có raw-value/value-label", () => {
    render(<FlatTable value={{ scope: "single_device", reversible: true }} testId="kv" />);
    expect(screen.queryByTestId("raw-value")).toBeNull();
    expect(screen.queryByTestId("value-label")).toBeNull();
  });
});
