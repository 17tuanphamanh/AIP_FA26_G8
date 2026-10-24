// Dựng luồng SSE giả cho test (không gọi mạng): khung `id/event/data` đúng dạng backend/app/api/events.py.
export type Wire = { type: string; step?: string; label?: string; at?: string; data?: Record<string, unknown>; child_id?: string };

export const wire = (type: string, extra: Omit<Wire, "type"> = {}): Wire => ({
  type,
  step: extra.step ?? "x",
  label: extra.label ?? "",
  at: "2026-10-24T04:00:00+00:00",
  ...extra,
});

export const status = (step: string, label: string, state = "active", child_id?: string): Wire =>
  wire("status", { step, label, data: { state }, ...(child_id ? { child_id } : {}) });
export const thought = (label: string): Wire => wire("thought", { step: "assess", label });
export const toolCall = (label: string, ok = true): Wire => wire("tool_call", { step: "diagnose", label, data: { ok } });
export const token = (message_id: string, text: string): Wire => wire("token", { step: "answer", data: { message_id, text } });
export const messageEnd = (message_id: string): Wire => wire("message_end", { step: "answer", data: { message_id } });
export const waiting = (waiting_for = "confirm"): Wire => wire("waiting", { step: waiting_for, label: "Chờ", data: { waiting_for } });
export const done = (label = "Hoàn tất"): Wire => wire("done", { step: "done", label });

export const frame = (event: Wire, id?: string): string =>
  `${id ? `id: ${id}\n` : ""}event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;

const encoder = new TextEncoder();
const SSE_HEADERS = { "Content-Type": "text/event-stream" };

/** Luồng đóng ngay sau khi phát hết `frames`. */
export function sseResponse(frames: readonly string[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(encoder.encode(f));
      controller.close();
    },
  });
  return new Response(body, { status, headers: SSE_HEADERS });
}

/** Luồng giữ mở: test tự đẩy khung / đóng. */
export function liveSse() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200, headers: SSE_HEADERS }),
    push: (...frames: string[]) => frames.forEach((f) => controller.enqueue(encoder.encode(f))),
    close: () => controller.close(),
  };
}
