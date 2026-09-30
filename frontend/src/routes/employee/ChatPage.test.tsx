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
// tiêu đề, thanh bên). Tiêu đề / "Gần đây" chỉ từ câu yêu cầu, không từ câu trả lời. Tải lại → "Yêu cầu của bạn".
describe("t26: câu yêu cầu trong bộ nhớ phiên", () => {
  const EMPLOYEE: Me = {
    user_id: "nv001",
    role: "employee",
    permissions: ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"],
  };
  const REPLY = { role: "user", text: "LAP-0342" }; // câu TRẢ LỜI khi hỏi thêm — không được thành tiêu đề

  function mount(notices: string[], at = "/chat") {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        if ((init.method ?? "GET") === "POST" && url === "/api/tickets") {
          return json(202, { ticket_id: ID, status: "S_NEW", notices });
        }
        if (url === `/api/tickets/${ID}`) {
          return json(200, view({ status: "S_DIAGNOSING", waiting_for: null, conversation: [QUESTION, REPLY] }));
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

  it("tải lại trang (bộ nhớ phiên trống) → tiêu đề \"Yêu cầu của bạn\", không bong bóng, câu trả lời không thành tiêu đề", async () => {
    const unmount = mount([], `/chat/${ID}`);
    try {
      await screen.findByText(QUESTION.text);
      expect(heading()).toBe(DEFAULT_TITLE);
      expect(bubble()).toBeUndefined();
      expect(screen.getByText("Chưa có yêu cầu nào trong phiên này.")).toBeTruthy();
    } finally {
      unmount();
    }
  });
});
