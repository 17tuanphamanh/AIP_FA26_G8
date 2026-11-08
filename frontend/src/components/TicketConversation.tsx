import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { ApiError, PURGED_TEXT, errorMessage, isPurged } from "../api/errors.ts";
import { ticketReadOnlyQuery } from "../api/tickets.ts";
import { Conversation } from "./Conversation.tsx";
import { normalizeConversation } from "./messages.ts";

const EMPTY = "(không có)";

// Hội thoại CHỈ ĐỌC của một ticket cho IT: `GET /api/tickets/{id}` thật (L1/L2 có ticket:read:any — 12b Q-fe-6). Không ô
// nhập, không nút xác nhận. Dùng ở chi tiết escalate (F3) và màn xem ticket để ghi đè (F4). Ticket đã kết thúc → đọc
// một lần, không polling. `failText`: đọc lỗi → hiện đúng câu trung tính này (không mã lỗi, không tô đỏ) thay cho câu lỗi
// (màn ghi đè F4 — Q-fe-24: ticket minh hoạ không có ở backend, phần còn lại của màn vẫn dùng được). M2 bn-a: 410
// `conversation_purged` (hạn giữ 90 ngày đã dọn) → câu chính sách lưu trữ, trung tính, đứng trước `failText`.
export function TicketConversation({ ticketId, failText }: { ticketId: string; failText?: string }) {
  const query = useQuery(ticketReadOnlyQuery(ticketId));
  const messages = useMemo(() => normalizeConversation(query.data?.conversation), [query.data]);
  return (
    <section aria-labelledby="conversation-heading" className="flex flex-col gap-2">
      <h2 id="conversation-heading" className="pl-1 text-label text-ink-2">
        Hội thoại
      </h2>
      {query.isPending ? (
        <p className="text-secondary text-ink-2">Đang tải hội thoại…</p>
      ) : query.data === undefined && isPurged(query.error) ? (
        <p data-testid="conversation-purged" className="text-secondary text-ink-2">
          {PURGED_TEXT}
        </p>
      ) : query.data === undefined && failText !== undefined ? (
        <p data-testid="ticket-unavailable" className="text-secondary text-ink-2">
          {failText}
        </p>
      ) : query.data === undefined ? (
        <p role="alert" className="text-secondary text-danger">
          Chưa tải được hội thoại: {errorMessage(query.error instanceof ApiError ? query.error : null)}
        </p>
      ) : messages.length === 0 ? (
        <p className="text-secondary text-ink-2">{EMPTY}</p>
      ) : (
        <Conversation messages={messages} />
      )}
    </section>
  );
}
