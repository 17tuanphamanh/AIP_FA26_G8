// N-TB — chuông thông báo + đồng hồ chờ IT duyệt của nhân viên (ĐP 26/10; hợp đồng thông báo §1, §2; bổ sung ĐP 23:51:
// không hiện link/mã ticket mới). Không gọi backend: fetch giả. t200–t216.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors.ts";
import { isIsoWithZone } from "../api/iso.ts";
import { notificationsPath, parseNotificationPage } from "../api/notifications.ts";
import type { Me, NotificationItem, NotificationPage, TicketView } from "../api/types.ts";
import { AuthContext, type AuthValue } from "../auth/context.ts";
import { Sidebar } from "../components/Sidebar.tsx";
import { lastSeenKey, readLastSeen, writeLastSeen } from "../lib/lastSeen.ts";
import { CAU_THONG_BAO, cauThongBao, KET_QUA_THONG_BAO } from "../lib/nhan.ts";
import { createMulti, viewOf } from "../mocks/fixtures/multi.ts";
import { createDuyet, createNotifications, DUYET_SAP_HET, duyetView, pageOf } from "../mocks/fixtures/notifications.ts";
import { clockDeadline, EXPIRED_TEXT, FIVE_MIN_TEXT } from "./employee/approvalClock.ts";
import { ChatRoute } from "./employee/ChatPage.tsx";
import { sessionTickets } from "./employee/sessionTickets.ts";

const clients: QueryClient[] = [];
const undo: (() => void)[] = [];
beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  for (const f of undo.splice(0)) f();
  for (const c of clients.splice(0)) c.clear();
  sessionTickets.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.localStorage.clear();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const MA_NOI_BO = /\bE\d\b|\bB\d{1,2}\b|\bR\d+\b|S_[A-Z]/;
const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
const EMP: Me = { user_id: "an.nv", role: "employee", permissions: BASE };
const EMP2: Me = { user_id: "binh.tt", role: "employee", permissions: BASE };
const L2: Me = { user_id: "long.nh", role: "l2", permissions: ["ticket:read:any", "escalation:handle"] };
const signedIn = (me: Me): AuthValue => ({ state: { status: "signedIn", me }, signIn: vi.fn(), signOut: vi.fn(async () => true) });

function spaced(el: Node): string {
  const out: string[] = [];
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) out.push(n.textContent ?? "");
  return out.join(" ");
}

const T0 = Date.parse("2026-10-26T09:00:00Z");
const at = (minAgo: number) => new Date(T0 - minAgo * 60_000).toISOString();
function item(over: Partial<NotificationItem> & { id: string }): NotificationItem {
  return {
    kind: "approval_decided",
    ticket_id: `tkt-${over.id.replace(/\W/g, "")}`,
    text: "IT đã duyệt yêu cầu cấp quyền thư mục của bạn.",
    result: "approved",
    new_ticket_id: null,
    created_at: at(1),
    ...over,
  };
}
const THREE = [
  item({ id: "appr:3", created_at: at(1) }),
  item({ id: "esc:2", kind: "escalation_closed", result: "completed", text: "Kỹ thuật viên đã xử lý xong.", created_at: at(10) }),
  item({ id: "appr:1", result: "rejected", text: "IT đã từ chối yêu cầu.", created_at: at(20) }),
];

type Route_ = (url: string) => Response | undefined;
function stub(route: Route_) {
  const calls: string[] = [];
  const fetch = vi.fn(async (input: string) => {
    calls.push(input);
    return route(input) ?? json(404, { detail: "Not Found" });
  });
  vi.stubGlobal("fetch", fetch);
  return calls;
}
/** Thay `window.localStorage` cho MỘT test (happy-dom giữ hàm đã bind theo đối tượng → spy trên Storage.prototype không
 *  chắc bắt được). `null` = chạm vào là ném SecurityError (trình duyệt chặn site data). */
function replaceStorage(fake: Partial<Storage> | null) {
  const own = Object.getOwnPropertyDescriptor(window, "localStorage");
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    get() {
      if (fake === null) throw new DOMException("blocked", "SecurityError");
      return fake;
    },
  });
  undo.push(() => {
    if (own) Object.defineProperty(window, "localStorage", own);
    else delete (window as { localStorage?: Storage }).localStorage;
  });
}
const tbCalls = (calls: string[]) => calls.filter((u) => u.startsWith("/api/me/notifications"));

