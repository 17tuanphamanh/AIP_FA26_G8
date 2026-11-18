// SSE tiến trình ticket: `GET /api/tickets/{id}/events` (backend/app/api/events.py). Chỉ là LỚP PHỤ trên polling: tin chính thức
// luôn lấy từ `GET /api/tickets/{id}` — luồng này chỉ cho thấy tiến trình (thought/status/tool_call) và chữ chạy (token).
// - Xác thực: đi qua `api.open` (cùng Bearer + làm mới token khi 401 như client hiện có) — KHÔNG tự đọc token.
// - Mọi sự kiện được kiểm dạng; sự kiện lạ / sai dạng bị bỏ (không làm vỡ màn).
// - 404 (server tắt ENABLE_SSE, hay không đọc được ticket) → `sseUnavailable()` = true cho cả phiên trang: không thử lại.
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { api } from "./http.ts";

export type StepState = "active" | "done" | "failed";
export type StreamEvent =
  | { type: "status"; step: string; label: string; state: StepState; childId?: string }
  | { type: "thought"; step: string; label: string; childId?: string }
  | { type: "tool_call"; step: string; label: string; ok: boolean; childId?: string }
  | { type: "token"; messageId: string; text: string }
  | { type: "message_end"; messageId: string }
  | { type: "waiting"; label: string; waitingFor: string }
  | { type: "done"; label: string };

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const STATES: ReadonlySet<string> = new Set<StepState>(["active", "done", "failed"]);
const LABEL_MAX = 200;
const TOKEN_MAX = 2_000;
const MESSAGE_ID = /^[a-z]{1,20}:\d{1,6}$/;

const text = (v: unknown, max: number): string | null => (typeof v === "string" && v.length <= max ? v : null);

/** Một khung `data:` → sự kiện đã kiểm dạng, hoặc null (JSON hỏng, loại lạ, thiếu/sai kiểu trường). */
export function parseStreamEvent(raw: string): StreamEvent | null {
  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(body) || typeof body.type !== "string") return null;
  const data = isRecord(body.data) ? body.data : {};
  const label = text(body.label, LABEL_MAX);
  const step = text(body.step, LABEL_MAX);
  const childId = typeof body.child_id === "string" && body.child_id.length <= 100 ? { childId: body.child_id } : {};
  switch (body.type) {
    case "status":
      return label && step && typeof data.state === "string" && STATES.has(data.state)
        ? { type: "status", step, label, state: data.state as StepState, ...childId }
        : null;
    case "thought":
      return label && step ? { type: "thought", step, label, ...childId } : null;
    case "tool_call":
      return label && step && typeof data.ok === "boolean" ? { type: "tool_call", step, label, ok: data.ok, ...childId } : null;
    case "token": {
      const piece = text(data.text, TOKEN_MAX);
      return typeof data.message_id === "string" && MESSAGE_ID.test(data.message_id) && piece !== null
        ? { type: "token", messageId: data.message_id, text: piece }
        : null;
    }
    case "message_end":
      return typeof data.message_id === "string" && MESSAGE_ID.test(data.message_id)
        ? { type: "message_end", messageId: data.message_id }
        : null;
    case "waiting":
      return label && typeof data.waiting_for === "string" ? { type: "waiting", label, waitingFor: data.waiting_for } : null;
    case "done":
      return label ? { type: "done", label } : null;
    default:
      return null;
  }
}

// ---- Trạng thái hiển thị -----------------------------------------------------------------------------------------------

export type StepItem = { step: string; label: string; state: StepState };
/** Dòng trong ThinkingBox: lý do chuẩn hoá, công cụ đã gọi, bước của ticket con. */
export type LogItem = { kind: "thought" | "tool_call" | "status"; label: string; ok?: boolean; childId?: string };
export type StreamMessage = { id: string; kind: string; ordinal: number; text: string; ended: boolean };
export type StreamEnd = { type: "done" | "waiting"; label: string; waitingFor?: string };
export type StreamView = { steps: StepItem[]; log: LogItem[]; messages: StreamMessage[]; end: StreamEnd | null };

export const EMPTY_VIEW: StreamView = { steps: [], log: [], messages: [], end: null };
const LOG_MAX = 200;
const STEPS_MAX = 30;
const MESSAGES_MAX = 20;

const withLog = (log: LogItem[], item: LogItem): LogItem[] => [...log, item].slice(-LOG_MAX);

/** Định tuyến MỘT sự kiện vào đúng khối: status → ProgressStepper (ticket gốc) hoặc dòng log (ticket con); thought/tool_call →
 *  ThinkingBox; token/message_end → tin đang chạy chữ; waiting/done → `end`. Sau `end`, sự kiện nội dung kế tiếp là LƯỢT MỚI:
 *  bước + log của lượt cũ bị xoá (tin giữ nguyên). */
/** Kiểm thử 18/11: luồng bị đóng phía màn (ticket chuyển sang chờ người — `active` = false) giữa các cụm token, trước `message_end` →
 *  tin dở dang kẹt "đang chạy" và che tin chính thức (thấy cụt chữ tới khi tải lại trang). `abandon` (chỉ phía màn) chốt các tin đó là
 *  xong → `reconcile` bỏ bản dở, hiện tin chính thức. */
