import { useInfiniteQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ApiError, errorMessage } from "../../api/errors.ts";
import { hasMore, loadedItems, queueQuery, type QueueItem } from "../../api/escalations.ts";
import type { EscalationCloseIn, EscalationCloseResult, EscalationQueueStatus } from "../../api/types.ts";
import { TicketConversation } from "../../components/TicketConversation.tsx";
import { formatAt } from "../shared/traceText.ts";
import { MaNhan, NhanMa } from "../../components/MaNhan.tsx";
import { caSo } from "../../lib/nhan.ts";
import { CloseForm } from "./CloseForm.tsx";
import {
  CLOSED_GONE_TEXT,
  CLOSED_TEXT,
  REOPENED_TEXT,
  closeResultLabel,
  DENY_BANNER,
  exitNhan,
  EMPTY_NOTE,
  GONE_TEXT,
  handoffRows,
  NOT_LOADED_NOTE,
  notLoadedText,
  waitingText,
} from "./queue.ts";

// B4L2Detail. Chưa có `GET /api/escalations/{id}` → ca lấy từ CHÍNH truy vấn hàng đợi (các trang đã tải, cùng cache
// TanStack) theo trạng thái trên URL (`?status=closed` — mặc định ca mở; Q-fe-N6). Không thấy mà server còn trang → KHÔNG
// khẳng định đã đóng, cho "Tải thêm". Hội thoại: `GET /api/tickets/{id}` thật (ticket:read:any), chỉ đọc. Ca mở: form đóng
// (CloseForm). Ca đã đóng: chỉ đọc (kết quả, ghi chú, người đóng, lúc đóng).

const BACK = (
  <Link to="/escalations" className="text-secondary text-fpt-blue">
    ‹ Hàng chờ chuyển L2
  </Link>
);

/** Route `/escalations/:escalationId` — `key` theo id + trạng thái để form đóng không mang nháp sang ca khác. */
type Submit = (id: number, body: EscalationCloseIn) => Promise<void>;

/** `closeAvailable` / `submit`: chỉ test truyền (mặc định `CLOSE_AVAILABLE` + `closeEscalation`). */
export function EscalationDetailRoute({ closeAvailable, submit }: { closeAvailable?: boolean; submit?: Submit }) {
  const { escalationId = "" } = useParams();
  const [params] = useSearchParams();
  const status: EscalationQueueStatus = params.get("status") === "closed" ? "closed" : "open";
  return <EscalationDetail key={`${escalationId}|${status}`} escalationId={escalationId} status={status} closeAvailable={closeAvailable} submit={submit} />;
}