function mountSidebar(me: Me = EMP) {
  const client = new QueryClient();
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Sidebar me={me} onSignOut={async () => true} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const bell = () => screen.findByTestId("tb-bell");
const count = () => screen.queryByTestId("tb-count")?.textContent ?? null;

// ------------------------------------------------------------------------------------------------------ t200 parser
describe("t200: getNotifications đọc CHẶT {items, next_cursor} — sai → 502 invalid_notifications_body cho cả thân", () => {
  const ok = { items: THREE, next_cursor: "c1" };
  it("thân đúng → giữ nguyên thứ tự, cả 2 kind, 5 result", () => {
    const all = (["approved", "rejected"] as const).map((r, i) => item({ id: `appr:${i}`, result: r }));
    const esc = (["completed", "confirmed_denial", "reopened_as_new"] as const).map((r, i) =>
      item({ id: `esc:${i}`, kind: "escalation_closed", result: r }),
    );
    expect(parseNotificationPage({ items: [...all, ...esc], next_cursor: null }).items).toHaveLength(5);
    expect(parseNotificationPage(ok).items.map((i) => i.id)).toStrictEqual(["appr:3", "esc:2", "appr:1"]);
  });
  const bad: [string, unknown][] = [
    ["mảng trần", THREE],
    ["thiếu next_cursor", { items: THREE }],
    ["next_cursor rỗng", { items: THREE, next_cursor: "" }],
    ["next_cursor số", { items: THREE, next_cursor: 2 }],
    ["items không phải mảng", { items: {}, next_cursor: null }],
    ["kind lạ", { items: [item({ id: "appr:1", kind: "approval_expired" as never })], next_cursor: null }],
    ["result lạ", { items: [item({ id: "appr:1", result: "timeout" as never })], next_cursor: null }],
    ["kind không khớp result", { items: [item({ id: "appr:1", result: "completed" })], next_cursor: null }],
    ["tiền tố id không khớp kind", { items: [item({ id: "esc:1" })], next_cursor: null }],
    ["id chỉ có tiền tố", { items: [item({ id: "appr:" })], next_cursor: null }],
    ["created_at thiếu múi giờ", { items: [item({ id: "appr:1", created_at: "2026-10-26T09:00:00" })], next_cursor: null }],
    ["created_at rác", { items: [item({ id: "appr:1", created_at: "hôm qua" })], next_cursor: null }],
    ["text không phải chuỗi", { items: [item({ id: "appr:1", text: null as never })], next_cursor: null }],
    ["new_ticket_id số", { items: [item({ id: "appr:1", new_ticket_id: 5 as never })], next_cursor: null }],
    ["ticket_id rỗng", { items: [item({ id: "appr:1", ticket_id: "" })], next_cursor: null }],
    ["một dòng hỏng giữa các dòng đúng", { items: [...THREE, { id: "appr:9" }], next_cursor: null }],
  ];
  it.each(bad)("%s → 502", (_name, body) => {
    let error: unknown = null;
    try {
      parseNotificationPage(body);
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(502);
    expect((error as ApiError).code).toBe("invalid_notifications_body");
  });
  it("đường dẫn: limit + after mã hoá", () => {
    expect(notificationsPath(20, null)).toBe("/api/me/notifications?limit=20");
    expect(notificationsPath(20, "a b&c")).toBe("/api/me/notifications?limit=20&after=a%20b%26c");
  });
});

// ------------------------------------------------------------------------------------------------------ t201 404
describe("t201: route chưa có (404) → không chuông, không câu lỗi, không hỏi lại", () => {
  it("404 → không có nút Thông báo; 90 s sau vẫn đúng 1 lời gọi", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = stub(() => undefined);
    mountSidebar();
    await waitFor(() => expect(tbCalls(calls)).toHaveLength(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(90_000);
    });
    expect(screen.queryByTestId("tb-bell")).toBeNull();
    expect(screen.queryByRole("button", { name: /Thông báo/ })).toBeNull();
    expect(document.body.textContent).not.toMatch(/Chưa tải được thông báo|lỗi/i);
    expect(tbCalls(calls)).toHaveLength(1);
  });
  it("401/403 → dừng hỏi lại", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = stub((u) => (u.startsWith("/api/me/notifications") ? json(403, { detail: "forbidden" }) : undefined));
    mountSidebar();
    await waitFor(() => expect(tbCalls(calls)).toHaveLength(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(90_000);
    });
    expect(tbCalls(calls)).toHaveLength(1);
  });
});

const feed = (items: NotificationItem[], next: string | null = null) =>
  stub((u) => (u.startsWith("/api/me/notifications") ? json(200, { items, next_cursor: next }) : undefined));

