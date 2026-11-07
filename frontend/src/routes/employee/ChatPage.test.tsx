// t25: luồng hỏi thêm (clarify) trên màn hội thoại — verify F2-3 BỎ QUA trên backend vì không có preset tất định, nên
// giả lập ở đây: waiting_for=clarify → ô trả lời mở → gửi → ĐÚNG 1 POST /messages với {text} → tải lại ticket ngay.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me, TicketView } from "../../api/types.ts";
import { Sidebar } from "../../components/Sidebar.tsx";
import { ChatHome } from "./ChatHome.tsx";
import { ChatRoute } from "./ChatPage.tsx";
import { DEFAULT_TITLE, REDACTED_NOTE, sessionTickets } from "./sessionTickets.ts";
import { SUGGESTIONS } from "./suggestions.ts";

afterEach(() => {
  cleanup();
  sessionTickets.clear();
});

const ID = "0811f300-6bb8-4cd1-8366-a6dcb8a17655";
const QUESTION = { role: "assistant", kind: "question", text: "Bạn cho mình xin mã thiết bị (ví dụ LAP-0342) nhé.", needs: "answer" };

const view = (over: Partial<TicketView>): TicketView => ({
  ticket_id: ID,
  status: "S_CLARIFYING",
  waiting_for: "clarify",
  conversation: [QUESTION],
  exit_code: null,
  close_reason: null,
  final_state: null,
  created_at: "2026-09-30T13:00:00Z",
  closed_at: null,
  ...over,
});

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("t25: ChatPage — hỏi thêm → trả lời → đi tiếp", () => {
  it("waiting_for=clarify → ô trả lời hiện; gửi → đúng 1 POST /messages {text} → tải lại ticket; ô trả lời đóng", async () => {
    const calls: { method: string; url: string; body: string | null }[] = [];
    let answered = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const method = init.method ?? "GET";
        calls.push({ method, url, body: typeof init.body === "string" ? init.body : null });
        if (method === "POST" && url === `/api/tickets/${ID}/messages`) {
          answered = true;
          return json(202, { ticket_id: ID, status: "S_CLARIFYING", notices: [] });
        }
        if (method === "GET" && url === `/api/tickets/${ID}`) {
          return json(
            200,
            answered
              ? view({ status: "S_DIAGNOSING", waiting_for: null, conversation: [QUESTION, { role: "user", text: "LAP-0342" }] })
              : view({}),
          );
        }
        return json(404, { detail: "not_found" });
      }),
    );
    const queryClient = new QueryClient();
    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[`/chat/${ID}`]}>
          <Routes>
            <Route path="/chat/:ticketId" element={<ChatRoute />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    try {
      // Ô trả lời hiện và mở khi waiting_for=clarify; câu hỏi nằm trong hội thoại.
      const box = (await screen.findByLabelText("Trả lời")) as HTMLTextAreaElement;
      expect(box.disabled).toBe(false);
      expect(screen.getByText(QUESTION.text)).toBeTruthy();

      fireEvent.change(box, { target: { value: "  LAP-0342  " } });
      fireEvent.click(screen.getByRole("button", { name: "Gửi" }));

      await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(1));
      const post = calls.find((c) => c.method === "POST")!;
      expect(post.url).toBe(`/api/tickets/${ID}/messages`);
      expect(JSON.parse(post.body ?? "null")).toStrictEqual({ text: "LAP-0342" });

      // Sau 202: gọi lại GET ngay (không chờ nhịp 10 s của waiting_for) → thấy tin người dùng, ô trả lời đóng.
      await waitFor(() =>
        expect(calls.slice(calls.indexOf(post) + 1).some((c) => c.method === "GET" && c.url === `/api/tickets/${ID}`)).toBe(true),
      );
      await waitFor(() => expect(document.querySelector('[data-role="user"]')?.textContent).toBe("LAP-0342"));
      expect(screen.queryByLabelText("Trả lời")).toBeNull();
      expect(calls.filter((c) => c.method === "POST")).toHaveLength(1); // không gửi lặp
    } finally {
      unmount();
      queryClient.clear(); // dừng polling trước khi gỡ fetch giả
    }
  });
});

