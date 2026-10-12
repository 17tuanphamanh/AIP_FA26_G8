// Client dùng chung của ứng dụng: nối `createClient` với trình duyệt thật.
import { type AuthChannel, createClient } from "./client.ts";

const sessionEndListeners = new Set<() => void>();

/** Đăng ký nghe "phiên hết" (refresh bị từ chối). Trả hàm huỷ đăng ký. */
export function subscribeSessionEnd(listener: () => void): () => void {
  sessionEndListeners.add(listener);
  return () => {
    sessionEndListeners.delete(listener);
  };
}

/** Đọc cookie theo tên (cookie `csrf` không HttpOnly; `refresh` HttpOnly nên JS không bao giờ thấy). */
export function readCookie(name: string): string | null {
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key !== name) continue;
    try {
      return decodeURIComponent(rest.join("="));
    } catch {
      return rest.join("=");
    }
  }
  return null;
}

// Kênh giữa các tab cùng origin (chỉ trong bộ nhớ, không ghi đĩa): chia sẻ access token vừa cấp để các tab không
// refresh qua lại (mỗi lần refresh backend thu hồi phiên cũ → token của tab kia chết).
function browserChannel(): AuthChannel | null {
  if (typeof BroadcastChannel === "undefined") return null;
  const channel = new BroadcastChannel("servicedesk-auth");
  return {
    post: (message) => channel.postMessage(message),
    subscribe: (listener) => {
      channel.onmessage = (event: MessageEvent<unknown>) => listener(event.data); // client tự kiểm dạng
    },
  };
}

export const api = createClient({
  fetch: (input, init) => globalThis.fetch(input, init),
  readCookie,
  // Web Locks có ở mọi trình duyệt hiện đại trong ngữ cảnh an toàn (https, localhost). Thiếu → vẫn single-flight trong tab.
  locks: typeof navigator !== "undefined" && navigator.locks ? navigator.locks : null,
  channel: browserChannel(),
  onSessionEnd: () => {
    for (const listener of sessionEndListeners) listener();
  },
});
