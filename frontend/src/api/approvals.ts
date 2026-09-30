// Duyệt L1 (F4). `POST /api/approvals/{id}/decision` là route THẬT (backend/app/api/approvals.py). Hộp thư
// (`GET /api/approvals?mine=1`) và xem phiếu (`GET /api/approvals/{id}`) CHƯA CÓ — Phase 4 chặng 4c; ghi đè
// (`POST /api/tickets/{id}/override`) CHƯA CÓ — 4d. Cả ba gọi đúng route theo spec: MSW bật → handler giả trả
// (mocks/handlers/approvals.ts, override.ts); MSW tắt → tới backend (chưa có route → 404, màn tự báo "có từ Phase 4").
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

export async function listApprovals(status: ApprovalStatus): Promise<ApprovalListItem[]> {
  const res = await api.request<unknown>(`/api/approvals?mine=1&status=${status}`);
  recordServerDate(res.headers);
  if (!Array.isArray(res.data)) throw new ApiError(502, "invalid_inbox_body");
  return res.data as ApprovalListItem[];
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

/** Hộp thư: spec nói list KHÔNG BAO GIỜ 404 (4c P5) → 404 nghĩa là backend chưa có route (4c chưa merge). */
export const inboxMissing = (error: unknown): boolean => error instanceof ApiError && error.status === 404;

/** Nhịp tự tải lại hộp thư; 403 (mất quyền) / 404 (chưa có route) → dừng. */
export const inboxRefetchInterval = (error: unknown): number | false =>
  error instanceof ApiError && (error.status === 403 || error.status === 404) ? false : INBOX_REFRESH_MS;
