import Markdown, { type Components } from "react-markdown";
import { ALLOWED_ELEMENTS, safeUrl } from "./markdownPolicy.ts";

// Markdown của tin `answer` — luật lọc ở markdownPolicy.ts. Link mở tab mới với `noopener noreferrer`.
const components: Components = {
  a: ({ href, children }) =>
    href ? (
      <a href={href} target="_blank" rel="noopener noreferrer" className="text-fpt-blue underline">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    ),
  ul: ({ children }) => <ul className="list-disc pl-5.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-5.5">{children}</ol>,
  code: ({ children }) => <code className="rounded bg-group px-1 font-mono">{children}</code>,
  pre: ({ children }) => <pre className="overflow-x-auto rounded-lg bg-group p-3">{children}</pre>,
  h3: ({ children }) => <p className="font-semibold">{children}</p>,
  h4: ({ children }) => <p className="font-semibold">{children}</p>,
};

export function SafeMarkdown({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-3 text-body">
      <Markdown allowedElements={ALLOWED_ELEMENTS} unwrapDisallowed urlTransform={safeUrl} components={components}>
        {text}
      </Markdown>
    </div>
  );
}
