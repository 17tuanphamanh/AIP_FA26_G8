import { useQueries, useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router";
import { inboxQuery, inboxRefetchInterval } from "../../api/approvals.ts";
import { ApiError, errorMessage } from "../../api/errors.ts";
import type { ApprovalListItem } from "../../api/types.ts";
import { hasPerm } from "../../auth/permissions.ts";
import { useMe } from "../../auth/useAuth.ts";
import { useServerNow } from "../../components/clock.ts";
import { ownEntry } from "../../lib/lookup.ts";
import {
  actionLabel,
  INBOX_COUNT_STALE_TEXT,
  INBOX_STALE_TEXT,
  INBOX_TABS,
  type InboxTab,
  isUrgent,
  remainingShort,
  sortByDeadline,
  STATUS_LABEL,
  TICKET_ID_PATTERN,
} from "./inbox.ts";

// B4L1Queue — hộp thư duyệt `GET /api/approvals?mine=1&status=…` (route THẬT 4c P5; dev:mock gộp thêm phiếu minh hoạ).
// Sắp theo hạn ở client. Tab "Hệ thống đã tự xử lý" ẩn tới Phase 7 (KH 4.6) → ô "Mã ticket" để mở màn ghi đè. Mọi lỗi
// (kể cả 404 — route đã có nên 404 là lỗi thật) → câu lỗi chung. Không nút duyệt ở danh sách — chỉ ở chi tiết phiếu.

export function ApprovalQueue() {
  const me = useMe();
  const [tab, setTab] = useState<InboxTab>("pending");
  const current = INBOX_TABS.find((t) => t.tab === tab) ?? INBOX_TABS[0]!;
  const pending = useQuery({ ...inboxQuery("pending"), refetchInterval: (q) => inboxRefetchInterval(q.state.error) });
  const lists = useQueries({
    queries: current.statuses.map((status) => ({
      ...inboxQuery(status),
      refetchInterval: (q: { state: { error: unknown } }) => inboxRefetchInterval(q.state.error),
    })),
  });

  const loading = lists.some((q) => q.data === undefined && q.isPending);
  const failed = lists.find((q) => q.data === undefined && q.isError);
  // Đã có dữ liệu mà lần tải lại gần nhất lỗi (kể cả 403 — nhịp tự tải lại đã dừng): GIỮ danh sách cũ (không ẩn phiếu đang
  // chờ, server vẫn quyết quyền khi mở) + báo có thể đã cũ. Lần tải lại sau thành công → isError hết → cảnh báo tự mất.
  const stale = lists.find((q) => q.data !== undefined && q.isError);
  // Số đếm "Chờ duyệt · N" là tín hiệu duy nhất về phiếu mới khi đang ở tab khác → truy vấn `pending` tải lại lỗi cũng phải
  // báo. Đang ở tab "Chờ duyệt" thì `stale` ở trên đã báo cùng lỗi đó — không hiện hai dòng.
  const countStale = tab !== "pending" && pending.data !== undefined && pending.isError;
  const items = lists.every((q) => q.data !== undefined) ? sortByDeadline(lists.flatMap((q) => q.data ?? [])) : null;

  return (
    <section className="flex flex-col gap-6 px-12 py-10">
      <div className="flex items-end gap-6">
        <div className="flex min-w-0 grow flex-col gap-1">
          <h1 className="text-title">Chờ tôi duyệt</h1>
          <p className="text-ink-2">Hết hạn sẽ tự chuyển L2 — không bao giờ tự thực hiện.</p>
        </div>
        <div role="tablist" aria-label="Trạng thái phiếu" className="flex shrink-0 rounded-lg bg-segmented p-0.5">
          {INBOX_TABS.map((t) => (
            <button
              key={t.tab}
              type="button"
              role="tab"
              aria-selected={tab === t.tab}
              onClick={() => setTab(t.tab)}
              className={`h-8 rounded-md px-4 text-secondary ${tab === t.tab ? "bg-white font-semibold shadow-input" : ""}`}
            >
              {t.label}
              {t.tab === "pending" && pending.data ? ` · ${pending.data.length}` : ""}
            </button>
          ))}
        </div>
      </div>

      {countStale ? (
        <p role="status" data-testid="inbox-count-stale" className="rounded-group bg-orange-bg px-5 py-3.5 text-orange-ink">
          {INBOX_COUNT_STALE_TEXT} {errorMessage(pending.error instanceof ApiError ? pending.error : null)}
        </p>
      ) : null}

      {loading ? (
        <p className="text-ink-2 motion-safe:animate-pulse">Đang tải hộp thư…</p>
      ) : failed ? (
        <p role="alert" className="text-danger">
          Chưa tải được hộp thư: {errorMessage(failed.error instanceof ApiError ? failed.error : null)}
        </p>
      ) : items ? (
        <>
          {stale ? (
            <p role="status" data-testid="inbox-stale" className="rounded-group bg-orange-bg px-5 py-3.5 text-orange-ink">
              {INBOX_STALE_TEXT} {errorMessage(stale.error instanceof ApiError ? stale.error : null)}
            </p>
          ) : null}
          <InboxList items={items} tab={tab} />
        </>
      ) : null}

      {hasPerm(me, "decision:override") ? <OverrideEntry /> : null}
    </section>
  );
}

const EMPTY: Record<InboxTab, string> = {
  pending: "Không có phiếu nào chờ bạn duyệt",
  decided: "Chưa có phiếu nào đã quyết",
  expired: "Không có phiếu nào hết hạn",
};

function InboxList({ items, tab }: { items: ApprovalListItem[]; tab: InboxTab }) {
  const now = useServerNow();
  if (items.length === 0) return <p className="rounded-group bg-group px-5 py-4 text-ink-2">{EMPTY[tab]}</p>;
  return (
    <ul aria-label="Phiếu duyệt" className="overflow-hidden rounded-group border border-line">
      {items.map((item) => (
        <InboxRow key={item.approval_id} item={item} now={now} />
      ))}
    </ul>
  );
}

function InboxRow({ item, now }: { item: ApprovalListItem; now: number }) {
  const pending = item.status === "pending";
  const urgent = pending && isUrgent(item.created_at, item.deadline, now);
  const reminder = item.reminder_2_at ? 2 : item.reminder_1_at ? 1 : 0;
  return (
    <li className="border-t border-line first:border-t-0 motion-safe:animate-rise-in">
      <Link
        to={`/approvals/${encodeURIComponent(item.approval_id)}`}
        data-testid="inbox-row"
        data-approval-id={item.approval_id}
        data-urgent={urgent}
        data-role-as={item.role_as}
        className={`grid min-h-15 grid-cols-[132px_minmax(0,1fr)_auto_14px] items-center gap-5 border-l-3 py-3 pr-5 pl-4.5 hover:bg-group focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fpt-blue ${
          urgent ? "border-l-danger" : pending ? "border-l-fpt-orange" : "border-l-transparent"
        }`}
      >
        {/* Vạch mép trái = mức gấp (đỏ: còn dưới 20% thời gian; cam: đang chờ) — cùng nghĩa với chữ thời gian, không thay chữ. */}
        <span
          data-testid="inbox-time"
          className={`text-secondary tabular-nums ${urgent ? "font-semibold text-danger" : pending ? "text-ink" : "text-ink-2"}`}
        >
          {pending ? remainingShort(item.deadline, now) : ownEntry(STATUS_LABEL, item.status, "")}
        </span>
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-semibold">{actionLabel(item.action_type)}</span>
          <span className="truncate text-secondary text-ink-2">
            Máy {item.device_id ?? "(không có)"} · Yêu cầu{" "}
            {/* Mã ticket dài (UUID): chỉ rút gọn khi HIỂN THỊ — chữ đủ vẫn nằm trong trang + hiện khi rê chuột. */}
            <span className="inline-block max-w-[10ch] truncate align-bottom font-mono" title={item.ticket_id}>
              {item.ticket_id}
            </span>
          </span>
        </span>
        <span className="flex items-center gap-2">
          {item.role_as === "backup" ? (
            <span data-testid="backup-badge" className="rounded-full bg-orange-bg px-2 text-label text-orange-ink">
              Dự phòng
            </span>
          ) : null}
          {reminder ? (
            <span
              data-testid="reminder-mark"
              title={`Hệ thống đã nhắc lần ${reminder}`}
              className="inline-flex items-center gap-1 text-label font-normal text-ink-2"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
                <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
              </svg>
              Đã nhắc {reminder}
            </span>
          ) : null}
        </span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="stroke-ink-3" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M9 6l6 6-6 6" />
        </svg>
      </Link>
    </li>
  );
}

// Tab "Hệ thống đã tự xử lý" ẩn tới Phase 7 (chưa có route liệt kê — nợ API #6) → mở ticket bằng mã (KH 4.6).
function OverrideEntry() {
  const navigate = useNavigate();
  const [ticketId, setTicketId] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    const id = ticketId.trim();
    if (!TICKET_ID_PATTERN.test(id)) {
      setError("Mã yêu cầu chỉ gồm chữ, số và . _ - (tối đa 64 ký tự).");
      return;
    }
    void navigate(`/approvals/ticket/${encodeURIComponent(id)}`);
  }

  return (
    <section aria-labelledby="override-entry-heading" className="flex flex-col gap-2">
      <h2 id="override-entry-heading" className="pl-1 text-label text-ink-2">
        Ghi đè quyết định của hệ thống
      </h2>
      <form onSubmit={submit} noValidate className="flex items-center gap-3 rounded-group border border-line px-5 py-3">
        <label htmlFor="override-ticket" className="shrink-0 text-secondary">
          Mã yêu cầu
        </label>
        <input
          id="override-ticket"
          value={ticketId}
          onChange={(e) => {
            setTicketId(e.target.value);
            setError(null);
          }}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={error !== null || undefined}
          className="h-9 min-w-0 grow rounded-lg border border-line px-3 font-mono text-secondary"
        />
        <button type="submit" className="h-7.5 shrink-0 rounded-full bg-button-2 px-3.5 text-secondary font-semibold text-fpt-blue">
          Xem yêu cầu
        </button>
      </form>
      {error ? (
        <p role="alert" className="pl-1 text-secondary text-danger">
          {error}
        </p>
      ) : null}
      <p className="pl-1 text-label font-normal text-ink-2">
        Màn này chưa có danh sách ca hệ thống đã tự xử lý — nhập mã yêu cầu cần xem lại.
      </p>
    </section>
  );
}
