import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router";
import { isoMs } from "../api/iso.ts";
import {
  hasMoreNotifications,
  isNewer,
  loadedNotifications,
  newestCreatedAt,
  notificationsQuery,
  notificationsRefetchInterval,
  notificationsUnavailable,
  unreadCount,
} from "../api/notifications.ts";
import type { Me, NotificationView } from "../api/types.ts";
import { hasPerm } from "../auth/permissions.ts";
import { readLastSeen, writeLastSeen } from "../lib/lastSeen.ts";
import { ownEntry } from "../lib/lookup.ts";
import { cauThongBao, KET_QUA_THONG_BAO } from "../lib/nhan.ts";
import { vnDateTime } from "../routes/manager/range.ts";

// Chuông thông báo (ĐP 26/10 N-TB P2; hợp đồng thông báo §1) — mọi vai trò đã đăng nhập, ở hàng logo của thanh bên (dưới
//   1024 px: ở thanh đầu — chỗ đứng do PlacedBell.tsx quyết).
// - Số trên chuông = số thông báo ĐÃ TẢI có `created_at` > mốc đã xem (lib/lastSeen.ts); không có → không số.
// - Mở danh sách = đánh dấu đã đọc: mốc = `created_at` mới nhất đang hiện.
// - Hỏi lại 30 s, CHỈ khi tab đang hiện (`refetchIntervalInBackground: false` — TanStack dừng nhịp khi
//   `document.visibilityState` = hidden); 401/403/404 → dừng. 404 (backend cũ) / 403 / thiếu `ticket:read:own` → không vẽ chuông.
// - Danh sách là popover gọn (không thêm trang `/notifications`): Bản 4 không có thanh trên, thanh bên 264 px.

/** Câu lỗi khung thông báo (ĐP soát 23d0f6a #4). */
const TB_LOI = "Chưa tải được thông báo";

const badgeText = (count: number, partial: boolean) => (count > 99 ? "99+" : partial ? `${count}+` : String(count));

