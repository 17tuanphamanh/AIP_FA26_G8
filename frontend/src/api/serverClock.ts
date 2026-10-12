// Giờ máy chủ cho đồng hồ duyệt L1 (F4 P5; KH 1.3 #5). `ApprovalView` có `deadline` nhưng không có `server_now` →
// lấy header `Date` của response gần nhất (cùng origin nên JS đọc được): độ lệch = Date (máy chủ) − giờ máy lúc nhận.
// Response thiếu / hỏng `Date` → độ lệch 0 (dùng giờ máy). Header `Date` chỉ tới giây → sai số ≤ 1 giây.
// Chỉ nằm trong bộ nhớ của tab.

let offsetMs = 0;

/** Độ lệch (ms) giữa giờ máy chủ và giờ máy, từ header `Date` nhận lúc `receivedAt` (giờ máy). */
export function offsetFrom(dateHeader: string | null, receivedAt: number): number {
  if (!dateHeader) return 0;
  const server = Date.parse(dateHeader);
  return Number.isNaN(server) ? 0 : server - receivedAt;
}

/** Ghi độ lệch theo response vừa nhận (gọi ngay sau khi nhận — `receivedAt` mặc định là giờ máy lúc này). */
export function recordServerDate(headers: Headers, receivedAt: number = Date.now()): void {
  offsetMs = offsetFrom(headers.get("Date"), receivedAt);
}

export const serverOffset = (): number => offsetMs;

/** Giờ máy chủ (ms) = giờ máy + độ lệch. */
export const serverNow = (machineNow: number = Date.now()): number => machineNow + offsetMs;
