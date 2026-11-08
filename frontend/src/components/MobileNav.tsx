import type { ReactNode } from "react";
import logoUrl from "../assets/logo.svg";
import { type MobileNav, NAV_ID } from "./useMobileNav.ts";

// Thanh bên trên điện thoại: dưới điểm `lg` (1024 px) thanh bên thu vào nút menu ở thanh đầu; mở ra là ngăn kéo phủ màn.
// Từ 1024 px trở lên thanh đầu ẩn, vỏ ngăn kéo là `display: contents` (không sinh hộp) nên thanh bên nằm đúng chỗ cũ.
// Trạng thái + phím + tiêu điểm: useMobileNav.ts. Đang mở: thanh đầu và vùng nội dung `inert` (App.tsx) — Tab không lọt
// ra sau ngăn kéo.

function MenuIcon({ open }: { open: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
    </svg>
  );
}

/** Thanh đầu trên điện thoại (ẩn từ 1024 px): nút menu + tên ứng dụng + (bên phải) `children` — chuông thông báo. */
export function MobileNavBar({ open, onToggle, buttonRef, children }: Pick<MobileNav, "open" | "buttonRef"> & { onToggle: () => void; children?: ReactNode }) {
  return (
    <header inert={open} className="flex h-14 shrink-0 items-center gap-1 border-b border-line bg-white pr-4 pl-2 lg:hidden">
      <button
        ref={buttonRef}
        type="button"
        aria-label="Menu"
        aria-expanded={open}
        aria-controls={NAV_ID}
        onClick={onToggle}
        className="flex size-11 shrink-0 items-center justify-center rounded-lg text-ink hover:bg-group focus-visible:outline-2 focus-visible:outline-fpt-blue"
      >
        <MenuIcon open={open} />
      </button>
      <img src={logoUrl} alt="" width={28} height={28} className="ml-1" />
      <span className="truncate text-secondary font-semibold">ServiceDesk AI</span>
      {/* Chỗ của chuông thông báo (PlacedBell) — dưới 1024 px chuông ở đây, không nằm trong ngăn kéo. */}
      <div className="ml-auto flex shrink-0 items-center">{children}</div>
    </header>
  );
}

/**
 * Vỏ của thanh bên. ≥ 1024 px: `display: contents` — thanh bên là con trực tiếp của khung, như trước. Dưới 1024 px: ẩn;
 * mở → phủ cả màn, thanh bên ở trái, phần còn lại là vùng mờ (chạm để đóng) kèm nút đóng.
 */
export function NavDrawer({ open, onClose, drawerRef, children }: Pick<MobileNav, "open" | "drawerRef"> & { onClose: () => void; children: ReactNode }) {
  return (
    <div
      id={NAV_ID}
      ref={drawerRef}
      data-open={open}
      className={open ? "fixed inset-0 z-40 flex motion-safe:animate-fade-in lg:contents" : "hidden lg:contents"}
      // Bấm một liên kết trong ngăn kéo (kể cả liên kết tới chính trang đang mở — đường dẫn không đổi) → đóng.
      onClick={(event) => {
        if ((event.target as Element).closest("a[href]")) onClose();
      }}
    >
      {children}
      <div aria-hidden="true" onClick={onClose} className="grow bg-ink/25 lg:hidden" />
      <button
        type="button"
        aria-label="Đóng menu"
        onClick={onClose}
        className="absolute top-3 right-3 flex size-11 items-center justify-center rounded-full bg-white text-ink shadow-input focus-visible:outline-2 focus-visible:outline-fpt-blue lg:hidden"
      >
        <MenuIcon open />
      </button>
    </div>
  );
}
