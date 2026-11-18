import { useInfiniteQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, errorMessage } from "../../api/errors.ts";
import { type CloseOutcome, hasMore, loadedItems, queueQuery, type QueueItem, type QueueTier } from "../../api/escalations.ts";
import type { EscalationCloseIn, EscalationCloseResult, EscalationQueueStatus } from "../../api/types.ts";
import { flashState } from "../../components/flash.ts";
import { TicketConversation } from "../../components/TicketConversation.tsx";
import { formatAt } from "../shared/traceText.ts";
import { MaNhan, NhanMa } from "../../components/MaNhan.tsx";
import { caSo } from "../../lib/nhan.ts";
import { CloseForm } from "./CloseForm.tsx";
import { HandlingActions } from "./HandlingActions.tsx";
import {
  CLOSED_GONE_TEXT,
  CLOSED_TEXT,
  REOPENED_NEW_TEXT,
  REOPENED_TEXT,
  closeResultLabel,
  DENY_BANNER,
  exitNhan,
  EMPTY_NOTE,
  GONE_TEXT,
  handoffRows,
  NOT_LOADED_NOTE,
  notLoadedText,
  QUEUE_TITLE,
  queueBase,
  RAISE_DONE_TEXT,
  raiseTargetLabel,
  waitingText,
} from "./queue.ts";

// B4L2Detail. Chưa có `GET /api/escalations/{id}` → ca lấy từ CHÍNH truy vấn hàng đợi (các trang đã tải, cùng cache
// TanStack) theo trạng thái trên URL (`?status=closed` — mặc định ca mở; Q-fe-N6). Không thấy mà server còn trang → KHÔNG
// khẳng định đã đóng, cho "Tải thêm". Hội thoại: `GET /api/tickets/{id}` thật (ticket:read:any), chỉ đọc. Ca mở: form đóng
// (CloseForm). Ca đã đóng: chỉ đọc (kết quả, ghi chú, người đóng, lúc đóng).

function Back({ tier }: { tier: QueueTier }) {
  return (
    <Link to={queueBase(tier)} className="text-secondary text-fpt-blue max-lg:inline-flex max-lg:min-h-11 max-lg:items-center">
      ‹ {QUEUE_TITLE[tier]}
    </Link>
  );
}

/** Route `/escalations/:escalationId` — `key` theo id + trạng thái để form đóng không mang nháp sang ca khác. */
type Submit = (id: number, body: EscalationCloseIn) => Promise<CloseOutcome | void>;

/** `submit`: chỉ test truyền (mặc định `closeEscalation` — route thật). */
export function EscalationDetailRoute({ submit, tier = 2 }: { submit?: Submit; tier?: QueueTier }) {
  const { escalationId = "" } = useParams();
  const [params] = useSearchParams();
  const status: EscalationQueueStatus = params.get("status") === "closed" ? "closed" : "open";
  return <EscalationDetail key={`${tier}|${escalationId}|${status}`} escalationId={escalationId} status={status} submit={submit} tier={tier} />;
}

function EscalationDetail({
  escalationId,
  status,
  submit,
  tier,
}: {
  escalationId: string;
  status: EscalationQueueStatus;
  submit?: Submit;
  tier: QueueTier;
}) {
  const id = /^\d{1,15}$/.test(escalationId) ? Number(escalationId) : null;
  const query = useInfiniteQuery(queueQuery(status, tier));
  const items = loadedItems(query.data);
  const found = id === null ? undefined : items?.find((i) => i.escalation_id === id);
  // Đóng xong: ca rời danh sách Mở (tải lại) — màn giữ bản chụp ca để còn hiện câu báo, không nhảy sang "không còn".
  const [closedSnap, setClosedSnap] = useState<{ item: QueueItem; result: EscalationCloseResult; reopened: boolean } | null>(null);
  const [raisedSnap, setRaisedSnap] = useState<QueueItem | null>(null); // D-99: ca vừa chuyển lên cấp 3 (rời hàng đợi cấp 2)
  const loadingMore = useRef(false);
  const navigate = useNavigate();

  if (closedSnap) {
    return (
      <Detail item={closedSnap.item} now={query.dataUpdatedAt} justClosed closedWith={closedSnap.result} reopened={closedSnap.reopened} tier={tier} />
    );
  }
  if (raisedSnap) {
    return <Detail item={raisedSnap} now={query.dataUpdatedAt} justRaised tier={tier} />;
  }
  if (query.isPending && id !== null) return <p className="px-12 py-10 text-ink-2 motion-safe:animate-pulse max-lg:px-4 max-lg:py-6">Đang tải ca…</p>;
  if (id !== null && items === undefined) {
    return (
      <section className="flex flex-col gap-2 px-12 py-10 max-lg:px-4 max-lg:py-6">
        <Back tier={tier} />
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
      <section className="flex flex-col gap-2 px-12 py-10 max-lg:px-4 max-lg:py-6">
        <Back tier={tier} />
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
            className={`h-9 self-start rounded-full bg-button-2 px-5 text-secondary font-semibold text-fpt-blue max-lg:min-h-11 ${busy ? "cursor-wait opacity-60" : ""}`}
          >
            {busy ? "Đang tải…" : "Tải thêm"}
          </button>
        ) : null}
      </section>
    );
  }
  return (
    <Detail
      item={found}
      now={query.dataUpdatedAt}
      submit={submit}
      tier={tier}
      onClosed={(result, reopened) => setClosedSnap({ item: found, result, reopened })}
      onRaised={() => setRaisedSnap(found)}
      // 409: ca đã đóng ở nơi khác → xem ca ở danh sách Đã đóng (chỉ đọc: kết quả, người đóng, lúc đóng) + câu báo một lần.
      onAlreadyClosed={() =>
        void navigate(`${queueBase(tier)}/${found.escalation_id}?status=closed`, {
          replace: true,
          state: flashState("escalation_already_closed"),
        })
      }
    />
  );
}

