// TA 14/11 ("chữ chạy và khung suy luận thô kệch"): Markdown ngay khi đang chạy chữ (không lộ `**`), một lượt trả lời một ảnh đại
// diện, không hai chỉ báo "đang xử lý" cùng lúc, danh sách bước thu lại khi chữ bắt đầu chạy, tin vừa chạy xong không nháy lại.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetSseAvailability } from "../../api/events.ts";
import type { TicketView } from "../../api/types.ts";
import { Conversation } from "../../components/Conversation.tsx";
import { normalizeConversation } from "../../components/messages.ts";
import { ChatRoute } from "./ChatPage.tsx";
import { ProgressStepper } from "./ProgressStepper.tsx";
import { sessionTickets } from "./sessionTickets.ts";
import { softClose } from "./softClose.ts";
import { StreamingText } from "./StreamingText.tsx";
import { frame, liveSse, status, token } from "./streamTestKit.ts";

const ID = "0811f300-6bb8-4cd1-8366-a6dcb8a17655";

beforeEach(() => resetSseAvailability());
afterEach(() => {
  cleanup();
  sessionTickets.clear();
  vi.unstubAllGlobals();
});

describe("softClose — giấu dấu mở chưa đóng khi đang chạy chữ", () => {
  it.each([
    ["Bấm **Gia h", "Bấm Gia h"],
    ["Bấm **Gia hạn**", "Bấm **Gia hạn**"],
    ["lỗi `CERT_EXP", "lỗi CERT_EXP"],
    ["**A** và **B", "**A** và B"],
    ["không có ký hiệu", "không có ký hiệu"],
  ])("%s → %s", (input, out) => expect(softClose(input)).toBe(out));
});

describe("StreamingText", () => {
  it("tin answer đang chạy: dựng Markdown (in đậm thật, không lộ **) + con trỏ", () => {
    render(<StreamingText message={{ id: "answer:1", kind: "answer", ordinal: 1, text: "Máy **LAP-0342** cần **gia h", ended: false }} reducedMotion={false} />);
    const box = screen.getByTestId("streaming-message");
    expect(box.querySelector("strong")?.textContent).toBe("LAP-0342");
    expect(box.textContent).not.toContain("**");
    expect(screen.getByTestId("stream-caret")).toBeTruthy();
  });

  it("bare: không vẽ ảnh đại diện (lượt trả lời đã có)", () => {
    const { container } = render(
      <StreamingText message={{ id: "answer:1", kind: "answer", ordinal: 1, text: "Chào", ended: false }} reducedMotion={false} bare />,
    );
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("ProgressStepper thu lại", () => {
  it("collapsed → vẫn trong DOM nhưng ẩn với trình đọc màn hình", () => {
    const { container } = render(<ProgressStepper steps={[{ step: "a", label: "Đang làm", state: "active" }]} collapsed />);
    expect(screen.getByTestId("progress-stepper")).toBeTruthy();
    expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("Conversation quiet", () => {
  it("tin được đánh dấu quiet không có hiệu ứng vào; tin khác vẫn có", () => {
    const messages = normalizeConversation([
      { role: "assistant", kind: "answer", text: "Tin cũ." },
      { role: "assistant", kind: "answer", text: "Tin vừa chạy chữ." },
    ]);
    const { container } = render(<Conversation messages={messages} quiet={(m) => m.text === "Tin vừa chạy chữ."} />);
    const rows = container.querySelectorAll('[data-kind="answer"]');
    expect(rows[0]?.className).toContain("animate-rise-in");
    expect(rows[1]?.className).not.toContain("animate-rise-in");
  });
});

describe("ChatPage — một lượt trả lời đang chạy", () => {
  const view = (): TicketView => ({
    ticket_id: ID,
    status: "S_DIAGNOSING",
    waiting_for: null,
    conversation: [],
    exit_code: null,
    close_reason: null,
    final_state: null,
    created_at: "2026-10-24T04:00:00Z",
    closed_at: null,
  });
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

  it("có khung tiến trình → không có dòng 'đang xử lý' thứ hai; chữ chạy → danh sách bước thu lại; chỉ một ảnh đại diện", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const live = liveSse();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === `/api/tickets/${ID}`) return json(view());
        if (url === `/api/tickets/${ID}/events`) return live.response;
        return new Response("{}", { status: 404 });
      }),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[`/chat/${ID}`]}>
          <Routes>
            <Route path="/chat/:ticketId" element={<ChatRoute />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("processing")).toBeTruthy(); // chưa có sự kiện nào: chỉ báo đơn
    act(() => live.push(frame(status("diagnose", "Đang kiểm tra hệ thống"), "1")));
    await screen.findByTestId("stream-progress");
    expect(screen.queryByTestId("processing")).toBeNull();
    const stepperBox = () => screen.getByTestId("progress-stepper").parentElement?.parentElement;
    expect(stepperBox()?.getAttribute("aria-hidden")).toBeNull();
    act(() => live.push(frame(token("answer:1", "Bạn mở ứng dụng VPN "), "2")));
    await waitFor(() => expect(screen.getByTestId("streaming-message").textContent).toContain("Bạn"));
    expect(stepperBox()?.getAttribute("aria-hidden")).toBe("true");
    expect(screen.getByTestId("assistant-turn").querySelectorAll("img")).toHaveLength(1);
    live.close();
  });
});
