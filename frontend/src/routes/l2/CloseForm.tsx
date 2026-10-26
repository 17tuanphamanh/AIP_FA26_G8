import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { ApiError, errorMessage } from "../../api/errors.ts";
import { CLOSE_AVAILABLE, CLOSE_NOTE_MAX, closeEscalation, type CloseResult } from "../../api/escalations.ts";
import type { EscalationCloseIn, EscalationCloseResult, EscalationQueueItem } from "../../api/types.ts";
import { ALREADY_CLOSED_TEXT, CLOSE_OPTIONS, CLOSE_UNAVAILABLE_TEXT, closeProblem, completedLock } from "./queue.ts";

type CloseFormProps = {
  item: EscalationQueueItem;
  /** Mặc định `CLOSE_AVAILABLE` (api/escalations.ts — một hằng một chỗ). Tắt → nút gửi khoá, KHÔNG gọi `/close`. */
  available?: boolean;
  onSubmit?: (id: number, body: EscalationCloseIn) => Promise<CloseResult | void>;
  /** 200: ca đã đóng (màn chi tiết giữ bản chụp ca + câu báo; `newTicketId` chỉ khi "Mở ticket mới" và server trả mã). */
  onClosed?: (newTicketId: string | null) => void;
};

// Khối "Đóng escalation" của B4L2Detail (hợp đồng N-PA §4): 3 kết quả (enum B20 §4.3) + ghi chú bắt buộc 1–1000 ký tự.
// "Đã hoàn tất" khoá khi `completedLock` (ca E5 / E6). 200 → ca rời danh sách Mở (tải lại hàng đợi); 409 `already_closed` →
// "Ca đã được đóng" + tải lại; 422 → lỗi đúng chỗ (nhóm kết quả / ô ghi chú). Câu lỗi KHÔNG nhắc lại ghi chú đã gõ. Không có
// nút duyệt [Chốt 2.2].
export function CloseForm({ item, available = CLOSE_AVAILABLE, onSubmit = closeEscalation, onClosed }: CloseFormProps) {
  const queryClient = useQueryClient();
  const lock = completedLock(item);
  const [result, setResult] = useState<EscalationCloseResult | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [choiceError, setChoiceError] = useState<string | null>(null);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const inFlight = useRef(false);

  const reloadQueue = () => void queryClient.invalidateQueries({ queryKey: ["escalations", "queue"] });

  function pick(value: EscalationCloseResult) {
    if (value === "completed" && lock !== null) return; // khoá: không chọn được, kể cả bằng bàn phím
    setResult(value);
    setError(null);
    setChoiceError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!available || inFlight.current) return;
    const problem = closeProblem(result, note, lock);
    if (problem !== null || result === null) {
      setError(problem);
      return;
    }
    inFlight.current = true;
    setSending(true);
    setError(null);
    setChoiceError(null);
    setNoteError(null);
    try {
      const done = await onSubmit(item.escalation_id, { close_result: result, note: note.trim() });
      reloadQueue();
      onClosed?.(result === "reopened_as_new" && done ? done.new_ticket_id : null);
    } catch (e) {
      // Giữ nguyên lựa chọn + ghi chú để sửa rồi gửi lại.
      const api = e instanceof ApiError ? e : null;
      if (api?.status === 409 && api.code === "already_closed") {
        setError(ALREADY_CLOSED_TEXT);
        reloadQueue();
      } else if (api?.status === 422 && (api.code === "deny_case_cannot_complete" || api.fields.includes("close_result"))) {
        setChoiceError(api.code === "deny_case_cannot_complete" ? errorMessage(api) : "Kết quả đóng này không dùng được cho ca này.");
      } else if (api?.status === 422 && api.fields.includes("note")) {
        setNoteError(`Ghi chú đóng chưa hợp lệ — cần 1–${CLOSE_NOTE_MAX} ký tự.`);
      } else {
        setError(errorMessage(api));
      }
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  }

  const noteMissing = (error !== null && !note.trim()) || noteError !== null;
  return (
    <form onSubmit={(e) => void submit(e)} aria-labelledby="close-heading" className="flex flex-col gap-2" noValidate>
      <h2 id="close-heading" className="pl-1 text-label text-ink-2">
        Đóng escalation
      </h2>
      <div role="radiogroup" aria-label="Kết quả đóng" className="overflow-hidden rounded-group border border-line">
        {CLOSE_OPTIONS.map((option) => {
          const locked = option.value === "completed" && lock !== null;
          const on = result === option.value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={on}
              aria-disabled={locked ? true : undefined}
              data-value={option.value}
              onClick={() => pick(option.value)}
              className={`flex w-full items-center gap-3 border-t border-line px-5 py-3 text-left first:border-t-0 focus-visible:outline-2 focus-visible:outline-fpt-blue ${
                locked ? "cursor-not-allowed bg-group" : "bg-white hover:bg-group"
              }`}
            >
              <span className="flex min-w-0 grow flex-col">
                <span className={locked ? "text-ink-2" : ""}>{option.title}</span>
                <span className="text-label font-normal text-ink-2">{locked ? lock : option.desc}</span>
              </span>
              {locked ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="shrink-0 stroke-ink-2" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                  <rect x="5" y="11" width="14" height="9" rx="2" />
                  <path d="M8 11V8a4 4 0 0 1 8 0v3" />
                </svg>
              ) : (
                <span className={`shrink-0 font-semibold text-fpt-blue ${on ? "visible" : "invisible"}`} aria-hidden="true">
                  ✓
                </span>
              )}
            </button>
          );
        })}
      </div>
      {choiceError ? (
        <p role="alert" data-testid="close-choice-error" className="text-secondary text-danger">
          {choiceError}
        </p>
      ) : null}

      <label htmlFor="close-note" className="sr-only">
        Ghi chú đóng
      </label>
      <textarea
        id="close-note"
        rows={4}
        maxLength={CLOSE_NOTE_MAX}
        value={note}
        onChange={(e) => {
          setNote(e.target.value);
          setError(null);
          setNoteError(null);
        }}
        placeholder="Ghi chú đóng (bắt buộc)"
        aria-invalid={noteMissing || undefined}
        className="mt-2 resize-none rounded-group border border-line px-5 py-3"
      />
      <span className="self-end text-label font-normal text-ink-2">
        {note.trim().length}/{CLOSE_NOTE_MAX}
      </span>
      {noteError ? (
        <p role="alert" data-testid="close-note-error" className="text-secondary text-danger">
          {noteError}
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="text-secondary text-danger">
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={!available || sending}
        className="mt-2 h-11 rounded-full bg-fpt-blue font-semibold text-white disabled:opacity-60"
      >
        {sending ? "Đang gửi…" : "Đóng escalation"}
      </button>
      {!available ? (
        <p className="text-secondary text-ink-2" data-testid="close-unavailable">
          {CLOSE_UNAVAILABLE_TEXT}
        </p>
      ) : null}
    </form>
  );
}
