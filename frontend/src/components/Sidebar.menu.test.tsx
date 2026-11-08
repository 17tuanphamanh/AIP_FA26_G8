// P3 "Gần đây" — menu ⋯ cho từng mục (PLAN p5-gan-day-menu, DỪNG 1). Người kiểm thử kiểm trên Chrome:
// - Rê chuột / focus bàn phím vào một mục → nút ⋯ (aria-label "Tùy chọn cho <tiêu đề>"); bấm → role="menu" ĐÚNG 2 mục
//   "Mở ở cửa sổ mới", "Xóa"; Esc / bấm ra ngoài đóng menu.
// - "Mở ở cửa sổ mới" = window.open(`/chat/<mã>`, "_blank", "noopener,noreferrer,popup") — cửa sổ hiện tại giữ nguyên.
// - "Xóa" = ẨN khỏi "Gần đây" của chính người đó (`POST /api/tickets/{id}/hide`, backend/app/api/tickets.py): mục mất NGAY (trước khi
//   API trả), các mục còn lại giữ thứ tự, không hộp xác nhận; xong → bỏ khỏi cache ["tickets","mine",userId] + bộ nhớ phiên; API lỗi
//   → mục quay lại ĐÚNG chỗ cũ + "Chưa xóa được, thử lại"; đang ở /chat/<mã đó> → /chat; mount lại (F5) không quay lại.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Me, TicketListItem } from "../api/types.ts";
import { sessionTickets } from "../routes/employee/sessionTickets.ts";
import { Sidebar } from "./Sidebar.tsx";

const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
const AN: Me = { user_id: "nv001", role: "employee", permissions: BASE };
const MENU_ITEMS = ["Mở ở cửa sổ mới", "Xóa"];
const FAILED = "Chưa xóa được, thử lại";
const FEATURES = "noopener,noreferrer,popup";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const noContent = () => new Response(null, { status: 204 });

const item = (ticket_id: string): TicketListItem => ({
  ticket_id,
  request_text: `câu của ${ticket_id}`,
  final_state: null,
  exit_code: null,
  created_at: "2026-11-07T08:00:00Z",
  closed_at: null,
});

type HideReply = (id: string) => Response | Promise<Response>;
let server: { items: TicketListItem[]; hidden: Set<string>; listCalls: number; hideCalls: string[] };

/** Backend giả có trạng thái: `POST …/hide` (theo `hideReply`; 204 → nhớ id), `GET /api/tickets` lọc id đã ẩn. Route khác → 404. */
function stubServer(items: TicketListItem[], hideReply: HideReply = () => noContent()) {
  server = { items, hidden: new Set(), listCalls: 0, hideCalls: [] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      if (method === "GET" && (url === "/api/tickets" || url.startsWith("/api/tickets?"))) {
        server.listCalls += 1;
        return json(200, { items: server.items.filter((t) => !server.hidden.has(t.ticket_id)) });
      }
      const hide = /^\/api\/tickets\/([^/]+)\/hide$/.exec(url);
      if (method === "POST" && hide) {
        const id = decodeURIComponent(hide[1] ?? "");
        server.hideCalls.push(id);
        const res = await hideReply(id);
        if (res.status === 204) server.hidden.add(id);
        return res;
      }
      return json(404, { detail: "not_found" });
    }),
  );
}

function deferred() {
  let resolve: (r: Response) => void = () => {};
  let reject: (e: unknown) => void = () => {};
  const promise = new Promise<Response>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function mount(path = "/chat", client = new QueryClient()) {
  const rendered = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <Sidebar me={AN} onSignOut={async () => true} />
                <LocationProbe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...rendered, client };
}

const list = () => screen.queryByRole("list", { name: "Yêu cầu gần đây" });
const titles = () => Array.from(list()?.querySelectorAll("li") ?? []).map((li) => within(li).getByRole("link").textContent);
const rowOf = (title: string) => within(list()!).getByText(title).closest("li")!;
const linkOf = (title: string) => within(rowOf(title)).getByRole("link");
const moreButton = (title: string) => screen.queryByRole("button", { name: `Tùy chọn cho ${title}` });
const location = () => screen.getByTestId("location").textContent;

async function openMenu(title: string) {
  fireEvent.mouseEnter(rowOf(title));
  const button = moreButton(title);
  expect(button).not.toBeNull();
  fireEvent.click(button!);
  return screen.getByRole("menu");
}

async function ready(expected: string[]) {
  await waitFor(() => expect(titles()).toEqual(expected));
}

