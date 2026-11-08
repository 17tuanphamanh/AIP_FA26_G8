import { progressLabel, progressTone, type ProgressView } from "../routes/employee/multi.ts";
import type { Tone } from "../routes/employee/status.ts";

// Khung tiến độ từng ý của yêu cầu nhiều ý (P1 §8.3, P10 §3.1 — D-31): KHÔNG phải tin nhắn, nằm trên đầu cuộc trò
// chuyện, cập nhật theo nhịp polling của ticket cha. B4EmpDigest vẽ chấm màu + tên trong header; ở đây thêm nhãn chữ
// cạnh mỗi chấm (không truyền thông tin chỉ bằng màu) — PLAN-fe mục 7 #24.

const DOT: Record<Tone, string> = {
  processing: "bg-fpt-blue",
  waiting: "bg-fpt-orange",
  done: "bg-done",
  closed: "bg-ink-3",
};

export function ProgressStrip({ items }: { items: readonly ProgressView[] }) {
  return (
    <div
      role="group"
      aria-label="Tiến độ từng việc"
      data-testid="progress-strip"
      className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-1.5 border-b border-line px-6 py-2.5 text-secondary max-lg:px-4"
    >
      {items.map((item) => {
        const tone = progressTone(item);
        return (
          <span key={item.child_id} data-testid="progress-item" data-child={item.child_id} data-tone={tone} className="inline-flex items-center gap-1.5">
            <span className={`size-1.75 shrink-0 rounded-full ${DOT[tone]}`} aria-hidden="true" />
            <span className="font-semibold">{item.title || `Ý ${item.index}`}</span>
            <span className="text-ink-2">· {progressLabel(item)}</span>
          </span>
        );
      })}
    </div>
  );
}
