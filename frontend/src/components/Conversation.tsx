import type { ReactNode } from "react";
import logoUrl from "../assets/logo.svg";
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
    <div className="flex items-start gap-2.5" data-kind={message.kind}>
      <img src={logoUrl} alt="" width={24} height={24} className="mt-0.5 shrink-0" />
      <div className="flex min-w-0 grow flex-col gap-3">
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

type ConversationProps = { messages: Message[]; renderDigest?: (digest: Digest) => ReactNode };

export function Conversation({ messages, renderDigest }: ConversationProps) {
  return (
    <div role="log" aria-live="polite" aria-label="Cuộc trò chuyện" className="flex flex-col gap-6">
      {messages.map((message, index) =>
        message.role === "user" ? (
          <p
            key={index}
            data-role="user"
            className="max-w-130 self-end rounded-sheet bg-button-2 px-4.5 py-3 whitespace-pre-line"
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
