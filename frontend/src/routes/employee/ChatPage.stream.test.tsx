// SSE trên màn chat nhân viên: định tuyến event vào đúng khối, ThinkingBox mặc định đóng, chữ chạy + không trùng tin sau
// message_end, reduced-motion, quay về polling khi server tắt SSE (404), không mở luồng khi đang chờ người (biểu mẫu #49 giữ nguyên).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetSseAvailability } from "../../api/events.ts";
import type { TicketView } from "../../api/types.ts";
import { ChatRoute } from "./ChatPage.tsx";
import { sessionTickets } from "./sessionTickets.ts";
import { done, frame, liveSse, messageEnd, status, thought, token, toolCall, waiting } from "./streamTestKit.ts";

const ID = "0811f300-6bb8-4cd1-8366-a6dcb8a17655";
const ANSWER = "Bạn mở ứng dụng VPN rồi bấm kết nối lại nhé.";

beforeEach(() => resetSseAvailability());
afterEach(() => {
  cleanup();
  sessionTickets.clear();
  vi.unstubAllGlobals();
});

const view = (over: Partial<TicketView> = {}): TicketView => ({
  ticket_id: ID,
  status: "S_DIAGNOSING",
  waiting_for: null,
  conversation: [],
  exit_code: null,
  close_reason: null,
  final_state: null,
  created_at: "2026-10-24T04:00:00Z",
  closed_at: null,
  ...over,
});
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

type Env = { ticket: () => TicketView; events: () => Response; calls: string[] };
function stubBackend(env: Env) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      env.calls.push(`${init.method ?? "GET"} ${url}`);
      if (url === `/api/tickets/${ID}`) return json(200, env.ticket());
      if (url === `/api/tickets/${ID}/events`) return env.events();
      return json(404, { detail: "not_found" });
    }),
  );
}
const eventsCalls = (calls: string[]) => calls.filter((c) => c.endsWith("/events")).length;
const ticketCalls = (calls: string[]) => calls.filter((c) => c === `GET /api/tickets/${ID}`).length;

function mount() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[`/chat/${ID}`]}>
        <Routes>
          <Route path="/chat/:ticketId" element={<ChatRoute />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const matchMedia = (reduce: boolean) =>
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: reduce && q.includes("reduce"), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));

