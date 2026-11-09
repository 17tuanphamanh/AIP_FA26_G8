// Route ticket của nhân viên (KH 1.1; backend/app/api/tickets.py). Đều là route THẬT, kể cả nhiều ý (T20b 5df24c7:
// `children_progress` trên GET cha, tin `digest`, `POST …/reply`). MSW chỉ chặn GET + reply của id minh hoạ
// `tkt-demo-multi-` (ca lỗi khó tạo trên stack — mocks/handlers/employee-multi.ts); id khác luôn đi backend.
import { queryOptions } from "@tanstack/react-query";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import { isIsoWithZone } from "./iso.ts";
import type { Accepted, ChildProgress, ConfirmIn, ParentReplyIn, TicketListItem, TicketView } from "./types.ts";

/** Khớp `TEXT_MAX`, `NOTE_MAX` ở backend/app/api/tickets.py — chặn sớm ở ô nhập, backend vẫn kiểm (422). */
export const TEXT_MAX = 4000;
export const NOTE_MAX = 1000;
/** Khớp `REQUEST_TEXT_MAX` ở backend/app/api/tickets.py: `request_text` bị CẮT (không dấu) ở 500 ký tự (điểm mã Unicode). */
export const REQUEST_TEXT_MAX = 500;

const ticketPath = (id: string) => `/api/tickets/${encodeURIComponent(id)}`;

