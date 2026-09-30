// F4 — L1: hộp thư duyệt, chi tiết phiếu, quyết định, ghi đè. Không gọi backend: fetch giả trả đúng dạng spec
// (phase4-thiet-ke-chi-tiet.md 1.0: 4c P5 hộp thư, P6 xem phiếu, 4d P1–P4 ghi đè; backend/app/api/approvals.py decision).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { overrideTicket } from "../../api/approvals.ts";
import { type AuthChannel, createClient } from "../../api/client.ts";
import { errorMessage, ApiError, GENERIC_LOGIN_ERROR } from "../../api/errors.ts";
import { offsetFrom, recordServerDate, serverNow } from "../../api/serverClock.ts";
import type { ApprovalListItem, ApprovalViewP4, Me } from "../../api/types.ts";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { AuthProvider } from "../../auth/AuthProvider.tsx";
import { RequirePerm } from "../../auth/RequireAuth.tsx";
import { useAuth } from "../../auth/useAuth.ts";
import { ActionView } from "../../components/ActionView.tsx";
import { FlashNotice } from "../../components/FlashNotice.tsx";
import { OverrideDialog } from "../../components/OverrideDialog.tsx";
import { ApprovalDetailRoute } from "./ApprovalDetail.tsx";
import { ApprovalQueue } from "./ApprovalQueue.tsx";
import {
  BACKUP_TEXT,
  DECISION_SENT,
  INBOX_MISSING_TITLE,
  isUrgent,
  NOTICES_TEXT,
  PLAN_CHANGED_TEXT,
  remainingShort,
  sortByDeadline,
  TICKET_UNAVAILABLE,
  VIEW_NOT_FOUND_TEXT,
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
    ...over,
  };
}

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

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
    const calls = stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? json(200, [c, a, b]) : undefined));
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
      if (url.endsWith("status=pending")) return json(200, []);
      if (url.endsWith("status=approved")) return json(200, [approved]);
      if (url.endsWith("status=rejected")) return json(200, [rejected]);
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
    stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? json(200, [item], { Date: new Date(T0).toUTCString() }) : undefined));
    renderAt("/approvals");
    const time = await screen.findByTestId("inbox-time");
    expect(time.textContent).toBe("còn 5 phút");
    expect(screen.getByTestId("inbox-row").dataset.urgent).toBe("true");
  });

  it("thiếu header Date → độ lệch 0: giờ máy nhanh 10 phút thì thấy đã quá hạn", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: T0 + 10 * MIN });
    stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? json(200, [item]) : undefined));
    renderAt("/approvals");
    expect((await screen.findByTestId("inbox-time")).textContent).toBe("đã quá hạn");
  });

  it("chi tiết: đồng hồ 'Còn mm:ss / 30 phút' theo giờ máy chủ", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: T0 - 7 * MIN });
    const date = { Date: new Date(T0).toUTCString() };
    stubFetch((_method, url) => {
      if (url === "/api/approvals/d") return json(200, viewOf("d", { deadline: at(5) }), date);
      if (url.startsWith("/api/approvals?")) return json(200, [item], date);
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
    expect(document.querySelector('[data-key="type"] dd')?.textContent).toBe('"renew_vpn_cert"');

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
      if (url.startsWith("/api/approvals?")) return json(200, [listItem("h")]);
      return undefined;
    });
    renderAt("/approvals/h");
    expect((await screen.findByTestId("request-summary")).textContent).toBe("VPN báo chứng chỉ hết hạn trên máy LAP-0342.");
    expect(screen.getByTestId("procedure").textContent).toContain("Gia hạn và cấp lại chứng chỉ VPN");
    expect(screen.getAllByTestId("risk-row").map((r) => r.dataset.key)).toStrictEqual(["decided_by", "matched_rule_id", "reason", "thresholds"]);
    expect(screen.getAllByTestId("fact-row").map((r) => r.dataset.key)).toStrictEqual(["cert_status"]);
    expect(screen.getAllByTestId("action-row")).toHaveLength(EXPECTED.length);
    expect(screen.getByTestId("action-hash").textContent).toBe(HASH);
    expect(screen.getByText("Finance")).toBeTruthy();
    expect(screen.queryByTestId("backup-banner")).toBeNull();
    expect(screen.getByRole("button", { name: /^Đồng ý/ })).toBeTruthy();
  });

  it("không có tiêu đề quy trình → hiện doc_id; dự phòng → dải 'Bạn duyệt với vai trò dự phòng'", async () => {
    stubFetch((_method, url) => {
      if (url === "/api/approvals/k") return json(200, viewOf("k", { procedure: { doc_id: "KB-VPN-004" }, role_as: "backup" }));
      if (url.startsWith("/api/approvals?")) return json(200, [listItem("k", { role_as: "backup" })]);
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
      if (url.startsWith("/api/approvals?")) return json(200, [listItem("ok", { status: "approved" })]);
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
    if (url.startsWith("/api/approvals?")) return json(200, [listItem("r")]);
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
      if (url.startsWith("/api/approvals?")) return json(200, [listItem("r")]);
      return undefined;
    });
    renderAt("/approvals/r");
    fireEvent.click(await screen.findByRole("button", { name: /^Đồng ý/ }));
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

describe("t46: MSW tắt + hộp thư 404 (route chưa có) → trang 'có từ Phase 4', không lỗi đỏ", () => {
  it("404 'Not Found' của Starlette → tiêu đề Phase 4 (4c); không alert, không tab; ô mã ticket vẫn dùng được", async () => {
    const calls = stubFetch((_method, url) => (url.startsWith("/api/approvals?") ? json(404, { detail: "Not Found" }) : undefined));
    renderAt("/approvals");
    const box = await screen.findByTestId("inbox-missing");
    expect(within(box).getByRole("heading").textContent).toBe(INBOX_MISSING_TITLE);
    expect(INBOX_MISSING_TITLE).toBe("Hộp thư duyệt có từ Phase 4 (4c)");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByLabelText("Mã ticket")).toBeTruthy();
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

  it("route chưa có (404 'Not Found') → 'Ghi đè có từ Phase 4 (4d)'", async () => {
    stubFetch((method) => (method === "POST" ? json(404, { detail: "Not Found" }) : undefined));
    const dialog = await openOverride("tkt-z");
    fillOverride(dialog, "Cần người duyệt", "policy_gap", "");
    expect((await within(dialog).findByRole("alert")).textContent).toContain("Ghi đè có từ Phase 4 (4d)");
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
      if (url.startsWith("/api/approvals?")) return json(200, [listItem("dq", { status: "approved" }), listItem("pq")]);
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
    fireEvent.click(await screen.findByRole("button", { name: /^Đồng ý/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(new ApiError(403, "forbidden")));
    expect(alert.textContent).toBe("Bạn không có quyền thực hiện thao tác này.");
    expect(document.body.textContent).not.toMatch(/xung đột|quản lý|forbidden|permission_denied/i);
    expect(screen.queryByTestId("decision-sent")).toBeNull();
    expect((screen.getByRole("button", { name: /^Đồng ý/ }) as HTMLButtonElement).disabled).toBe(false);
    expect(posts(calls, "/decision")).toHaveLength(1);
  });
});