let openSpy: ReturnType<typeof vi.fn>;
let confirmSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sessionTickets.clear();
  openSpy = vi.fn(() => null);
  confirmSpy = vi.fn(() => true);
  vi.stubGlobal("open", openSpy);
  vi.stubGlobal("confirm", confirmSpy);
});
afterEach(() => {
  cleanup();
  sessionTickets.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("nút ⋯ — hiện khi rê chuột / focus bàn phím", () => {
  it("chưa rê chuột → không có nút; rê vào → nút đúng nhãn, chỉ của mục đó; rời ra → ẩn", async () => {
    stubServer([item("t2"), item("t1")]);
    mount();
    await ready(["câu của t2", "câu của t1"]);
    expect(moreButton("câu của t2")).toBeNull();
    fireEvent.mouseEnter(rowOf("câu của t2"));
    expect(moreButton("câu của t2")).not.toBeNull();
    expect(moreButton("câu của t1")).toBeNull();
    fireEvent.mouseLeave(rowOf("câu của t2"));
    expect(moreButton("câu của t2")).toBeNull();
  });

  it("focus bàn phím vào link của mục → hiện nút ⋯ (Tab tới được); focus rời khỏi mục → ẩn", async () => {
    stubServer([item("t2"), item("t1")]);
    mount();
    await ready(["câu của t2", "câu của t1"]);
    fireEvent.focus(linkOf("câu của t1"));
    const button = moreButton("câu của t1");
    expect(button).not.toBeNull();
    expect(button!.getAttribute("aria-haspopup")).toBe("menu");
    expect(button!.getAttribute("aria-expanded")).toBe("false");
    fireEvent.blur(linkOf("câu của t1"), { relatedTarget: document.body });
    expect(moreButton("câu của t1")).toBeNull();
  });
});

describe("menu — đúng 2 mục, Esc / bấm ra ngoài đóng", () => {
  it("bấm ⋯ → role=menu với ĐÚNG 2 menuitem theo thứ tự; aria-expanded=true; mục đầu nhận focus", async () => {
    stubServer([item("t2"), item("t1")]);
    mount();
    await ready(["câu của t2", "câu của t1"]);
    const menu = await openMenu("câu của t2");
    const items = within(menu).getAllByRole("menuitem");
    expect(items.map((el) => el.textContent?.trim())).toEqual(MENU_ITEMS);
    expect(moreButton("câu của t2")!.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(items[0]);
    fireEvent.mouseLeave(rowOf("câu của t2")); // đang mở menu → rời chuột không đóng
    expect(screen.queryByRole("menu")).not.toBeNull();
  });

  it("Esc đóng menu, focus về nút ⋯; không gọi API, không mở cửa sổ", async () => {
    stubServer([item("t2"), item("t1")]);
    mount();
    await ready(["câu của t2", "câu của t1"]);
    const menu = await openMenu("câu của t2");
    fireEvent.keyDown(within(menu).getAllByRole("menuitem")[0]!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(moreButton("câu của t2"));
    expect(server.hideCalls).toEqual([]);
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("bấm ra ngoài đóng menu, không xóa", async () => {
    stubServer([item("t2"), item("t1")]);
    mount();
    await ready(["câu của t2", "câu của t1"]);
    await openMenu("câu của t2");
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(titles()).toEqual(["câu của t2", "câu của t1"]);
    expect(server.hideCalls).toEqual([]);
  });
});

describe("Mở ở cửa sổ mới", () => {
  it("window.open(`/chat/<mã>`, \"_blank\", \"noopener,noreferrer,popup\"); cửa sổ hiện tại giữ nguyên trang; menu đóng", async () => {
    stubServer([item("t2"), item("t1")]);
    mount("/chat/t1");
    await ready(["câu của t2", "câu của t1"]);
    const menu = await openMenu("câu của t2");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Mở ở cửa sổ mới" }));
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith("/chat/t2", "_blank", FEATURES);
    expect(location()).toBe("/chat/t1");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(titles()).toEqual(["câu của t2", "câu của t1"]);
    expect(server.hideCalls).toEqual([]);
  });

  it("mã có ký tự đặc biệt → mã hoá giống href của link", async () => {
    stubServer([item("tk a/b")]);
    mount();
    await ready(["câu của tk a/b"]);
    const menu = await openMenu("câu của tk a/b");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Mở ở cửa sổ mới" }));
    const href = linkOf("câu của tk a/b").getAttribute("href");
    expect(href).toBe("/chat/tk%20a%2Fb");
    expect(openSpy).toHaveBeenCalledWith(href, "_blank", FEATURES);
  });
});

describe("Xóa = ẩn khỏi Gần đây", () => {
  it("mục mất NGAY (API chưa trả), các mục còn lại giữ thứ tự; không hộp xác nhận; xong → cache không còn mục", async () => {
    const pending = deferred();
    stubServer([item("t3"), item("t2"), item("t1")], () => pending.promise);
    const { client } = mount();
    await ready(["câu của t3", "câu của t2", "câu của t1"]);
    const menu = await openMenu("câu của t2");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Xóa" }));
    expect(titles()).toEqual(["câu của t3", "câu của t1"]);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(server.hideCalls).toEqual(["t2"]));
    await act(async () => pending.resolve(noContent()));
    await waitFor(() => {
      const cached = client.getQueryData<TicketListItem[]>(["tickets", "mine", AN.user_id]);
      expect(cached?.map((t) => t.ticket_id)).toEqual(["t3", "t1"]);
    });
    expect(titles()).toEqual(["câu của t3", "câu của t1"]);
    expect(screen.queryByText(FAILED)).toBeNull();
    expect(server.listCalls).toBe(1); // không tải lại danh sách
  });

  it("ticket tạo trong phiên → bỏ khỏi bộ nhớ phiên", async () => {
    sessionTickets.add("s1", "ticket trong phiên", []);
    stubServer([item("t1")]);
    mount();
    await ready(["ticket trong phiên", "câu của t1"]);
    const menu = await openMenu("ticket trong phiên");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Xóa" }));
    expect(titles()).toEqual(["câu của t1"]);
    await waitFor(() => expect(server.hideCalls).toEqual(["s1"]));
    await waitFor(() => expect(sessionTickets.getSnapshot().map((t) => t.ticket_id)).toEqual([]));
  });

  it("xóa đúng mục đang mở (/chat/<mã>) → về /chat (màn Yêu cầu mới)", async () => {
    stubServer([item("t2"), item("t1")]);
    mount("/chat/t2");
    await ready(["câu của t2", "câu của t1"]);
    const menu = await openMenu("câu của t2");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Xóa" }));
    await waitFor(() => expect(location()).toBe("/chat"));
    expect(titles()).toEqual(["câu của t1"]);
  });

  it("xóa mục KHÁC mục đang mở → giữ nguyên trang", async () => {
    stubServer([item("t2"), item("t1")]);
    mount("/chat/t1");
    await ready(["câu của t2", "câu của t1"]);
    const menu = await openMenu("câu của t2");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Xóa" }));
    await waitFor(() => expect(server.hideCalls).toEqual(["t2"]));
    expect(location()).toBe("/chat/t1");
  });

  it.each([
    ["500", () => json(500, { detail: "boom" })],
    ["404", () => json(404, { detail: "not_found" })],
    ["mạng hỏng", () => Promise.reject(new TypeError("Failed to fetch"))],
  ])("API lỗi (%s) → mục quay lại ĐÚNG chỗ cũ + \"Chưa xóa được, thử lại\"; cache giữ mục", async (_name, reply) => {
    stubServer([item("t3"), item("t2"), item("t1")], reply);
    const { client } = mount();
    await ready(["câu của t3", "câu của t2", "câu của t1"]);
    const menu = await openMenu("câu của t2");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Xóa" }));
    expect(titles()).toEqual(["câu của t3", "câu của t1"]);
    await waitFor(() => expect(screen.getByText(FAILED)).toBeTruthy());
    expect(titles()).toEqual(["câu của t3", "câu của t2", "câu của t1"]);
    expect(screen.getByText(FAILED).closest("[role=status]")).not.toBeNull();
    const cached = client.getQueryData<TicketListItem[]>(["tickets", "mine", AN.user_id]);
    expect(cached?.map((t) => t.ticket_id)).toEqual(["t3", "t2", "t1"]);
  });

  it("API lỗi với ticket trong phiên → quay lại đầu danh sách, vẫn trong bộ nhớ phiên", async () => {
    sessionTickets.add("s1", "ticket trong phiên", []);
    stubServer([item("t1")], () => json(500, { detail: "boom" }));
    mount();
    await ready(["ticket trong phiên", "câu của t1"]);
    const menu = await openMenu("ticket trong phiên");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Xóa" }));
    await waitFor(() => expect(screen.getByText(FAILED)).toBeTruthy());
    expect(titles()).toEqual(["ticket trong phiên", "câu của t1"]);
    expect(sessionTickets.getSnapshot().map((t) => t.ticket_id)).toEqual(["s1"]);
  });

  it("mount lại (giả F5: QueryClient mới, bộ nhớ phiên rỗng) → mục đã xóa không quay lại", async () => {
    stubServer([item("t3"), item("t2"), item("t1")]);
    const first = mount();
    await ready(["câu của t3", "câu của t2", "câu của t1"]);
    const menu = await openMenu("câu của t2");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Xóa" }));
    await waitFor(() => expect(server.hidden.has("t2")).toBe(true));
    first.unmount();
    sessionTickets.clear();
    mount("/chat", new QueryClient());
    await ready(["câu của t3", "câu của t1"]);
    expect(server.listCalls).toBe(2);
  });
});
