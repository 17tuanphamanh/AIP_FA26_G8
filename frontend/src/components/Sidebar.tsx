import type { ReactNode } from "react";
import logoUrl from "../assets/logo.svg";

type SidebarProps = {
  /** Mục điều hướng — F1 dựng theo `permissions` từ `/api/auth/me` (KH 4.1 #8), không theo tên role. */
  children?: ReactNode;
  /** Ô hồ sơ ở đáy (F1: `user_id` + chữ tắt, 12b Q-fe-9). */
  footer?: ReactNode;
};

// Thanh bên hợp nhất Bản 4 (B4Sidebar): 264 px, không có thanh trên. Chuông ẩn tới Phase 7 (KH 4.6).
export function Sidebar({ children, footer }: SidebarProps) {
  return (
    <nav
      aria-label="Điều hướng chính"
      className="flex h-full w-(--sidebar-width) shrink-0 flex-col gap-1 border-r border-line bg-sidebar px-3 py-4"
    >
      <div className="flex h-10 items-center gap-2.5 px-2">
        <img src={logoUrl} alt="" width={28} height={28} />
        <span className="text-secondary font-semibold">ServiceDesk AI</span>
      </div>
      {children}
      <span className="grow" />
      <div className="mx-2 mb-2 flex h-9 items-center justify-center rounded-lg border border-dashed border-line text-label font-normal text-ink-2">
        Logo đơn vị
      </div>
      <div className="flex min-h-12 items-center gap-2.5 border-t border-line p-2 pt-3">{footer}</div>
    </nav>
  );
}
