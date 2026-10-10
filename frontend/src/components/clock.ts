// Nhịp 1 giây dùng chung cho mọi đồng hồ trên màn (một setInterval cho cả trang, dừng khi không còn ai nghe).
// `useServerNow()` = giờ máy chủ (giờ máy + độ lệch từ header `Date` — api/serverClock.ts).
import { useSyncExternalStore } from "react";
import { serverNow } from "../api/serverClock.ts";

export const TICK_MS = 1000;

let tick = Date.now();
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (timer === null) {
    tick = Date.now(); // lần nghe đầu sau khi dừng: không để đồng hồ đứng ở mốc cũ
    timer = setInterval(() => {
      tick = Date.now();
      for (const l of listeners) l();
    }, TICK_MS);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };
}

const machineNow = () => tick;

/** Giờ máy chủ (ms), cập nhật mỗi giây. */
export function useServerNow(): number {
  return serverNow(useSyncExternalStore(subscribe, machineNow));
}
