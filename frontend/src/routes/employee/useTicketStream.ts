// Hook SSE cho màn chat nhân viên (api/events.ts). Quy tắc quay về polling (S3):
//   404 (server tắt SSE / không đọc được) · 401-403 sau khi client đã thử làm mới · ngắt/lỗi quá `MAX_RECONNECTS` lần liên tiếp
//   → phase "fallback": ChatPage dùng đúng nhịp polling hiện có (status.ts `pollDelay`). Còn kết nối tốt thì polling chỉ là lưới an toàn
//   (`POLL_STREAMING_MS`) + gọi lại ngay mỗi khi có `message_end` / `waiting` / `done`.
// `done`/`waiting` là kết thúc BÌNH THƯỜNG (không tính lỗi). Sau đó nếu ticket vẫn "đang xử lý" ở phía màn (vừa gửi 202, GET chưa
// kịp đổi bước) thì mở lại sau `reopenDelayMs`, nối tiếp từ `Last-Event-ID` cuối — không phát lại.
import { useEffect, useReducer, useRef, useState } from "react";
import {
  connectTicketStream,
  EMPTY_VIEW,
  markSseUnavailable,
  reduceStream,
  sseUnavailable,
  type StreamEvent,
  type StreamMessage,
  type StreamView,
} from "../../api/events.ts";
import { SOURCES_HEADER, type Message } from "../../components/messages.ts";

export type StreamPhase = "off" | "connecting" | "streaming" | "fallback";
export const MAX_RECONNECTS = 3;
export const RETRY_DELAY_MS = 1_000;
export const REOPEN_DELAY_MS = 1_500;
/** Lưới an toàn khi luồng đang sống: polling thưa (không thay thế được tin chính thức, chỉ đề phòng mất sự kiện). */
export const POLL_STREAMING_MS = 10_000;

/** Phần chữ hiện ra: bỏ khối "Nguồn:" cuối câu trả lời (tin chính thức hiện nguồn bằng ô riêng). */
export function displayText(raw: string): string {
  const at = raw.indexOf(`\n\n${SOURCES_HEADER}\n`);
  return at < 0 ? raw : raw.slice(0, at);
}

/** Khớp tin đang chạy chữ với tin chính thức (cùng loại, cùng thứ tự — hoặc cùng chữ). Tin xong mà chính thức đã có → bỏ bản
 *  chạy chữ (KHÔNG hiện trùng); chưa xong mà chính thức đã có → ẩn bản chính thức tới khi `message_end`. */
export function reconcile(
  messages: readonly Message[],
  streamed: readonly StreamMessage[],
): { official: Message[]; streaming: StreamMessage[] } {
  const hidden = new Set<number>();
  const streaming: StreamMessage[] = [];
  for (const s of streamed) {
    const same = messages.flatMap((m, i) => (m.role === "assistant" && !m.digest && m.kind === s.kind ? [i] : []));
    const byOrdinal = same[s.ordinal - 1];
    if (s.ended) {
      const shown = displayText(s.text);
      const byText = same.some((i) => messages[i]?.text === shown);
      if (byOrdinal === undefined && !byText) streaming.push(s); // chính thức chưa tới: giữ bản đã chạy xong, không để mất chữ
      continue;
    }
    if (byOrdinal !== undefined) hidden.add(byOrdinal);
    streaming.push(s);
  }
  return { official: messages.filter((_, i) => !hidden.has(i)), streaming };
}

export type StreamOptions = {
  ticketId: string;
  /** Ticket đang xử lý (chưa kết thúc, không chờ người — hoặc vừa gửi 202 mà GET chưa đổi). */
  active: boolean;
  /** Gọi lại `GET /api/tickets/{id}` ngay (tin chính thức). */
  onSync: () => void;
  retryDelayMs?: number;
  reopenDelayMs?: number;
  connect?: typeof connectTicketStream;
};

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });

export function useTicketStream({
  ticketId,
  active,
  onSync,
  retryDelayMs = RETRY_DELAY_MS,
  reopenDelayMs = REOPEN_DELAY_MS,
  connect = connectTicketStream,
}: StreamOptions): { phase: StreamPhase; view: StreamView } {
  const [view, dispatch] = useReducer(reduceStream, EMPTY_VIEW);
  const [conn, setPhase] = useState<StreamPhase>("off");
  const lastId = useRef<string | null>(null);
  const failures = useRef(0);
  const syncRef = useRef(onSync);
  useEffect(() => {
    syncRef.current = onSync;
  });

  useEffect(() => {
    if (!active || sseUnavailable() || failures.current > MAX_RECONNECTS) return;
    const abort = new AbortController();
    const handle = (event: StreamEvent, id: string | undefined) => {
      if (id) lastId.current = id;
      failures.current = 0; // có sự kiện = luồng sống
      dispatch(event);
      if (event.type === "message_end" || event.type === "waiting" || event.type === "done") syncRef.current();
    };
    const loop = async () => {
      while (!abort.signal.aborted) {
        setPhase("connecting");
        const out = await connect({
          ticketId,
          lastEventId: lastId.current,
          signal: abort.signal,
          onOpen: () => setPhase("streaming"),
          onEvent: handle,
        });
        if (abort.signal.aborted || out.kind === "aborted") return;
        if (out.kind === "unavailable") markSseUnavailable();
        if (out.kind === "unavailable" || out.kind === "refused") {
          setPhase("fallback");
          return;
        }
        if (out.kind === "ended") {
          setPhase("off");
          await sleep(reopenDelayMs, abort.signal);
          continue;
        }
        failures.current += 1; // closed | error
        if (failures.current > MAX_RECONNECTS) {
          setPhase("fallback");
          return;
        }
        setPhase("connecting");
        await sleep(retryDelayMs * failures.current, abort.signal);
      }
    };
    void loop();
    return () => abort.abort();
  }, [ticketId, active, connect, retryDelayMs, reopenDelayMs]);

  // Phase suy ra khi render (không setState đồng bộ trong effect): hết cớ chạy → "off"; SSE đã bị loại (404 / lỗi quá số lần) → "fallback".
  const phase: StreamPhase = conn === "fallback" || sseUnavailable() ? "fallback" : active ? conn : "off";
  return { phase, view };
}