export function NotificationBell({ me }: { me: Me }) {
  const userId = me.user_id;
  // Route thật đòi `ticket:read:own` (backend/app/api/notifications.py) — không có quyền → không hỏi, không chuông.
  const allowed = hasPerm(me, "ticket:read:own");
  const query = useInfiniteQuery({
    ...notificationsQuery(userId),
    enabled: allowed,
    refetchInterval: (q) => notificationsRefetchInterval(q.state.error),
    refetchIntervalInBackground: false,
  });
  const items = loadedNotifications(query.data);
  const more = hasMoreNotifications(query.data);
  // Mốc đọc giữ trong bộ nhớ (Storage hỏng vẫn đúng trong phiên) + ghi xuống Storage khi đổi.
  const [lastSeen, setLastSeen] = useState<string | null>(() => readLastSeen(userId));
  const [open, setOpen] = useState(false);
  // Mốc lúc MỞ danh sách — chấm "mới" cho các dòng chưa đọc trước lần mở này.
  const [seenAtOpen, setSeenAtOpen] = useState<string | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const newest = newestCreatedAt(items);

  // Đang mở = đã đọc mọi dòng đang hiện: mốc = `created_at` mới nhất (cả dòng mới tới khi đang mở). Chỉnh state ngay lúc
  // render (mẫu "điều chỉnh state theo giá trị render trước" của React) — không qua effect.
  if (open && newest !== null && isNewer(newest, lastSeen)) setLastSeen(newest);
  // Đồng bộ ra Storage (hệ ngoài). Ghi hỏng → mốc vẫn đúng trong phiên (state), tải lại trang thì coi như chưa đọc.
  useEffect(() => {
    if (lastSeen !== null) writeLastSeen(userId, lastSeen);
  }, [lastSeen, userId]);

  useEffect(() => {
    if (!open) return;
    panel.current?.focus();
    const onPointer = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!panel.current?.contains(target) && !button.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [open]);

  if (!allowed) return null;
  if (query.data === undefined && (query.isPending || notificationsUnavailable(query.error))) return null;
  if (notificationsUnavailable(query.error)) return null;

  const unread = unreadCount(items, lastSeen);
  const partial = more && unread === items.length; // mọi dòng đã tải đều chưa đọc + còn trang → có thể còn nữa

  function toggle() {
    if (open) return close();
    setSeenAtOpen(lastSeen);
    setOpen(true);
  }
  function close() {
    setOpen(false);
    button.current?.focus();
  }

  return (
    <div className="relative">
      <button
        ref={button}
        type="button"
        aria-label={unread > 0 ? `Thông báo, ${badgeText(unread, partial)} chưa đọc` : "Thông báo"}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-haspopup="dialog"
        onClick={toggle}
        data-testid="tb-bell"
        className="relative flex size-8 items-center justify-center rounded-lg text-ink-2 hover:bg-group hover:text-ink focus-visible:outline-2 focus-visible:outline-fpt-blue max-lg:size-11"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unread > 0 ? (
          <span
            aria-hidden="true"
            data-testid="tb-count"
            className="absolute -top-1 -right-1 flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-send px-1 text-label text-white"
          >
            {badgeText(unread, partial)}
          </span>
        ) : null}
      </button>
      {open ? (
        <div
          ref={panel}
          id={panelId}
          role="dialog"
          aria-label="Thông báo"
          tabIndex={-1}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              close();
            }
          }}
          className="absolute top-10 left-0 z-30 flex max-h-120 w-90 origin-top-left flex-col overflow-hidden rounded-group border border-line bg-white shadow-input outline-none motion-safe:animate-pop-in max-lg:fixed max-lg:inset-x-3 max-lg:top-[calc(4rem+env(safe-area-inset-top))] max-lg:max-h-[min(30rem,calc(100dvh_-_5rem_-_env(safe-area-inset-top)))] max-lg:w-auto"
        >
          <h2 className="border-b border-line px-4 py-3 text-secondary font-semibold">Thông báo</h2>
          <div className="flex min-h-0 flex-col overflow-y-auto">
            {/* Lỗi (thân sai 502 invalid_notifications_body, mạng, 5xx…) → nói ra, không im lặng (ĐP soát 23d0f6a #4). Chưa
                có dữ liệu: câu ĐP nguyên văn; đã có dữ liệu cũ (vẫn hiện bên dưới): thêm "— đang thử lại" (nhịp 30 s vẫn chạy). */}
            {query.isError ? (
              <p role="status" data-testid="tb-error" className="px-4 py-3 text-secondary text-ink-2">
                {items.length > 0 ? `${TB_LOI} — đang thử lại.` : `${TB_LOI}.`}
              </p>
            ) : null}
            {items.length === 0 && !query.isError ? <p className="px-4 py-6 text-secondary text-ink-2">Chưa có thông báo nào.</p> : null}
            <ul className="flex flex-col" aria-label="Danh sách thông báo">
              {items.map((item) => (
                <NotificationRow
                  key={item.id}
                  item={item}
                  fresh={(isoMs(seenAtOpen) ?? -Infinity) < Date.parse(item.created_at)}
                  onNavigate={() => setOpen(false)}
                />
              ))}
            </ul>
            {more ? (
              <button
                type="button"
                disabled={query.isFetchingNextPage}
                onClick={() => void query.fetchNextPage({ cancelRefetch: false })}
                className="m-3 h-9 rounded-full bg-button-2 text-secondary font-semibold disabled:opacity-60 max-lg:min-h-11"
              >
                {query.isFetchingNextPage ? "Đang tải…" : "Tải thêm"}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function NotificationRow({
  item,
  fresh,
  onNavigate,
}: {
  item: NotificationView;
  fresh: boolean;
  onNavigate: () => void;
}) {
  // ĐP 23:51: đợt này KHÔNG hiện link / mã ticket mới kể cả khi `new_ticket_id` lỡ có giá trị — chỉ link ticket gốc.
  const label = ownEntry<string | null>(KET_QUA_THONG_BAO, item.result, null);
  return (
    <li className="flex gap-2.5 border-b border-line px-4 py-3 last:border-b-0 motion-safe:animate-fade-in" data-testid="tb-row">
      <span className={`mt-2 size-1.75 shrink-0 rounded-full bg-send ${fresh ? "" : "invisible"}`} aria-hidden="true" />
      <div className="flex min-w-0 grow flex-col gap-1">
        <p className="text-secondary">{cauThongBao(item)}</p>
        <p className="flex flex-wrap items-center gap-x-2 text-label font-normal text-ink-2">
          {fresh ? <span className="sr-only">Mới · </span> : null}
          {label ? <span className="font-semibold">{label}</span> : null}
          <time dateTime={item.created_at}>{vnDateTime(item.created_at)}</time>
        </p>
        {/* Chuông chỉ có khi có `ticket:read:own` — cùng quyền route /chat/:id. */}
        <p className="flex flex-wrap gap-x-4 text-label">
          <Link to={`/chat/${encodeURIComponent(item.ticket_id)}`} onClick={onNavigate} className="text-fpt-blue max-lg:inline-flex max-lg:min-h-11 max-lg:items-center">
            Xem yêu cầu
          </Link>
        </p>
      </div>
    </li>
  );
}
