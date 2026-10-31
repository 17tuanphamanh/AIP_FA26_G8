// Mốc "đã xem thông báo tới đâu" (`last_seen_at`) — hợp đồng thông báo §1: trạng thái đọc giữ Ở TRÌNH DUYỆT.
//
// NGOẠI LỆ CÓ CHỦ Ý của luật cấm Storage (KH 4.1 #1, ĐP 26/10 N-TB P3): đây là module DUY NHẤT trong src được chạm
// `localStorage` (eslint.config.js + scripts/check-style.mjs miễn đúng một file này). Luật cấm vì TOKEN; ở đây:
// - giá trị CHỈ là chuỗi ISO có múi giờ (kiểm cả lúc ghi lẫn lúc đọc — chuỗi khác bị bỏ qua); không token, không nội dung
//   thông báo, không mã ticket;
// - khoá theo người dùng `tb.last_seen.<user_id>` → đổi người trên cùng máy không lẫn mốc;
// - mọi lần đọc/ghi bọc try/catch: Storage bị chặn / đầy / trình duyệt riêng tư → coi như CHƯA đọc, màn không vỡ;
// - đăng xuất KHÔNG xoá: không nhạy cảm, và giữ lại thì đăng nhập lại không thấy cả loạt "chưa đọc" cũ.
import { isIsoWithZone } from "../api/iso.ts";

export const LAST_SEEN_PREFIX = "tb.last_seen.";
export const lastSeenKey = (userId: string): string => `${LAST_SEEN_PREFIX}${userId}`;

/** Mốc đã xem của người dùng; chưa có / sai dạng / Storage lỗi → null (mọi thông báo coi là chưa đọc). */
export function readLastSeen(userId: string): string | null {
  try {
    const value = window.localStorage.getItem(lastSeenKey(userId));
    return isIsoWithZone(value) ? value : null;
  } catch {
    return null;
  }
}

/** Ghi mốc; chỉ nhận ISO có múi giờ. Trả false khi không ghi được (màn vẫn giữ mốc trong bộ nhớ cho phiên này). */
export function writeLastSeen(userId: string, iso: string): boolean {
  if (!isIsoWithZone(iso)) return false;
  try {
    window.localStorage.setItem(lastSeenKey(userId), iso);
    return true;
  } catch {
    return false;
  }
}
