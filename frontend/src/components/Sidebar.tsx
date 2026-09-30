import { useState } from "react";
import { NavLink } from "react-router";
import type { Me } from "../api/types.ts";
import logoUrl from "../assets/logo.svg";
import { CHAT_NAV, hasPerm, isStaff, ROLE_HEADING, ROLE_LABEL, STAFF_NAV } from "../auth/permissions.ts";
import { titleOf, useSessionTickets } from "../routes/employee/sessionTickets.ts";
import type { Tone } from "../routes/employee/status.ts";

/** `onSignOut` trả false khi CHƯA đăng xuất được (mạng/5xx) — phải báo, phiên vẫn sống. */
type SidebarProps = { me: Me; onSignOut: () => Promise<boolean> };

const itemClass = ({ isActive }: { isActive: boolean }) =>
  `flex h-9 items-center gap-2.5 rounded-lg px-3 text-secondary ${
    isActive ? "bg-selected font-semibold text-fpt-blue" : "text-ink hover:bg-group"
  }`;

const DOT: Record<Tone, string> = {
  processing: "bg-fpt-blue",
  waiting: "bg-fpt-orange",
  done: "bg-done",
  closed: "bg-ink-3",
};

// "Gần đây" = ticket tạo trong phiên này (bộ nhớ, KH 4.6). Chấm: cam chờ bạn/IT, xanh lá xong, xám đã chuyển/dừng.
function RecentTickets() {
  const tickets = useSessionTickets();
  if (tickets.length === 0) {
    return <p className="px-3 py-1 text-label font-normal text-ink-2">Chưa có yêu cầu nào trong phiên này.</p>;
  }
  return (
    <ul className="flex flex-col gap-1" aria-label="Yêu cầu gần đây">
      {tickets.map((t) => (
        <li key={t.ticket_id}>
          <NavLink to={`/chat/${encodeURIComponent(t.ticket_id)}`} className={itemClass}>
            <span className={`size-1.75 shrink-0 rounded-full ${DOT[t.tone]}`} aria-hidden="true" />
            <span className="truncate">{titleOf(t)}</span>
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

// Thanh bên hợp nhất Bản 4 (B4Sidebar): 264 px, không có thanh trên. Mục theo `permissions` (KH 4.1 #8), không
// theo tên role. Chuông ẩn tới Phase 7 (KH 4.6). Hồ sơ hiện `user_id` (Q-fe-9 — `me` chưa có tên).
export function Sidebar({ me, onSignOut }: SidebarProps) {
  const staff = isStaff(me);
  const [signOutFailed, setSignOutFailed] = useState(false);
  return (
    <nav
      aria-label="Điều hướng chính"
      className="flex h-full w-(--sidebar-width) shrink-0 flex-col gap-1 border-r border-line bg-sidebar px-3 py-4"
    >
      <div className="flex h-10 items-center gap-2.5 px-2">
        <img src={logoUrl} alt="" width={28} height={28} />
        <span className="text-secondary font-semibold">ServiceDesk AI</span>
      </div>

      {staff ? (
        <>
          <span className="px-3 pt-4 pb-1 text-label text-ink-2">{ROLE_HEADING[me.role]}</span>
          {STAFF_NAV.filter((item) => hasPerm(me, item.perm)).map((item) => (
            <NavLink key={item.to} to={item.to} className={itemClass}>
              {item.label}
            </NavLink>
          ))}
        </>
      ) : hasPerm(me, CHAT_NAV.perm) ? (
        <>
          <NavLink
            to={CHAT_NAV.to}
            end
            className="mt-3 mb-2 flex h-10 items-center gap-2 rounded-lg border border-line bg-white px-3 text-secondary font-semibold"
          >
            <span className="flex size-5 items-center justify-center rounded-full bg-send">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" className="stroke-white" strokeWidth="3" strokeLinecap="round" aria-hidden="true">
                <path d="M12 5v14M5 12h14" />
              </svg>
            </span>
            {CHAT_NAV.label}
          </NavLink>
          <span className="px-3 pt-3 pb-1 text-label text-ink-2">Gần đây</span>
          <RecentTickets />
        </>
      ) : null}

      <span className="grow" />
      <div className="mx-2 mb-2 flex h-9 items-center justify-center rounded-lg border border-dashed border-line text-label font-normal text-ink-2">
        Logo đơn vị
      </div>
      {signOutFailed ? (
        <p role="alert" className="mx-2 mb-1 rounded-lg bg-danger-bg px-3 py-2 text-label font-normal text-danger-ink">
          Chưa đăng xuất được — kiểm tra mạng rồi thử lại.
        </p>
      ) : null}
      <div className="flex items-center gap-2.5 border-t border-line p-2 pt-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-fpt-blue text-label text-white">
          {me.user_id.slice(0, 2).toUpperCase()}
        </span>
        <span className="flex min-w-0 grow flex-col">
          <span className="truncate text-secondary font-semibold" data-testid="me-user-id">
            {me.user_id}
          </span>
          <span className="truncate text-label font-normal text-ink-2">{ROLE_LABEL[me.role]}</span>
        </span>
        {/* Q-fe-16: Bản 4 không vẽ nút đăng xuất → nút biểu tượng 32 px để nhãn vai trò giữ một dòng. */}
        <button
          type="button"
          aria-label="Đăng xuất"
          title="Đăng xuất"
          onClick={() => void onSignOut().then((done) => setSignOutFailed(!done))}
          className="flex size-8 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:bg-group hover:text-ink focus-visible:outline-2 focus-visible:outline-fpt-blue"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M9 20H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4" />
            <path d="M16 16l4-4-4-4" />
            <path d="M20 12H9" />
          </svg>
        </button>
      </div>
    </nav>
  );
}