function Detail({
  item,
  now,
  submit,
  onClosed,
  onAlreadyClosed,
  justClosed = false,
  closedWith = null,
  reopened = false,
  justRaised = false,
  onRaised,
  tier,
}: {
  item: QueueItem;
  now: number;
  submit?: Submit;
  onClosed?: (result: EscalationCloseResult, reopened: boolean) => void;
  onAlreadyClosed?: () => void;
  justClosed?: boolean;
  justRaised?: boolean;
  onRaised?: () => void;
  tier: QueueTier;
  /** Kết quả vừa đóng: "Mở ticket mới" → `REOPENED_TEXT` (hợp đồng sửa lần 3 — KHÔNG mã / link ticket mới); khác → `CLOSED_TEXT`. */
  closedWith?: EscalationCloseResult | null;
  /** D-100: server đã tạo ticket mới cho `reopened_as_new` (phiên người gửi còn sống) — chỉ cờ, không mã. */
  reopened?: boolean;
}) {
  // Kiểm thử 17/11: vừa đóng xong (`justClosed`) thì bản chụp ca chưa có `closed_at` — đầu trang vẫn ghi "đang xử lý"/thời gian chờ.
  const closed = typeof item.closed_at === "string" || justClosed;
  return (
    <section className="flex flex-col gap-6 px-12 pt-6 pb-8 max-lg:px-4 max-lg:pt-3 max-lg:pb-6">
      <div className="flex flex-col gap-1">
        {/* Hàng nút quay lại ngang hàng nút "Nhật ký quyết định" (nổi ở góc phải). */}
        <div className="flex h-9 items-center max-lg:h-11"><Back tier={tier} /></div>
        <div className="flex items-center gap-4 max-lg:flex-wrap max-lg:gap-y-1">
          <h1 data-testid="detail-exit" className="min-w-0 grow text-title">
            <NhanMa {...exitNhan(item)} />
          </h1>
          <span className="shrink-0 text-secondary text-ink-2">
            {closed ? "Đã đóng" : justRaised ? "Đã chuyển cấp" : waitingText(item.created_at, now)}
          </span>
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
          {/* Kiểm thử 18/11: vừa chuyển lên cấp 3 thì ca đã rời người nhận ở cấp 2 — không còn "… đang xử lý". */}
          {justRaised
            ? " · Đã chuyển lên cấp cao hơn"
            : item.assigned_to
              ? ` · ${item.assigned_to} ${closed ? "đã xử lý" : "đang xử lý"}`
              : ""}
          {item.tier === 3 ? ` · Chuyển lên: ${raiseTargetLabel(item.raise_target)}${item.raised_by ? ` (bởi ${item.raised_by})` : ""}` : ""}
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-5">
          {item.is_deny_case ? (
            <div role="note" data-testid="deny-banner" className="rounded-group bg-danger-bg px-5 py-3.5 text-danger-ink">
              <b className="font-semibold">{DENY_BANNER.strong}</b> {DENY_BANNER.rest}
            </div>
          ) : null}
          {item.tier === 3 && item.raise_note ? (
            <div role="note" data-testid="raise-note-view" className="rounded-group bg-group px-5 py-3.5">
              <b className="font-semibold">Lý do chuyển lên:</b> <span className="whitespace-pre-line">{item.raise_note}</span>
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
                {closedWith === "reopened_as_new" ? (reopened ? REOPENED_NEW_TEXT : REOPENED_TEXT) : CLOSED_TEXT}
              </p>
              <Link to={`${queueBase(tier)}/${item.escalation_id}?status=closed`} className="pl-1 text-secondary text-fpt-blue max-lg:inline-flex max-lg:min-h-11 max-lg:items-center">
                Xem ca trong danh sách Đã đóng
              </Link>
            </div>
          ) : justRaised ? (
            <p role="status" data-testid="raise-done" className="rounded-group bg-group px-4 py-3">
              {RAISE_DONE_TEXT}
            </p>
          ) : closed ? (
            <ClosedInfo item={item} />
          ) : (
            <div className="flex flex-col gap-6">
              <HandlingActions item={item} tier={tier} onRaised={() => onRaised?.()} />
              <CloseForm item={item} onSubmit={submit} onClosed={onClosed} onAlreadyClosed={onAlreadyClosed} />
            </div>
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
    { label: "Lời nhắn người gửi", text: item.user_message ?? "—", testId: "closed-user-message" },
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
          <div key={r.label} className="grid grid-cols-[110px_minmax(0,1fr)] gap-4 border-t border-line px-5 py-3 first:border-t-0 max-lg:grid-cols-1 max-lg:gap-1">
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
            className="grid grid-cols-[140px_minmax(0,1fr)] gap-4 border-t border-line px-5 py-3 first:border-t-0 max-lg:grid-cols-1 max-lg:gap-1"
          >
            <dt className="pt-0.75 text-secondary text-ink-2 max-lg:pt-0">{row.label}</dt>
            <dd className={`min-w-0 break-words whitespace-pre-line ${row.text === null ? "text-ink-2 italic" : ""}`}>
              {row.text ?? EMPTY_NOTE}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