// ------------------------------------------------------------------------------------------------------ t202 đếm + đã đọc
describe("t202: số chưa đọc = created_at > last_seen_at; mở danh sách → đã đọc; tải lại vẫn giữ", () => {
  it("chưa có mốc → 3; mở → mốc = created_at mới nhất, số biến mất; gắn lại (tải lại trang) → vẫn không số", async () => {
    feed(THREE);
    const first = mountSidebar();
    await bell();
    await waitFor(() => expect(count()).toBe("3"));
    expect((await bell()).getAttribute("aria-label")).toBe("Thông báo, 3 chưa đọc");
    fireEvent.click(await bell());
    await screen.findByRole("dialog", { name: "Thông báo" });
    await waitFor(() => expect(count()).toBeNull());
    expect(window.localStorage.getItem(lastSeenKey(EMP.user_id))).toBe(THREE[0]!.created_at);
    first.unmount();
    mountSidebar();
    await bell();
    expect(count()).toBeNull();
  });
  it("mốc ở giữa → chỉ đếm dòng mới hơn", async () => {
    window.localStorage.setItem(lastSeenKey(EMP.user_id), THREE[1]!.created_at);
    feed(THREE);
    mountSidebar();
    await bell();
    await waitFor(() => expect(count()).toBe("1"));
  });
  it("danh sách rỗng → chuông không số", async () => {
    feed([]);
    mountSidebar();
    await bell();
    expect(count()).toBeNull();
    fireEvent.click(await bell());
    expect(await screen.findByText("Chưa có thông báo nào.")).toBeTruthy();
  });
  it("mốc so theo THỜI ĐIỂM (múi giờ khác nhau) chứ không theo chuỗi", async () => {
    // 09:00Z = 16:00+07:00 — chuỗi khác nhưng cùng thời điểm với dòng mới nhất → 0 chưa đọc.
    window.localStorage.setItem(lastSeenKey(EMP.user_id), "2026-10-26T15:59:00+07:00");
    feed(THREE);
    mountSidebar();
    await bell();
    expect(count()).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------------ t203 khoá theo người
describe("t203: mốc đã xem tách theo user_id", () => {
  it("an.nv đọc hết → binh.tt (cùng máy) vẫn thấy 3; khoá = tb.last_seen.<user_id>, giá trị chỉ ISO", async () => {
    feed(THREE);
    const a = mountSidebar(EMP);
    fireEvent.click(await bell());
    await waitFor(() => expect(window.localStorage.getItem("tb.last_seen.an.nv")).toBe(THREE[0]!.created_at));
    a.unmount();
    mountSidebar(EMP2);
    await bell();
    await waitFor(() => expect(count()).toBe("3"));
    expect(window.localStorage.getItem("tb.last_seen.binh.tt")).toBeNull();
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i)!;
      expect(key.startsWith("tb.last_seen.")).toBe(true);
      expect(isIsoWithZone(window.localStorage.getItem(key))).toBe(true);
    }
  });
});

// ------------------------------------------------------------------------------------------------------ t204 Storage lỗi
describe("t204: Storage lỗi (chặn / đầy) → coi như chưa đọc, màn không vỡ", () => {
  it("getItem + setItem ném → chuông 3, mở được, trong phiên hết số", async () => {
    const setItem = vi.fn(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    replaceStorage({
      getItem: () => {
        throw new DOMException("blocked", "SecurityError");
      },
      setItem,
    });
    feed(THREE);
    mountSidebar();
    await bell();
    await waitFor(() => expect(count()).toBe("3"));
    fireEvent.click(await bell());
    expect(await screen.findAllByTestId("tb-row")).toHaveLength(3);
    await waitFor(() => expect(count()).toBeNull());
    expect(readLastSeen("x")).toBeNull();
    expect(writeLastSeen("x", THREE[0]!.created_at)).toBe(false);
  });
  it("chạm `window.localStorage` cũng ném (trình duyệt chặn) → vẫn không vỡ", async () => {
    replaceStorage(null);
    feed(THREE);
    mountSidebar();
    await bell();
    await waitFor(() => expect(count()).toBe("3"));
    fireEvent.click(await bell());
    await waitFor(() => expect(count()).toBeNull());
  });
  it("giá trị lưu không phải ISO có múi giờ → bỏ qua (coi như chưa đọc); ghi chuỗi không ISO bị từ chối", () => {
    window.localStorage.setItem(lastSeenKey("u"), "eyJhbGciOi.token");
    expect(readLastSeen("u")).toBeNull();
    window.localStorage.setItem(lastSeenKey("u"), "2026-10-26T09:00:00");
    expect(readLastSeen("u")).toBeNull();
    expect(writeLastSeen("u", "Bearer abc")).toBe(false);
    expect(window.localStorage.getItem(lastSeenKey("u"))).toBe("2026-10-26T09:00:00");
    expect(writeLastSeen("u", "2026-10-26T09:00:00Z")).toBe(true);
    expect(readLastSeen("u")).toBe("2026-10-26T09:00:00Z");
  });
});

// ------------------------------------------------------------------------------------------------------ t205 lọc mã
describe("t205: chữ server có dáng mã → câu chung theo result (fail-closed); nhân viên không thấy mã trong chuông", () => {
  it.each([
    ["Bị chặn theo R18", "rejected"],
    ["Mã E6: hết hạn", "rejected"],
    ["Đang ở B12", "approved"],
    ["Trạng thái S_REJECTED", "rejected"],
    ["   ", "approved"],
  ] as const)("%j → câu chung", (text, result) => {
    expect(cauThongBao({ kind: "approval_decided", result, text })).toBe(CAU_THONG_BAO[result]);
  });
  it("chữ thường giữ nguyên văn (kể cả từ chứa chữ số không dáng mã)", () => {
    const text = "IT đã duyệt quyền VPN cho máy LAP-2201 của bạn.";
    expect(cauThongBao({ kind: "approval_decided", result: "approved", text })).toBe(text);
  });
  it("màn: dòng có mã hiện câu chung; toàn chuông (mở) không còn chuỗi mã nào; chữ là nút văn bản (không HTML)", async () => {
    const items = [
      item({ id: "appr:9", result: "rejected", text: "Từ chối theo luật R18, trạng thái S_REJECTED, bước B15.", created_at: at(1) }),
      item({ id: "appr:8", text: "<b>IT</b> đã duyệt <img src=x onerror=alert(1)>", created_at: at(2) }),
      ...THREE.slice(1),
    ];
    feed(items);
    mountSidebar();
    fireEvent.click(await bell());
    const dialog = await screen.findByRole("dialog", { name: "Thông báo" });
    expect(within(dialog).getByText(CAU_THONG_BAO.rejected!)).toBeTruthy();
    expect(spaced(dialog)).not.toMatch(MA_NOI_BO);
    expect(dialog.querySelector("img, b")).toBeNull();
    expect(within(dialog).getByText("<b>IT</b> đã duyệt <img src=x onerror=alert(1)>")).toBeTruthy();
    for (const label of Object.values(KET_QUA_THONG_BAO)) expect(label).not.toMatch(MA_NOI_BO);
  });
});

// ------------------------------------------------------------------------------------------------------ t206 tải thêm
describe("t206: \"Tải thêm\" theo next_cursor — không trùng dòng", () => {
  it("trang 2 lặp 1 dòng của trang 1 → hiện 1 lần; hết next_cursor → hết nút", async () => {
    const p1 = THREE.slice(0, 2);
    const p2 = [THREE[1]!, THREE[2]!];
    const calls = stub((u) => {
      if (u === "/api/me/notifications?limit=20") return json(200, { items: p1, next_cursor: "o2" });
      if (u === "/api/me/notifications?limit=20&after=o2") return json(200, { items: p2, next_cursor: null });
      return undefined;
    });
    mountSidebar();
    fireEvent.click(await bell());
    expect(await screen.findAllByTestId("tb-row")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Tải thêm" }));
    await waitFor(() => expect(screen.getAllByTestId("tb-row")).toHaveLength(3));
    expect(screen.queryByRole("button", { name: "Tải thêm" })).toBeNull();
    expect(tbCalls(calls)).toContain("/api/me/notifications?limit=20&after=o2");
  });
  it("mọi dòng đã tải đều chưa đọc + còn trang → số có dấu \"+\"", async () => {
    feed(THREE, "o3");
    mountSidebar();
    await bell();
    await waitFor(() => expect(count()).toBe("3+"));
  });
});

// ------------------------------------------------------------------------------------------------------ t207 polling
describe("t207: hỏi lại 30 s khi tab hiện; tab ẩn → dừng", () => {
  it("hiện: 30 s → thêm 1 lời gọi; ẩn: 120 s → không thêm", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = feed(THREE);
    mountSidebar();
    await waitFor(() => expect(tbCalls(calls)).toHaveLength(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_500);
    });
    await waitFor(() => expect(tbCalls(calls)).toHaveLength(2));
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(tbCalls(calls)).toHaveLength(2);
  });
});

// ------------------------------------------------------------------------------------------------------ t208 link
describe("t208: dòng thông báo — \"Xem yêu cầu\" tới /chat/<ticket_id>; reopened_as_new KHÔNG link/mã ticket mới (ĐP 23:51)", () => {
  it("lỡ có new_ticket_id → vẫn không hiện; chỉ 1 link tới ticket gốc", async () => {
    feed([item({ id: "esc:5", kind: "escalation_closed", result: "reopened_as_new", ticket_id: "tkt-goc", new_ticket_id: "tkt-moi-777", text: "Đã mở yêu cầu mới." })]);
    mountSidebar();
    fireEvent.click(await bell());
    const dialog = await screen.findByRole("dialog", { name: "Thông báo" });
    const links = within(dialog).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toStrictEqual([["Xem yêu cầu", "/chat/tkt-goc"]]);
    expect(dialog.textContent).not.toContain("tkt-moi-777");
    expect([...dialog.querySelectorAll("[href]")].map((a) => a.getAttribute("href"))).not.toContain("/chat/tkt-moi-777");
    expect(within(dialog).getByText("Cần gửi yêu cầu mới")).toBeTruthy();
  });
  it("nhân sự IT không có ticket:read:own → không link (route /chat/:id sẽ là 403)", async () => {
    feed(THREE);
    mountSidebar(L2);
    fireEvent.click(await bell());
    const dialog = await screen.findByRole("dialog", { name: "Thông báo" });
    expect(within(dialog).queryAllByRole("link")).toHaveLength(0);
    expect(within(dialog).getAllByTestId("tb-row")).toHaveLength(3);
  });
});

// ------------------------------------------------------------------------------------------------------ t209 bàn phím
describe("t209: bàn phím — Escape đóng, tiêu điểm về chuông; aria-expanded", () => {
  it("mở → tiêu điểm vào hộp; Escape → đóng + tiêu điểm về chuông", async () => {
    feed(THREE);
    mountSidebar();
    const button = await bell();
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    const dialog = await screen.findByRole("dialog", { name: "Thông báo" });
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(button.getAttribute("aria-controls")).toBe(dialog.id);
    expect(document.activeElement).toBe(dialog);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(button);
  });
  it("bấm ra ngoài → đóng", async () => {
    feed(THREE);
    mountSidebar();
    fireEvent.click(await bell());
    await screen.findByRole("dialog");
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------------ đồng hồ
const TICKET = "tkt-210";
const view = (over: Partial<TicketView> = {}): TicketView => ({
  ticket_id: TICKET,
  status: "S_PENDING_APPROVAL",
  waiting_for: "approval",
  conversation: [],
  exit_code: null,
  close_reason: null,
  final_state: null,
  created_at: new Date(T0 - 60_000).toISOString(),
  closed_at: null,
  ...over,
});

/** Ticket giả: `respond(n)` = thân lần GET thứ n (từ 1). */
function stubTicket(respond: (n: number) => TicketView, id = TICKET) {
  let n = 0;
  const calls = stub((u) => (u === `/api/tickets/${id}` ? json(200, respond(++n)) : undefined));
  return { calls, gets: () => calls.filter((u) => u === `/api/tickets/${id}`).length };
}
function mountChat(id = TICKET) {
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthContext value={signedIn(EMP)}>
        <MemoryRouter initialEntries={[`/chat/${id}`]}>
          <Routes>
            <Route path="/chat/:ticketId" element={<ChatRoute />} />
          </Routes>
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
}
const clockText = () => screen.queryByTestId("approval-clock")?.textContent ?? null;
const tick = async (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

describe("t210: \"Chờ IT duyệt · còn mm:ss\" theo server_now — giờ máy lệch ±5 phút vẫn đúng", () => {
  it.each([
    ["máy nhanh 5 phút", +5],
    ["máy chậm 5 phút", -5],
  ])("%s → còn 10:00, 1 giây sau 09:59", async (_name, skewMin) => {
    const serverNow = T0;
    vi.useFakeTimers({ shouldAdvanceTime: false, now: serverNow + skewMin * 60_000 });
    stubTicket(() => view({ deadline: new Date(serverNow + 10 * 60_000).toISOString(), server_now: new Date(serverNow).toISOString() }));
    mountChat();
    await tick(50);
    await vi.waitFor(() => expect(clockText()).toContain("Chờ IT duyệt · còn 10:00"));
    await tick(1000);
    expect(clockText()).toContain("còn 09:59");
    expect(spaced(document.body)).not.toMatch(MA_NOI_BO);
  });
  it("thiếu server_now → dùng độ lệch header Date (0 khi không có): còn theo giờ máy", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, now: T0 });
    stubTicket(() => view({ deadline: new Date(T0 + 3 * 60_000).toISOString() }));
    mountChat();
    await tick(50);
    await vi.waitFor(() => expect(clockText()).toContain("còn 03:00"));
  });
  it("≥ 1 giờ → h:mm:ss", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, now: T0 });
    stubTicket(() => view({ deadline: new Date(T0 + 75 * 60_000).toISOString(), server_now: new Date(T0).toISOString() }));
    mountChat();
    await tick(50);
    await vi.waitFor(() => expect(clockText()).toContain("còn 1:15:00"));
  });
});

describe("t211: hết hạn → câu quá hạn + tải lại ticket ĐÚNG MỘT lần (không tự kết luận)", () => {
  it("còn 3 s → 4 s sau: câu quá hạn, GET thêm đúng 1; 5 s tiếp (chưa tới nhịp poll 10 s) không thêm", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, now: T0 });
    const deadline = new Date(T0 + 3000).toISOString();
    const t = stubTicket(() => view({ deadline, server_now: new Date(Date.now()).toISOString() }));
    mountChat();
    await tick(50);
    await vi.waitFor(() => expect(clockText()).toContain("còn 00:03"));
    expect(t.gets()).toBe(1);
    await tick(3100);
    await vi.waitFor(() => expect(clockText()).toContain(EXPIRED_TEXT));
    await vi.waitFor(() => expect(t.gets()).toBe(2));
    await tick(5000);
    expect(t.gets()).toBe(2);
    expect(clockText()).not.toMatch(/còn \d/);
    // Không tự đổi trạng thái: nhãn trạng thái vẫn là "Chờ IT duyệt" tới khi server nói khác.
    expect(screen.getAllByRole("status").some((s) => s.textContent?.includes("Chờ IT duyệt"))).toBe(true);
  });
  it("lần tải lại trả ticket đã chuyển kỹ thuật viên → đồng hồ biến mất", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, now: T0 });
    const deadline = new Date(T0 + 2000).toISOString();
    const t = stubTicket((n) =>
      n === 1
        ? view({ deadline, server_now: new Date(Date.now()).toISOString() })
        : view({ status: "S_ESCALATED", waiting_for: null, final_state: "S_ESCALATED", exit_code: "E6", deadline: null, server_now: new Date(Date.now()).toISOString() }),
    );
    mountChat();
    await tick(50);
    await vi.waitFor(() => expect(clockText()).toContain("còn 00:02"));
    await tick(2100);
    await vi.waitFor(() => expect(t.gets()).toBe(2));
    await vi.waitFor(() => expect(clockText()).toBeNull());
    expect(spaced(document.body)).not.toMatch(MA_NOI_BO);
  });
});

