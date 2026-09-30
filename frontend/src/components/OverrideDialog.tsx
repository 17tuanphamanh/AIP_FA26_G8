import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { NOTE_MAX, overrideTicket } from "../api/approvals.ts";
import { ApiError } from "../api/errors.ts";
import type { OverrideDecision, OverrideIn, OverrideReasonCode } from "../api/types.ts";
import { homePath } from "../auth/permissions.ts";
import { useMe } from "../auth/useAuth.ts";
import { MOCK_ENABLED } from "../mocks/flag.ts";
import { OVERRIDE_OPTIONS, OVERRIDE_REASONS, overrideBody, overrideErrorMessage, overrideProblem } from "../routes/l1/inbox.ts";
import { sessionTickets } from "../routes/employee/sessionTickets.ts";
import { flashState } from "./flash.ts";
import { Modal } from "./Modal.tsx";
import { ReauthDialog, type ReauthOutcome } from "./ReauthDialog.tsx";

type OverrideDialogProps = {
  ticketId: string;
  onClose: () => void;
  /** Mặc định: `POST /api/tickets/{id}/override` qua client dùng chung (4d; MSW bật → handler giả). */
  submit?: (ticketId: string, body: OverrideIn) => Promise<void>;
};

const isReauth = (e: unknown) => e instanceof ApiError && e.status === 403 && e.code === "reauth_required";

// Hộp "Ghi đè…" (KH 4.6; 4d P1–P4): 4 lựa chọn `override_decision` (đủ cả 4 — client không biết quyết định gốc,
// Q-fe-10), 6 `reason_code`, ghi chú bắt buộc khi "Khác". 403 `reauth_required` → hộp đăng nhập lại (Q-fe-4, Q-fe-25):
// - `sub` token mới = người cũ → gửi lại ĐÚNG một lần body đang chờ;
// - đăng nhập lại thất bại / huỷ → không gửi lại;
// - người KHÁC → không gửi lại, xoá toàn bộ dữ liệu đã tải của người cũ, về trang đầu của người mới kèm câu báo huỷ.
// Ghi đè không đổi ticket — chỉ ghi nhật ký (4d P4).
export function OverrideDialog({ ticketId, onClose, submit = overrideTicket }: OverrideDialogProps) {
  const me = useMe();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [decision, setDecision] = useState<OverrideDecision | null>(null);
  const [reason, setReason] = useState<OverrideReasonCode | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [reauth, setReauth] = useState(false);
  const inFlight = useRef(false); // chặn bấm 2 lần trong cùng một nhịp (state chưa kịp cập nhật)
  const waiting = useRef<OverrideIn | null>(null); // body chờ gửi lại sau khi đăng nhập lại

  async function send(body: OverrideIn, retry: boolean) {
    if (inFlight.current) return;
    inFlight.current = true;
    setSending(true);
    setError(null);
    try {
      await submit(ticketId, body);
      setDone(true);
    } catch (e) {
      if (isReauth(e) && !retry) {
        waiting.current = body;
        setReauth(true);
      } else {
        setError(overrideErrorMessage(e)); // gửi lại vẫn 403 reauth → báo, KHÔNG lặp
      }
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (sending || done || inFlight.current) return;
    const problem = overrideProblem(decision, reason, note);
    if (problem !== null || decision === null || reason === null) {
      setError(problem);
      return;
    }
    void send(overrideBody(decision, reason, note), false);
  }

  function onReauth(outcome: ReauthOutcome) {
    const body = waiting.current;
    waiting.current = null; // bỏ body chờ trong MỌI trường hợp — chỉ nhánh cùng người mới dùng
    setReauth(false);
    if (outcome.kind === "ok" && body) {
      void send(body, true);
    } else if (outcome.kind === "other_user") {
      // Phiên giờ là người khác (cookie đã bị ghi đè): không để lại dữ liệu nào của người cũ trên màn.
      queryClient.clear();
      sessionTickets.clear();
      void navigate(homePath(outcome.me), { replace: true, state: flashState("override_other_user") });
    } else {
      setError("Chưa gửi ghi đè — cần đăng nhập lại để xác nhận thao tác này.");
    }
  }

  if (reauth) return <ReauthDialog userId={me.user_id} onDone={onReauth} />;

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
