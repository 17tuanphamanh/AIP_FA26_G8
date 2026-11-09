// Đồng hồ "Chờ IT duyệt" của nhân viên (ĐP 26/10 N-TB P5; hợp đồng thông báo §2) — phần thuần, không React.
// Giờ máy chủ = giờ máy + độ lệch đo LÚC NHẬN ticket: `server_now − giờ máy lúc nhận`. Có `server_now` hợp lệ → dùng nó
// (ưu tiên hơn header `Date`); thiếu / hỏng → độ lệch header `Date` chung (api/serverClock.ts, 0 khi chưa có).
import { isIsoWithZone, isoMs } from "../../api/iso.ts";
import { serverOffset } from "../../api/serverClock.ts";
import type { TicketView } from "../../api/types.ts";

export const WAIT_LABEL = "Chờ IT duyệt";
export const EXPIRED_TEXT = "Đã quá hạn duyệt, yêu cầu đang được chuyển kỹ thuật viên";
/** [ĐX] — câu đọc cho trình đọc màn hình khi còn 5 phút. */
export const FIVE_MIN_TEXT = "Còn 5 phút để IT duyệt yêu cầu của bạn.";
export const FIVE_MIN_MS = 5 * 60_000;
/** Ngưỡng đỏ = luật L1 hiện có (routes/l1/inbox.ts `URGENT_RATIO`): còn < 20% khoảng chờ. */
export const URGENT_RATIO = 0.2;

/** Độ lệch giờ máy chủ − giờ máy (ms). */
export function clockOffset(serverNowIso: string | null | undefined, receivedAt: number): number {
  const server = isoMs(serverNowIso);
  return server === null ? serverOffset() : server - receivedAt;
}

/** Hạn hiện đồng hồ duyệt — null = không hiện gì (hợp đồng sửa ĐP 27/10 00:05). `deadline` giữ nghĩa R3 (hạn của LẦN CHỜ
 *  hiện tại, cả clarify/confirm) → đồng hồ CHỈ khi `waiting_for === "approval"` (không dựa `S_PENDING_APPROVAL`); hạn của
 *  lần chờ khác không hiện ở đây. Ticket cha: dùng nguyên `deadline` server trả cho cha (FE không tự tính từ các ý con).
 *  Đã kết thúc / hạn không phải ISO có múi giờ → null. */
export function clockDeadline(view: TicketView, waiting: TicketView["waiting_for"]): string | null {
  if (view.final_state || waiting !== "approval" || !isIsoWithZone(view.deadline)) return null;
  return view.deadline;
}

const two = (n: number) => String(n).padStart(2, "0");

/** "mm:ss" (≥ 1 giờ → "h:mm:ss"); làm tròn LÊN giây để chưa hết hạn thì không hiện 00:00. */
export function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const mm = two(Math.floor((total % 3600) / 60));
  return h > 0 ? `${h}:${mm}:${two(total % 60)}` : `${mm}:${two(total % 60)}`;
}

export type ClockPhase = "normal" | "five" | "expired";
export const phaseOf = (remaining: number): ClockPhase => (remaining <= 0 ? "expired" : remaining <= FIVE_MIN_MS ? "five" : "normal");

/** Đỏ khi còn < 20% khoảng từ lần đầu thấy `server_now` (cho hạn này) tới hạn. Khoảng ≤ 0 → không đỏ (không có mốc). */
export const isUrgent = (remaining: number, deadlineMs: number, firstSeenMs: number): boolean =>
  deadlineMs - firstSeenMs > 0 && remaining < URGENT_RATIO * (deadlineMs - firstSeenMs);