describe("t212: không đồng hồ duyệt khi: deadline null / thiếu / hỏng; đã kết thúc; waiting_for ≠ approval dù có deadline (ĐP 27/10 00:05)", () => {
  it.each([
    ["null", { deadline: null }],
    ["thiếu khoá", {}],
    ["không múi giờ", { deadline: "2026-10-26T09:10:00" }],
    ["đã kết thúc dù còn hạn", { final_state: "S_RESOLVED", status: "S_RESOLVED", waiting_for: null, deadline: new Date(T0 + 60_000).toISOString() }],
    ["waiting_for clarify + deadline (hạn R3 của lần hỏi thêm)", { waiting_for: "clarify", status: "S_CLARIFYING", deadline: new Date(T0 + 60_000).toISOString() }],
    ["waiting_for confirm + deadline", { waiting_for: "confirm", status: "S_CONFIRMING", deadline: new Date(T0 + 60_000).toISOString() }],
    ["S_PENDING_APPROVAL nhưng waiting_for null (không dựa status)", { waiting_for: null, deadline: new Date(T0 + 60_000).toISOString() }],
  ] as [string, Partial<TicketView>][])("%s", async (_name, over) => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: T0 });
    stubTicket(() => view({ server_now: new Date(T0).toISOString(), ...over }));
    mountChat();
    await vi.waitFor(() => expect(document.body.textContent?.length ?? 0).toBeGreaterThan(20));
    await tick(50);
    expect(clockText()).toBeNull();
    expect(document.body.textContent).not.toMatch(/còn \d\d:\d\d/);
  });
});

