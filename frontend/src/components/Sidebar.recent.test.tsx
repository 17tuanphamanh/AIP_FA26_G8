// P3 "Gần đây" (lỗi mất danh sách sau F5 / đăng nhập lại): thanh bên đọc `GET /api/tickets` (backend/app/api/tickets.py
// `list_tickets` — ticket gốc của CHÍNH người gọi, mới nhất trước) MỘT lần, ghép với ticket vừa tạo trong phiên (khử trùng
// theo `ticket_id`, ticket trong phiên đứng trước và giữ chấm/tiêu đề như cũ). API lỗi → vẫn hiện ticket trong phiên, không
// chữ đỏ. Đổi người dùng → không lộ danh sách người trước. Không ghi danh sách xuống localStorage/sessionStorage.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Me, TicketListItem } from "../api/types.ts";
import { DEFAULT_TITLE, sessionTickets } from "../routes/employee/sessionTickets.ts";
import { Sidebar } from "./Sidebar.tsx";

const EMPTY = "Chưa có yêu cầu nào.";
const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
const AN: Me = { user_id: "nv001", role: "employee", permissions: BASE };
const BINH: Me = { user_id: "nv002", role: "employee", permissions: BASE };

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const item = (over: Partial<TicketListItem> & Pick<TicketListItem, "ticket_id">): TicketListItem => ({
  request_text: `câu của ${over.ticket_id}`,
  final_state: null,
  exit_code: null,
  created_at: "2026-11-07T08:00:00Z",
  closed_at: null,
  ...over,
});

type Reply = Response | Promise<Response> | (() => Response | Promise<Response>);
let listCalls: string[] = [];

/** fetch giả: `GET /api/tickets…` → `reply(người dùng hiện tại)`; mọi route khác (chuông thông báo…) → 404. */
function stubFetch(reply: (call: number) => Reply) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      if ((init.method ?? "GET") === "GET" && (url === "/api/tickets" || url.startsWith("/api/tickets?"))) {
        listCalls.push(url);
        const r = reply(listCalls.length);
        return typeof r === "function" ? r() : r;
      }
      return json(404, { detail: "not_found" });
    }),
  );
}

function mount(me: Me, client = new QueryClient()) {
  const ui = (who: Me) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Sidebar me={who} onSignOut={async () => true} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const rendered = render(ui(me));
  return { ...rendered, client, rerenderAs: (who: Me) => rendered.rerender(ui(who)) };
}

const list = () => screen.queryByRole("list", { name: "Yêu cầu gần đây" });
const titles = () => Array.from(list()?.querySelectorAll("li") ?? []).map((li) => li.textContent);
const dotOf = (title: string) => within(list()!).getByText(title).previousElementSibling?.className ?? "";
const linkOf = (title: string) => within(list()!).getByText(title).closest("a")?.getAttribute("href");

