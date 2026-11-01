import type { Source } from "../api/types.ts";

/** Nguồn tài liệu đã trích (`sources` thật — 12b Q-fe-2): tin `answer` và khối của tin tổng hợp. Chữ thô, không link. */
export function Sources({ sources }: { sources: readonly Source[] }) {
  return (
    <div className="flex flex-col gap-2" data-testid="sources">
      <span className="text-label font-normal text-ink-2">Nguồn tham khảo:</span>
      <div className="flex flex-wrap gap-2">
        {sources.map((s) => (
          <span
            key={s.chunk_id}
            data-testid="source"
            className="inline-flex min-h-8 max-w-full items-center gap-1.5 rounded-full border border-line bg-white px-3 py-1 text-label font-normal text-ink"
          >
            <svg viewBox="0 0 16 16" className="size-3.5 shrink-0 fill-none stroke-fpt-blue" strokeWidth="1.5" aria-hidden="true">
              <path d="M4 1.75h5.5L13 5.25v9H4z" strokeLinejoin="round" />
              <path d="M9.5 1.75v3.5H13M6 8.5h5M6 11h3.5" strokeLinecap="round" />
            </svg>
            <span className="min-w-0 truncate">{s.heading_path ? `${s.title} · ${s.heading_path}` : s.title}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
