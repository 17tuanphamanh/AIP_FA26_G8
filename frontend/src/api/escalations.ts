// Hàng đợi L2 (KH 1.1; hợp đồng N-PA §4 — chốt ĐP 26/10 17:30, be-tuan8):
// - `GET /api/escalations/queue?status=open|closed&limit=&after=` → `{items, next_cursor}` (đọc CHẶT: mảng trần, item sai
//   kiểu, ca đóng thiếu `closed_at`/`close_result`/`closed_by`, ca mở mang thông tin đóng → 502 `invalid_queue_body`).
//   `limit` ≤ 100; `after` = chuỗi mờ lấy nguyên từ `next_cursor` của trang trước. Giữ thứ tự server.
// - `POST /api/escalations/{id}/close` thân `{close_result, note}` → 200. Route CHƯA CÓ ở backend: chỉ gọi được khi
//   `CLOSE_AVAILABLE` (hiện = MSW bật, mocks/handlers/escalation-close.ts) — không bao giờ gửi tới backend thật khi tắt.
// Chưa có `GET /api/escalations/{id}` → chi tiết tìm ca trong các trang ĐÃ tải của hàng đợi (cùng cache).
import { infiniteQueryOptions, type InfiniteData } from "@tanstack/react-query";
import { MOCK_ENABLED } from "../mocks/flag.ts";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type {
  EscalationCloseIn,
  EscalationCloseResult,
  EscalationQueuePage,
  EscalationQueueStatus,
} from "./types.ts";

/** Cỡ một trang hàng đợi (backend: tối đa 100 — Q-fe-N7 chọn 50). */
export const QUEUE_PAGE_LIMIT = 50;
export const QUEUE_REFRESH_MS = 15_000;
/** Ghi chú đóng: bắt buộc, sau khi cắt khoảng trắng 1…1000 ký tự. */
export const CLOSE_NOTE_MAX = 1000;
/**
 * Đóng ca chỉ có khi MSW bật (dev + `VITE_API_MOCK=1`). Bản build: hằng `false`.
 * BẬT khi route thật `POST /api/escalations/{id}/close` (be-tuan8) vào nhánh: đổi DUY NHẤT dòng này thành `true` rồi xoá
 * mocks/handlers/escalation-close.ts.
 */
export const CLOSE_AVAILABLE: boolean = MOCK_ENABLED;
export const CLOSE_RESULTS: readonly EscalationCloseResult[] = ["completed", "confirmed_denial", "reopened_as_new"];

export type QueueItem = EscalationQueuePage["items"][number];

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const isNullableString = (v: unknown) => v === null || typeof v === "string";
const absentOrNull = (v: unknown) => v === undefined || v === null;

function isBaseItem(v: Record<string, unknown>): boolean {
  return (
    typeof v.escalation_id === "number" &&
    Number.isSafeInteger(v.escalation_id) &&
    typeof v.ticket_id === "string" &&
    typeof v.exit_code === "string" &&
    typeof v.priority === "number" &&
    Number.isFinite(v.priority) &&
    typeof v.label === "string" &&
    isNullableString(v.reason_detail) &&
    typeof v.is_deny_case === "boolean" &&
    isNullableString(v.assigned_to) &&
    typeof v.created_at === "string"
    // `handoff_note` kiểm lúc hiện (routes/l2/queue.ts `noteText` — thiếu / rỗng → "(không có)").
  );
}

/** Ca đóng: 3 trường bắt buộc (Q-fe-N5) + `close_note` tuỳ chọn (Q-fe-N4); ca mở: không mang thông tin đóng. */
function isItem(v: unknown, status: EscalationQueueStatus): boolean {
  if (!isRecord(v) || !isBaseItem(v)) return false;
  if (!(v.close_note === undefined || isNullableString(v.close_note))) return false;
  if (status === "closed") {
    return (
      typeof v.closed_at === "string" &&
      CLOSE_RESULTS.includes(v.close_result as EscalationCloseResult) &&
      typeof v.closed_by === "string"
    );
  }
  return absentOrNull(v.closed_at) && absentOrNull(v.close_result) && absentOrNull(v.closed_by) && absentOrNull(v.close_note);
}

