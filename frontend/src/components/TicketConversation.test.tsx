// M2 bn-a: hội thoại CHỈ ĐỌC của IT (chi tiết escalate F3, màn ghi đè F4) khi job hạn giữ đã dọn checkpoint → backend 410
// `conversation_purged` → câu chính sách lưu trữ (trung tính, không alert), kể cả khi màn truyền `failText` riêng.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PURGED_TEXT } from "../api/errors.ts";
import { TicketConversation } from "./TicketConversation.tsx";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function mount(status: number, detail: string, failText?: string) {
  vi.stubGlobal("fetch", vi.fn(async () => json(status, { detail })));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TicketConversation ticketId="tkt-cu" failText={failText} />
    </QueryClientProvider>,
  );
}

describe("M2: TicketConversation — 410 conversation_purged", () => {
  it.each([undefined, "Chưa tải được chi tiết yêu cầu."])("failText=%j → câu chính sách lưu trữ, không alert", async (failText) => {
    mount(410, "conversation_purged", failText);
    expect((await screen.findByTestId("conversation-purged")).textContent).toBe(PURGED_TEXT);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("ticket-unavailable")).toBeNull();
  });

  it("lỗi khác (503) vẫn như cũ — không nhầm thành 'đã dọn'", async () => {
    mount(503, "checkpoint_unavailable");
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByTestId("conversation-purged")).toBeNull();
  });
});

// Kiểm thử 12/11: L1/L2 xem hội thoại chỉ đọc mà không thấy câu người dùng đã xin (conversation bắt đầu từ câu hỏi của bot).
// Câu yêu cầu đầu = `request_text` (đã che) — bong bóng đầu, như ChatPage; null/rỗng → không bong bóng.
const QUESTION = "Bạn cần dùng trong bao nhiêu ngày? Trả lời bằng số ngày, ví dụ 30.";
function mountView(over: Record<string, unknown>) {
  const body = {
    ticket_id: "tkt-cu",
    status: "S_CLARIFYING",
    children_progress: [],
    conversation: [{ role: "assistant", kind: "question", text: QUESTION, ref: null, needs: "answer" }],
    request_text: "Cho mình quyền đọc thư mục shared/templates",
    ...over,
  };
  vi.stubGlobal("fetch", vi.fn(async () => json(200, body)));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TicketConversation ticketId="tkt-cu" />
    </QueryClientProvider>,
  );
}

describe("12/11: câu yêu cầu đầu trong hội thoại chỉ đọc của IT", () => {
  it("có request_text → bong bóng đầu là câu gốc, rồi mới tới câu hỏi của bot", async () => {
    mountView({});
    const first = await screen.findByText("Cho mình quyền đọc thư mục shared/templates");
    expect(first.getAttribute("data-role")).toBe("request");
    const question = screen.getByText(QUESTION);
    expect(first.compareDocumentPosition(question) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each([null, "   ", undefined])("request_text=%j → không bong bóng câu gốc", async (requestText) => {
    mountView({ request_text: requestText });
    expect(await screen.findByText(QUESTION)).toBeTruthy();
    expect(document.querySelector('[data-role="request"]')).toBeNull();
  });

  it("chưa có tin nào nhưng có câu gốc → hiện câu gốc, không '(không có)'", async () => {
    mountView({ conversation: [] });
    expect(await screen.findByText("Cho mình quyền đọc thư mục shared/templates")).toBeTruthy();
    expect(screen.queryByText("(không có)")).toBeNull();
  });

  it("câu gốc đủ 500 ký tự (backend cắt) → thêm '…'", async () => {
    mountView({ request_text: "a".repeat(500) });
    expect(await screen.findByText(`${"a".repeat(500)}…`)).toBeTruthy();
  });
});
