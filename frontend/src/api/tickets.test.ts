// t23–t24: body /confirm đúng `ConfirmIn` (backend extra="forbid"); 503 + Retry-After → tự gửi lại có giới hạn.
// t127–t128 (N-T20 P2): bộ đọc hình dạng `children_progress` + tin `digest` của T20b (openapi chỉ khai list[dict]).
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./errors.ts";
import {
  BUSY_RETRIES,
  confirmBody,
  confirmTicket,
  getTicket,
  parseChildrenProgress,
  parseDigest,
  parseTicketView,
  withBusyRetry,
} from "./tickets.ts";

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

describe("t202: withBusyRetry — 503 `strategy_unavailable` có Retry-After vẫn ném NGAY, 0 lần chờ (hợp đồng sửa lần 3)", () => {
  it("1 lần gửi, không gọi onWait; ticket_busy vẫn tự thử lại như cũ", async () => {
    vi.useFakeTimers();
    const onWait = vi.fn();
    const send = vi.fn().mockRejectedValue(new ApiError(503, "strategy_unavailable", [], 1));
    await expect(withBusyRetry(send, onWait)).rejects.toMatchObject({ status: 503, code: "strategy_unavailable" });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(send).toHaveBeenCalledTimes(1);
    expect(onWait).not.toHaveBeenCalled();
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

// ------------------------------------------------------------------------------------------------ t127, t128

const T = "5b0e6c1a-2f4d-4e8b-9a7c-1d2e3f4a5b6c";
const bad = (fn: () => unknown) => {
  try {
    fn();
  } catch (error) {
    return error instanceof ApiError && error.status === 502 && error.code === "invalid_ticket_body";
  }
  return false;
};
const row = (i: number, over: Record<string, unknown> = {}) => ({
  child_id: `${T}-${i}`,
  index: i,
  title: "Đặt lại mật khẩu",
  progress: "needs_user",
  outcome: null,
  ...over,
});

describe("t127: parseChildrenProgress — hình dạng `children_progress` (T20b P11)", () => {
  it("hợp lệ → trả nguyên; thiếu / null → null (ticket thường); [] hợp lệ; title '' hợp lệ; progress/outcome lạ KHÔNG phải lỗi hình dạng", () => {
    const list = [row(1), row(2, { title: "", progress: "closed", outcome: "resolved" }), row(10, { progress: "archived", outcome: "blocked" })];
    expect(parseChildrenProgress(list, T)).toBe(list);
    expect(parseChildrenProgress(undefined, T)).toBeNull();
    expect(parseChildrenProgress(null, T)).toBeNull();
    expect(parseChildrenProgress([], T)).toStrictEqual([]);
  });

  it.each([
    ["không phải mảng", {}],
    ["phần tử null", [row(1), null]],
    ["phần tử là mảng", [[]]],
    ["thiếu child_id", [{ ...row(1), child_id: undefined }]],
    ["thiếu title", [{ ...row(1), title: undefined }]],
    ["thiếu progress", [{ ...row(1), progress: undefined }]],
    ["thiếu outcome (phải có khoá, null khi chưa closed)", [{ child_id: `${T}-1`, index: 1, title: "A", progress: "ready" }]],
    ["title số", [row(1, { title: 7 })]],
    ["progress số", [row(1, { progress: 1 })]],
    ["outcome số", [row(1, { outcome: 0 })]],
    ["index chuỗi", [row(1, { index: "1" })]],
    ["index 0", [row(1, { index: 0, child_id: `${T}-0` })]],
    ["index 100 (backend chỉ nhận 1–2 chữ số)", [row(1, { index: 100, child_id: `${T}-100` })]],
    ["index lẻ", [row(1, { index: 1.5, child_id: `${T}-1.5` })]],
    ["child_id ≠ <cha>-<index>", [row(1, { child_id: `${T}-2` })]],
    ["child_id của cha khác", [row(1, { child_id: "khac-1" })]],
    ["child_id prototype", [row(1, { child_id: "__proto__" })]],
    ["trùng child_id", [row(1), row(1)]],
  ])("%s → 502 invalid_ticket_body (MỘT phần tử hỏng = cả danh sách hỏng, không vẽ một phần)", (_name, raw) => {
    expect(bad(() => parseChildrenProgress(raw, T))).toBe(true);
  });
});

const item = (i: number, over: Record<string, unknown> = {}) => ({
  child_id: `${T}-${i}`,
  index: i,
  title: "Gia hạn quyền truy cập",
  kind: "question",
  text: "Bạn cần gia hạn thêm bao nhiêu ngày?",
  needs: "answer",
  ...over,
});
const digest = (items: unknown[], over: Record<string, unknown> = {}) => ({ role: "assistant", kind: "digest", round: 1, text: "…", items, ...over });

describe("t128: parseDigest / parseTicketView — tin tổng hợp (P9) kiểm chặt, tin thường dễ dãi", () => {
  it("hợp lệ (không options/sources); items [] (vòng cuối chỉ có câu tổng kết); kind/needs lạ; 1 con có khối none + khối confirm → không lỗi", () => {
    expect(() => parseDigest(digest([item(1, { kind: "result", needs: "confirm" }), item(2)]), T)).not.toThrow();
    expect(() => parseDigest(digest([], { round: 3, text: "Cả 2 yêu cầu đã hoàn tất." }), T)).not.toThrow();
    expect(() => parseDigest(digest([item(1, { kind: "weird", needs: "maybe" })]), T)).not.toThrow();
    expect(() => parseDigest(digest([item(1, { kind: "escalation", needs: "none" }), item(1, { kind: "result", needs: "confirm" })]), T)).not.toThrow();
  });

  it.each([
    ["round 0", digest([item(1)], { round: 0 })],
    ["round chuỗi", digest([item(1)], { round: "1" })],
    ["thiếu text", digest([item(1)], { text: undefined })],
    ["items không phải mảng", digest([], { items: {} })],
    ["khối null", digest([null])],
    ["khối thiếu kind", digest([{ ...item(1), kind: undefined }])],
    ["khối thiếu needs", digest([{ ...item(1), needs: undefined }])],
    ["khối thiếu text", digest([{ ...item(1), text: undefined }])],
    ["khối title số", digest([item(1, { title: 1 })])],
    ["child_id ≠ <cha>-<index>", digest([item(1, { child_id: `${T}-10` })])],
    ["2 khối CÙNG con đều cần trả lời", digest([item(1, { needs: "confirm" }), item(1)])],
  ])("%s → 502 invalid_ticket_body", (_name, raw) => {
    expect(bad(() => parseDigest(raw, T))).toBe(true);
  });

  it("parseTicketView: ticket_id của thân = id đã hỏi; digest kiểm theo id đó; trùng round → 502; tin thường hỏng vẫn qua (Q-fe-2)", () => {
    const body = {
      ticket_id: T,
      status: "S_CONFIRMING",
      waiting_for: "reply",
      conversation: [{ role: "user", kind: "digest", text: "người dùng — không kiểm" }, { role: "assistant", kind: "weird" }, null, digest([item(1)])],
      children_progress: [row(1)],
    };
    expect(parseTicketView(body, T)).toBe(body);
    expect(bad(() => parseTicketView({ ...body, children_progress: [row(1, { child_id: "x-1" })] }, T))).toBe(true);
    expect(bad(() => parseTicketView({ ...body, conversation: [digest([item(1, { child_id: "x-1" })])] }, T))).toBe(true);
    expect(bad(() => parseTicketView(body, "khac"))).toBe(true); // thân của ticket khác id đã hỏi
    expect(bad(() => parseTicketView({ ticket_id: "t-1", conversation: [], children_progress: null }, "t-2"))).toBe(true); // kể cả ticket thường
    expect(bad(() => parseTicketView({ ...body, conversation: [digest([item(1)]), digest([item(2)])] }, T))).toBe(true); // trùng round
    expect(() => parseTicketView({ ...body, conversation: [digest([item(1)]), digest([item(2)], { round: 2 })] }, T)).not.toThrow();
    expect(bad(() => parseTicketView([], T))).toBe(true);
    expect(bad(() => parseTicketView({ status: "S_NEW" }, T))).toBe(true);
    // Ticket thường: children_progress null, conversation không có digest → qua.
    expect(() => parseTicketView({ ticket_id: "t-1", conversation: [{ role: "assistant", kind: "answer", text: "x" }], children_progress: null }, "t-1")).not.toThrow();
  });

  it("getTicket: thân hỏng → ném 502 invalid_ticket_body (route `GET /api/tickets/{id}` trả 200)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ ticket_id: T, conversation: [], children_progress: [row(1, { index: 2 })] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(getTicket(T)).rejects.toMatchObject({ status: 502, code: "invalid_ticket_body" });
  });
});
