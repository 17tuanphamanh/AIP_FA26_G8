import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { NavLink, useMatch, useNavigate } from "react-router";
import { hideTicket, myTicketsQuery } from "../api/tickets.ts";
import type { Me, TicketListItem } from "../api/types.ts";
import fptLogoUrl from "../assets/fpt-university-logo.png";
import logoUrl from "../assets/logo.svg";
import { CHAT_NAV, hasPerm, isStaff, ROLE_HEADING, ROLE_LABEL, STAFF_NAV } from "../auth/permissions.ts";
import { AD_ADMIN_URL, DEMO_TOOLS, MOCK_CONSOLE_URL, phoneUrl } from "../lib/demoTools.ts";
import { ownEntry } from "../lib/lookup.ts";
import { PlacedBell } from "./PlacedBell.tsx";
import {
  type RecentTicket,
  recentTickets,
  sessionTickets,
  titleOf,
  useHiddenTickets,
  useSessionTickets,
} from "../routes/employee/sessionTickets.ts";
import type { Tone } from "../routes/employee/status.ts";

/** `onSignOut` trả false khi CHƯA đăng xuất được (mạng/5xx) — phải báo, phiên vẫn sống. */
type SidebarProps = { me: Me; onSignOut: () => Promise<boolean> };

export { AD_ADMIN_URL };

const itemClass = ({ isActive }: { isActive: boolean }) =>
  `flex h-9 items-center gap-2.5 rounded-lg px-3 text-secondary max-lg:min-h-11 ${
    isActive ? "bg-selected font-semibold text-fpt-blue" : "text-ink hover:bg-group"
  }`;

const DOT: Record<Tone, string> = {
  processing: "bg-fpt-blue",
  waiting: "bg-fpt-orange",
  done: "bg-done",
  closed: "bg-ink-3",
};

// "Gần đây" (P3) = ticket vừa tạo trong phiên (bộ nhớ, KH 4.6) ghép với `GET /api/tickets` tải MỘT lần (sống qua F5 / đăng
// nhập lại; khoá theo `user_id`). API lỗi → chỉ ticket trong phiên, không báo lỗi (thanh bên không chặn trang). Không lưu
// danh sách xuống Storage. Chấm: cam chờ bạn/IT, xanh lá xong, xám đã chuyển/dừng, xanh FPT đang chạy (chỉ ticket phiên).
//
// Menu ⋯ từng mục (người kiểm thử yêu cầu, ĐP duyệt 08/11): "Mở ở cửa sổ mới" (cửa sổ riêng, vẫn đăng nhập nhờ cookie refresh +
// Web Locks/BroadcastChannel ở api/http.ts) và "Xóa" = ẨN khỏi "Gần đây" của chính người đó (`POST /api/tickets/{id}/hide` — không
// xoá dữ liệu, mở bằng link vẫn đọc được). Xóa: mục mất ngay (tập "đang ẩn" của sessionTickets), đang ở /chat/<mã đó> → /chat ngay;
// API xong → bỏ khỏi cache + bộ nhớ phiên; API lỗi → mục về đúng chỗ cũ + dòng trạng thái. Không hộp xác nhận.
// Giới hạn: cửa sổ/tab khác đang mở không tự cập nhật (phải F5); chưa có "bỏ ẩn".
const OPEN_FEATURES = "noopener,noreferrer,popup";
const HIDE_FAILED = "Chưa xóa được, thử lại";
const HIDE_FAILED_MS = 6000;

const chatPath = (id: string) => `${CHAT_NAV.to}/${encodeURIComponent(id)}`;

function RecentTickets({ me }: { me: Me }) {
  const session = useSessionTickets();
  const hidden = useHiddenTickets();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const openId = useMatch(`${CHAT_NAV.to}/:ticketId`)?.params.ticketId;
  const [failed, setFailed] = useState(0); // >0 = đang hiện câu lỗi (đổi số để hẹn giờ lại mỗi lần lỗi)
  const listQuery = myTicketsQuery(me.user_id);
  const fromApi = useQuery({ ...listQuery, enabled: hasPerm(me, "ticket:read:own") }).data;
  const tickets = recentTickets(session, fromApi ?? [], hidden);

  useEffect(() => {
    if (!failed) return;
    const timer = setTimeout(() => setFailed(0), HIDE_FAILED_MS);
    return () => clearTimeout(timer);
  }, [failed]);

  function hide(id: string) {
    setFailed(0);
    sessionTickets.hide(id);
    if (openId === id) navigate(CHAT_NAV.to, { replace: true });
    hideTicket(id).then(
      () => {
        queryClient.setQueryData<TicketListItem[]>(listQuery.queryKey, (old) => old?.filter((t) => t.ticket_id !== id));
        sessionTickets.remove(id);
      },
      () => {
        sessionTickets.unhide(id);
        setFailed((n) => n + 1);
      },
    );
  }

  const notice = failed ? (
    <p role="status" className="px-3 py-1 text-label font-normal text-danger-ink">
      {HIDE_FAILED}
    </p>
  ) : null;
  if (tickets.length === 0) {
    return (
      <>
        <p className="px-3 py-1 text-label font-normal text-ink-2">Chưa có yêu cầu nào.</p>
        {notice}
      </>
    );
  }
  return (
    <>
      <ul className="flex flex-col gap-1" aria-label="Yêu cầu gần đây">
        {tickets.map((t) => (
          <RecentRow key={t.ticket_id} ticket={t} onHide={() => hide(t.ticket_id)} />
        ))}
      </ul>
      {notice}
    </>
  );
}

