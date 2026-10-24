import type { StepItem, StepState } from "../../api/events.ts";

// Các bước xử lý của ticket (sự kiện `status` của SSE, ticket gốc): mỗi bước một dòng — đã xong · đang làm · chưa được. Không truyền
// thông tin chỉ bằng màu: mỗi trạng thái có ký hiệu chữ + nhãn đọc được cho trình đọc màn hình. Hiệu ứng nhấp nháy tắt khi người
// dùng bật giảm chuyển động (`motion-safe:`).

const MARK: Record<StepState, { symbol: string; tone: string; text: string }> = {
  done: { symbol: "✓", tone: "bg-done text-white", text: "xong" },
  active: { symbol: "•", tone: "bg-fpt-blue text-white motion-safe:animate-pulse", text: "đang làm" },
  failed: { symbol: "!", tone: "bg-orange-bg text-orange-ink", text: "chưa được" },
};

export function ProgressStepper({ steps }: { steps: readonly StepItem[] }) {
  if (steps.length === 0) return null;
  return (
    <ol aria-label="Tiến trình xử lý" data-testid="progress-stepper" className="flex flex-col gap-1.5 text-secondary">
      {steps.map((item) => {
        const mark = MARK[item.state];
        return (
          <li key={item.step} data-step={item.step} data-state={item.state} className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className={`inline-flex size-5 shrink-0 items-center justify-center rounded-full text-label ${mark.tone}`}
            >
              {mark.symbol}
            </span>
            <span className={item.state === "active" ? "font-semibold" : "text-ink-2"}>{item.label}</span>
            <span className="sr-only">({mark.text})</span>
          </li>
        );
      })}
    </ol>
  );
}