describe("t212b: clockDeadline — cổng duy nhất của đồng hồ duyệt (màn còn lớp thứ hai: chỉ nhánh approval của ActionPanel vẽ)", () => {
  const d = new Date(T0 + 60_000).toISOString();
  it.each([
    ["approval", view({ deadline: d }), "approval", d],
    ["clarify", view({ status: "S_CLARIFYING", waiting_for: "clarify", deadline: d }), "clarify", null],
    ["confirm", view({ status: "S_CONFIRMING", waiting_for: "confirm", deadline: d }), "confirm", null],
    ["reply (cha)", view({ status: "S_CONFIRMING", waiting_for: "reply", deadline: d }), "reply", null],
    ["S_PENDING_APPROVAL + waiting null", view({ waiting_for: null, deadline: d }), null, null],
    ["đã kết thúc", view({ final_state: "S_RESOLVED", deadline: d }), "approval", null],
    ["không múi giờ", view({ deadline: "2026-10-26T09:01:00" }), "approval", null],
  ] as [string, TicketView, TicketView["waiting_for"], string | null][])("%s", (_name, v, waiting, expected) => {
    expect(clockDeadline(v, waiting)).toBe(expected);
  });
});

describe("t213: đọc cho trình đọc màn hình CHỈ ở mốc 5 phút và lúc hết hạn; đỏ khi còn < 20%", () => {
  it("vùng aria-live rỗng lúc đầu, không đổi mỗi giây; ≤ 5 phút → câu 5 phút; hết hạn → câu quá hạn", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, now: T0 });
    const deadline = new Date(T0 + 5 * 60_000 + 3000).toISOString();
    stubTicket(() => view({ deadline, server_now: new Date(Date.now()).toISOString() }));
    mountChat();
    await tick(50);
    const live = await vi.waitFor(() => screen.getByTestId("approval-clock-live"));
    expect(live.getAttribute("aria-live")).toBe("polite");
    expect(live.textContent).toBe("");
    await tick(1000);
    expect(screen.getByTestId("approval-clock-live").textContent).toBe("");
    await tick(3000);
    expect(screen.getByTestId("approval-clock-live").textContent).toBe(FIVE_MIN_TEXT);
    await tick(1000);
    expect(screen.getByTestId("approval-clock-live").textContent).toBe(FIVE_MIN_TEXT);
    // Chữ đếm giây không nằm trong vùng đọc tự động.
    expect(screen.getByRole("timer").closest("[aria-live='polite']")).toBeNull();
    await tick(5 * 60_000);
    await vi.waitFor(() => expect(screen.getByTestId("approval-clock-live").textContent).toBe(EXPIRED_TEXT));
  });
  it("khoảng 10 phút từ lần đầu thấy: còn 2:01 không đỏ, còn 1:59 đỏ", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, now: T0 });
    stubTicket(() => view({ deadline: new Date(T0 + 10 * 60_000).toISOString(), server_now: new Date(Date.now()).toISOString() }));
    mountChat();
    await tick(50);
    await vi.waitFor(() => expect(screen.getByRole("timer")).toBeTruthy());
    await tick(8 * 60_000 - 1000 - 50);
    expect(screen.getByRole("timer").textContent).toBe("02:01");
    expect(screen.getByRole("timer").dataset.urgent).toBeUndefined();
    await tick(2000);
    expect(screen.getByRole("timer").textContent).toBe("01:59");
    expect(screen.getByRole("timer").dataset.urgent).toBe("true");
  });
});