beforeEach(() => {
  listCalls = [];
  sessionTickets.clear();
});
afterEach(() => {
  cleanup();
  sessionTickets.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Gần đây — tải từ API (giả F5: mount mới, bộ nhớ phiên rỗng)", () => {
  it("hiện danh sách từ GET /api/tickets theo đúng thứ tự backend, link tới /chat/<id>; gọi đúng 1 lần", async () => {
    stubFetch(() => json(200, { items: [item({ ticket_id: "t3" }), item({ ticket_id: "t2" }), item({ ticket_id: "t1" })] }));
    const { rerenderAs } = mount(AN);
    await waitFor(() => expect(titles()).toEqual(["câu của t3", "câu của t2", "câu của t1"]));
    expect(linkOf("câu của t2")).toBe("/chat/t2");
    rerenderAs({ ...AN }); // render lại cùng người → không gọi thêm
    await new Promise((r) => setTimeout(r, 20));
    expect(listCalls).toHaveLength(1);
    expect(screen.queryByText(EMPTY)).toBeNull();
  });

  it("chấm suy từ final_state/exit_code: xong → xanh lá; đã chuyển/dừng → xám; chưa kết thúc → cam", async () => {
    stubFetch(() =>
      json(200, {
        items: [
          item({ ticket_id: "a", request_text: "đang chờ", final_state: null, exit_code: null }),
          item({ ticket_id: "b", request_text: "đã xong", final_state: "S_RESOLVED", exit_code: null, closed_at: "2026-11-07T09:00:00Z" }),
          item({ ticket_id: "c", request_text: "đã chuyển", final_state: "S_ESCALATED", exit_code: "E5" }),
          item({ ticket_id: "d", request_text: "bị chặn", final_state: "S_BLOCKED", exit_code: "E0" }),
          item({ ticket_id: "e", request_text: "có mã thoát", final_state: null, exit_code: "E9" }),
        ],
      }),
    );
    mount(AN);
    await waitFor(() => expect(titles()).toHaveLength(5));
    expect(dotOf("đang chờ")).toContain("bg-fpt-orange");
    expect(dotOf("đã xong")).toContain("bg-done");
    expect(dotOf("đã chuyển")).toContain("bg-ink-3");
    expect(dotOf("bị chặn")).toContain("bg-ink-3");
    expect(dotOf("có mã thoát")).toContain("bg-ink-3");
  });

  it("tiêu đề = titleOf(request_text): một dòng, cắt 60 ký tự; null → \"Yêu cầu của bạn\"", async () => {
    const long = `Không vào được VPN   từ sáng,\nlỗi 809 ${"x".repeat(80)}`;
    stubFetch(() => json(200, { items: [item({ ticket_id: "l", request_text: long }), item({ ticket_id: "n", request_text: null })] }));
    mount(AN);
    await waitFor(() => expect(titles()).toHaveLength(2));
    const [first, second] = titles();
    expect(first).toMatch(/^Không vào được VPN từ sáng, lỗi 809 x+…$/);
    expect(first).toHaveLength(60);
    expect(second).toBe(DEFAULT_TITLE);
  });
});

describe("Gần đây — ghép với ticket vừa tạo trong phiên", () => {
  it("khử trùng theo ticket_id; ticket trong phiên đứng trước và giữ chấm + tiêu đề của phiên", async () => {
    sessionTickets.add("s1", "câu phiên 1", []);
    sessionTickets.add("dup", "câu phiên dup", []); // mới nhất trong phiên
    stubFetch(() =>
      json(200, {
        items: [
          item({ ticket_id: "dup", request_text: "bản backend dup", final_state: "S_RESOLVED", exit_code: null }),
          item({ ticket_id: "old", request_text: "ticket cũ", final_state: "S_RESOLVED" }),
        ],
      }),
    );
    mount(AN);
    await waitFor(() => expect(titles()).toEqual(["câu phiên dup", "câu phiên 1", "ticket cũ"]));
    expect(screen.queryByText("bản backend dup")).toBeNull();
    expect(dotOf("câu phiên dup")).toContain("bg-fpt-blue"); // tone của phiên (processing), không lấy final_state của API
    expect(dotOf("ticket cũ")).toContain("bg-done");
  });

  it("tạo ticket mới sau khi đã tải → hiện ngay ở đầu, không gọi lại API", async () => {
    stubFetch(() => json(200, { items: [item({ ticket_id: "old", request_text: "ticket cũ" })] }));
    mount(AN);
    await waitFor(() => expect(titles()).toEqual(["ticket cũ"]));
    sessionTickets.add("new", "ticket mới", []);
    await waitFor(() => expect(titles()).toEqual(["ticket mới", "ticket cũ"]));
    expect(listCalls).toHaveLength(1);
  });

  it("ticket phiên có notices (đã che) vẫn giữ tiêu đề mặc định của phiên, không lấy câu gốc ở đâu", async () => {
    sessionTickets.add("r", "câu gốc có bí mật", ["Vui lòng không gửi mật khẩu qua chat"]);
    stubFetch(() => json(200, { items: [item({ ticket_id: "r", request_text: "câu [BÍ_MẬT_ĐÃ_ẨN]" })] }));
    mount(AN);
    await waitFor(() => expect(listCalls).toHaveLength(1));
    await waitFor(() => expect(titles()).toEqual([DEFAULT_TITLE]));
    expect(document.body.textContent).not.toContain("câu gốc có bí mật");
  });
});