describe("ChatPage + SSE", () => {
  it("event vào đúng khối: status → ProgressStepper; thought/tool_call → ThinkingBox (mặc định ĐÓNG, mở được)", async () => {
    const live = liveSse();
    const env: Env = { ticket: () => view(), events: () => live.response, calls: [] };
    stubBackend(env);
    mount();
    await waitFor(() => expect(eventsCalls(env.calls)).toBe(1));
    act(() => {
      live.push(
        frame(status("safety", "Đã kiểm tra an toàn", "done"), "1"),
        frame(status("diagnose", "Đang kiểm tra hệ thống"), "2"),
        frame(thought("Hướng dẫn phù hợp được tìm thấy trong tài liệu nội bộ"), "3"),
        frame(toolCall("Kiểm tra chứng chỉ VPN", true), "4"),
      );
    });
    const stepper = await screen.findByTestId("progress-stepper");
    expect(within(stepper).getByText("Đã kiểm tra an toàn")).toBeTruthy();
    expect(stepper.querySelector('[data-step="diagnose"]')?.getAttribute("data-state")).toBe("active");
    // lý do + công cụ KHÔNG nằm ở stepper và chưa hiện khi hộp đóng
    expect(within(stepper).queryByText(/tài liệu nội bộ/)).toBeNull();
    const box = screen.getByTestId("thinking-box");
    expect(box.getAttribute("data-open")).toBe("false");
    expect(screen.getByRole("button", { name: /Hệ thống đang xử lý/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/tài liệu nội bộ/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Hệ thống đang xử lý/ }));
    expect(box.getAttribute("data-open")).toBe("true");
    expect(within(box).getByText("Hướng dẫn phù hợp được tìm thấy trong tài liệu nội bộ")).toBeTruthy();
    expect(within(box).getByText("Kiểm tra chứng chỉ VPN — thành công")).toBeTruthy();
    expect(within(box).queryByText("Đang kiểm tra hệ thống")).toBeNull(); // status không lẫn vào ThinkingBox
    fireEvent.click(screen.getByRole("button", { name: /Hệ thống đang xử lý/ }));
    expect(box.getAttribute("data-open")).toBe("false");
    live.close();
  });

  it("token chạy chữ rồi message_end; tin chính thức về → CHỈ MỘT bản (không trùng)", async () => {
    matchMedia(false);
    const live = liveSse();
    let current = view();
    const env: Env = { ticket: () => current, events: () => live.response, calls: [] };
    stubBackend(env);
    mount();
    await waitFor(() => expect(eventsCalls(env.calls)).toBe(1));
    act(() => live.push(frame(token("answer:1", "Bạn mở ứng dụng "), "9.1"), frame(token("answer:1", "VPN rồi bấm "), "9.2")));
    const streaming = await screen.findByTestId("streaming-message");
    // nhịp chữ phía màn (usePacedMessages): cụm đã nhận KHÔNG hiện cả một lần mà hiện dần
    expect(streaming.textContent ?? "").not.toContain("Bạn mở ứng dụng VPN rồi bấm");
    await waitFor(() => expect(screen.getByTestId("streaming-message").textContent).toContain("Bạn mở ứng dụng VPN rồi bấm"));
    expect(screen.queryByTestId("stream-caret")).not.toBeNull(); // đang chạy: có con trỏ
    // tin chính thức về TRƯỚC message_end (polling bắt kịp): chỉ một bản hiện
    current = view({ status: "S_CONFIRMING", waiting_for: null, conversation: [{ role: "assistant", kind: "answer", text: ANSWER, ref: "m1", needs: "confirm" }] });
    await act(async () => {
      live.push(frame(token("answer:1", "kết nối lại nhé."), "9.3"));
      await new Promise((r) => setTimeout(r, 20));
    });
    const count = () => screen.queryAllByText((_, el) => el?.tagName === "P" && (el.textContent ?? "").includes("kết nối lại nhé")).length;
    await waitFor(() => expect(count()).toBe(1));
    // message_end → gọi lại GET ngay → bản chạy chữ được thay bằng tin chính thức
    const before = ticketCalls(env.calls);
    act(() => live.push(frame(messageEnd("answer:1"), "9")));
    await waitFor(() => expect(ticketCalls(env.calls)).toBeGreaterThan(before));
    await waitFor(() => expect(screen.queryByTestId("streaming-message")).toBeNull());
    expect(screen.getAllByText(ANSWER)).toHaveLength(1);
    live.close();
  });

  it("message_end mà GET chưa có tin → vẫn giữ chữ đã chạy xong; GET có tin → thay, không nhân đôi", async () => {
    matchMedia(false);
    const live = liveSse();
    let current = view();
    const env: Env = { ticket: () => current, events: () => live.response, calls: [] };
    stubBackend(env);
    mount();
    await waitFor(() => expect(eventsCalls(env.calls)).toBe(1));
    act(() => live.push(frame(token("answer:1", ANSWER), "9.1"), frame(messageEnd("answer:1"), "9")));
    await waitFor(() => expect(screen.getByTestId("streaming-message").getAttribute("data-ended")).toBe("true"));
    expect(screen.getAllByText(ANSWER)).toHaveLength(1);
    current = view({ status: "S_CONFIRMING", waiting_for: "confirm", conversation: [{ role: "assistant", kind: "answer", text: ANSWER, ref: "m1", needs: "confirm" }] });
    act(() => live.push(frame(waiting("confirm"))));
    await waitFor(() => expect(screen.queryByTestId("streaming-message")).toBeNull());
    expect(screen.getAllByText(ANSWER)).toHaveLength(1);
    live.close();
  });

  it("reduced-motion: KHÔNG chạy chữ — chỉ 'Đang soạn câu trả lời…' tới message_end, rồi hiện cả tin; không con trỏ nhấp nháy", async () => {
    matchMedia(true);
    const live = liveSse();
    const env: Env = { ticket: () => view(), events: () => live.response, calls: [] };
    stubBackend(env);
    mount();
    await waitFor(() => expect(eventsCalls(env.calls)).toBe(1));
    act(() => live.push(frame(token("answer:1", "Bạn mở ứng dụng "), "9.1"), frame(token("answer:1", "VPN rồi bấm kết nối lại nhé."), "9.2")));
    expect(await screen.findByText("Đang soạn câu trả lời…")).toBeTruthy();
    expect(screen.queryByText(/Bạn mở ứng dụng/)).toBeNull();
    expect(screen.queryByTestId("stream-caret")).toBeNull();
    act(() => live.push(frame(messageEnd("answer:1"), "9")));
    await waitFor(() => expect(screen.queryByText("Đang soạn câu trả lời…")).toBeNull());
    expect(screen.getByText(/Bạn mở ứng dụng VPN rồi bấm kết nối lại nhé\./)).toBeTruthy();
    live.close();
  });

  it("server tắt SSE (404) → không dựng khối SSE, polling 2 s như cũ, không gọi /events lại", async () => {
    const env: Env = { ticket: () => view(), events: () => json(404, { detail: "not_found" }), calls: [] };
    stubBackend(env);
    mount();
    await screen.findByTestId("processing");
    await waitFor(() => expect(eventsCalls(env.calls)).toBe(1));
    const first = ticketCalls(env.calls);
    await waitFor(() => expect(ticketCalls(env.calls)).toBeGreaterThan(first), { timeout: 4_000 }); // nhịp 2 s của status.ts
    expect(eventsCalls(env.calls)).toBe(1);
    expect(screen.queryByTestId("stream-progress")).toBeNull();
    expect(screen.queryByTestId("thinking-box")).toBeNull();
  }, 10_000);

  it("luồng đang sống → polling chỉ còn là lưới an toàn thưa (không còn nhịp 2 s)", async () => {
    const live = liveSse();
    const env: Env = { ticket: () => view(), events: () => live.response, calls: [] };
    stubBackend(env);
    mount();
    await waitFor(() => expect(eventsCalls(env.calls)).toBe(1));
    act(() => live.push(frame(status("safety", "Đang kiểm tra an toàn"), "1")));
    await screen.findByTestId("progress-stepper");
    // Không thưa: GET lặp mỗi 2 s → sau 4,6 s phải ≥ 3 lần. Có thưa: lần GET đầu có thể còn theo nhịp 2 s (luồng chưa mở), sau đó 10 s → ≤ 2.
    await new Promise((r) => setTimeout(r, 4_600));
    expect(ticketCalls(env.calls)).toBeLessThanOrEqual(2);
    live.close();
  }, 15_000);

  it("ticket đang CHỜ người (waiting_for) → không mở luồng; giao diện hiện có giữ nguyên", async () => {
    const env: Env = {
      ticket: () => view({ status: "S_PENDING_APPROVAL", waiting_for: "approval" }),
      events: () => liveSse().response,
      calls: [],
    };
    stubBackend(env);
    mount();
    expect((await screen.findAllByText("Chờ IT duyệt")).length).toBeGreaterThan(0); // N-NGU: nhãn trạng thái = câu chờ duyệt
    await new Promise((r) => setTimeout(r, 30));
    expect(eventsCalls(env.calls)).toBe(0);
    expect(screen.queryByTestId("stream-progress")).toBeNull();
  });

  it("ticket đã kết thúc → không mở luồng", async () => {
    const env: Env = { ticket: () => view({ status: "S_RESOLVED", final_state: "S_RESOLVED" }), events: () => liveSse().response, calls: [] };
    stubBackend(env);
    mount();
    await screen.findByTestId("final-note");
    await new Promise((r) => setTimeout(r, 30));
    expect(eventsCalls(env.calls)).toBe(0);
  });

  it("nhận 'done' → gọi lại GET ngay (tin chính thức), khối tiến trình biến mất khi ticket đã kết thúc", async () => {
    const live = liveSse();
    let current = view();
    const env: Env = { ticket: () => current, events: () => live.response, calls: [] };
    stubBackend(env);
    mount();
    await waitFor(() => expect(eventsCalls(env.calls)).toBe(1));
    act(() => live.push(frame(status("execute", "Đang thực hiện"), "1")));
    await screen.findByTestId("progress-stepper");
    current = view({ status: "S_RESOLVED", final_state: "S_RESOLVED" });
    const before = ticketCalls(env.calls);
    act(() => live.push(frame(done())));
    await waitFor(() => expect(ticketCalls(env.calls)).toBeGreaterThan(before));
    await screen.findByTestId("final-note");
    expect(screen.queryByTestId("stream-progress")).toBeNull();
    live.close();
  });
});
