import { type FormEvent, useState } from "react";
import { NOTE_MAX, overrideTicket } from "../api/approvals.ts";
import type { OverrideDecision, OverrideIn, OverrideReasonCode, OverrideRecorded } from "../api/types.ts";
import {
  NOTICES_TEXT,
  OVERRIDE_DONE,
  OVERRIDE_OPTIONS,
  OVERRIDE_ORIGINAL_PREFIX,
  OVERRIDE_REASONS,
  overrideBody,
  overrideDecisionLabel,
  overrideFailure,
  overrideProblem,
} from "../routes/l1/inbox.ts";
import { Modal } from "./Modal.tsx";
import { useReauthRetry } from "./useReauthRetry.tsx";

type OverrideDialogProps = {
  ticketId: string;
  onClose: () => void;
  /** Mặc định: `POST /api/tickets/{id}/override` THẬT qua client dùng chung (4d `e510a6e`; dev:mock chỉ giả id minh hoạ).
   *  `null` = đã ghi nhưng không đọc được chi tiết. */
  submit?: (ticketId: string, body: OverrideIn) => Promise<OverrideRecorded | null>;
};

const NOTE_ERROR_ID = "override-note-error";
const FIELD_ERROR_ID = "override-field-error";

/** Câu lỗi ngay dưới ô (L1). */
function FieldError({ text }: { text: string }) {
  return (
    <p id={FIELD_ERROR_ID} role="alert" className="-mt-2 px-1 text-secondary text-danger">
      {text}
    </p>
  );
}

