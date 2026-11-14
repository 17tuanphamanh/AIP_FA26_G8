import logoUrl from "../../assets/logo.svg";
import type { StreamMessage } from "../../api/events.ts";
import { AVATAR_CLASS } from "../../components/avatar.ts";
import { SafeMarkdown } from "../../components/SafeMarkdown.tsx";
import { softClose } from "./softClose.ts";
import { displayText } from "./useTicketStream.ts";

// Chữ chạy của tin trả lời (sự kiện `token`). Khi `message_end` + tin chính thức đã về, ChatPage bỏ khối này (reconcile) — không trùng.
// Giảm chuyển động (`prefers-reduced-motion: reduce`): KHÔNG chạy chữ — chỉ hiện câu "Đang soạn câu trả lời…" tĩnh rồi hiện cả tin một
// lần khi `message_end`.
// TA 14/11 ("thô kệch"): tin `answer` dựng Markdown NGAY khi đang chạy (cùng bộ lọc SafeMarkdown với tin chính thức) — không còn hiện
// ký hiệu thô `**` rồi nhảy định dạng lúc đổi sang tin chính thức; con trỏ mảnh nhấp nháy êm đứng sau chữ cuối (tokens.css).
// `bare`: nằm trong khối lượt trả lời đã có ảnh đại diện (ChatPage) → không vẽ ảnh lần nữa.

const COMPOSING = "Đang soạn câu trả lời…";

export function StreamingText({ message, reducedMotion, bare = false }: { message: StreamMessage; reducedMotion: boolean; bare?: boolean }) {
  const shown = displayText(message.text);
  const hold = reducedMotion && !message.ended; // chưa xong mà không được chạy chữ → chỉ báo đang soạn
  const caret = message.ended || reducedMotion ? null : <span aria-hidden="true" data-testid="stream-caret" className="stream-caret" />;
  return (
    <div className="flex items-start gap-3" data-testid="streaming-message" data-kind={message.kind} data-ended={message.ended}>
      {bare ? null : <img src={logoUrl} alt="" width={28} height={28} className={AVATAR_CLASS} />}
      <div className="flex min-w-0 grow flex-col gap-3 pt-0.5">
        {hold ? (
          <p className="shimmer-text" role="status">
            {COMPOSING}
          </p>
        ) : message.kind === "answer" ? (
          <div className="stream-md">
            <SafeMarkdown text={message.ended ? shown : softClose(shown)} />
            {caret}
          </div>
        ) : (
          <p className="whitespace-pre-line">
            {shown}
            {caret}
          </p>
        )}
      </div>
    </div>
  );
}
