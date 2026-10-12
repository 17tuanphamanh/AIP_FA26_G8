// Cảnh báo (F5) — route thật M9 A3 @3f15afb (backend/app/api/alerts.py): `GET /api/alerts?status=open` ("Đang mở"),
// `GET /api/alerts` ("Tất cả" — không tham số, Q-fe-27) → 200 `{items, truncated}` (object, KHÔNG phải mảng trần; tối đa
// 200 cảnh báo mới nhất, `truncated` = còn cảnh báo cũ hơn); `POST /api/alerts/{id}/ack` → 200 cảnh báo đã ack | 404
// `not_found` | 409 `already_acked`. Không gửi `audience` (nhãn, không phải quyền — ai có `alert:read` thấy mọi cảnh báo),
// `limit` (mặc định 200 của server) hay tham số rỗng (`?status=` → 422).
import { queryOptions } from "@tanstack/react-query";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type { AlertItem, AlertList } from "./types.ts";

export type AlertFilter = "open" | "all";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const isTextOrNull = (value: unknown) => value === null || typeof value === "string";

/**
 * Đúng hình dạng `AlertView` (12 khoá). `alert_id` phải là số nguyên AN TOÀN ≥ 1: cột là BIGINT, id vượt 2^53−1 đã bị JS
 * làm tròn khi đọc JSON → bấm "Đã xem" sẽ ack nhầm cảnh báo khác. `audience` là mảng chuỗi (giá trị lạ → hiện nguyên).
 */
export function isAlertItem(value: unknown): value is AlertItem {
  if (!isRecord(value)) return false;
  const { alert_id: id, audience } = value;
  return (
    typeof id === "number" &&
    Number.isSafeInteger(id) &&
    id >= 1 &&
    typeof value.rule_id === "string" &&
    typeof value.subject === "string" &&
    typeof value.severity === "string" &&
    typeof value.window_start === "string" &&
    typeof value.created_at === "string" &&
    (value.value === null || typeof value.value === "number") &&
    (value.status === "open" || value.status === "acked") &&
    isRecord(value.detail) &&
    Array.isArray(audience) &&
    audience.every((a) => typeof a === "string") &&
    isTextOrNull(value.acked_by) &&
    isTextOrNull(value.acked_at)
  );
}

/**
 * Thân danh sách — MỘT hình dạng `{items, truncated}`. Mảng trần, thiếu `truncated`, hay CHỈ MỘT cảnh báo hỏng → 502
 * `invalid_alerts_body` (màn báo lỗi): không đoán dạng, không lặng lẽ bỏ cảnh báo.
 */
export function parseAlerts(body: unknown): AlertList {
  if (!isRecord(body) || typeof body.truncated !== "boolean" || !Array.isArray(body.items) || !body.items.every(isAlertItem)) {
    throw new ApiError(502, "invalid_alerts_body");
  }
  return { items: body.items, truncated: body.truncated };
}

export async function listAlerts(filter: AlertFilter): Promise<AlertList> {
  return parseAlerts((await api.request<unknown>(filter === "open" ? "/api/alerts?status=open" : "/api/alerts")).data);
}

/**
 * 200 → cảnh báo đã ack (đúng hình dạng, đúng id, `status: "acked"`). `null` = server đã trả 200 mà thân không đọc được
 * (JSON hỏng, sai hình dạng, id khác) → nơi gọi KHÔNG báo thành công, KHÔNG sửa cache, tải lại danh sách (P6). Lỗi HTTP →
 * ApiError như mọi route. SyntaxError cũng có thể đến từ thân `/api/auth/refresh` hỏng (khi đó ack chưa được ghi) — vẫn
 * an toàn: màn không báo thành công và danh sách tải lại cho thấy sự thật.
 */
export async function ackAlert(id: number): Promise<AlertItem | null> {
  let body: unknown;
  try {
    body = (await api.request<unknown>(`/api/alerts/${encodeURIComponent(String(id))}/ack`, { method: "POST" })).data;
  } catch (error) {
    if (error instanceof SyntaxError) return null;
    throw error;
  }
  return isAlertItem(body) && body.alert_id === id && body.status === "acked" ? body : null;
}

export const alertsQuery = (filter: AlertFilter) =>
  queryOptions({
    queryKey: ["alerts", filter] as const,
    queryFn: () => listAlerts(filter),
    retry: false,
  });
