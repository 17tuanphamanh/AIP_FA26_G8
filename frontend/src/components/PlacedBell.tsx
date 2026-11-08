import type { Me } from "../api/types.ts";
import { useIsDesktop } from "../lib/viewport.ts";
import { NotificationBell } from "./NotificationBell.tsx";

// Chuông thông báo có MỘT chỗ đứng tuỳ khổ: ≥ 1024 px ở hàng logo của thanh bên (như cũ); dưới 1024 px ở thanh đầu — ngăn kéo
// menu đóng thì thanh bên ẩn, chuông nằm trong đó sẽ mất cả chấm "chưa đọc". Dựng ĐÚNG MỘT bản chuông (không dựng cả hai rồi
// ẩn bằng CSS: hai bản là hai state "đã đọc" riêng). Qua điểm 1024 px bản này gỡ, bản kia gắn; mốc "đã xem" đọc lại từ
// lib/lastSeen.ts, truy vấn chung cache nên số chưa đọc không đổi.
export function PlacedBell({ me, where }: { me: Me; where: "sidebar" | "header" }) {
  const desktop = useIsDesktop();
  if (desktop !== (where === "sidebar")) return null;
  return <NotificationBell key={me.user_id} me={me} />;
}
