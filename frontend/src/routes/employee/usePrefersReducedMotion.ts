import { useEffect, useState } from "react";

// `prefers-reduced-motion: reduce` của hệ điều hành — theo dõi cả khi người dùng đổi lúc đang mở trang. Không có `matchMedia` → false.
const QUERY = "(prefers-reduced-motion: reduce)";

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => (typeof window !== "undefined" && window.matchMedia?.(QUERY).matches) || false);
  useEffect(() => {
    const media = typeof window !== "undefined" ? window.matchMedia?.(QUERY) : undefined;
    if (!media) return;
    const onChange = () => setReduced(media.matches);
    media.addEventListener?.("change", onChange);
    return () => media.removeEventListener?.("change", onChange);
  }, []);
  return reduced;
}
