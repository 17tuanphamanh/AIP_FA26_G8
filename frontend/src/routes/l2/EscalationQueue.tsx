import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { ApiError, errorMessage } from "../../api/errors.ts";
import { QUEUE_LIMIT, QUEUE_REFRESH_MS, queueQuery, queueRefetchInterval } from "../../api/escalations.ts";
import type { EscalationQueueItem } from "../../api/types.ts";
import { DENY_BADGE, groupQueue, reasonLine, splitLabel, waitingText } from "./queue.ts";

// B4L2Queue — hàng đợi escalate THẬT (`GET /api/escalations/queue`, quyền escalation:handle: L1 + L2). Thứ tự của server
// giữ nguyên, chỉ gom nhóm liên tiếp theo `priority` (queue.ts). L1/L2 được thấy mã E (KH 4.2 #2). Không nút duyệt nào
// ở màn này [Chốt 2.2]. Khác Bản 4: nhóm không tô màu theo mức (màu theo hạng = bảng ưu tiên thứ hai ở frontend).

export function EscalationQueue() {
  const query = useQuery({ ...queueQuery(), refetchInterval: (q) => queueRefetchInterval(q.state.error) });
  const items = query.data;

  return (
    <section className="flex flex-col gap-6 px-12 py-10">
      <div className="flex items-end gap-4">
        <div className="flex min-w-0 grow flex-col gap-1">
          <h1 className="text-title">Hàng đợi escalate</h1>
          <p className="text-ink-2">
            {items ? (
              <>
                <span data-testid="queue-count">Đang hiện {items.length} ca</span> ·{" "}
              </>
            ) : null}
            theo mức ưu tiên, rồi thời gian chờ · tự tải lại mỗi {QUEUE_REFRESH_MS / 1000} giây.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
          className="h-7.5 shrink-0 rounded-full bg-button-2 px-3.5 text-secondary font-semibold text-fpt-blue disabled:opacity-60"
        >
          {query.isFetching ? "Đang tải…" : "Tải lại"}
        </button>
      </div>

      {items === undefined ? (
        query.isPending ? (
          <p className="text-ink-2">Đang tải hàng đợi…</p>
        ) : (
          <p role="alert" className="text-danger">
            Chưa tải được hàng đợi: {errorMessage(query.error instanceof ApiError ? query.error : null)}
          </p>
        )
      ) : (
        <>
          {query.isError ? (
            <p role="status" className="text-secondary text-ink-2">
              Chưa tải lại được — đang hiện dữ liệu lần trước.
            </p>
          ) : null}
          {items.length >= QUEUE_LIMIT ? (
            <p role="status" className="rounded-group bg-orange-bg px-4 py-3 text-secondary text-orange-ink" data-testid="queue-overflow">
              Hàng đợi đang quá {QUEUE_LIMIT} ca — chỉ hiện {QUEUE_LIMIT} ca đầu theo ưu tiên (ca cũ trước), ca mới hơn có thể
              chưa hiện.
            </p>
          ) : null}
          <QueueGroups items={items} now={query.dataUpdatedAt} />
        </>
      )}
    </section>
  );
}

function QueueGroups({ items, now }: { items: EscalationQueueItem[]; now: number }) {
  if (items.length === 0) {
    return <p className="rounded-group bg-group px-5 py-4 text-ink-2">Không có ca nào đang chờ</p>;
  }
  return (
    <div className="flex flex-col gap-4">
      {groupQueue(items).map((group, index) => (
        <section
          key={`${group.priority}-${index}`}
          aria-labelledby={`queue-group-${index}`}
          data-testid="queue-group"
          data-priority={group.priority}
          className="flex flex-col gap-1.5"
        >
          <h2 id={`queue-group-${index}`} className="inline-flex items-center gap-2 pl-1 text-label text-ink-2">
            <span className="size-1.75 rounded-full bg-ink-3" aria-hidden="true" />
            {group.name}
          </h2>
          <ul className="overflow-hidden rounded-group border border-line">
            {group.items.map((item) => (
              <QueueRow key={item.escalation_id} item={item} now={now} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function QueueRow({ item, now }: { item: EscalationQueueItem; now: number }) {
  const reason = reasonLine(item);
  const extra = splitLabel(item.label).extra;
  const meta = [waitingText(item.created_at, now), item.assigned_to ? `${item.assigned_to} đang xử lý` : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="border-t border-line first:border-t-0">
      <Link
        to={`/escalations/${item.escalation_id}`}
        data-testid="queue-row"
        data-escalation-id={item.escalation_id}
        data-ticket-id={item.ticket_id}
        data-exit-code={item.exit_code}
        className="grid min-h-13 grid-cols-[44px_minmax(0,1fr)_auto_14px] items-center gap-4 px-5 py-2 hover:bg-group focus-visible:outline-2 focus-visible:outline-fpt-blue"
      >
        <span className="font-mono text-label font-normal text-ink-2">{item.exit_code}</span>
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate" title={reason}>
            {reason}
          </span>
          {item.is_deny_case ? (
            <span className="shrink-0 rounded-full bg-danger-bg px-2 text-label text-danger-ink" data-testid="deny-badge">
              {DENY_BADGE}
            </span>
          ) : null}
          {extra ? (
            <span className="shrink-0 rounded-full bg-orange-bg px-2 text-label text-orange-ink">{extra}</span>
          ) : null}
        </span>
        <span className="text-secondary text-ink-2">{meta}</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="stroke-ink-3" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M9 6l6 6-6 6" />
        </svg>
      </Link>
    </li>
  );
}
