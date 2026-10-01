// Route ticket của nhân viên (KH 1.1; backend/app/api/tickets.py). Đều là route THẬT — F2 không dùng MSW. Ngoại lệ F6:
// `/reply` (CHƯA CÓ, T20); MSW chỉ chặn GET + reply của id `tkt-demo-multi-` (mocks/handlers/employee-multi.ts).
import { queryOptions } from "@tanstack/react-query";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type { Accepted, ConfirmIn, ParentReplyIn, TicketView } from "./types.ts";

/** Khớp `TEXT_MAX`, `NOTE_MAX` ở backend/app/api/tickets.py — chặn sớm ở ô nhập, backend vẫn kiểm (422). */
export const TEXT_MAX = 4000;
export const NOTE_MAX = 1000;

const ticketPath = (id: string) => `/api/tickets/${encodeURIComponent(id)}`;

export async function createTicket(text: string): Promise<Accepted> {
  return (await api.request<Accepted>("/api/tickets", { method: "POST", json: { text } })).data;
}

export async function getTicket(id: string): Promise<TicketView> {
  return (await api.request<TicketView>(ticketPath(id))).data;
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

/** Chỉ khi `waiting_for = reply` (ticket cha nhiều ý, D-31). Route CHƯA CÓ — Phase 5 T20; hiện chỉ MSW với id
 *  `tkt-demo-multi-` (hình dạng đề xuất: PLAN-fe mục 8). Body dựng ở routes/employee/multi.ts `digestReplyBody`. */
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

/**
 * Gửi; 503 có `Retry-After` (vd `ticket_busy`) → chờ đúng số giây đó rồi gửi lại, tối đa `BUSY_RETRIES` lần. 503 nghĩa
 * là backend CHƯA nhận (guard lỗi thì không INSERT; bận thì không `start_event`) nên gửi lại không tạo trùng. 503 không
 * có `Retry-After` (privacy guard) → ném ngay để người dùng tự thử lại (12b Q-fe-3).
 */
export async function withBusyRetry<T>(send: () => Promise<T>, onWait: (seconds: number) => void): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await send();
    } catch (error) {
      const busy = error instanceof ApiError && error.status === 503 && error.retryAfter !== null;
      if (!busy || attempt >= BUSY_RETRIES) throw error;
      const seconds = Math.min(error.retryAfter ?? 1, BUSY_WAIT_MAX_S);
      onWait(seconds);
      await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
    }
  }
}
