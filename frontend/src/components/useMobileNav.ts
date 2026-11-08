import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

// Trạng thái của thanh bên thu gọn trên điện thoại (hiển thị: MobileNav.tsx).
// - Đóng bằng: Esc · chạm vùng mờ · nút "Đóng menu" · bấm một liên kết trong ngăn kéo · đổi đường dẫn · kéo rộng tới ≥ 1024 px.
// - Mở → tiêu điểm vào ngăn kéo; đóng → tiêu điểm về nút menu.

/** Điểm `lg` của Tailwind (64rem). Phải trùng điểm gãy của các lớp `max-lg:` và khối @media trong tokens.css. */
export const DESKTOP_QUERY = "(min-width: 64rem)";
export const NAV_ID = "app-sidebar";

export type MobileNav = {
  open: boolean;
  toggle: () => void;
  close: () => void;
  /** Gắn vào nút menu ở thanh đầu — nơi tiêu điểm quay về khi đóng. */
  buttonRef: RefObject<HTMLButtonElement | null>;
  /** Gắn vào vỏ ngăn kéo — nơi tiêu điểm vào khi mở. */
  drawerRef: RefObject<HTMLDivElement | null>;
};

/** `pathname`: đổi đường dẫn (bấm liên kết, nút Back, chuyển hướng) → tự đóng. */
export function useMobileNav(pathname: string): MobileNav {
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState(pathname);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);

  // Đổi màn → đóng ngay lúc render (mẫu "điều chỉnh state theo giá trị render trước"), không qua effect.
  if (path !== pathname) {
    setPath(pathname);
    setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    // Xoay ngang / kéo rộng tới ≥ 1024 px: thanh bên đã hiện cố định, ngăn kéo hết nghĩa → đóng.
    const wide = window.matchMedia?.(DESKTOP_QUERY);
    const onWide = () => {
      if (wide?.matches) setOpen(false);
    };
    wide?.addEventListener("change", onWide);
    return () => {
      document.removeEventListener("keydown", onKey);
      wide?.removeEventListener("change", onWide);
    };
  }, [open]);

  // Tiêu điểm: mở → vào ngăn kéo (phần tử đầu tiên bấm được); đóng → về nút menu. Lần dựng đầu không làm gì.
  useEffect(() => {
    if (open) {
      drawerRef.current?.querySelector<HTMLElement>("a[href], button:not([disabled])")?.focus();
    } else if (wasOpen.current) {
      buttonRef.current?.focus();
    }
    wasOpen.current = open;
  }, [open]);

  const toggle = useCallback(() => setOpen((v) => !v), []);
  const close = useCallback(() => setOpen(false), []);
  return { open, toggle, close, buttonRef, drawerRef };
}