export async function createTicket(text: string): Promise<Accepted> {
  return (await api.request<Accepted>("/api/tickets", { method: "POST", json: { text } })).data;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const isIndex = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
/** Hậu tố id con: 1–2 chữ số (`_CHILD_INDEX` của backend/app/api/tickets.py) — ≥ 100 thì `/reply` chắc chắn 422 chung. */
const isChildIndex = (value: unknown): value is number => isIndex(value) && value <= 99;
const BAD_BODY = "invalid_ticket_body";
const badBody = () => new ApiError(502, BAD_BODY);

/** `child_id` phải ĐÚNG "<ticket_id>-<index>" (backend `child_id`/`child_index`) — khoá `/reply` khác dạng là 422 chung. */
const childOf = (ticketId: string, value: Record<string, unknown>): string | null =>
  typeof value.child_id === "string" && isChildIndex(value.index) && value.child_id === `${ticketId}-${value.index}` ? value.child_id : null;

/**
 * `children_progress` của `GET /api/tickets/{cha}` (T20b P11). Thiếu / null → null (ticket thường, ticket con). Mảng mà
 * CHỈ MỘT phần tử sai hình dạng (thiếu khoá, sai kiểu, `child_id` ≠ "<cha>-<index>", trùng `child_id`) → 502
 * `invalid_ticket_body`: không đoán, không vẽ một phần. `progress`/`outcome` là chuỗi bất kỳ — giá trị lạ có nhãn dự phòng
 * (routes/employee/multi.ts); `title` có thể "".
 */
export function parseChildrenProgress(raw: unknown, ticketId: string): ChildProgress[] | null {
  if (raw === undefined || raw === null) return null;
  if (!Array.isArray(raw)) throw badBody();
  const seen = new Set<string>();
  for (const entry of raw) {
    if (!isRecord(entry)) throw badBody();
    const id = childOf(ticketId, entry);
    if (
      id === null ||
      seen.has(id) ||
      typeof entry.title !== "string" ||
      typeof entry.progress !== "string" ||
      !(entry.outcome === null || typeof entry.outcome === "string")
    ) {
      throw badBody();
    }
    seen.add(id);
  }
  return raw as ChildProgress[];
}

/**
 * Một tin `kind:"digest"` (P9): `round` nguyên ≥ 1, `text` chuỗi, `items` mảng (rỗng = vòng cuối chỉ có câu tổng kết);
 * mỗi khối đủ `child_id` (= "<cha>-<index>"), `title`, `kind`, `text`, `needs` (chuỗi — giá trị lạ chuẩn hoá ở
 * components/messages.ts). Một con có thể có nhiều khối, nhưng ≥ 2 khối CÙNG con cần trả lời (`needs` answer/confirm) →
 * không biết gửi gì → lỗi. Sai → 502 `invalid_ticket_body`.
 */
export function parseDigest(raw: unknown, ticketId: string): void {
  if (!isRecord(raw) || !isIndex(raw.round) || typeof raw.text !== "string" || !Array.isArray(raw.items)) throw badBody();
  const asking = new Set<string>();
  for (const item of raw.items) {
    if (!isRecord(item)) throw badBody();
    const id = childOf(ticketId, item);
    if (id === null || typeof item.title !== "string" || typeof item.kind !== "string" || typeof item.text !== "string" || typeof item.needs !== "string") {
      throw badBody();
    }
    if (item.needs === "answer" || item.needs === "confirm") {
      if (asking.has(id)) throw badBody();
      asking.add(id);
    }
  }
}

/** Thân `TicketView`: `ticket_id` chuỗi và = id đã hỏi (khoá `/reply` dựng từ nó, gửi tới URL của id đã hỏi);
 *  `children_progress` + MỌI tin digest kiểm chặt (trên), không hai tin digest trùng `round` (chỉ tin round lớn nhất có
 *  form); tin thường vẫn dễ dãi (12b Q-fe-2, components/messages.ts). */
export function parseTicketView(body: unknown, requestedId: string): TicketView {
  if (!isRecord(body) || body.ticket_id !== requestedId) throw badBody();
  parseChildrenProgress(body.children_progress, requestedId);
  if (Array.isArray(body.conversation)) {
    const rounds = new Set<unknown>();
    for (const m of body.conversation) {
      if (!isRecord(m) || m.role === "user" || m.kind !== "digest") continue;
      parseDigest(m, requestedId);
      if (rounds.has(m.round)) throw badBody();
      rounds.add(m.round);
    }
  }
  return body as TicketView;
}

export async function getTicket(id: string): Promise<TicketView> {
  return parseTicketView((await api.request<unknown>(ticketPath(id))).data, id);
}

/** P3 "Gần đây": số ticket thanh bên xin (`LIST_LIMIT_DEFAULT` của backend — route nhận 1–50). */
export const MY_TICKETS_LIMIT = 20;
const BAD_LIST = "invalid_ticket_list_body";
const strOrNull = (v: unknown): v is string | null => v === null || typeof v === "string";

function isListItem(v: unknown): v is TicketListItem {
  return (
    isRecord(v) &&
    typeof v.ticket_id === "string" &&
    v.ticket_id !== "" &&
    strOrNull(v.request_text) &&
    strOrNull(v.final_state) &&
    strOrNull(v.exit_code) &&
    isIsoWithZone(v.created_at) &&
    (v.closed_at === null || isIsoWithZone(v.closed_at))
  );
}

/** Thân `GET /api/tickets` = `{items: TicketListItem[]}`; MỘT phần tử sai (thiếu khoá, sai kiểu, giờ không múi) → 502
 *  `invalid_ticket_list_body` cho cả thân — không vẽ một phần. Thanh bên coi mọi lỗi là "không có danh sách" (im lặng). */
export function parseTicketList(body: unknown): TicketListItem[] {
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(isListItem)) throw new ApiError(502, BAD_LIST);
  return body.items;
}

/** Ticket gốc của CHÍNH người đang đăng nhập (backend lọc theo token, mọi vai), mới nhất trước. */
export async function listMyTickets(limit: number = MY_TICKETS_LIMIT): Promise<TicketListItem[]> {
  return parseTicketList((await api.request<unknown>(`/api/tickets?limit=${limit}`)).data);
}

/** Khoá theo `user_id`: đổi người là query khác (không bao giờ thấy danh sách người trước). Tải MỘT lần mỗi lần mở trang
 *  (không polling, không tải lại khi đổi tab/mạng về); lỗi không thử lại. Ticket vừa tạo hiện qua bộ nhớ phiên. */
