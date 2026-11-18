// useTicketStream: quay về polling (404 / lỗi / ngắt quá 3 lần), nối lại bằng Last-Event-ID, kết thúc bình thường không tính lỗi;
// reconcile: không hiện trùng tin sau message_end.
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type ConnectOptions, resetSseAvailability, sseUnavailable, type StreamEvent, type StreamMessage, type StreamOutcome } from "../../api/events.ts";
import type { Message } from "../../components/messages.ts";
import { displayText, MAX_RECONNECTS, reconcile, useTicketStream } from "./useTicketStream.ts";

beforeEach(() => resetSseAvailability());
afterEach(cleanup);

type Script = (o: ConnectOptions, call: number) => Promise<StreamOutcome> | StreamOutcome;

function setup(script: Script, active = true) {
  const calls: ConnectOptions[] = [];
  const connect = vi.fn((o: ConnectOptions) => {
    calls.push(o);
    return Promise.resolve(script(o, calls.length));
  });
  const onSync = vi.fn();
  const hook = renderHook(
    ({ active }) => useTicketStream({ ticketId: "t", active, onSync, retryDelayMs: 0, reopenDelayMs: 5, connect }),
    { initialProps: { active } },
  );
  return { ...hook, calls, connect, onSync };
}

const emit = (o: ConnectOptions, event: StreamEvent, id?: string) => act(() => o.onEvent(event, id));
const STATUS: StreamEvent = { type: "status", step: "safety", label: "Đang kiểm tra an toàn", state: "active" };
const never = (o: ConnectOptions) => new Promise<StreamOutcome>((resolve) => o.signal.addEventListener("abort", () => resolve({ kind: "aborted" })));

describe("useTicketStream", () => {
  it("không hoạt động (active=false) → không mở kết nối", async () => {
    const { connect, result } = setup(never, false);
    await new Promise((r) => setTimeout(r, 20));
    expect(connect).not.toHaveBeenCalled();
    expect(result.current.phase).toBe("off");
  });

  it("mở → streaming; sự kiện vào view; message_end/waiting/done gọi onSync ngay, status/token thì không", async () => {
    const { result, calls, onSync } = setup(never);
    await waitFor(() => expect(calls).toHaveLength(1));
    act(() => calls[0]!.onOpen());
    expect(result.current.phase).toBe("streaming");
    await emit(calls[0]!, STATUS, "1");
    await emit(calls[0]!, { type: "token", messageId: "answer:1", text: "a b" }, "2.1");
    expect(onSync).not.toHaveBeenCalled();
    await emit(calls[0]!, { type: "message_end", messageId: "answer:1" }, "2");
    expect(onSync).toHaveBeenCalledTimes(1);
    await emit(calls[0]!, { type: "waiting", label: "x", waitingFor: "confirm" });
    expect(onSync).toHaveBeenCalledTimes(2);
    expect(result.current.view.steps).toHaveLength(1);
    expect(result.current.view.messages[0]).toMatchObject({ text: "a b", ended: true });
  });

  it("unmount / active=false → huỷ kết nối đang mở", async () => {
    const { calls, rerender } = setup(never);
    await waitFor(() => expect(calls).toHaveLength(1));
    rerender({ active: false });
    expect(calls[0]!.signal.aborted).toBe(true);
  });

  it("kiểm thử 18/11: đóng luồng (active=false) giữa các cụm token, chưa message_end → tin dở chốt xong, nhường tin chính thức", async () => {
    const { result, calls, rerender } = setup(never);
    await waitFor(() => expect(calls).toHaveLength(1));
    act(() => calls[0]!.onOpen());
    await emit(calls[0]!, { type: "token", messageId: "question:1", text: "Mỗi yêu cầu mình chỉ xử lý một " }, "5.1");
    expect(result.current.view.messages[0]).toMatchObject({ ended: false });
    rerender({ active: false });
    expect(result.current.view.messages[0]).toMatchObject({ text: "Mỗi yêu cầu mình chỉ xử lý một ", ended: true });
    const full: Message = { role: "assistant", kind: "question", text: "Mỗi yêu cầu mình chỉ xử lý một tài khoản. Bạn muốn làm cho ai trước?", sources: [] };
    const r = reconcile([full], result.current.view.messages);
    expect(r.official).toStrictEqual([full]);
    expect(r.streaming).toHaveLength(0);
  });

  it("404 → fallback ngay, nhớ cho cả phiên, không thử lại", async () => {
    const { result, connect } = setup(() => ({ kind: "unavailable" }));
    await waitFor(() => expect(result.current.phase).toBe("fallback"));
    await new Promise((r) => setTimeout(r, 30));
    expect(connect).toHaveBeenCalledTimes(1);
    expect(sseUnavailable()).toBe(true);
    const second = setup(never); // ticket khác cùng phiên: đi thẳng polling
    expect(second.result.current.phase).toBe("fallback");
    expect(second.connect).not.toHaveBeenCalled();
  });

  it("401/403/5xx từ server (refused) → fallback, không thử lại, KHÔNG đánh dấu 'không có SSE'", async () => {
    const { result, connect } = setup(() => ({ kind: "refused", status: 503 }));
    await waitFor(() => expect(result.current.phase).toBe("fallback"));
    expect(connect).toHaveBeenCalledTimes(1);
    expect(sseUnavailable()).toBe(false);
  });

  it(`ngắt quá ${MAX_RECONNECTS} lần liên tiếp → fallback (sau đúng ${MAX_RECONNECTS + 1} lần mở)`, async () => {
    const { result, connect } = setup(() => ({ kind: "closed" }));
    await waitFor(() => expect(result.current.phase).toBe("fallback"));
    await new Promise((r) => setTimeout(r, 30));
    expect(connect).toHaveBeenCalledTimes(MAX_RECONNECTS + 1);
  });

  it("lỗi mạng cũng tính; nhưng có sự kiện thì đếm lại từ 0 (không fallback oan)", async () => {
    const script: Script = (o, call) => {
      if (call <= 6) {
        o.onEvent(STATUS, String(call)); // mỗi lần mở đều có tiến triển rồi mới đứt
        return { kind: "error" };
      }
      return never(o);
    };
    const { result, connect } = setup(script);
    await waitFor(() => expect(connect).toHaveBeenCalledTimes(7));
    expect(result.current.phase).not.toBe("fallback");
  });

  it("nối lại gửi Last-Event-ID = id cuối đã nhận", async () => {
    const script: Script = (o, call) => {
      if (call === 1) {
        o.onEvent(STATUS, "5");
        o.onEvent({ type: "token", messageId: "answer:1", text: "x y" }, "6.1");
        return { kind: "closed" };
      }
      return never(o);
    };
    const { calls } = setup(script);
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls.map((c) => c.lastEventId)).toEqual([null, "6.1"]);
  });

  it("kết thúc bình thường (done/waiting) không tính lỗi và mở lại khi ticket vẫn đang xử lý", async () => {
    const { calls, result } = setup((o, call) => (call <= 6 ? { kind: "ended" } : never(o)));
    await waitFor(() => expect(calls).toHaveLength(7));
    expect(result.current.phase).not.toBe("fallback");
  });
});

