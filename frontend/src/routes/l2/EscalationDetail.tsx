import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useParams } from "react-router";
import { ApiError, errorMessage } from "../../api/errors.ts";
import { QUEUE_LIMIT, queueQuery } from "../../api/escalations.ts";
import { getTicket } from "../../api/tickets.ts";
import type { EscalationQueueItem } from "../../api/types.ts";
import { Conversation } from "../../components/Conversation.tsx";
import { normalizeConversation } from "../../components/messages.ts";
import { CloseForm } from "./CloseForm.tsx";
import { DENY_BANNER, EMPTY_NOTE, GONE_TEXT, handoffRows, OVERFLOW_NOTE, OVERFLOW_TEXT, splitLabel, waitingText } from "./queue.ts";

// B4L2Detail. Chưa có `GET /api/escalations/{id}` (Phase 7) → ca lấy từ CHÍNH truy vấn hàng đợi (cache TanStack; tải lại
// trang → gọi lại queue limit=200 rồi tìm theo `escalation_id`). Hội thoại: `GET /api/tickets/{id}` thật (L1/L2 có
// ticket:read:any — 12b Q-fe-6), chỉ đọc. Đóng ca: CloseForm (minh hoạ tới Phase 7).

const BACK = (
  <Link to="/escalations" className="text-secondary text-fpt-blue">
    ‹ Hàng đợi escalate
  </Link>
);

/** Route `/escalations/:escalationId` — `key` theo id để form đóng không mang nháp sang ca khác. */
export function EscalationDetailRoute({ closeAvailable }: { closeAvailable?: boolean }) {
  const { escalationId = "" } = useParams();
  return <EscalationDetail key={escalationId} escalationId={escalationId} closeAvailable={closeAvailable} />;
}

function EscalationDetail({ escalationId, closeAvailable }: { escalationId: string; closeAvailable?: boolean }) {
  const id = /^\d{1,15}$/.test(escalationId) ? Number(escalationId) : null;
  const query = useQuery(queueQuery());
  const item = id === null ? undefined : query.data?.find((i) => i.escalation_id === id);

  if (query.isPending && id !== null) {
    return <p className="px-12 py-10 text-ink-2">Đang tải ca…</p>;
  }
  if (id !== null && query.data === undefined) {
    return (
      <section className="flex flex-col gap-2 px-12 py-10">
        {BACK}
        <h1 className="text-heading">Chưa tải được ca này.</h1>
        <p role="alert" className="text-ink-2">
          {errorMessage(query.error instanceof ApiError ? query.error : null)}
        </p>
      </section>
    );
  }
  if (!item) {
    // Hàng đợi đã đủ trần → không khẳng định "đã đóng": ca có thể nằm ngoài 200 ca đầu.
    const overflow = id !== null && (query.data?.length ?? 0) >= QUEUE_LIMIT;
    return (
      <section className="flex flex-col gap-2 px-12 py-10">
        {BACK}
        <h1 className="text-heading">{overflow ? OVERFLOW_TEXT : GONE_TEXT}</h1>
        <p className="text-ink-2">{overflow ? OVERFLOW_NOTE : "Mở lại hàng đợi để xem các ca đang chờ."}</p>
      </section>
    );
  }
  return <Detail item={item} now={query.dataUpdatedAt} closeAvailable={closeAvailable} />;
}

function Detail({ item, now, closeAvailable }: { item: EscalationQueueItem; now: number; closeAvailable?: boolean }) {
  const { base } = splitLabel(item.label);
  return (
    <section className="flex flex-col gap-6 px-12 py-8">
      <div className="flex flex-col gap-1">
        {BACK}
        <div className="flex items-center gap-4">
          <h1 className="min-w-0 grow text-title">
            {item.exit_code} · {base}
          </h1>
          <span className="shrink-0 text-secondary text-ink-2">{waitingText(item.created_at, now)}</span>
        </div>
        <p className="text-label font-normal text-ink-2">
          Mã ticket{" "}
          <span className="font-mono select-all" data-testid="ticket-id">
            {item.ticket_id}
          </span>{" "}
          · Escalation #{item.escalation_id}
          {item.reason_detail ? (
            <>
              {" "}
              · <span className="font-mono">{item.reason_detail}</span>
            </>
          ) : null}
          {item.assigned_to ? ` · ${item.assigned_to} đang xử lý` : ""}
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-5">
          {item.is_deny_case ? (
            <div role="note" data-testid="deny-banner" className="rounded-group bg-danger-bg px-5 py-3.5 text-danger-ink">
              <b className="font-semibold">{DENY_BANNER.strong}</b> {DENY_BANNER.rest}
            </div>
          ) : null}
          <Handoff note={item.handoff_note} />
          <TicketConversation ticketId={item.ticket_id} />
        </div>
        <CloseForm item={item} available={closeAvailable} />
      </div>
    </section>
  );
}

// Chữ THÔ, giữ xuống dòng (`whitespace-pre-line`) — không Markdown, không HTML: "<b>x</b>" hiện đúng 8 ký tự.
function Handoff({ note }: { note: unknown }) {
  return (
    <section aria-labelledby="handoff-heading" className="flex flex-col gap-2">
      <h2 id="handoff-heading" className="pl-1 text-label text-ink-2">
        Ghi chú bàn giao
      </h2>
      <dl className="overflow-hidden rounded-group border border-line">
        {handoffRows(note).map((row) => (
          <div
            key={row.key}
            data-testid="handoff-row"
            data-key={row.key}
            className="grid grid-cols-[140px_minmax(0,1fr)] gap-4 border-t border-line px-5 py-3 first:border-t-0"
          >
            <dt className="pt-0.75 text-secondary text-ink-2">{row.label}</dt>
            <dd className={`min-w-0 break-words whitespace-pre-line ${row.text === null ? "text-ink-2 italic" : ""}`}>
              {row.text ?? EMPTY_NOTE}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function TicketConversation({ ticketId }: { ticketId: string }) {
  // Ticket escalate đã kết thúc (S_ESCALATED / S_BLOCKED) → đọc một lần, không polling.
  const query = useQuery({ queryKey: ["ticket", ticketId], queryFn: () => getTicket(ticketId), retry: false });
  const messages = useMemo(() => normalizeConversation(query.data?.conversation), [query.data]);
  return (
    <section aria-labelledby="conversation-heading" className="flex flex-col gap-2">
      <h2 id="conversation-heading" className="pl-1 text-label text-ink-2">
        Hội thoại
      </h2>
      {query.isPending ? (
        <p className="text-secondary text-ink-2">Đang tải hội thoại…</p>
      ) : query.data === undefined ? (
        <p role="alert" className="text-secondary text-danger">
          Chưa tải được hội thoại: {errorMessage(query.error instanceof ApiError ? query.error : null)}
        </p>
      ) : messages.length === 0 ? (
        <p className="text-secondary text-ink-2">{EMPTY_NOTE}</p>
      ) : (
        <Conversation messages={messages} />
      )}
    </section>
  );
}