export const myTicketsQuery = (userId: string) =>
  queryOptions({
    queryKey: ["tickets", "mine", userId] as const,
    queryFn: () => listMyTickets(),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

/** P3 menu ⋯ "Xóa": ẨN ticket khỏi "Gần đây" của chính người đang đăng nhập (204; gọi lại vẫn 204). Không xoá dữ liệu — mở bằng
 *  link vẫn đọc được. Ticket không có / không phải của mình / ticket con → 404 (ApiError). */
export async function hideTicket(id: string): Promise<void> {
  await api.request<void>(`${ticketPath(id)}/hide`, { method: "POST" });
}

/** Đọc một lần, không polling — cho màn chỉ đọc của IT (L1/L2 có ticket:read:any): chi tiết escalate, ghi đè. */
export const ticketReadOnlyQuery = (id: string) =>
  queryOptions({ queryKey: ["ticket", id] as const, queryFn: () => getTicket(id), retry: false });

/** Chỉ khi `waiting_for = clarify`. */
export async function sendMessage(id: string, text: string): Promise<Accepted> {
  return (await api.request<Accepted>(`${ticketPath(id)}/messages`, { method: "POST", json: { text } })).data;
}

/** Chỉ khi `waiting_for = confirm`. */
export async function confirmTicket(id: string, body: ConfirmIn): Promise<Accepted> {
  return (await api.request<Accepted>(`${ticketPath(id)}/confirm`, { method: "POST", json: body })).data;
}

/** Chỉ khi `waiting_for = reply` (ticket cha nhiều ý, D-31 — route thật T20b). Body dựng ở routes/employee/multi.ts
 *  `digestReplyBody`. */
export async function replyTicket(id: string, body: ParentReplyIn): Promise<Accepted> {
  return (await api.request<Accepted>(`${ticketPath(id)}/reply`, { method: "POST", json: body })).data;
}

/** Body `/confirm`: ĐÚNG khoá của `ConfirmIn` (backend `extra="forbid"`). Ghi chú rỗng → bỏ hẳn khoá `note`. */
export function confirmBody(confirmed: boolean, note?: string): ConfirmIn {
  const text = note?.trim() ?? "";
  return text ? { confirmed, note: text } : { confirmed };
}

/** Số lần tự gửi lại tối đa khi 503 có `Retry-After`; số giây chờ tối đa mỗi lần. */
export const BUSY_RETRIES = 3;
export const BUSY_WAIT_MAX_S = 30;
/** 503 không bao giờ tự gửi lại (kể cả có `Retry-After`). */
export const NO_AUTO_RETRY = "strategy_unavailable";

/**
 * Gửi; 503 có `Retry-After` (vd `ticket_busy`) → chờ đúng số giây đó rồi gửi lại, tối đa `BUSY_RETRIES` lần. 503 nghĩa
 * là backend CHƯA nhận (guard lỗi thì không INSERT; bận thì không `start_event`) nên gửi lại không tạo trùng. 503 không
 * có `Retry-After` (privacy guard) → ném ngay để người dùng tự thử lại (12b Q-fe-3). 503 `strategy_unavailable` (hợp đồng
 * sửa lần 3) → ném ngay DÙ có `Retry-After`: lỗi chờ vài phút, người dùng tự bấm gửi lại (chữ đã gõ giữ nguyên ở ô nhập).
 */
export async function withBusyRetry<T>(send: () => Promise<T>, onWait: (seconds: number) => void): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await send();
    } catch (error) {
      const busy = error instanceof ApiError && error.status === 503 && error.retryAfter !== null && error.code !== NO_AUTO_RETRY;
      if (!busy || attempt >= BUSY_RETRIES) throw error;
      const seconds = Math.min(error.retryAfter ?? 1, BUSY_WAIT_MAX_S);
      onWait(seconds);
      await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
    }
  }
}
