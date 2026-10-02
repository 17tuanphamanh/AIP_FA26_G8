// Duyệt L1 (F4, nối thật N4c). Route THẬT ở backend/app/api/approvals.py (4c `b457e6e`): hộp thư
// `GET /api/approvals?mine=1&status=…` → `{items: [...]}`, xem phiếu `GET /api/approvals/{id}`, quyết định
// `POST /api/approvals/{id}/decision`. Ghi đè (`POST /api/tickets/{id}/override`) CHƯA CÓ — 4d (MSW ở dev:mock; MSW tắt →
// 404 "Not Found" → hộp ghi đè tự báo "có từ Phase 4 (4d)").
// Mọi response thành công của hộp thư / phiếu cập nhật độ lệch giờ máy chủ (header `Date`, serverClock.ts).
import { queryOptions } from "@tanstack/react-query";
import type { Client } from "./client.ts";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import { recordServerDate } from "./serverClock.ts";
import type { ApprovalListItem, ApprovalStatus, ApprovalViewP4, DecisionAccepted, DecisionIn, OverrideIn } from "./types.ts";

/** Khớp `NOTE_MAX` ở backend/app/api/approvals.py và `note ≤ 1000` của ghi đè (4d P2). */
export const NOTE_MAX = 1000;
/** Hộp thư trả tối đa 50 phiếu (4c P5). */
export const INBOX_LIMIT = 50;
export const INBOX_REFRESH_MS = 30_000;

const approvalPath = (id: string) => `/api/approvals/${encodeURIComponent(id)}`;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

/** Đủ để dựng một dòng và mở phiếu: id, ticket, hạn là chuỗi. Trường khác thiếu/lạ → màn tự xử (nhãn, "(không có)"). */
const isInboxItem = (value: unknown): value is ApprovalListItem =>
  isRecord(value) && typeof value.approval_id === "string" && typeof value.ticket_id === "string" && typeof value.deadline === "string";

/**
 * Thân hộp thư — MỘT hình dạng duy nhất `{items: [...]}`. Mảng trần, thiếu `items`, hay CHỈ MỘT phần tử hỏng → 502
 * `invalid_inbox_body` (màn báo lỗi): không đoán dạng, không lặng lẽ bỏ phiếu — người duyệt phải thấy đủ phiếu được giao.
 */
export function parseInbox(body: unknown): ApprovalListItem[] {
  const items = isRecord(body) ? body.items : undefined;
  if (!Array.isArray(items) || !items.every(isInboxItem)) throw new ApiError(502, "invalid_inbox_body");
  return items;
}

export async function listApprovals(status: ApprovalStatus): Promise<ApprovalListItem[]> {
  const res = await api.request<unknown>(`/api/approvals?mine=1&status=${status}`);
  recordServerDate(res.headers);
  return parseInbox(res.data);
}

export async function getApproval(id: string): Promise<ApprovalViewP4> {
  const res = await api.request<ApprovalViewP4>(approvalPath(id));
  recordServerDate(res.headers);
  return res.data;
}

export async function decideApproval(id: string, body: DecisionIn): Promise<DecisionAccepted> {
  return (await api.request<DecisionAccepted>(`${approvalPath(id)}/decision`, { method: "POST", json: body })).data;
}

/** `client` mặc định là client dùng chung — CÙNG client với đăng nhập (đăng nhập lại khi 403 `reauth_required`). */
export async function overrideTicket(ticketId: string, body: OverrideIn, client: Client = api): Promise<void> {
  await client.request<unknown>(`/api/tickets/${encodeURIComponent(ticketId)}/override`, { method: "POST", json: body });
}

export const inboxQuery = (status: ApprovalStatus) =>
  queryOptions({
    queryKey: ["approvals", "list", status] as const,
    queryFn: () => listApprovals(status),
    retry: false,
  });

export const approvalQuery = (id: string) =>
  queryOptions({
    queryKey: ["approvals", "view", id] as const,
    queryFn: () => getApproval(id),
    retry: false,
  });

/** Nhịp tự tải lại hộp thư; 403 (mất quyền) → dừng. Lỗi khác (404, 5xx, mạng) là lỗi thật → vẫn thử lại theo nhịp. */
export const inboxRefetchInterval = (error: unknown): number | false =>
  error instanceof ApiError && error.status === 403 ? false : INBOX_REFRESH_MS;
