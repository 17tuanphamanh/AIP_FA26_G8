import type { Source } from "../api/types.ts";

/** Nguồn tài liệu đã trích (`sources` thật — 12b Q-fe-2): tin `answer` và khối của tin tổng hợp. Chữ thô, không link. */
export function Sources({ sources }: { sources: readonly Source[] }) {
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
