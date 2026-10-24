// Nhịp chữ chạy phía màn (usePacedMessages) — đồng hồ giả: ~18 từ/giây, tin dài xong trong ≤ 7 giây, tin đã `message_end` chỉ báo
// xong khi đã hiện hết, giảm chuyển động trả nguyên tin, dọn khung khi unmount.
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamMessage } from "../../api/events.ts";
import { PACE_MAX_S, PACE_WORDS_PER_S, paceRate, usePacedMessages, wordUnits } from "./usePacedMessages.ts";

const msg = (text: string, ended = false): StreamMessage => ({ id: "answer:1", kind: "answer", ordinal: 1, text, ended });
const words = (n: number) => Array.from({ length: n }, (_, i) => `t${i}`).join(" ") + ".";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "requestAnimationFrame", "cancelAnimationFrame", "performance"] });
});
afterEach(() => {
  vi.useRealTimers();
});

const advance = async (ms: number) => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};

describe("usePacedMessages", () => {
  it("wordUnits ghép lại đúng chuỗi; bỏ khối Nguồn", () => {
    expect(wordUnits("Bạn mở  ứng dụng").join("")).toBe("Bạn mở  ứng dụng");
    expect(wordUnits("a b\n\nNguồn:\n- x").join("")).toBe("a b");
    expect(paceRate(10)).toBe(PACE_WORDS_PER_S);
    expect(paceRate(700)).toBe(700 / PACE_MAX_S);
  });

  it("hiện dần ~18 từ/giây; tin đã message_end chỉ 'xong' khi hiện hết", async () => {
    const full = msg(words(36), true);
    const { result } = renderHook(({ m }) => usePacedMessages(m, false), { initialProps: { m: [full] } });
    expect(result.current[0]?.text).toBe("");
    expect(result.current[0]?.ended).toBe(false);
    await advance(1000);
    const after1s = wordUnits(result.current[0]?.text ?? "").length;
    expect(after1s).toBeGreaterThanOrEqual(15);
    expect(after1s).toBeLessThanOrEqual(20);
    expect(result.current[0]?.ended).toBe(false);
    await advance(1500);
    expect(result.current[0]?.text).toBe(full.text);
    expect(result.current[0]?.ended).toBe(true);
  });

  it("tin dài: hiện xong trong ≤ 7 giây", async () => {
    const full = msg(words(400), true);
    const { result } = renderHook(() => usePacedMessages([full], false));
    await advance(PACE_MAX_S * 1000 + 200);
    expect(result.current[0]?.ended).toBe(true);
    expect(result.current[0]?.text).toBe(full.text);
  });

  it("token mới nối tiếp không làm lùi chữ đã hiện", async () => {
    const { result, rerender } = renderHook(({ m }) => usePacedMessages(m, false), { initialProps: { m: [msg("một hai ba bốn năm ")] } });
    await advance(200);
    const before = result.current[0]?.text ?? "";
    rerender({ m: [msg("một hai ba bốn năm sáu bảy tám ")] });
    expect((result.current[0]?.text ?? "").startsWith(before)).toBe(true);
    await advance(1000);
    expect(result.current[0]?.text).toBe("một hai ba bốn năm sáu bảy tám ");
    expect(result.current[0]?.ended).toBe(false); // chưa message_end
  });

  it("giảm chuyển động: trả nguyên tin, không chạy khung", () => {
    const full = msg(words(20), true);
    const { result } = renderHook(() => usePacedMessages([full], true));
    expect(result.current[0]).toEqual(full);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("unmount → huỷ khung, không còn hẹn giờ", async () => {
    const { unmount } = renderHook(() => usePacedMessages([msg(words(50), true)], false));
    await advance(100);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
