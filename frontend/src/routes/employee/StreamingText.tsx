import logoUrl from "../../assets/logo.svg";
import type { StreamMessage } from "../../api/events.ts";
import { AVATAR_CLASS } from "../../components/avatar.ts";
import { displayText } from "./useTicketStream.ts";

// Chữ chạy của tin trả lời (sự kiện `token`). Khi `message_end` + tin chính thức đã về, ChatPage bỏ khối này (reconcile) — không trùng.
// Giảm chuyển động (`prefers-reduced-motion: reduce`): KHÔNG chạy chữ — chỉ hiện câu "Đang soạn câu trả lời…" tĩnh rồi hiện cả tin một
// lần khi `message_end`.

const COMPOSING = "Đang soạn câu trả lời…";

export function StreamingText({ message, reducedMotion }: { message: StreamMessage; reducedMotion: boolean }) {
  const shown = displayText(message.text);
  const hold = reducedMotion && !message.ended; // chưa xong mà không được chạy chữ → chỉ báo đang soạn
  return (
    <div className="flex items-start gap-3" data-testid="streaming-message" data-kind={message.kind} data-ended={message.ended}>
      <img src={logoUrl} alt="" width={28} height={28} className={AVATAR_CLASS} />
      <div className="flex min-w-0 grow flex-col gap-3 pt-0.5">
        {hold ? (
          <p className="text-ink-2" role="status">
            {COMPOSING}
          </p>
        ) : (
          <p className="whitespace-pre-line">
            {shown}
            {message.ended || reducedMotion ? null : (
              <span aria-hidden="true" data-testid="stream-caret" className="ml-0.5 inline-block w-1.5 animate-pulse bg-ink-2">
                &nbsp;
              </span>
            )}
          </p>
        )}
      </div>
    </div>
  );
}
