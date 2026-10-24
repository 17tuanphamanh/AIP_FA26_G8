// Nhịp chữ chạy phía màn (không đổi backend): server phát `token` theo cụm 2–4 từ cách ~30 ms nên chữ ra gần như tức thì. Hook này
// ĐỆM phần chữ đã nhận và cho hiện dần đều ~PACE_WORDS_PER_S từ/giây; tin dài thì tăng tốc để phần còn lại hiện xong trong
// ≤ PACE_MAX_S giây. Tin đã `message_end` nhưng chưa hiện hết vẫn được báo là CHƯA xong (`ended: false`) → `reconcile` giữ bản chạy
// chữ, ẩn bản chính thức tới khi hiện hết rồi mới đổi (không nháy, không trùng, không mất chữ). Giảm chuyển động → trả nguyên tin
// (giữ hành vi cũ: "Đang soạn câu trả lời…" rồi hiện cả tin). Dùng requestAnimationFrame; dọn khi đổi đầu vào hoặc unmount.
import { useEffect, useMemo, useRef, useState } from "react";
import type { StreamMessage } from "../../api/events.ts";
import { displayText } from "./useTicketStream.ts";

export const PACE_WORDS_PER_S = 18;
export const PACE_MAX_S = 7;
/** Bước thời gian tối đa mỗi khung (tab bị ẩn rồi hiện lại không nhảy cả đoạn). */
const MAX_FRAME_S = 0.25;

/** Tách phần chữ hiện ra thành các "từ" kèm khoảng trắng (ghép lại đúng chuỗi gốc). */
export function wordUnits(raw: string): string[] {
  return displayText(raw).match(/\s*\S+\s*/g) ?? [];
}

/** Tốc độ (từ/giây) cho tin có `total` từ: tối thiểu PACE_WORDS_PER_S, tin dài thì đủ nhanh để xong trong PACE_MAX_S. */
export function paceRate(total: number): number {
  return Math.max(PACE_WORDS_PER_S, total / PACE_MAX_S);
}

const nextFrame = (cb: (now: number) => void): number =>
  typeof requestAnimationFrame === "function"
    ? requestAnimationFrame(cb)
    : (setTimeout(() => cb(performance.now()), 16) as unknown as number);
const cancelFrame = (id: number) =>
  typeof cancelAnimationFrame === "function" ? cancelAnimationFrame(id) : clearTimeout(id);

export function usePacedMessages(messages: readonly StreamMessage[], reducedMotion: boolean): StreamMessage[] {
  const [shown, setShown] = useState<Readonly<Record<string, number>>>({});
  const pos = useRef<Record<string, number>>({});
  const goal = useRef<Map<string, number>>(new Map());
  const frame = useRef<number | null>(null);
  const last = useRef<number | null>(null);

  // Một vòng khung DUY NHẤT chạy khi còn chữ chưa hiện; token mới chỉ nâng đích (`goal`), không khởi động lại vòng (không mất nhịp).
  useEffect(() => {
    goal.current = new Map(messages.map((m) => [m.id, wordUnits(m.text).length]));
    for (const id of Object.keys(pos.current)) if (!goal.current.has(id)) delete pos.current[id];
    if (reducedMotion || frame.current !== null) return;
    const step = (now: number) => {
      const dt = last.current === null ? 0 : Math.min(Math.max(now - last.current, 0) / 1000, MAX_FRAME_S);
      last.current = now;
      let pending = false;
      let changed = false;
      for (const [id, total] of goal.current) {
        const cur = pos.current[id] ?? 0;
        if (cur >= total) continue;
        const next = Math.min(total, cur + paceRate(total) * dt);
        if (Math.floor(next) !== Math.floor(cur)) changed = true;
        pos.current[id] = next;
        if (next < total) pending = true;
      }
      if (changed) {
        const snap: Record<string, number> = {};
        for (const [id, v] of Object.entries(pos.current)) snap[id] = Math.floor(v);
        setShown(snap);
      }
      if (pending) {
        frame.current = nextFrame(step);
      } else {
        frame.current = null;
        last.current = null;
      }
    };
    frame.current = nextFrame(step);
  }, [messages, reducedMotion]);

  useEffect(
    () => () => {
      if (frame.current !== null) cancelFrame(frame.current);
      frame.current = null;
    },
    [],
  );

  return useMemo(() => {
    if (reducedMotion) return [...messages];
    return messages.map((m) => {
      const units = wordUnits(m.text);
      const k = Math.min(shown[m.id] ?? 0, units.length);
      if (k >= units.length) return m; // đã hiện hết (tin xong thì giữ nguyên `ended`)
      return { ...m, text: units.slice(0, k).join(""), ended: false };
    });
  }, [messages, shown, reducedMotion]);
}