describe("Gần đây — đổi người dùng / đăng xuất", () => {
  it("đổi sang người khác: danh sách người trước biến mất ngay (kể cả khi API của người sau chưa trả)", async () => {
    let release: (r: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    stubFetch((call) => (call === 1 ? json(200, { items: [item({ ticket_id: "an1", request_text: "ticket của An" })] }) : pending));
    const { rerenderAs } = mount(AN);
    await waitFor(() => expect(titles()).toEqual(["ticket của An"]));
    sessionTickets.clear(); // App.tsx `clearCache` khi đăng xuất / hết phiên
    rerenderAs(BINH);
    expect(screen.queryByText("ticket của An")).toBeNull();
    expect(screen.getByText(EMPTY)).toBeTruthy();
    release(json(200, { items: [item({ ticket_id: "b1", request_text: "ticket của Bình" })] }));
    await waitFor(() => expect(titles()).toEqual(["ticket của Bình"]));
    expect(screen.queryByText("ticket của An")).toBeNull();
    expect(listCalls).toHaveLength(2);
  });

  it("queryClient.clear() (đăng xuất) rồi người khác vào → không còn danh sách cũ trong bộ nhớ đệm", async () => {
    stubFetch((call) => json(200, { items: [item({ ticket_id: `x${call}`, request_text: call === 1 ? "của An" : "của Bình" })] }));
    const { client, unmount } = mount(AN);
    await waitFor(() => expect(titles()).toEqual(["của An"]));
    unmount();
    client.clear();
    sessionTickets.clear();
    mount(BINH, client);
    await waitFor(() => expect(titles()).toEqual(["của Bình"]));
    expect(screen.queryByText("của An")).toBeNull();
  });
});

describe("Gần đây — API lỗi không chặn trang", () => {
  it.each([
    ["500", () => json(500, { detail: "boom" })],
    ["503", () => json(503, { detail: "runtime_unavailable" })],
    ["404 (backend cũ)", () => json(404, { detail: "Not Found" })],
    ["mạng hỏng", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["thân sai hình dạng", () => json(200, [item({ ticket_id: "z" })])],
    ["phần tử thiếu khoá", () => json(200, { items: [{ ticket_id: "z" }] })],
  ])("%s → vẫn hiện ticket trong phiên, không chữ lỗi đỏ", async (_name, reply) => {
    sessionTickets.add("s1", "ticket trong phiên", []);
    stubFetch(() => reply);
    mount(AN);
    await waitFor(() => expect(listCalls).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(titles()).toEqual(["ticket trong phiên"]);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("z")).toBeNull();
  });

  it("API lỗi và phiên rỗng → chữ trống mới", async () => {
    stubFetch(() => json(500, { detail: "boom" }));
    mount(AN);
    await waitFor(() => expect(listCalls).toHaveLength(1));
    expect(screen.getByText(EMPTY)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("Gần đây — chữ trống, quyền, lưu trữ", () => {
  it("API trả rỗng + phiên rỗng → \"Chưa có yêu cầu nào.\" (bỏ chữ \"trong phiên này\")", async () => {
    stubFetch(() => json(200, { items: [] }));
    mount(AN);
    await waitFor(() => expect(listCalls).toHaveLength(1));
    expect(screen.getByText(EMPTY)).toBeTruthy();
    expect(document.body.textContent).not.toContain("trong phiên này");
  });

  it("không ghi danh sách xuống localStorage / sessionStorage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    sessionTickets.add("s1", "ticket trong phiên", []);
    stubFetch(() => json(200, { items: [item({ ticket_id: "api1", request_text: "ticket từ api" })] }));
    mount(AN);
    await waitFor(() => expect(titles()).toEqual(["ticket trong phiên", "ticket từ api"]));
    const written = setItem.mock.calls.flat().join(" ");
    for (const s of ["api1", "s1", "ticket từ api", "ticket trong phiên"]) expect(written).not.toContain(s);
  });
});