function EscalationDetail({
  escalationId,
  status,
  closeAvailable,
  submit,
}: {
  escalationId: string;
  status: EscalationQueueStatus;
  closeAvailable?: boolean;
  submit?: Submit;
}) {
  const id = /^\d{1,15}$/.test(escalationId) ? Number(escalationId) : null;
  const query = useInfiniteQuery(queueQuery(status));
  const items = loadedItems(query.data);
  const found = id === null ? undefined : items?.find((i) => i.escalation_id === id);
  // Đóng xong: ca rời danh sách Mở (tải lại) — màn giữ bản chụp ca để còn hiện câu báo, không nhảy sang "không còn".
  const [closedSnap, setClosedSnap] = useState<{ item: QueueItem; result: EscalationCloseResult } | null>(null);
  const loadingMore = useRef(false);

  if (closedSnap) {
    return <Detail item={closedSnap.item} now={query.dataUpdatedAt} closeAvailable={closeAvailable} justClosed closedWith={closedSnap.result} />;
  }
  if (query.isPending && id !== null) return <p className="px-12 py-10 text-ink-2">Đang tải ca…</p>;
  if (id !== null && items === undefined) {
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
  if (!found) {
    const more = id !== null && hasMore(query.data);
    const busy = query.isFetching;
    return (
      <section className="flex flex-col gap-2 px-12 py-10">
        {BACK}
        <h1 className="text-heading">{more ? notLoadedText(items?.length ?? 0) : status === "closed" ? CLOSED_GONE_TEXT : GONE_TEXT}</h1>
        <p className="text-ink-2">{more ? NOT_LOADED_NOTE : "Mở lại hàng đợi để xem các ca."}</p>
        {more ? (
          <button
            type="button"
            data-testid="detail-more"
            aria-disabled={busy ? true : undefined}
            onClick={() => {
              if (busy || loadingMore.current) return;
              loadingMore.current = true;
              void query.fetchNextPage({ cancelRefetch: false }).finally(() => {
                loadingMore.current = false;
              });
            }}
            className={`h-9 self-start rounded-full bg-button-2 px-5 text-secondary font-semibold text-fpt-blue ${busy ? "cursor-wait opacity-60" : ""}`}
          >
            {busy ? "Đang tải…" : "Tải thêm"}
          </button>
        ) : null}
      </section>
    );
  }
  return <Detail item={found} now={query.dataUpdatedAt} closeAvailable={closeAvailable} submit={submit} onClosed={(result) => setClosedSnap({ item: found, result })} />;
}

function Detail({
  item,
  now,
  closeAvailable,
  submit,
  onClosed,
  justClosed = false,
  closedWith = null,
}: {
  item: QueueItem;
  now: number;
  closeAvailable?: boolean;
  submit?: Submit;
  onClosed?: (result: EscalationCloseResult) => void;
  justClosed?: boolean;
  /** Kết quả vừa đóng: "Mở ticket mới" → `REOPENED_TEXT` (hợp đồng sửa lần 3 — KHÔNG mã / link ticket mới); khác → `CLOSED_TEXT`. */
  closedWith?: EscalationCloseResult | null;
}) {
  const closed = typeof item.closed_at === "string";
  return (
    <section className="flex flex-col gap-6 px-12 pt-6 pb-8">
      <div className="flex flex-col gap-1">
        {/* Hàng nút quay lại ngang hàng nút "Nhật ký quyết định" (nổi ở góc phải). */}
        <div className="flex h-9 items-center">{BACK}</div>
        <div className="flex items-center gap-4">
          <h1 data-testid="detail-exit" className="min-w-0 grow text-title">
            <NhanMa {...exitNhan(item)} />
          </h1>
          <span className="shrink-0 text-secondary text-ink-2">{closed ? "Đã đóng" : waitingText(item.created_at, now)}</span>
        </div>
        <p className="text-label font-normal text-ink-2">
          Mã yêu cầu{" "}
          <span className="font-mono select-all" data-testid="ticket-id">
            {item.ticket_id}
          </span>{" "}
          · <span data-testid="ca-so">{caSo(item.escalation_id)}</span>
          {item.reason_detail ? (
            <>
              {" "}
              · Lý do <MaNhan loai="ly_do" ma={item.reason_detail} />
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
        {/* Cột phải đứng yên khi cuộn hội thoại dài: hộp đóng ca luôn trong tầm tay. */}
        <div className="self-start lg:sticky lg:top-20">
          {justClosed ? (
            <div className="flex flex-col gap-2">
              <p role="status" data-testid="close-done" className="rounded-group bg-group px-4 py-3">
                {closedWith === "reopened_as_new" ? REOPENED_TEXT : CLOSED_TEXT}
              </p>
              <Link to={`/escalations/${item.escalation_id}?status=closed`} className="pl-1 text-secondary text-fpt-blue">
                Xem ca trong danh sách Đã đóng
              </Link>
            </div>
          ) : closed ? (
            <ClosedInfo item={item} />
          ) : (
            <CloseForm item={item} available={closeAvailable} onSubmit={submit} onClosed={onClosed} />
          )}
        </div>
      </div>
    </section>
  );
}

/** Ca đã đóng — chỉ đọc. Ghi chú đóng (`close_note`, khoá tuỳ chọn — Q-fe-N4) thiếu / null → "—". Chữ thô. */
function ClosedInfo({ item }: { item: QueueItem }) {
  const rows: { label: string; text: string; testId: string }[] = [
    { label: "Kết quả", text: item.close_result ? closeResultLabel(item.close_result) : "—", testId: "closed-result" },
    { label: "Ghi chú", text: item.close_note ?? "—", testId: "closed-note" },
    { label: "Người đóng", text: item.closed_by ?? "—", testId: "closed-by" },
    { label: "Lúc đóng", text: item.closed_at ? formatAt(item.closed_at) : "—", testId: "closed-at" },
  ];
  return (
    <section aria-labelledby="closed-heading" data-testid="closed-info" className="flex flex-col gap-2">
      <h2 id="closed-heading" className="pl-1 text-label text-ink-2">
        Ca đã đóng
      </h2>
      <dl className="overflow-hidden rounded-group border border-line text-secondary">
        {rows.map((r) => (
          <div key={r.label} className="grid grid-cols-[110px_minmax(0,1fr)] gap-4 border-t border-line px-5 py-3 first:border-t-0">
            <dt className="text-ink-2">{r.label}</dt>
            <dd data-testid={r.testId} className="min-w-0 break-words whitespace-pre-line">
              {r.text}
            </dd>
          </div>
        ))}
      </dl>
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
