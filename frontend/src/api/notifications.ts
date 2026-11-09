// Thông báo của người dùng — route THẬT backend/app/api/notifications.py (be-thong-bao 56ea4d9; hợp đồng thông báo §1):
// `GET /api/me/notifications?limit=&after=` (quyền `ticket:read:own`) → `NotificationPage` {items, next_cursor}, mới nhất
// trước. Kiểu từ schema.gen.ts (types.ts). Đọc CHẶT như hàng đợi L2: thân sai hình dạng, `kind`/`result` lạ, `kind` không
// khớp `result`/`id` (`appr:<số>` | `esc:<số>` — `ID_PATTERN` của backend/app/db/notifications.py), `created_at` không phải
// ISO có múi giờ → 502 `invalid_notifications_body` cho CẢ thân (không vẽ một phần, không đoán).
// Backend cũ chưa có route (404) / người dùng không được đọc (403) → chuông ẩn im lặng (`notificationsUnavailable`).
import { infiniteQueryOptions, type InfiniteData } from "@tanstack/react-query";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import { isIsoWithZone, isoMs } from "./iso.ts";
import type { NotificationView, NotificationKind, NotificationPage, NotificationResult } from "./types.ts";

/** Cỡ trang (hợp đồng: 1–50, mặc định 20). */
export const NOTIFICATION_PAGE_LIMIT = 20;
/** Nhịp hỏi lại khi tab đang hiện (P2). */
export const NOTIFICATION_POLL_MS = 30_000;

const BAD_BODY = "invalid_notifications_body";

/** Kết quả hợp lệ theo từng loại: phiếu duyệt → duyệt/từ chối; đóng ca L2 → 3 kết quả đóng (CLOSE_RESULTS). */
const RESULTS_OF: Readonly<Record<NotificationKind, readonly NotificationResult[]>> = {
  approval_decided: ["approved", "rejected"],
  escalation_closed: ["completed", "confirmed_denial", "reopened_as_new"],
};
/** `id` theo loại — đúng `ID_PATTERN` của backend (`(appr|esc):[0-9]{1,19}`). */
const ID_OF: Readonly<Record<NotificationKind, RegExp>> = { approval_decided: /^appr:[0-9]{1,19}$/, escalation_closed: /^esc:[0-9]{1,19}$/ };

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const nonEmpty = (v: unknown): v is string => typeof v === "string" && v !== "";

function isItem(v: unknown): v is NotificationView {
  if (!isRecord(v)) return false;
  const kind = v.kind;
  if (kind !== "approval_decided" && kind !== "escalation_closed") return false;
  return (
    typeof v.id === "string" &&
    ID_OF[kind].test(v.id) &&
    nonEmpty(v.ticket_id) &&
    typeof v.text === "string" &&
    RESULTS_OF[kind].includes(v.result as NotificationResult) &&
    (v.new_ticket_id === null || nonEmpty(v.new_ticket_id)) &&
    isIsoWithZone(v.created_at)
  );
}

export function parseNotificationPage(body: unknown): NotificationPage {
  const ok =
    isRecord(body) &&
    Array.isArray(body.items) &&
    body.items.every(isItem) &&
    (body.next_cursor === null || nonEmpty(body.next_cursor));
  if (!ok) throw new ApiError(502, BAD_BODY);
  return { items: body.items as NotificationView[], next_cursor: body.next_cursor as string | null };
}

export const notificationsPath = (limit: number, after: string | null): string =>
  `/api/me/notifications?limit=${limit}${after === null ? "" : `&after=${encodeURIComponent(after)}`}`;

export async function getNotifications(limit: number = NOTIFICATION_PAGE_LIMIT, after: string | null = null): Promise<NotificationPage> {
  const { data } = await api.request<unknown>(notificationsPath(limit, after));
  return parseNotificationPage(data);
}

/** Route chưa có (404, backend cũ) / không được đọc (403) → không chuông, không câu lỗi. Lỗi khác (502 thân sai, 503
 *  `notifications_unavailable`, mạng) → chuông vẫn hiện, khung báo "Chưa tải được thông báo". */
export const notificationsUnavailable = (error: unknown): boolean => error instanceof ApiError && (error.status === 404 || error.status === 403);

/** Dừng hỏi lại: chưa có route (404), hết phiên / mất quyền (401/403). Lỗi khác (mạng, 5xx, 502 thân sai) → hỏi lại theo nhịp. */
export const notificationsRefetchInterval = (error: unknown): number | false =>
  error instanceof ApiError && [401, 403, 404].includes(error.status) ? false : NOTIFICATION_POLL_MS;

/** Theo `user_id`: đổi người trên cùng máy không thấy thông báo của người trước. */
export const notificationsQuery = (userId: string) =>
  infiniteQueryOptions({
    queryKey: ["notifications", userId] as const,
    queryFn: ({ pageParam }) => getNotifications(NOTIFICATION_PAGE_LIMIT, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last: NotificationPage) => last.next_cursor ?? undefined,
    retry: false,
  });

/** Mọi trang đã tải nối theo thứ tự server; trùng `id` (thông báo mới đẩy trang lệch) → giữ lần đầu. */
export function loadedNotifications(data: InfiniteData<NotificationPage> | undefined): NotificationView[] {
  if (!data) return [];
  const seen = new Set<string>();
  const out: NotificationView[] = [];
  for (const page of data.pages) {
    for (const item of page.items) {
      if (seen.has(item.id)) continue;
      seen.add(item.id);
      out.push(item);
    }
  }
  return out;
}

export const hasMoreNotifications = (data: InfiniteData<NotificationPage> | undefined): boolean =>
  !!data && data.pages.length > 0 && data.pages[data.pages.length - 1]!.next_cursor !== null;

/** `a` muộn hơn mốc `b` (mốc null / hỏng → luôn muộn hơn). */
export function isNewer(a: string, b: string | null): boolean {
  const mark = isoMs(b);
  return mark === null || Date.parse(a) > mark;
}

/** Số thông báo mới hơn mốc đã xem (mốc null / hỏng → mọi thông báo chưa đọc). */
export const unreadCount = (items: readonly NotificationView[], lastSeen: string | null): number =>
  items.filter((i) => isNewer(i.created_at, lastSeen)).length;

/** `created_at` mới nhất (theo thời điểm, không theo chuỗi) — null khi danh sách rỗng. */
export function newestCreatedAt(items: readonly NotificationView[]): string | null {
  let best: NotificationView | null = null;
  for (const item of items) if (best === null || Date.parse(item.created_at) > Date.parse(best.created_at)) best = item;
  return best?.created_at ?? null;
}