/** Một mục "Gần đây": nút ⋯ chỉ hiện khi rê chuột / focus trong mục / menu đang mở. Menu: mở → focus mục đầu; ↑/↓ chuyển mục;
 *  Esc → đóng, focus về ⋯; Tab hoặc bấm ra ngoài → đóng. */
function RecentRow({ ticket, onHide }: { ticket: RecentTicket; onHide: () => void }) {
  const title = titleOf(ticket);
  const href = chatPath(ticket.ticket_id);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [open, setOpen] = useState(false);
  const row = useRef<HTMLLIElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    const onPointer = (e: MouseEvent) => {
      if (!row.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [open]);

  function close() {
    setOpen(false);
    button.current?.focus();
  }

  function onMenuKey(e: React.KeyboardEvent<HTMLDivElement>) {
    const items = Array.from(menu.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? []);
    const at = items.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      items[(at + step + items.length) % items.length]?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <li
      ref={row}
      className="relative motion-safe:animate-rise-in"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        if (!row.current?.contains(e.relatedTarget as Node | null)) setFocused(false);
      }}
    >
      <NavLink to={href} className={(state) => `${itemClass(state)} pr-10`}>
        <span className={`size-1.75 shrink-0 rounded-full ${DOT[ticket.tone]}`} aria-hidden="true" />
        <span className="truncate">{title}</span>
      </NavLink>
      {hovered || focused || open ? (
        <button
          ref={button}
          type="button"
          aria-label={`Tùy chọn cho ${title}`}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          onClick={() => (open ? close() : setOpen(true))}
          className="absolute top-1 right-1 flex size-7 items-center justify-center rounded-lg text-ink-2 hover:bg-group hover:text-ink focus-visible:outline-2 focus-visible:outline-fpt-blue"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="5" cy="12" r="1.8" />
            <circle cx="12" cy="12" r="1.8" />
            <circle cx="19" cy="12" r="1.8" />
          </svg>
        </button>
      ) : null}
      {open ? (
        <div
          ref={menu}
          id={menuId}
          role="menu"
          aria-label={`Tùy chọn cho ${title}`}
          onKeyDown={onMenuKey}
          className="absolute top-9 right-0 z-30 flex w-48 origin-top-right flex-col rounded-group border border-line bg-white py-1 shadow-input motion-safe:animate-pop-in"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              window.open(href, "_blank", OPEN_FEATURES);
              close();
            }}
            className="flex h-9 items-center px-3 text-left text-secondary text-ink outline-none hover:bg-group focus:bg-group"
          >
            Mở ở cửa sổ mới
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onHide();
            }}
            className="flex h-9 items-center px-3 text-left text-secondary text-danger-ink outline-none hover:bg-group focus:bg-group"
          >
            Xóa
          </button>
        </div>
      ) : null}
    </li>
  );
}

const demoItem =
  "flex h-8 items-center gap-2 rounded-lg px-3 text-secondary text-ink hover:bg-white focus-visible:outline-2 focus-visible:outline-fpt-blue max-lg:min-h-11";

/** Nhóm "Demo · giả lập" (TA 14/11 — "khó mở"): mọi người có "Điện thoại của tôi" (đọc SMS mật khẩu tạm); nhân viên IT có thêm
 *  "Hệ thống giả lập" (AD, VPN, phần mềm…). Chỉ ở bản demo (lib/demoTools.ts). Mở tab mới — app không đọc gì từ trang đó. */
