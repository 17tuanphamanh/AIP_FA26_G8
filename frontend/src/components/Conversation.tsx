import type { ReactNode } from "react";
import logoUrl from "../assets/logo.svg";
import { AVATAR_CLASS } from "./avatar.ts";
import { DigestMessage } from "./DigestMessage.tsx";
import type { Digest, Message } from "./messages.ts";
import { SafeMarkdown } from "./SafeMarkdown.tsx";
import { Sources } from "./Sources.tsx";

// Hội thoại theo `kind` (12b Q-fe-2): `answer` (Markdown đã lọc + nguồn), `question`, `result`, `escalation`,
// `rejection` (4c) — và `kind` lạ → hiện `text` như tin thường, KHÔNG lỗi. Kiểm dạng từng tin: messages.ts.
// `digest` (tin tổng hợp nhiều ý, D-31): mặc định chỉ đọc; màn chat nhân viên truyền `renderDigest` để gắn form trả lời
// cho tin round lớn nhất (routes/employee/ChatPage.tsx).

function AssistantMessage({ message }: { message: Message }) {
  return (
    <div className="flex items-start gap-3" data-kind={message.kind}>
      <img src={logoUrl} alt="" width={28} height={28} className={AVATAR_CLASS} />
      <div className="flex min-w-0 grow flex-col gap-3 pt-0.5">
        {!message.text.trim() ? null : message.kind === "answer" ? (
          <SafeMarkdown text={message.text} />
        ) : (
          <p className="whitespace-pre-line">{message.text}</p>
        )}
        {message.sources.length > 0 ? <Sources sources={message.sources} /> : null}
      </div>
    </div>
  );
}

/** Bong bóng tin của người dùng — dùng chung cho câu yêu cầu đầu (ChatPage). */
export const USER_BUBBLE = "max-w-[80%] self-end rounded-sheet rounded-br-md bg-selected px-5 py-3 whitespace-pre-line";

type ConversationProps = { messages: Message[]; renderDigest?: (digest: Digest) => ReactNode };

export function Conversation({ messages, renderDigest }: ConversationProps) {
  return (
    <div role="log" aria-live="polite" aria-label="Cuộc trò chuyện" className="flex flex-col gap-8">
      {messages.map((message, index) =>
        message.role === "user" ? (
          <p
            key={index}
            data-role="user"
            className={USER_BUBBLE}
          >
            {message.text}
          </p>
        ) : message.digest ? (
          <div key={index} data-kind="digest">
            {renderDigest ? renderDigest(message.digest) : <DigestMessage digest={message.digest} />}
          </div>
        ) : (
          <AssistantMessage key={index} message={message} />
        ),
      )}
    </div>
  );
}