// t26 (12b Q-fe-18): câu yêu cầu chỉ hiện khi 202 có notices rỗng; notices có → câu gốc KHÔNG ở đâu cả (bong bóng,
// tiêu đề, thanh bên). Tiêu đề / "Gần đây" chỉ từ câu yêu cầu, không từ câu trả lời.
// Sửa có chủ ý (Q-fe-18 (a), Nợ API #8): tải lại / mở bằng URL mà ticket có `request_text` (câu ĐÃ CHE) → đúng 1 bong
// bóng + tiêu đề từ nó; có bộ nhớ phiên → giữ (b), không nhân đôi; `request_text` null hoặc thiếu khoá → như cũ.
describe("t26: câu yêu cầu trong bộ nhớ phiên", () => {
  const EMPLOYEE: Me = {
    user_id: "nv001",
    role: "employee",
    permissions: ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"],
  };
  const REPLY = { role: "user", text: "LAP-0342" }; // câu TRẢ LỜI khi hỏi thêm — không được thành tiêu đề

  function mount(notices: string[], at = "/chat", request_text?: string | null) {
    const extra = request_text === undefined ? {} : { request_text };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        if ((init.method ?? "GET") === "POST" && url === "/api/tickets") {
          return json(202, { ticket_id: ID, status: "S_NEW", notices });
        }
        if (url === `/api/tickets/${ID}`) {
          return json(200, view({ status: "S_DIAGNOSING", waiting_for: null, conversation: [QUESTION, REPLY], ...extra }));
        }
        return json(404, { detail: "not_found" });
      }),
    );
    const queryClient = new QueryClient();
    const rendered = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[at]}>
          <Sidebar me={EMPLOYEE} onSignOut={async () => true} />
          <Routes>
            <Route path="/chat" element={<ChatHome />} />
            <Route path="/chat/:ticketId" element={<ChatRoute />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    return () => {
      rendered.unmount();
      queryClient.clear();
    };
  }

  async function send(text: string) {
    fireEvent.change(await screen.findByLabelText("Mô tả vấn đề"), { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi" }));
    await screen.findByText(QUESTION.text); // đã sang màn hội thoại và tải xong ticket
  }

  const heading = () => screen.getByRole("heading", { level: 1 }).textContent;
  const recent = () => screen.getByRole("list", { name: "Yêu cầu gần đây" }).textContent;
  const bubble = () => document.querySelector('[data-role="request"]')?.textContent;
  const bubbles = () => document.querySelectorAll('[data-role="request"]').length;

  it("notices rỗng → hiện câu vừa gõ ở bong bóng, tiêu đề, thanh bên; câu trả lời không thành tiêu đề", async () => {
    const unmount = mount([]);
    try {
      await send("VPN công ty dùng cổng nào?");
      expect(bubble()).toBe("VPN công ty dùng cổng nào?");
      expect(heading()).toBe("VPN công ty dùng cổng nào?");
      expect(recent()).toBe("VPN công ty dùng cổng nào?");
      expect(heading()).not.toBe(REPLY.text);
    } finally {
      unmount();
    }
  });

  it("notices có → câu gốc không xuất hiện ở bất kỳ đâu; bong bóng = câu đã ẩn, tiêu đề + thanh bên = mặc định", async () => {
    const secret = "Xk9#pq2Lm7";
    const typed = `mật khẩu AD của mình là ${secret}, sao không vào được VPN`;
    const unmount = mount(["Vui lòng không gửi mật khẩu qua chat"]);
    try {
      await send(typed);
      expect(bubble()).toBe(REDACTED_NOTE);
      expect(heading()).toBe(DEFAULT_TITLE);
      expect(recent()).toBe(DEFAULT_TITLE);
      expect(document.body.textContent).not.toContain(secret);
      expect(document.body.textContent).not.toContain("mật khẩu AD của mình");
      expect(screen.getByText("Vui lòng không gửi mật khẩu qua chat")).toBeTruthy(); // notice vẫn hiện
    } finally {
      unmount();
    }
  });

  it("tải lại trang, ticket thiếu khoá request_text (backend cũ) → tiêu đề \"Yêu cầu của bạn\", không bong bóng, câu trả lời không thành tiêu đề", async () => {
    const unmount = mount([], `/chat/${ID}`);
    try {
      await screen.findByText(QUESTION.text);
      expect(heading()).toBe(DEFAULT_TITLE);
      expect(bubble()).toBeUndefined();
      expect(screen.getByText("Chưa có yêu cầu nào.")).toBeTruthy();
    } finally {
      unmount();
    }
  });
  it("tải lại trang, có request_text → đúng 1 bong bóng người dùng (trên hội thoại) + tiêu đề từ câu đã che", async () => {
    const masked = "Không vào được VPN, gọi giúp em số <SĐT_1>";
    const unmount = mount([], `/chat/${ID}`, masked);
    try {
      await screen.findByText(QUESTION.text);
      expect(bubbles()).toBe(1);
      expect(bubble()).toBe(masked);
      expect(heading()).toBe(masked);
      expect(heading()).not.toBe(REPLY.text);
      const req = document.querySelector('[data-role="request"]')!;
      expect(req.compareDocumentPosition(screen.getByText(QUESTION.text)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(screen.getByText("Chưa có yêu cầu nào.")).toBeTruthy(); // GET /api/tickets 404 ở fetch giả → chỉ ticket trong phiên (rỗng)
    } finally {
      unmount();
    }
  });

  it("có bộ nhớ phiên (mine) + ticket có request_text → giữ hành vi (b), không nhân đôi bong bóng", async () => {
    const unmount = mount([], "/chat", "bản che từ backend — không được hiện");
    try {
      await send("VPN công ty dùng cổng nào?");
      expect(bubbles()).toBe(1);
      expect(bubble()).toBe("VPN công ty dùng cổng nào?");
      expect(heading()).toBe("VPN công ty dùng cổng nào?");
      expect(document.body.textContent).not.toContain("bản che từ backend");
    } finally {
      unmount();
    }
  });

  it("tải lại trang, request_text toàn khoảng trắng → như null: \"Yêu cầu của bạn\", không bong bóng", async () => {
    const unmount = mount([], `/chat/${ID}`, "  \n\t  ");
    try {
      await screen.findByText(QUESTION.text);
      expect(bubbles()).toBe(0);
      expect(heading()).toBe(DEFAULT_TITLE);
    } finally {
      unmount();
    }
  });

  it("tải lại trang, request_text đúng 500 ký tự (backend đã cắt) → bong bóng thêm \"…\" ở cuối; dưới 500 → không thêm", async () => {
    const cut = `${"Không vào được VPN từ nhà. ".repeat(20)}`.slice(0, 500);
    expect(Array.from(cut).length).toBe(500);
    let unmount = mount([], `/chat/${ID}`, cut);
    try {
      await screen.findByText(QUESTION.text);
      expect(bubbles()).toBe(1);
      expect(bubble()).toBe(`${cut}…`);
      expect(heading()!.endsWith("…")).toBe(true);
      expect(heading()!.length).toBeLessThanOrEqual(60); // tiêu đề vẫn cắt riêng ở 60 như cũ
    } finally {
      unmount();
    }
    const short = cut.slice(0, 499);
    unmount = mount([], `/chat/${ID}`, short);
    try {
      await screen.findByText(QUESTION.text);
      expect(bubble()).toBe(short);
    } finally {
      unmount();
    }
  });

  it("tải lại trang, request_text null → như cũ: \"Yêu cầu của bạn\", không bong bóng", async () => {
    const unmount = mount([], `/chat/${ID}`, null);
    try {
      await screen.findByText(QUESTION.text);
      expect(bubbles()).toBe(0);
      expect(heading()).toBe(DEFAULT_TITLE);
    } finally {
      unmount();
    }
  });
});

// ------------------------------------------------------------------------------------------------ t76 (F6 P4)

describe("t76: nút gợi ý nhanh (B4EmpHome) — điền câu mẫu + focus ô nhập, KHÔNG gửi", () => {
  it("4 nút đúng chữ Bản 4; bấm 'Lỗi VPN' → ô có câu mẫu, con trỏ cuối câu, focus ô nhập; 0 lời gọi mạng", async () => {
    const fetchSpy = vi.fn(async () => json(500, {}));
    vi.stubGlobal("fetch", fetchSpy);
    const queryClient = new QueryClient();
    const rendered = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/chat"]}>
          <Routes>
            <Route path="/chat" element={<ChatHome />} />
            <Route path="/chat/:ticketId" element={<p>trang ticket</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    try {
      const labels = SUGGESTIONS.map((s) => s.label);
      expect(labels).toStrictEqual(["Quên mật khẩu", "Lỗi VPN", "Cài phần mềm", "Xin quyền truy cập"]);
      for (const label of labels) expect(screen.getByRole("button", { name: label })).toBeTruthy();
      const box = screen.getByLabelText("Mô tả vấn đề") as HTMLTextAreaElement;
      (document.activeElement as HTMLElement | null)?.blur();

      fireEvent.click(screen.getByRole("button", { name: "Lỗi VPN" }));
      const sample = SUGGESTIONS.find((s) => s.label === "Lỗi VPN")!.text;
      await waitFor(() => expect(box.value).toBe(sample));
      expect(document.activeElement).toBe(box);
      expect(box.selectionStart).toBe(sample.length);
      // Bấm chip khác → THAY câu (không nối), vẫn không gửi; người dùng sửa được.
      fireEvent.click(screen.getByRole("button", { name: "Quên mật khẩu" }));
      await waitFor(() => expect(box.value).toBe(SUGGESTIONS[0]!.text));
      fireEvent.change(box, { target: { value: `${box.value} Tài khoản email.` } });
      await new Promise((r) => setTimeout(r, 30));
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(screen.queryByText("trang ticket")).toBeNull();
    } finally {
      rendered.unmount();
      queryClient.clear();
    }
  });

  it("câu mẫu là câu đầy đủ, không chứa dữ liệu cá nhân (tên tài khoản, mã máy, email, số)", () => {
    for (const { label, text } of SUGGESTIONS) {
      expect(text.length).toBeGreaterThan(label.length);
      expect(text).toMatch(/^Tôi .+\.$/);
      expect(text).not.toMatch(/\d|@|LAP-|PC-|an\.nv|nv0/i);
    }
  });
});

// ------------------------------------------------------------------------------------------------ t121, t123 (N-PROTO)

/** Mở /chat/:id với GET ticket trả `respond()`; trả hàm gỡ. Ghi console.error để bắt cảnh báo "not valid as a React child". */
function mountTicket(respond: () => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => (url === `/api/tickets/${ID}` ? respond() : json(404, { detail: "not_found" }))),
  );
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  const queryClient = new QueryClient();
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/chat/${ID}`]}>
        <Routes>
          <Route path="/chat/:ticketId" element={<ChatRoute />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const reactChildErrors = () => consoleError.mock.calls.filter((args) => args.some((a) => String(a).includes("React child")));
  return {
    reactChildErrors,
    done: () => {
      rendered.unmount();
      queryClient.clear();
    },
  };
}
const noLeak = () => expect(document.body.textContent).not.toMatch(/function |\[object /);

describe("t121 (render): lỗi tải ticket với mã '__proto__' / 'constructor' / 'toString' → câu chung theo status", () => {
  it.each(["__proto__", "constructor", "toString"])("500 {detail: %j} → 'Có lỗi xảy ra, vui lòng thử lại.'", async (code) => {
    const page = mountTicket(() => json(500, { detail: code }));
    try {
      expect((await screen.findByRole("heading", { name: "Chưa tải được yêu cầu." })).nextElementSibling?.textContent).toBe(
        "Có lỗi xảy ra, vui lòng thử lại.",
      );
      expect(page.reactChildErrors()).toHaveLength(0);
      noLeak();
    } finally {
      page.done();
    }
  });

  it("mã hợp lệ (503 ticket_busy) vẫn ra câu riêng", async () => {
    const page = mountTicket(() => json(503, { detail: "ticket_busy" }));
    try {
      expect((await screen.findByRole("heading", { name: "Chưa tải được yêu cầu." })).nextElementSibling?.textContent).toBe(
        "Hệ thống đang bận, sẽ tự thử lại.",
      );
    } finally {
      page.done();
    }
  });
});

describe("t123: final_state '__proto__' / 'constructor' / 'toString' → câu kết thúc = nhãn trạng thái lạ, màn không vỡ", () => {
  it.each(["__proto__", "constructor", "toString"])("final_state %j → 'Đang xử lý yêu cầu' (câu cuối + nhãn header)", async (state) => {
    const page = mountTicket(() => json(200, view({ status: state, waiting_for: null, final_state: state })));
    try {
      expect((await screen.findByTestId("final-note")).firstElementChild?.textContent).toBe("Đang xử lý yêu cầu");
      expect(document.querySelector('header [role="status"]')?.textContent).toBe("Đang xử lý yêu cầu");
      expect(page.reactChildErrors()).toHaveLength(0);
      noLeak();
    } finally {
      page.done();
    }
  });

  it("final_state hợp lệ (S_RESOLVED) vẫn ra câu kết thúc cũ", async () => {
    const page = mountTicket(() => json(200, view({ status: "S_RESOLVED", waiting_for: null, final_state: "S_RESOLVED" })));
    try {
      expect((await screen.findByTestId("final-note")).firstElementChild?.textContent).toBe(
        "Yêu cầu đã hoàn tất. Cần thêm gì, bạn tạo yêu cầu mới nhé.",
      );
    } finally {
      page.done();
    }
  });
});

// ------------------------------------------------------------------------------------------------ t201 (hợp đồng sửa lần 3, ĐP 26/10 23:51)

describe("t201: tạo ticket 503 `strategy_unavailable` → đúng câu, giữ chữ đã gõ, KHÔNG tự gửi lại (kể cả có Retry-After), không lộ mã", () => {
  it("1 lần gọi; câu đúng chữ; ô nhập giữ nguyên; người dùng bấm Gửi lại → gọi lần 2", async () => {
    const TEXT = "Tôi không vào được VPN từ sáng nay.";
    const fetchSpy = vi.fn(
      async () => new Response(JSON.stringify({ detail: "strategy_unavailable" }), { status: 503, headers: { "Content-Type": "application/json", "Retry-After": "1" } }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const queryClient = new QueryClient();
    const rendered = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/chat"]}>
          <Routes>
            <Route path="/chat" element={<ChatHome />} />
            <Route path="/chat/:ticketId" element={<p>trang ticket</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    try {
      const box = screen.getByLabelText("Mô tả vấn đề") as HTMLTextAreaElement;
      fireEvent.change(box, { target: { value: TEXT } });
      fireEvent.click(screen.getByRole("button", { name: "Gửi" }));
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toBe("Hệ thống tạm thời chưa nhận yêu cầu, vui lòng thử lại sau ít phút.");
      expect(box.value).toBe(TEXT);
      expect(document.body.textContent).not.toMatch(/strategy_unavailable|503|tự thử lại/);
      // Quá Retry-After (1 giây) mà vẫn chỉ 1 lần gọi — không tự gửi lại.
      await new Promise((r) => setTimeout(r, 1_200));
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      expect(screen.queryByText("trang ticket")).toBeNull();
      // Người dùng tự bấm gửi lại → đúng 1 lần gọi nữa, cùng chữ.
      fireEvent.click(screen.getByRole("button", { name: "Gửi" }));
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
      const [, init] = fetchSpy.mock.calls[1] as unknown as [string, RequestInit];
      expect(JSON.parse(String(init.body))).toStrictEqual({ text: TEXT });
      await new Promise((r) => setTimeout(r, 50));
      expect(fetchSpy).toHaveBeenCalledTimes(2);
      expect(box.value).toBe(TEXT);
    } finally {
      rendered.unmount();
      queryClient.clear();
    }
  });
});
