// Ô biểu tượng cạnh tiêu đề trang L1/L2 (gói fe-role-dep) — cùng phong cách ảnh đại diện ở màn chat: khối bo góc, màu token,
// thuần trang trí (aria-hidden). Không mang thông tin nào mà chữ bên cạnh chưa nói.
const PATHS = {
  inbox: "M4 13l2.5-7h11L20 13M4 13v5h16v-5M4 13h4.5l1 2h5l1-2H20",
  ticket: "M7 4h10v16l-5-3-5 3zM10 9.5l1.5 1.5 3-3",
  queue: "M4 6h16M4 12h16M4 18h10",
  alert: "M12 4l9 16H3zM12 10v4M12 17h.01",
} as const;

export type PageIconName = keyof typeof PATHS;

export function PageIcon({ name, tone = "blue" }: { name: PageIconName; tone?: "blue" | "orange" | "danger" }) {
  const box = tone === "danger" ? "bg-danger-bg text-danger" : tone === "orange" ? "bg-orange-bg text-fpt-orange" : "bg-selected text-fpt-blue";
  return (
    <span aria-hidden="true" className={`flex size-12 shrink-0 items-center justify-center rounded-2xl shadow-sm ${box}`}>
      <svg viewBox="0 0 24 24" className="size-6 fill-none stroke-current" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d={PATHS[name]} />
      </svg>
    </span>
  );
}

/** Thẻ nội dung chung của màn L1/L2: bo 16, viền mảnh, nền trắng, bóng nhẹ (đồng bộ fe-chat-dep). */
export const CARD = "overflow-hidden rounded-2xl border border-line bg-white shadow-sm";
