import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { createTicket, TEXT_MAX, withBusyRetry } from "../../api/tickets.ts";
import logoUrl from "../../assets/logo.svg";
import { Composer } from "../../components/Composer.tsx";
import { describeSendError } from "./sendError.ts";
import { sessionTickets } from "./sessionTickets.ts";
import { SUGGESTIONS } from "./suggestions.ts";

function LockHint() {
  return (
    <span className="inline-flex items-center gap-1.5 text-label font-normal text-ink-2">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        <rect x="5" y="11" width="14" height="9" rx="2" />
        <path d="M8 11V8a4 4 0 0 1 8 0v3" />
      </svg>
      Mật khẩu lỡ gõ sẽ được tự động ẩn
    </span>
  );
}

// B4EmpHome: lời chào không tên (12b Q-fe-9), ô nhập lớn 720 px, 4 nút gợi ý nhanh (suggestions.ts). Chip "N yêu cầu đang chờ IT duyệt" của Bản 4
// cần lịch sử từ server (Phase 7) → chưa hiện.
export function ChatHome() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waitNote, setWaitNote] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const caretToEnd = useRef(false);

  // Nút gợi ý (F6 P4): điền câu mẫu → focus ô nhập, con trỏ cuối câu để sửa tiếp. KHÔNG gửi.
  function suggest(sample: string) {
    caretToEnd.current = true;
    setText(sample);
    inputRef.current?.focus();
  }
  useEffect(() => {
    const box = inputRef.current;
    if (!caretToEnd.current || !box) return;
    caretToEnd.current = false;
    box.setSelectionRange(box.value.length, box.value.length);
  }, [text]);

  async function submit() {
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    setFieldError(null);
    setError(null);
    try {
      const accepted = await withBusyRetry(
        () => createTicket(value),
        (seconds) => setWaitNote(`Hệ thống đang bận — tự thử lại sau ${seconds} giây…`),
      );
      sessionTickets.add(accepted.ticket_id, value, accepted.notices);
      navigate(`/chat/${encodeURIComponent(accepted.ticket_id)}`, { state: { notices: accepted.notices } });
    } catch (e) {
      const view = describeSendError(e);
      setFieldError(view.field);
      setError(view.message);
    } finally {
      setBusy(false);
      setWaitNote(null);
    }
  }

  return (
    <section className="flex min-h-full flex-col items-center justify-center px-6 pt-10 pb-16">
      <div className="flex w-full max-w-(--chat-width) flex-col items-center">
        <img src={logoUrl} alt="" width={48} height={48} className="size-12" />
        <h1 className="mt-6 text-center text-title">Hôm nay IT giúp gì cho bạn?</h1>
        <p className="mt-2 text-center text-ink-2">Mô tả vấn đề bằng lời thường — trợ lý sẽ hướng dẫn, hoặc chuyển IT khi cần.</p>
        <div className="mt-8 w-full">
          <Composer
            variant="home"
            label="Mô tả vấn đề"
            placeholder="Mô tả vấn đề như đang nhắn cho đồng nghiệp…"
            value={text}
            onChange={setText}
            onSubmit={() => void submit()}
            maxLength={TEXT_MAX}
            busy={busy}
            error={fieldError}
            hint={<LockHint />}
            autoFocus
            inputRef={inputRef}
          />
        </div>
        {waitNote || error ? (
          <p role={error ? "alert" : "status"} className={`mt-3 text-secondary ${error ? "text-danger" : "text-ink-2"}`}>
            {error ?? waitNote}
          </p>
        ) : null}
        <div className="mt-6 grid w-full gap-3 sm:grid-cols-2">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion.label}
              type="button"
              aria-label={suggestion.label}
              onClick={() => suggest(suggestion.text)}
              className="flex min-w-0 flex-col rounded-group border border-line bg-white px-4 py-3 text-left hover:border-fpt-blue/40 hover:bg-group focus-visible:outline-2 focus-visible:outline-fpt-blue"
            >
              <span className="flex min-w-0 flex-col">
                <span className="text-secondary font-semibold">{suggestion.label}</span>
                <span className="truncate text-label font-normal text-ink-2">{suggestion.text}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
