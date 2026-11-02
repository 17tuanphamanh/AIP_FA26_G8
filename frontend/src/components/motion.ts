import { type RefObject, useEffect, useRef } from "react";

// Chuyển động khi đổi màn: chạy bằng Web Animations API trên vùng nội dung đang có — KHÔNG đổi `key` nên màn không
// bị dựng lại (giữ trạng thái form, luồng chat, cache truy vấn). Máy bật "giảm chuyển động" hoặc trình duyệt không có
// `Element.animate` (môi trường test) → không làm gì.
const REDUCED = "(prefers-reduced-motion: reduce)";

export const EASE_SOFT = "cubic-bezier(0.22, 1, 0.36, 1)";

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && (window.matchMedia?.(REDUCED).matches ?? false);
}

/** Mờ dần + nhích lên 8px mỗi khi `trigger` đổi (lần dựng đầu không chạy — trang vừa tải đã có hiệu ứng riêng). */
export function useEnterOnChange(ref: RefObject<HTMLElement | null>, trigger: unknown) {
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const el = ref.current;
    if (!el || typeof el.animate !== "function" || prefersReducedMotion()) return;
    const animation = el.animate(
      [
        { opacity: 0, transform: "translateY(8px)" },
        { opacity: 1, transform: "none" },
      ],
      { duration: 260, easing: EASE_SOFT },
    );
    return () => animation.cancel();
  }, [ref, trigger]);
}
