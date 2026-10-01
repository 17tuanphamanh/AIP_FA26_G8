import { type FormEvent, useState } from "react";
import { NOTE_MAX, overrideTicket } from "../api/approvals.ts";
import type { OverrideDecision, OverrideIn, OverrideReasonCode } from "../api/types.ts";
import { MOCK_ENABLED } from "../mocks/flag.ts";
import { OVERRIDE_OPTIONS, OVERRIDE_REASONS, overrideBody, overrideErrorMessage, overrideProblem } from "../routes/l1/inbox.ts";
import { Modal } from "./Modal.tsx";
import { useReauthRetry } from "./useReauthRetry.tsx";

type OverrideDialogProps = {
  ticketId: string;
  onClose: () => void;
  /** Mặc định: `POST /api/tickets/{id}/override` qua client dùng chung (4d; MSW bật → handler giả). */
  submit?: (ticketId: string, body: OverrideIn) => Promise<void>;
};

// Hộp "Ghi đè…" (KH 4.6; 4d P1–P4): 4 lựa chọn `override_decision` (đủ cả 4 — client không biết quyết định gốc,
// Q-fe-10), 6 `reason_code`, ghi chú bắt buộc khi "Khác". 403 `reauth_required` → hộp đăng nhập lại (Q-fe-4, Q-fe-25)
// qua `useReauthRetry` (Q-fe-30): cùng người → gửi lại ĐÚNG một lần; thất bại / huỷ → không gửi lại; người KHÁC → không
// gửi lại, xoá dữ liệu của người cũ, về trang đầu người mới kèm câu báo huỷ. Ghi đè không đổi ticket — chỉ ghi nhật ký
// (4d P4).
export function OverrideDialog({ ticketId, onClose, submit = overrideTicket }: OverrideDialogProps) {
  const [decision, setDecision] = useState<OverrideDecision | null>(null);
  const [reason, setReason] = useState<OverrideReasonCode | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const retry = useReauthRetry({
    send: (body: OverrideIn) => submit(ticketId, body),
    onSuccess: () => setDone(true),
    onFailure: (e) => setError(overrideErrorMessage(e)),
    onCancelled: () => setError("Chưa gửi ghi đè — cần đăng nhập lại để xác nhận thao tác này."),
    otherUserFlash: "override_other_user",
  });
  const sending = retry.sending;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (sending || done || retry.busy()) return;
    const problem = overrideProblem(decision, reason, note);
    if (problem !== null || decision === null || reason === null) {
      setError(problem);
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
            Ticket <span className="font-mono">{ticketId}</span> — ghi vào nhật ký để đánh giá lại, không đổi ticket.
          </p>
          {MOCK_ENABLED ? (
            <p className="text-label font-normal text-orange-ink">Minh hoạ — ghi đè thật có từ Phase 4 (4d).</p>
          ) : null}
        </div>

        <div role="radiogroup" aria-label="Quyết định đúng" className="overflow-hidden rounded-group border border-line">
          {OVERRIDE_OPTIONS.map((option) => {
            const on = decision === option.value;
            return (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={on}
                data-value={option.value}
                disabled={done}
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

        <div className="overflow-hidden rounded-xl bg-group">
          <label htmlFor="override-reason" className="flex items-center justify-between gap-4 border-b border-line px-4 py-3">
            Lý do
            <select
              id="override-reason"
              value={reason ?? ""}
              disabled={done}
              onChange={(e) => {
                setReason(e.target.value ? (e.target.value as OverrideReasonCode) : null);
                setError(null);
              }}
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
            disabled={done}
            onChange={(e) => {
              setNote(e.target.value);
              setError(null);
            }}
            placeholder={reason === "other" ? "Ghi chú (bắt buộc khi chọn “Khác”)" : "Ghi chú (không bắt buộc)"}
            className="block w-full resize-none bg-transparent px-4 py-3"
          />
        </div>
        <span className="text-center text-label font-normal text-ink-2">
          {note.trim().length}/{NOTE_MAX}
        </span>

        {error ? (
          <p role="alert" className="text-secondary text-danger">
            {error}
          </p>
        ) : null}
        {done ? (
          <p role="status" className="rounded-group bg-group px-4 py-3 text-center">
            Đã ghi nhận ghi đè{MOCK_ENABLED ? " (minh hoạ)" : ""}.
          </p>
        ) : null}

        <div className="grid grid-cols-2 gap-3">
          <button type="button" onClick={onClose} disabled={sending} className="h-11 rounded-full bg-button-2 font-semibold disabled:opacity-60">
            {done ? "Đóng" : "Huỷ"}
          </button>
          <button type="submit" disabled={sending || done} className="h-11 rounded-full bg-fpt-blue font-semibold text-white disabled:opacity-60">
            {sending ? "Đang gửi…" : "Gửi ghi đè"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
