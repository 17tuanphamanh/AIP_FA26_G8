import type { Source } from "../api/types.ts";
import logoUrl from "../assets/logo.svg";
import type { Message } from "./messages.ts";
import { SafeMarkdown } from "./SafeMarkdown.tsx";

// Hội thoại theo `kind` (12b Q-fe-2): `answer` (Markdown đã lọc + nguồn), `question`, `result`, `escalation`,
// `rejection` (4c) — và `kind` lạ → hiện `text` như tin thường, KHÔNG lỗi. Kiểm dạng từng tin: messages.ts.

function Sources({ sources }: { sources: Source[] }) {
  return (
    <div className="flex flex-wrap gap-2" data-testid="sources">
      <span className="sr-only">Nguồn tham khảo:</span>
      {sources.map((s) => (
        <span
          key={s.chunk_id}
          data-testid="source"
          className="inline-flex h-7 items-center rounded-lg border border-line px-2.5 text-label font-normal"
        >
          {s.heading_path ? `${s.title} · ${s.heading_path}` : s.title}
        </span>
      ))}
    </div>
  );
}

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

export function Conversation({ messages }: { messages: Message[] }) {
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
        ) : (
          <AssistantMessage key={index} message={message} />
        ),
      )}
    </div>
  );
}
