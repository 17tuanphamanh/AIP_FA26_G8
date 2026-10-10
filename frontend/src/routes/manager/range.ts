// Khoảng thời gian của Tổng quan (F5 P4; Q-fe-31) — hàm thuần, KHÔNG đọc múi giờ của máy khách: "ngày" là ngày theo
// giờ Việt Nam (Asia/Ho_Chi_Minh = UTC+7, không đổi giờ mùa hè — ke-hoach-m9-monitor.md Q-M9-2). Backend 422 nếu
// `from`/`to` thiếu múi giờ (§4.5) → mọi chuỗi gửi đi đều kết thúc bằng "+07:00".
//   Hôm nay  : from = 00:00 VN hôm nay
//   7 ngày   : from = 00:00 VN của 6 ngày trước (7 ngày lịch, tính cả hôm nay) — mặc định
//   30 ngày  : from = 00:00 VN của 29 ngày trước
//   to       = thời điểm hiện tại (tính LÚC GỬI — nút "Tải lại" lấy giờ mới).
import { queryOptions } from "@tanstack/react-query";
import { type DashboardWindow, getAiDashboard, getBusinessDashboard } from "../../api/dashboard.ts";

export type RangeKey = "today" | "7d" | "30d";
export const RANGES: readonly { key: RangeKey; label: string; days: number }[] = [
  { key: "today", label: "Hôm nay", days: 1 },
  { key: "7d", label: "7 ngày", days: 7 },
  { key: "30d", label: "30 ngày", days: 30 },
];
export const DEFAULT_RANGE: RangeKey = "7d";

const VN_OFFSET_MS = 7 * 3_600_000;
const DAY_MS = 86_400_000;
const pad = (n: number, width = 2) => String(n).padStart(width, "0");

/** Giờ VN dưới dạng các trường UTC của một Date đã dời +7 giờ (không phụ thuộc múi giờ máy). */
const vnFields = (ms: number) => new Date(ms + VN_OFFSET_MS);

/** ISO 8601 theo giờ VN, luôn có "+07:00": `2026-10-01T14:05:09.123+07:00`. */
export function vnIso(ms: number): string {
  const d = vnFields(ms);
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
    `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(d.getUTCMilliseconds(), 3)}+07:00`
  );
}

/** 00:00 giờ VN của ngày (theo giờ VN) chứa thời điểm `ms`. */
export const vnStartOfDay = (ms: number): number => Math.floor((ms + VN_OFFSET_MS) / DAY_MS) * DAY_MS - VN_OFFSET_MS;

export function rangeWindow(key: RangeKey, now: number): DashboardWindow {
  const days = RANGES.find((r) => r.key === key)?.days ?? 7;
  const from = vnStartOfDay(now) - (days - 1) * DAY_MS;
  // `from < to` (§4.5): đúng 00:00:00.000 VN thì đẩy `to` thêm 1 ms.
  return { from: vnIso(from), to: vnIso(Math.max(now, from + 1)) };
}

/** "30/09 14:05" theo giờ VN; chuỗi không đọc được → trả nguyên văn. */
export function vnDateTime(iso: string): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const d = vnFields(ms);
  return `${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** "30/09" theo giờ VN. */
export function vnDate(iso: string): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const d = vnFields(ms);
  return `${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)}`;
}

// Khoá truy vấn theo khoảng (KHÔNG theo giờ): đổi khoảng → khoá mới, không mượn số của khoảng khác. Không
// `placeholderData` — lỗi thì màn không có số nào để hiện.
export const businessQuery = (range: RangeKey) =>
  queryOptions({
    queryKey: ["dashboard", "business", range] as const,
    queryFn: () => getBusinessDashboard(rangeWindow(range, Date.now())),
    retry: false,
  });

export const aiQuery = (range: RangeKey) =>
  queryOptions({
    queryKey: ["dashboard", "ai", range] as const,
    queryFn: () => getAiDashboard(rangeWindow(range, Date.now())),
    retry: false,
  });