// Hộp "Ghi đè…" (KH 4.6; 4d `e510a6e`): 4 lựa chọn `override_decision` (đủ cả 4 — client không biết quyết định gốc,
// Q-fe-10), 6 `reason_code`, ghi chú bắt buộc khi "Khác". 403 `reauth_required` → hộp đăng nhập lại (Q-fe-4, Q-fe-25)
// qua `useReauthRetry` (Q-fe-30): cùng người → gửi lại ĐÚNG một lần; thất bại / huỷ → không gửi lại; người KHÁC → không
// gửi lại, xoá dữ liệu của người cũ, về trang đầu người mới kèm câu báo huỷ. Ghi đè không đổi ticket — chỉ ghi nhật ký.
// Sau 201 (N4d P3): câu xác nhận + quyết định ban đầu do server suy (khi đọc được) + câu chung nếu ghi chú bị che — không
// hiện nguyên văn `notices`, không nhắc lại ghi chú. 422 vì ghi chú → câu lỗi ngay dưới ô ghi chú, giữ nguyên dữ liệu (P4).
export function OverrideDialog({ ticketId, onClose, submit = overrideTicket }: OverrideDialogProps) {
  const [decision, setDecision] = useState<OverrideDecision | null>(null);
  const [reason, setReason] = useState<OverrideReasonCode | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<{ text: string; field: "decision" | "reason" | "note" | null } | null>(null);
  const [done, setDone] = useState<{ original: string | null; redacted: boolean } | null>(null);
  const retry = useReauthRetry({
    send: (body: OverrideIn) => submit(ticketId, body),
    // Đã 2xx = đã ghi: không đọc được chi tiết (null) thì chỉ hiện câu xác nhận — không bao giờ ném ở đây (báo lỗi giả).
    onSuccess: (recorded: OverrideRecorded | null) =>
      setDone({
        original: recorded ? overrideDecisionLabel(recorded.original_decision) : null,
        redacted: recorded ? recorded.notices.length > 0 : false,
      }),
    onFailure: (e) => setError(overrideFailure(e)),
    onCancelled: () => setError({ text: "Chưa gửi ghi đè — cần đăng nhập lại để xác nhận thao tác này.", field: null }),
    otherUserFlash: "override_other_user",
  });
  const sending = retry.sending;
  const noteError = error?.field === "note";

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (sending || done || retry.busy()) return;
    const problem = overrideProblem(decision, reason, note);
    if (problem !== null || decision === null || reason === null) {
      // L1 (soát 01/11): lỗi nhập báo ĐÚNG ô (viền đỏ + câu ngay dưới), không gom về cuối hộp.
      setError(problem === null ? null : { text: problem, field: decision === null ? "decision" : reason === null ? "reason" : "note" });
      return;
    }
    setError(null);
    retry.run(overrideBody(decision, reason, note));
  }

  if (retry.dialog) return retry.dialog;

  return (
    <Modal label="Ghi đè quyết định" onClose={sending ? undefined : onClose}>
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <div className="flex flex-col gap-1 text-center">
          <h2 className="text-heading">Ghi đè quyết định</h2>
          <p className="text-secondary text-ink-2">
            Yêu cầu <span className="font-mono">{ticketId}</span> — ghi vào nhật ký để đánh giá lại (không gỡ được), không đổi yêu cầu.
          </p>
        </div>

        <div
          role="radiogroup"
          aria-label="Quyết định đúng"
          aria-invalid={error?.field === "decision" || undefined}
          aria-describedby={error?.field === "decision" ? FIELD_ERROR_ID : undefined}
          className={`overflow-hidden rounded-group border ${error?.field === "decision" ? "border-danger" : "border-line"}`}
        >
          {OVERRIDE_OPTIONS.map((option) => {
            const on = decision === option.value;
            return (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={on}
                data-value={option.value}
                disabled={done !== null}
                onClick={() => {
                  setDecision(option.value);
                  setError(null);
                }}
                className="flex w-full items-center gap-3 border-t border-line bg-white px-4 py-2.5 text-left first:border-t-0 hover:bg-group"
              >
                <span className="flex min-w-0 grow flex-col">
                  <span>{option.title}</span>
                  <span className="text-label font-normal text-ink-2">{option.desc}</span>
                </span>
                <span className={`shrink-0 font-semibold text-fpt-blue ${on ? "visible" : "invisible"}`} aria-hidden="true">
                  ✓
                </span>
              </button>
            );
          })}
        </div>
        {error?.field === "decision" ? <FieldError text={error.text} /> : null}

        <div className={`overflow-hidden rounded-xl bg-group ${error?.field === "reason" || noteError ? "ring-1 ring-danger" : ""}`}>
          <label
            htmlFor="override-reason"
            className={`flex items-center justify-between gap-4 border-b border-line px-4 py-3 ${error?.field === "reason" ? "bg-danger-bg" : ""}`}
          >
            Lý do
            <select
              id="override-reason"
              value={reason ?? ""}
              disabled={done !== null}
              onChange={(e) => {
                setReason(e.target.value ? (e.target.value as OverrideReasonCode) : null);
                setError(null);
              }}
              aria-invalid={error?.field === "reason" || undefined}
              aria-describedby={error?.field === "reason" ? FIELD_ERROR_ID : undefined}
              className="min-w-0 bg-transparent text-right text-ink-2"
            >
              <option value="">Chọn lý do…</option>
              {OVERRIDE_REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor="override-note" className="sr-only">
            Ghi chú ghi đè
          </label>
          <textarea
            id="override-note"
            rows={3}
            maxLength={NOTE_MAX}
            value={note}
            disabled={done !== null}
            aria-invalid={noteError || undefined}
            aria-describedby={noteError ? NOTE_ERROR_ID : undefined}
            onChange={(e) => {
              setNote(e.target.value);
              setError(null);
            }}
            placeholder={reason === "other" ? "Ghi chú (bắt buộc khi chọn “Khác”)" : "Ghi chú (không bắt buộc)"}
            className={`block w-full resize-none px-4 py-3 ${noteError ? "bg-danger-bg" : "bg-transparent"}`}
          />
        </div>
        {error?.field === "reason" ? <FieldError text={error.text} /> : null}
        {error && noteError ? (
          <p id={NOTE_ERROR_ID} role="alert" data-testid="override-note-error" className="-mt-2 px-1 text-secondary text-danger">
            {error.text}
          </p>
        ) : null}
        <span className="text-center text-label font-normal text-ink-2">
          {note.trim().length}/{NOTE_MAX}
        </span>

        {error && error.field === null ? (
          <p role="alert" className="text-secondary text-danger">
            {error.text}
          </p>
        ) : null}
        {done ? (
          <div role="status" data-testid="override-done" className="flex flex-col gap-1 rounded-group bg-group px-4 py-3 text-center">
            <p>{OVERRIDE_DONE}</p>
            {done.original ? (
              <p data-testid="override-original" className="text-secondary text-ink-2">
                {OVERRIDE_ORIGINAL_PREFIX}
                {done.original}
              </p>
            ) : null}
            {done.redacted ? (
              <p data-testid="override-notices" className="text-secondary text-ink-2">
                {NOTICES_TEXT}
              </p>
            ) : null}
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-3">
          <button type="button" onClick={onClose} disabled={sending} className="h-11 rounded-full bg-button-2 font-semibold disabled:opacity-60">
            {done ? "Đóng" : "Huỷ"}
          </button>
          <button type="submit" disabled={sending || done !== null} className="h-11 rounded-full bg-fpt-blue font-semibold text-white disabled:opacity-60">
            {sending ? "Đang gửi…" : "Gửi ghi đè"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
