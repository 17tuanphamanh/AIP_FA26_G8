import { useState, type FormEvent } from "react";
import { ApiError, errorMessage } from "../../api/errors.ts";
import { CLOSE_AVAILABLE, CLOSE_NOTE_MAX, closeEscalation } from "../../api/escalations.ts";
import type { EscalationCloseIn, EscalationCloseResult, EscalationQueueItem } from "../../api/types.ts";
import { CLOSE_OPTIONS, closeProblem, completedLock } from "./queue.ts";

type CloseFormProps = {
  item: EscalationQueueItem;
  /** Mặc định: chỉ khi MSW bật (route Phase 7). Tắt → nút gửi khoá, KHÔNG gọi `/close`. */
  available?: boolean;
  onSubmit?: (id: number, body: EscalationCloseIn) => Promise<void>;
};

// Khối "Đóng escalation" của B4L2Detail: 3 kết quả (B20 §4.3) + ghi chú bắt buộc. "Đã hoàn tất" khoá khi `completedLock`
// (ca E5 / E6). Đây là MINH HOẠ tới Phase 7: 202 của MSW không xoá ca khỏi hàng đợi thật. Không có nút duyệt [Chốt 2.2].
export function CloseForm({ item, available = CLOSE_AVAILABLE, onSubmit = closeEscalation }: CloseFormProps) {
  const lock = completedLock(item);
  const [result, setResult] = useState<EscalationCloseResult | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);

  function pick(value: EscalationCloseResult) {
    if (value === "completed" && lock !== null) return; // khoá: không chọn được, kể cả bằng bàn phím
    setResult(value);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!available || sending || done) return;
    const problem = closeProblem(result, note, lock);
    if (problem !== null || result === null) {
      setError(problem);
      return;
    }
    setSending(true);
    setError(null);
    try {
      await onSubmit(item.escalation_id, { close_result: result, note: note.trim() });
      setDone(true);
    } catch (e) {
      // Giữ nguyên lựa chọn + ghi chú để sửa rồi gửi lại.
      setError(errorMessage(e instanceof ApiError ? e : null));
    } finally {
      setSending(false);
    }
  }

  const noteMissing = error !== null && !note.trim();
  return (
    <form onSubmit={(e) => void submit(e)} aria-labelledby="close-heading" className="flex flex-col gap-2" noValidate>
      <h2 id="close-heading" className="pl-1 text-label text-ink-2">
        Đóng escalation
      </h2>
      {available ? (
        <p className="pl-1 text-label font-normal text-orange-ink">Minh hoạ — chưa ghi vào hệ thống (đóng ca thật có ở Phase 7).</p>
      ) : null}
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
        }}
        placeholder="Ghi chú đóng (bắt buộc)"
        aria-invalid={noteMissing || undefined}
        disabled={done}
        className="mt-2 resize-none rounded-group border border-line px-5 py-3 disabled:bg-group"
      />
      <span className="self-end text-label font-normal text-ink-2">
        {note.trim().length}/{CLOSE_NOTE_MAX}
      </span>

      {error ? (
        <p role="alert" className="text-secondary text-danger">
          {error}
        </p>
      ) : null}
      {done ? (
        <p role="status" className="rounded-group bg-orange-bg px-4 py-3 text-orange-ink">
          Đã ghi nhận (minh hoạ)
          <span className="block text-label font-normal">Ca vẫn nằm trong hàng đợi — đóng ca thật có ở Phase 7.</span>
        </p>
      ) : null}

      <button
        type="submit"
        disabled={!available || sending || done}
        className="mt-2 h-11 rounded-full bg-fpt-blue font-semibold text-white disabled:opacity-60"
      >
        {sending ? "Đang gửi…" : "Đóng escalation"}
      </button>
      {!available ? (
        <p className="text-secondary text-ink-2" data-testid="close-unavailable">
          Đóng ca có ở Phase 7
        </p>
      ) : null}
    </form>
  );
}
