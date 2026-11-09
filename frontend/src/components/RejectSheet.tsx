import { type FormEvent, useState } from "react";
import { NOTE_MAX } from "../api/approvals.ts";
import type { ReasonCode } from "../api/types.ts";
import { REJECT_REASONS, rejectProblem } from "../routes/l1/inbox.ts";
import { Modal } from "./Modal.tsx";

type RejectSheetProps = {
  sending: boolean;
  /** Lỗi từ server (409, 422…) — hiện trong sheet, giữ nguyên lựa chọn + ghi chú. */
  serverError: string | null;
  onCancel: () => void;
  onSubmit: (reason: ReasonCode, note: string) => void;
};

// Sheet từ chối (B4L1Detail): 1 trong 7 `reason_code` + ghi chú BẮT BUỘC (backend 422 `rejected_requires_note`).
// Thiếu một trong hai → không gửi. Ghi chú hiển thị cho người gửi (sau khi qua privacy guard).
export function RejectSheet({ sending, serverError, onCancel, onSubmit }: RejectSheetProps) {
  const [reason, setReason] = useState<ReasonCode | null>(null);
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (sending) return;
    const found = rejectProblem(reason, note);
    setProblem(found);
    if (found !== null || reason === null) return;
    onSubmit(reason, note);
  }

  // L1 (soát 01/11): lỗi nhập báo ĐÚNG ô (viền đỏ + câu ngay dưới); lỗi của server vẫn ở cuối hộp.
  const reasonBad = problem !== null && reason === null;
  const noteBad = problem !== null && reason !== null;
  return (
    <Modal label="Từ chối yêu cầu" onClose={sending ? undefined : onCancel}>
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <h2 className="text-center text-heading">Từ chối yêu cầu</h2>
        <div className={`overflow-hidden rounded-xl bg-group ${problem !== null ? "ring-1 ring-danger" : ""}`}>
          <label
            htmlFor="reject-reason"
            className={`flex items-center justify-between gap-4 border-b border-line px-4 py-3 ${reasonBad ? "bg-danger-bg" : ""}`}
          >
            Lý do
            <select
              id="reject-reason"
              value={reason ?? ""}
              onChange={(e) => {
                setReason(e.target.value ? (e.target.value as ReasonCode) : null);
                setProblem(null);
              }}
              aria-invalid={reasonBad || undefined}
              aria-describedby={reasonBad ? "reject-field-error" : undefined}
              className="min-w-0 bg-transparent text-right text-ink-2 max-lg:min-h-11"
            >
              <option value="">Chọn lý do…</option>
              {REJECT_REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor="reject-note" className="sr-only">
            Lý do gửi người dùng
          </label>
          <textarea
            id="reject-note"
            rows={4}
            maxLength={NOTE_MAX}
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
              setProblem(null);
            }}
            placeholder="Lý do gửi người dùng (bắt buộc)"
            aria-invalid={noteBad || undefined}
            aria-describedby={noteBad ? "reject-field-error" : undefined}
            autoFocus
            className={`block w-full resize-none px-4 py-3 ${noteBad ? "bg-danger-bg" : "bg-transparent"}`}
          />
        </div>
        {problem !== null ? (
          <p id="reject-field-error" role="alert" className="-mt-2 px-1 text-secondary text-danger">
            {problem}
          </p>
        ) : null}
        <span className="text-center text-label font-normal text-ink-2">
          Lý do hiển thị cho người gửi (thông tin nhạy cảm được ẩn tự động) · {note.trim().length}/{NOTE_MAX}
        </span>
        {problem === null && serverError ? (
          <p role="alert" className="text-secondary text-danger">
            {serverError}
          </p>
        ) : null}
        <div className="grid grid-cols-2 gap-3">
          <button type="button" onClick={onCancel} disabled={sending} className="h-11 rounded-full bg-button-2 font-semibold disabled:opacity-60">
            Huỷ
          </button>
          <button type="submit" disabled={sending} className="h-11 rounded-full bg-danger font-semibold text-white disabled:opacity-60">
            {sending ? "Đang gửi…" : "Gửi từ chối"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