export function parseQueuePage(body: unknown, status: EscalationQueueStatus): EscalationQueuePage {
  const ok =
    isRecord(body) &&
    Array.isArray(body.items) &&
    body.items.every((i) => isItem(i, status)) &&
    (body.next_cursor === null || (typeof body.next_cursor === "string" && body.next_cursor !== ""));
  if (!ok) throw new ApiError(502, "invalid_queue_body");
  return body as EscalationQueuePage;
}

export const queuePath = (status: EscalationQueueStatus, after: string | null): string =>
  `/api/escalations/queue?status=${status}&limit=${QUEUE_PAGE_LIMIT}${after === null ? "" : `&after=${encodeURIComponent(after)}`}`;

export async function getEscalationQueuePage(status: EscalationQueueStatus, after: string | null): Promise<EscalationQueuePage> {
  const { data } = await api.request<unknown>(queuePath(status, after));
  return parseQueuePage(data, status);
}

const is403 = (error: unknown) => error instanceof ApiError && error.status === 403;

export const queueQuery = (status: EscalationQueueStatus = "open") =>
  infiniteQueryOptions({
    queryKey: ["escalations", "queue", status] as const,
    queryFn: ({ pageParam }) => getEscalationQueuePage(status, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last: EscalationQueuePage) => last.next_cursor ?? undefined,
    retry: false,
  });

/** Các ca đã tải (mọi trang) nối theo thứ tự server; trùng `escalation_id` (ca đổi chỗ giữa hai lần tải trang) → giữ lần đầu. */
export function loadedItems(data: InfiniteData<EscalationQueuePage> | undefined): QueueItem[] | undefined {
  if (!data) return undefined;
  const seen = new Set<number>();
  const out: QueueItem[] = [];
  for (const page of data.pages) {
    for (const item of page.items) {
      if (seen.has(item.escalation_id)) continue;
      seen.add(item.escalation_id);
      out.push(item);
    }
  }
  return out;
}

/** Còn trang chưa tải (theo `next_cursor` của trang cuối). */
export const hasMore = (data: InfiniteData<EscalationQueuePage> | undefined): boolean =>
  !!data && data.pages.length > 0 && data.pages[data.pages.length - 1]!.next_cursor !== null;

/** Nhịp tự tải lại của màn hàng đợi; 403 (mất quyền) → dừng. */
export const queueRefetchInterval = (error: unknown): number | false => (is403(error) ? false : QUEUE_REFRESH_MS);

/**
 * Gửi `POST /close` (KHÔNG kiểm `CLOSE_AVAILABLE` — chỉ `closeEscalation` và test gọi). CHỈ 200 = đã đóng; 2xx khác → 502
 * (không chắc đã ghi → không báo thành công giả; gửi lại → 409 `already_closed` là đúng sự thật).
 */
export async function requestClose(id: number, body: EscalationCloseIn): Promise<void> {
  const res = await api.request<unknown>(`/api/escalations/${id}/close`, { method: "POST", json: body });
  if (res.status !== 200) throw new ApiError(502, "unexpected_close_status");
  // Thân 200 KHÔNG đọc (hợp đồng sửa lần 3, ĐP 26/10 23:51): `new_ticket_id` luôn null đợt này — kể cả server lỡ trả mã, màn
  // không hiện mã / link ticket mới.
}

/** Đóng ca từ màn. Lớp chặn thứ hai (lớp đầu: nút gửi khoá): route chưa bật → tuyệt đối không gửi. */
export async function closeEscalation(id: number, body: EscalationCloseIn): Promise<void> {
  if (!CLOSE_AVAILABLE) throw new Error("close_unavailable");
  return requestClose(id, body);
}