describe("t214: ticket cha nhiều ý — dùng nguyên deadline server trả cho cha, chỉ khi cha waiting_for = approval", () => {
  it("cha chờ duyệt + deadline → đồng hồ theo deadline của cha; không mã", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, now: T0 });
    const multi = createMulti("tkt-demo-multi-1", T0);
    const parent: TicketView = {
      ...viewOf(multi),
      waiting_for: "approval",
      deadline: new Date(T0 + 7 * 60_000).toISOString(),
      server_now: new Date(T0).toISOString(),
    };
    stubTicket(() => parent, parent.ticket_id);
    mountChat(parent.ticket_id);
    await tick(50);
    await vi.waitFor(() => expect(clockText()).toContain("Chờ IT duyệt · còn 07:00"));
    expect(spaced(document.body)).not.toMatch(MA_NOI_BO);
  });
  it("cha chờ trả lời (reply) + deadline → không đồng hồ duyệt (FE không tự tính từ các ý con)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: T0 });
    const multi = createMulti("tkt-demo-multi-2", T0);
    const parent: TicketView = { ...viewOf(multi), waiting_for: "reply", deadline: new Date(T0 + 7 * 60_000).toISOString(), server_now: new Date(T0).toISOString() };
    stubTicket(() => parent, parent.ticket_id);
    mountChat(parent.ticket_id);
    await vi.waitFor(() => expect(document.body.textContent?.length ?? 0).toBeGreaterThan(20));
    await tick(50);
    expect(clockText()).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------------ t215 MSW fixture
describe("t215: fixture dev:mock — đủ minh hoạ, đúng hợp đồng", () => {
  it("≥ 25 dòng, cả 2 kind, 1 dòng chữ có mã, có reopened_as_new, new_ticket_id luôn null; mọi trang qua parser", () => {
    const all = createNotifications(T0);
    expect(all.length).toBeGreaterThanOrEqual(25);
    expect(new Set(all.map((i) => i.kind))).toStrictEqual(new Set(["approval_decided", "escalation_closed"]));
    expect(all.filter((i) => MA_NOI_BO.test(i.text))).toHaveLength(1);
    expect(all.some((i) => i.result === "reopened_as_new")).toBe(true);
    expect(all.every((i) => i.new_ticket_id === null)).toBe(true);
    let after: string | null = null;
    const seen: string[] = [];
    do {
      const page: NotificationPage = pageOf(all, 20, after)!;
      parseNotificationPage(page);
      seen.push(...page.items.map((i) => i.id));
      after = page.next_cursor;
    } while (after !== null);
    expect(seen).toStrictEqual(all.map((i) => i.id));
    expect(pageOf(all, 20, "lạ")).toBeNull();
  });
  it("ticket chờ duyệt minh hoạ: deadline + server_now ISO có múi giờ; quá hạn 15 s → đã chuyển, deadline null", () => {
    const t = createDuyet(DUYET_SAP_HET, T0);
    const v = duyetView(t, T0);
    expect(isIsoWithZone(v.deadline)).toBe(true);
    expect(isIsoWithZone(v.server_now)).toBe(true);
    expect(v.waiting_for).toBe("approval");
    const later = duyetView(t, t.deadline + 15_000);
    expect(later.final_state).toBe("S_ESCALATED");
    expect(later.deadline).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------------ t216 Storage 1 file
describe("t216: Storage chỉ đụng ở lib/lastSeen.ts — chuông không ghi gì ngoài khoá tb.last_seen.<user>", () => {
  it("mở chuông: setItem chỉ với khoá của người đang đăng nhập, giá trị ISO; không sessionStorage", async () => {
    const store = new Map<string, string>();
    const setItem = vi.fn((key: string, value: string) => void store.set(key, value));
    replaceStorage({ getItem: (key: string) => store.get(key) ?? null, setItem });
    feed(THREE);
    mountSidebar();
    fireEvent.click(await bell());
    await waitFor(() => expect(setItem).toHaveBeenCalled());
    for (const [key, value] of setItem.mock.calls) {
      expect(key).toBe("tb.last_seen.an.nv");
      expect(isIsoWithZone(value)).toBe(true);
    }
    expect(setItem.mock.calls.length).toBeGreaterThan(0);
  });
});

// ------------------------------------------------------------------------------------------------------ ĐP soát 23d0f6a
describe("t217: câu chữ reopened_as_new / confirmed_denial (ĐP soát 23d0f6a #1, #2)", () => {
  it("nhãn + câu chung đúng nguyên văn; không còn \"đã tạo yêu cầu mới\" ở nhãn/câu/fixture của nhân viên", () => {
    expect(KET_QUA_THONG_BAO.reopened_as_new).toBe("Cần gửi yêu cầu mới");
    expect(CAU_THONG_BAO.reopened_as_new).toBe("Kỹ thuật viên đề nghị bạn gửi một yêu cầu mới cho việc này.");
    expect(CAU_THONG_BAO.confirmed_denial).toBe("Kỹ thuật viên đã xem lại và giữ quyết định từ chối.");
    const texts = [...Object.values(KET_QUA_THONG_BAO), ...Object.values(CAU_THONG_BAO), ...createNotifications(T0).map((i) => i.text)];
    for (const t of texts) expect(t.toLowerCase()).not.toContain("đã tạo yêu cầu mới");
  });
  it("dòng reopened_as_new chữ có mã → câu chung mới + nhãn mới; chỉ link ticket gốc", async () => {
    feed([item({ id: "esc:7", kind: "escalation_closed", result: "reopened_as_new", ticket_id: "tkt-goc", text: "Đóng ca E5, mở lại", new_ticket_id: null })]);
    mountSidebar();
    fireEvent.click(await bell());
    const dialog = await screen.findByRole("dialog", { name: "Thông báo" });
    expect(within(dialog).getByText("Kỹ thuật viên đề nghị bạn gửi một yêu cầu mới cho việc này.")).toBeTruthy();
    expect(within(dialog).getByText("Cần gửi yêu cầu mới")).toBeTruthy();
    expect(within(dialog).getAllByRole("link").map((a) => a.getAttribute("href"))).toStrictEqual(["/chat/tkt-goc"]);
  });
  it("dòng confirmed_denial chữ có mã → câu chung mới", () => {
    expect(cauThongBao({ kind: "escalation_closed", result: "confirmed_denial", text: "Giữ E3" })).toBe("Kỹ thuật viên đã xem lại và giữ quyết định từ chối.");
  });
});

describe("t218: lỗi tải thông báo → chuông vẫn hiện (không số), mở khung thấy \"Chưa tải được thông báo\" (ĐP soát 23d0f6a #4)", () => {
  it.each([
    ["thân sai hình dạng (502 invalid_notifications_body)", () => json(200, { items: [{ id: "esc:1", kind: "approval_decided" }], next_cursor: null })],
    ["kind↔result lệch (đọc chặt giữ nguyên)", () => json(200, { items: [item({ id: "appr:1", result: "completed" })], next_cursor: null })],
    ["5xx", () => json(500, { detail: "boom" })],
  ] as [string, () => Response][])("%s", async (_name, respond) => {
    stub((u) => (u.startsWith("/api/me/notifications") ? respond() : undefined));
    mountSidebar();
    const button = await bell();
    expect(count()).toBeNull();
    expect(button.getAttribute("aria-label")).toBe("Thông báo");
    fireEvent.click(button);
    const dialog = await screen.findByRole("dialog", { name: "Thông báo" });
    expect(within(dialog).getByTestId("tb-error").textContent).toBe("Chưa tải được thông báo.");
    expect(within(dialog).queryByText("Chưa có thông báo nào.")).toBeNull();
    expect(within(dialog).queryAllByTestId("tb-row")).toHaveLength(0);
  });
  it("đã có dữ liệu rồi lần hỏi lại lỗi → giữ dòng cũ + \"Chưa tải được thông báo — đang thử lại.\"", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let n = 0;
    stub((u) => (u.startsWith("/api/me/notifications") ? (++n === 1 ? json(200, { items: THREE, next_cursor: null }) : json(200, { items: "hỏng", next_cursor: null })) : undefined));
    mountSidebar();
    await bell();
    await waitFor(() => expect(count()).toBe("3"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_500);
    });
    await waitFor(() => expect(n).toBeGreaterThanOrEqual(2));
    fireEvent.click(await bell());
    const dialog = await screen.findByRole("dialog", { name: "Thông báo" });
    await waitFor(() => expect(within(dialog).getByTestId("tb-error").textContent).toBe("Chưa tải được thông báo — đang thử lại."));
    expect(within(dialog).getAllByTestId("tb-row")).toHaveLength(3);
  });
});

describe("t219: đồng hồ quá hạn → ô nhập \"Đang chuyển kỹ thuật viên\" tới khi ticket đổi (ĐP soát 23d0f6a #5)", () => {
  const composer = () => document.querySelector("textarea")?.getAttribute("placeholder") ?? null;
  it("trước hạn: \"Đang chờ IT duyệt\"; quá hạn (tải lại vẫn chờ duyệt): \"Đang chuyển kỹ thuật viên\"; ticket đổi hạn mới → về \"Đang chờ IT duyệt\"", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, now: T0 });
    const first = new Date(T0 + 2000).toISOString();
    let deadline = first;
    stubTicket(() => view({ deadline, server_now: new Date(Date.now()).toISOString() }));
    mountChat();
    await tick(50);
    await vi.waitFor(() => expect(clockText()).toContain("còn 00:02"));
    expect(composer()).toBe("Đang chờ IT duyệt");
    await tick(2100);
    await vi.waitFor(() => expect(clockText()).toContain(EXPIRED_TEXT));
    await tick(50);
    expect(composer()).toBe("Đang chuyển kỹ thuật viên");
    // Lần chờ duyệt mới (hạn khác) → đồng hồ mới, ô nhập về câu chờ duyệt.
    deadline = new Date(T0 + 20 * 60_000).toISOString();
    await tick(10_000);
    await vi.waitFor(() => expect(clockText()).toMatch(/còn \d\d:\d\d/));
    expect(composer()).toBe("Đang chờ IT duyệt");
  });
  it("tải lại ra ticket đã chuyển (final) → không còn ô nhập; không câu \"đang chuyển\" treo lại", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, now: T0 });
    const deadline = new Date(T0 + 1000).toISOString();
    stubTicket((n) =>
      n === 1
        ? view({ deadline, server_now: new Date(Date.now()).toISOString() })
        : view({ status: "S_ESCALATED", waiting_for: null, final_state: "S_ESCALATED", deadline: null, server_now: new Date(Date.now()).toISOString() }),
    );
    mountChat();
    await tick(50);
    await vi.waitFor(() => expect(clockText()).toContain("còn 00:01"));
    await tick(1100);
    await vi.waitFor(() => expect(clockText()).toBeNull());
    expect(document.body.textContent).not.toContain("Đang chuyển kỹ thuật viên");
  });
});