describe("displayText / reconcile — không hiện trùng tin", () => {
  const answer = (text: string): Message => ({ role: "assistant", kind: "answer", text, sources: [] });
  const stream = (over: Partial<StreamMessage>): StreamMessage => ({ id: "answer:1", kind: "answer", ordinal: 1, text: "Mở VPN rồi kết nối lại.", ended: false, ...over });

  it("cắt khối Nguồn khi hiện chữ chạy", () => {
    expect(displayText("Mở VPN.\n\nNguồn:\n- Tài liệu › Mục")).toBe("Mở VPN.");
    expect(displayText("Không có nguồn")).toBe("Không có nguồn");
  });

  it("đang chạy chữ mà tin chính thức đã về → ẩn bản chính thức, hiện bản chạy chữ (đúng 1 bong bóng)", () => {
    const r = reconcile([answer("Mở VPN rồi kết nối lại.")], [stream({ text: "Mở VPN" })]);
    expect(r.official).toHaveLength(0);
    expect(r.streaming).toHaveLength(1);
  });

  it("message_end + tin chính thức đã có → bỏ bản chạy chữ (không trùng)", () => {
    const r = reconcile([answer("Mở VPN rồi kết nối lại.")], [stream({ ended: true })]);
    expect(r.official).toHaveLength(1);
    expect(r.streaming).toHaveLength(0);
  });

  it("message_end nhưng chính thức chưa về → giữ bản đã chạy xong (không mất chữ)", () => {
    const r = reconcile([], [stream({ ended: true })]);
    expect(r.official).toHaveLength(0);
    expect(r.streaming).toHaveLength(1);
  });

  it("khớp theo chữ khi thứ tự lệch (hội thoại bị cắt 20 tin) và tin khác loại/thứ tự không bị ẩn", () => {
    const earlier = answer("Tin cũ hơn");
    const r = reconcile([earlier, answer("Mở VPN rồi kết nối lại.")], [stream({ ordinal: 9, ended: true })]);
    expect(r.official).toHaveLength(2);
    expect(r.streaming).toHaveLength(0);
    const r2 = reconcile([earlier, answer("Mở VPN rồi kết nối lại.")], [stream({ ordinal: 2, text: "Mở", ended: false })]);
    expect(r2.official.map((m) => m.text)).toEqual(["Tin cũ hơn"]);
    const user: Message = { role: "user", kind: "", text: "Mở VPN rồi kết nối lại.", sources: [] };
    expect(reconcile([user], [stream({ ended: true })]).streaming).toHaveLength(1); // tin người dùng không bao giờ khớp
  });
});