export type StreamAction = StreamEvent | { type: "abandon" };

export function reduceStream(view: StreamView, event: StreamAction): StreamView {
  if (event.type === "abandon") {
    return view.messages.every((m) => m.ended) ? view : { ...view, messages: view.messages.map((m) => (m.ended ? m : { ...m, ended: true })) };
  }
  if (event.type === "waiting") return { ...view, end: { type: "waiting", label: event.label, waitingFor: event.waitingFor } };
  if (event.type === "done") return { ...view, end: { type: "done", label: event.label } };
  const base = view.end ? { ...view, steps: [], log: [], end: null } : view;
  switch (event.type) {
    case "status": {
      if (event.childId) return { ...base, log: withLog(base.log, { kind: "status", label: event.label, childId: event.childId }) };
      const item: StepItem = { step: event.step, label: event.label, state: event.state };
      const at = base.steps.findIndex((s) => s.step === event.step);
      const steps = at < 0 ? [...base.steps, item].slice(-STEPS_MAX) : base.steps.map((s, i) => (i === at ? item : s));
      return { ...base, steps };
    }
    case "thought":
      return { ...base, log: withLog(base.log, { kind: "thought", label: event.label, ...(event.childId ? { childId: event.childId } : {}) }) };
    case "tool_call":
      return {
        ...base,
        log: withLog(base.log, { kind: "tool_call", label: event.label, ok: event.ok, ...(event.childId ? { childId: event.childId } : {}) }),
      };
    case "token": {
      const found = base.messages.find((m) => m.id === event.messageId);
      if (found?.ended) return base; // phát lại sau nối lại: tin đã xong thì bỏ
      if (found) return { ...base, messages: base.messages.map((m) => (m === found ? { ...m, text: m.text + event.text } : m)) };
      const [kind = "", ordinal = "0"] = event.messageId.split(":");
      const added: StreamMessage = { id: event.messageId, kind, ordinal: Number(ordinal), text: event.text, ended: false };
      return { ...base, messages: [...base.messages, added].slice(-MESSAGES_MAX) };
    }
    case "message_end":
      return { ...base, messages: base.messages.map((m) => (m.id === event.messageId ? { ...m, ended: true } : m)) };
  }
}

// ---- Kết nối -----------------------------------------------------------------------------------------------------------

let unavailable = false;
/** Server không có SSE (404) — nhớ cho cả phiên trang để mọi ticket sau đi thẳng polling. */
export const sseUnavailable = (): boolean => unavailable;
export const markSseUnavailable = (): void => {
  unavailable = true;
};
export const resetSseAvailability = (): void => {
  unavailable = false;
};

export type StreamOutcome =
  | { kind: "ended" } // nhận `done`/`waiting` rồi server đóng
  | { kind: "closed" } // đóng mà không có sự kiện cuối (mất mạng, hết 10 phút…)
  | { kind: "unavailable" } // 404
  | { kind: "refused"; status: number } // 401/403/lỗi khác từ server: không đáng thử lại ngay
  | { kind: "error" } // lỗi mạng / sai kiểu nội dung
  | { kind: "aborted" };

export type ConnectOptions = {
  ticketId: string;
  lastEventId: string | null;
  signal: AbortSignal;
  onOpen: () => void;
  onEvent: (event: StreamEvent, id: string | undefined) => void;
};

class Stop extends Error {}

export function ticketEventsPath(ticketId: string): string {
  return `/api/tickets/${encodeURIComponent(ticketId)}/events`;
}

/** Mở MỘT kết nối; trả kết cục khi nó kết thúc (không tự nối lại — hook `useTicketStream` quyết). */
export function connectTicketStream(options: ConnectOptions): Promise<StreamOutcome> {
  return new Promise((resolve) => {
    let ended = false;
    let outcome: StreamOutcome | null = null;
    const finish = (value: StreamOutcome): never => {
      outcome ??= value;
      throw new Stop();
    };
    fetchEventSource(ticketEventsPath(options.ticketId), {
      signal: options.signal,
      headers: options.lastEventId ? { "Last-Event-ID": options.lastEventId } : {},
      openWhenHidden: true,
      fetch: (input, init) => {
        const { method, headers, signal } = init ?? {}; // GET: không thân
        return api.open(String(input), { method, headers, signal });
      },
      onopen: async (res) => {
        if (res.status === 404) return finish({ kind: "unavailable" });
        if (!res.ok) return finish({ kind: "refused", status: res.status });
        if (!(res.headers.get("Content-Type") ?? "").startsWith("text/event-stream")) return finish({ kind: "error" });
        options.onOpen();
      },
      onmessage: (message) => {
        const event = parseStreamEvent(message.data);
        if (event === null) return;
        if (event.type === "done" || event.type === "waiting") ended = true;
        options.onEvent(event, message.id || undefined);
      },
      onclose: () => finish(ended ? { kind: "ended" } : { kind: "closed" }),
      onerror: (error) => {
        if (error instanceof Stop) throw error;
        return finish({ kind: "error" });
      },
    }).then(
      () => resolve(outcome ?? { kind: "aborted" }), // fetchEventSource kết thúc êm khi bị huỷ
      () => resolve(options.signal.aborted ? { kind: "aborted" } : (outcome ?? { kind: "error" })),
    );
  });
}