function DemoTools({ me }: { me: Me }) {
  if (!DEMO_TOOLS) return null;
  return (
    <div className="mx-1 mb-2 rounded-xl border border-dashed border-line bg-group p-1" data-testid="demo-tools">
      <span className="block px-3 pt-1 pb-0.5 text-label text-ink-2">Demo · hệ thống giả lập</span>
      <a href={phoneUrl(me.user_id)} target="_blank" rel="noopener noreferrer" data-testid="nav-demo-phone" className={demoItem}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="5" y="2" width="14" height="20" rx="2" />
          <path d="M12 18h.01" />
        </svg>
        Điện thoại của tôi ↗
      </a>
      {isStaff(me) ? (
        <a href={MOCK_CONSOLE_URL} target="_blank" rel="noopener noreferrer" data-testid="nav-demo-console" className={demoItem}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="2" y="2" width="20" height="8" rx="2" />
            <rect x="2" y="14" width="20" height="8" rx="2" />
            <path d="M6 6h.01M6 18h.01" />
          </svg>
          Hệ thống giả lập ↗
        </a>
      ) : null}
    </div>
  );
}

// Thanh bên hợp nhất Bản 4 (B4Sidebar): 264 px, không có thanh trên. Mục theo `permissions` (KH 4.1 #8), không
// theo tên role. Chuông thông báo ở hàng logo (N-TB — components/NotificationBell.tsx; route chưa có → ẩn). Hồ sơ hiện `user_id` (Q-fe-9 — `me` chưa có tên).
export function Sidebar({ me, onSignOut }: SidebarProps) {
  const staff = isStaff(me);
  const [signOutFailed, setSignOutFailed] = useState(false);
  return (
    <nav
      aria-label="Điều hướng chính"
      className="flex h-full w-(--sidebar-width) shrink-0 flex-col gap-1 border-r border-line bg-sidebar px-3 py-4 max-lg:overflow-y-auto"
    >
      <div className="flex h-10 items-center gap-2.5 px-2 max-lg:h-12">
        <img src={logoUrl} alt="" width={28} height={28} />
        <span className="grow text-secondary font-semibold">ServiceDesk AI</span>
        <PlacedBell me={me} where="sidebar" />
      </div>

      {staff ? (
        <>
          <span className="px-3 pt-4 pb-1 text-label text-ink-2">{ownEntry(ROLE_HEADING, me.role, "")}</span>
          {STAFF_NAV.filter((item) => hasPerm(me, item.perm)).map((item) => (
            <NavLink key={item.to} to={item.to} className={itemClass}>
              {item.label}
            </NavLink>
          ))}
          {/* D-97 (TA 14/11, cách 1): quản trị nhân viên nằm ở AD của công ty (ở đây: AD giả lập), KHÔNG trong app — app chỉ mở sang.
              Ghi ra hệ thống ngoài vẫn chỉ qua B17. Trang chỉ chạy trên chính máy chạy hệ thống (127.0.0.1). */}
          {DEMO_TOOLS && hasPerm(me, "policy:edit") ? (
            <a href={AD_ADMIN_URL} target="_blank" rel="noopener noreferrer" data-testid="nav-ad-admin" className={itemClass({ isActive: false })}>
              Quản trị nhân viên (AD) ↗
            </a>
          ) : null}
        </>
      ) : hasPerm(me, CHAT_NAV.perm) ? (
        <>
          <NavLink
            to={CHAT_NAV.to}
            end
            className="mt-3 mb-2 flex h-10 items-center gap-2 rounded-lg border border-line bg-white px-3 text-secondary font-semibold max-lg:min-h-11"
          >
            <span className="flex size-5 items-center justify-center rounded-full bg-send">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" className="stroke-white" strokeWidth="3" strokeLinecap="round" aria-hidden="true">
                <path d="M12 5v14M5 12h14" />
              </svg>
            </span>
            {CHAT_NAV.label}
          </NavLink>
          <span className="px-3 pt-3 pb-1 text-label text-ink-2">Gần đây</span>
          <RecentTickets me={me} />
        </>
      ) : null}

      <span className="grow" />
      <DemoTools me={me} />
      {/* Chỗ dành sẵn "Logo đơn vị" → logo FPT (gói fe-logo-fpt): cao 24 px, rộng theo tỉ lệ (330×93). */}
      <div className="mx-2 mb-2 flex h-9 items-center gap-2 px-1" data-testid="sidebar-fpt">
        <img src={fptLogoUrl} alt="Trường Đại học FPT" width={330} height={93} className="h-6 w-auto shrink-0" />
        <span className="whitespace-nowrap text-label font-normal text-ink-2">Trường Đại học FPT</span>
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
          <span className="truncate text-label font-normal text-ink-2">{ownEntry(ROLE_LABEL, me.role, "")}</span>
        </span>
        {/* Q-fe-16: Bản 4 không vẽ nút đăng xuất → nút biểu tượng 32 px để nhãn vai trò giữ một dòng. */}
        <button
          type="button"
          aria-label="Đăng xuất"
          title="Đăng xuất"
          onClick={() => void onSignOut().then((done) => setSignOutFailed(!done))}
          className="flex size-8 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:bg-group hover:text-ink focus-visible:outline-2 focus-visible:outline-fpt-blue max-lg:size-11"
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
