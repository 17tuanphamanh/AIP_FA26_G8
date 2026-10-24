// Duyệt L1 (F4, nối thật N4c, N4d). Route THẬT ở backend/app/api/approvals.py (4c `b457e6e`): hộp thư
// `GET /api/approvals?mine=1&status=…` → `{items: [...]}`, xem phiếu `GET /api/approvals/{id}`, quyết định
// `POST /api/approvals/{id}/decision`. Ghi đè `POST /api/tickets/{id}/override` THẬT ở backend/app/api/tickets.py (4d
// `e510a6e`) → 201 `{ticket_id, original_decision, override_decision, reason_code, notices}`; dev:mock chỉ giả id ticket
// minh hoạ (mocks/handlers/override.ts), id khác tới backend thật.
// Mọi response thành công của hộp thư / phiếu cập nhật độ lệch giờ máy chủ (header `Date`, serverClock.ts).
import { queryOptions } from "@tanstack/react-query";
import type { Client } from "./client.ts";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import { recordServerDate } from "./serverClock.ts";
import type {
  ApprovalListItem,
  ApprovalStatus,
  ApprovalViewP4,
  DecisionAccepted,
  DecisionIn,
  OverrideIn,
  OverrideRecorded,
} from "./types.ts";

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

const isString = (value: unknown): value is string => typeof value === "string";
const isStringOrNull = (value: unknown): value is string | null => value === null || typeof value === "string";
const isNumberOrNull = (value: unknown): value is number | null => value === null || (typeof value === "number" && Number.isFinite(value));
const oneOf = (value: unknown, allowed: readonly (string | null)[]): boolean => allowed.includes(value as string | null);
const BAD_APPROVAL = "invalid_approval_body";

/** `affected.manager`: `known` ⇒ có `user_id`; `unknown` ⇒ `user_id` và `full_name` đều null (backend không bao giờ có
 *  giá trị "không có quản lý"). Sai kiểu / giá trị lạ / mâu thuẫn → false. */
function isManagerRef(value: unknown): boolean {
  if (!isRecord(value) || !isStringOrNull(value.user_id) || !isStringOrNull(value.full_name)) return false;
  if (value.status === "known") return value.user_id !== null;
  return value.status === "unknown" && value.user_id === null && value.full_name === null;
}

function isAffected(value: unknown): boolean {
  return (
    isRecord(value) &&
    isString(value.user_id) &&
    value.user_id !== "" &&
    typeof value.is_requester === "boolean" &&
    isStringOrNull(value.department) &&
    isManagerRef(value.manager)
  );
}

/** `risk_view`: đủ enum + hai cờ suy ra PHẢI khớp trường gốc (`calibrated` ⇔ `calibrated_prob` khác null, `auto_allowed` ⇔
 *  `route` = "AUTO") — cờ lệch trường gốc nghĩa là thân không đáng tin, không đoán bên nào đúng. */
function isRiskView(value: unknown): boolean {
  return (
    isRecord(value) &&
    oneOf(value.decided_by, ["rule", "llm"]) &&
    oneOf(value.policy_decision, ["allow", "approval_required", "deny", null]) &&
    isStringOrNull(value.matched_rule_id) &&
    isNumberOrNull(value.raw_prob) &&
    isNumberOrNull(value.calibrated_prob) &&
    oneOf(value.p_method, ["self_report", "sampling_k5", null]) &&
    oneOf(value.risk_level, ["low", "medium", "high"]) &&
    oneOf(value.route, ["AUTO", "HITL", "ESCALATE_L2"]) &&
    isString(value.reason) &&
    (value.thresholds === null ||
      (Array.isArray(value.thresholds) && value.thresholds.length === 2 && value.thresholds.every((t) => typeof t === "number"))) &&
    value.calibrated === (value.calibrated_prob !== null) &&
    value.auto_allowed === (value.route === "AUTO")
  );
}

/**
 * Thân xem phiếu (F6 #76). Fail-closed: `affected` (người BỊ TÁC ĐỘNG — căn cứ để duyệt) thiếu / sai kiểu, `risk_view` sai
 * kiểu, hoặc `risk_view` null khác `risk` null → 502 `invalid_approval_body`: màn báo lỗi, KHÔNG hiện phiếu và KHÔNG có
 * thanh quyết định (người duyệt không được duyệt khi không thấy đúng ai bị tác động / mức rủi ro). Các trường cũ vẫn dễ dãi
 * (màn tự xử lý null — phòng ban, căn cứ…), `role_as` lạ → `viewer` (decisionRole).
 */
export function parseApprovalView(body: unknown): ApprovalViewP4 {
  if (!isRecord(body) || !isAffected(body.affected)) throw new ApiError(502, BAD_APPROVAL);
  const riskView = body.risk_view;
  if (riskView !== null && !isRiskView(riskView)) throw new ApiError(502, BAD_APPROVAL);
  if (!(body.risk === null || isRecord(body.risk)) || (riskView === null) !== (body.risk === null)) throw new ApiError(502, BAD_APPROVAL);
  return body as ApprovalViewP4;
}

export async function getApproval(id: string): Promise<ApprovalViewP4> {
  const res = await api.request<unknown>(approvalPath(id));
  recordServerDate(res.headers);
  return parseApprovalView(res.data);
}

export async function decideApproval(id: string, body: DecisionIn): Promise<DecisionAccepted> {
  return (await api.request<DecisionAccepted>(`${approvalPath(id)}/decision`, { method: "POST", json: body })).data;
}

/**
 * Thân 201 của ghi đè: object có `ticket_id` chuỗi và `notices` mảng → đúng `OverrideRecorded`; khác → null. Không lọc
 * `original_decision` ở đây — giá trị lạ / thiếu thì màn không hiện dòng quyết định gốc (`overrideDecisionLabel`).
 */
export function parseOverrideRecorded(body: unknown): OverrideRecorded | null {
  return isRecord(body) && typeof body.ticket_id === "string" && Array.isArray(body.notices) ? (body as OverrideRecorded) : null;
}

/**
 * `client` mặc định là client dùng chung — CÙNG client với đăng nhập (đăng nhập lại khi 403 `reauth_required`).
 * CHỈ 201 (mã duy nhất route trả khi ghi) = ĐÃ GHI (không gỡ được); `null` = đã ghi nhưng thân không đọc được chi tiết (P2) —
 * KHÔNG báo lỗi để người dùng khỏi gửi lại. Nguyên tắc: không chắc đã ghi → báo lỗi, không báo thành công giả; gửi lại → 409
 * `already_overridden` là đúng sự thật, không ghi trùng. Vì vậy: 2xx khác 201 (proxy sai…) → `ApiError(502)` (Q-fe-41 = A);
 * thân 201 JSON hỏng thì `client.request` ném trước khi tới đây → màn báo lỗi (Q-fe-39 = A).
 */
export async function overrideTicket(ticketId: string, body: OverrideIn, client: Client = api): Promise<OverrideRecorded | null> {
  const res = await client.request<unknown>(`/api/tickets/${encodeURIComponent(ticketId)}/override`, { method: "POST", json: body });
  if (res.status !== 201) throw new ApiError(502, "unexpected_override_status");
  return parseOverrideRecorded(res.data);
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
