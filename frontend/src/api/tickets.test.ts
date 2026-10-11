// t23–t24: body /confirm đúng `ConfirmIn` (backend extra="forbid"); 503 + Retry-After → tự gửi lại có giới hạn.
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./errors.ts";
import { BUSY_RETRIES, confirmBody, confirmTicket, withBusyRetry } from "./tickets.ts";

afterEach(() => {
  vi.useRealTimers();
});

describe("t23: body /confirm", () => {
  it("chỉ khoá confirmed (+ note khi có chữ); ghi chú rỗng / toàn khoảng trắng → không có khoá note", () => {
    expect(confirmBody(true)).toStrictEqual({ confirmed: true });
    expect(confirmBody(false)).toStrictEqual({ confirmed: false });
    expect(confirmBody(false, "   ")).toStrictEqual({ confirmed: false });
    expect(confirmBody(false, "  vẫn chưa vào được  ")).toStrictEqual({ confirmed: false, note: "vẫn chưa vào được" });
  });

  it("confirmTicket gửi POST /api/tickets/{id}/confirm với đúng JSON", async () => {
    const fetch = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () =>
      new Response(JSON.stringify({ ticket_id: "t-1", status: "S_CONFIRMING", notices: [] }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    await confirmTicket("t-1", confirmBody(false, "máy vẫn báo lỗi"));
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/api/tickets/t-1/confirm");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toStrictEqual({ confirmed: false, note: "máy vẫn báo lỗi" });
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  });
});

describe("t24: 503 + Retry-After → tự thử lại", () => {
  it("503 có Retry-After → chờ đúng số giây rồi gửi lại; 503 không có Retry-After → ném ngay", async () => {
    vi.useFakeTimers();
    const onWait = vi.fn();
    const send = vi.fn().mockRejectedValueOnce(new ApiError(503, "ticket_busy", [], 2)).mockResolvedValueOnce("ok");
    const result = withBusyRetry(send, onWait);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(send).toHaveBeenCalledTimes(1); // chưa hết 2 giây
    await vi.advanceTimersByTimeAsync(1);
    await expect(result).resolves.toBe("ok");
    expect(onWait).toHaveBeenCalledWith(2);

    const guard = vi.fn().mockRejectedValue(new ApiError(503, "privacy_guard_unavailable"));
    await expect(withBusyRetry(guard, onWait)).rejects.toMatchObject({ status: 503 });
    expect(guard).toHaveBeenCalledTimes(1);
  });

  it(`bận mãi → dừng sau ${BUSY_RETRIES} lần gửi lại`, async () => {
    vi.useFakeTimers();
    const send = vi.fn().mockRejectedValue(new ApiError(503, "ticket_busy", [], 1));
    const result = withBusyRetry(send, () => undefined);
    const settled = expect(result).rejects.toMatchObject({ status: 503 });
    await vi.advanceTimersByTimeAsync(10_000);
    await settled;
    expect(send).toHaveBeenCalledTimes(1 + BUSY_RETRIES);
  });
});
