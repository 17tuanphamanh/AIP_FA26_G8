// Khổ màn hình cho logic (không phải CSS). `DESKTOP_QUERY` là điểm `lg` của Tailwind (64rem = 1024 px) — phải trùng điểm gãy
// của các lớp `max-lg:` và khối @media trong styles/tokens.css. Không có `matchMedia` (môi trường lạ) → coi như màn rộng,
// tức giữ hành vi cũ của desktop.
import { useSyncExternalStore } from "react";

export const DESKTOP_QUERY = "(min-width: 64rem)";

/** Đang ở khổ ≥ 1024 px? Đọc một lần, đúng lúc gọi. */
export function isDesktop(): boolean {
  return typeof window === "undefined" || (window.matchMedia?.(DESKTOP_QUERY).matches ?? true);
}

function subscribe(onChange: () => void): () => void {
  const media = typeof window === "undefined" ? undefined : window.matchMedia?.(DESKTOP_QUERY);
  media?.addEventListener?.("change", onChange);
  return () => media?.removeEventListener?.("change", onChange);
}

/** Như `isDesktop()` nhưng dựng lại khi khổ vượt qua 1024 px (xoay máy, kéo cửa sổ). Dựng phía server → coi là màn rộng. */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, isDesktop, () => true);
}
