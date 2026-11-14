import type { StepItem, StepState } from "../../api/events.ts";

// Các bước xử lý của ticket (sự kiện `status` của SSE, ticket gốc): mỗi bước một dòng trên một đường thời gian dọc — đã xong · đang
// làm · chưa được. Không truyền thông tin chỉ bằng màu: mỗi trạng thái có biểu tượng riêng + nhãn đọc được cho trình đọc màn hình.
// TA 14/11 ("thô kệch"): vòng quay mảnh cho bước đang làm, dấu tích bật nhẹ khi xong, chữ bước đang làm loang sáng, đường nối giữa
// các bước; bước mới trồi lên. Giảm chuyển động → đứng yên (tokens.css).
// `collapsed`: khi câu trả lời đã bắt đầu chạy chữ, khung thu lại (chuyển động chiều cao) để chữ không bị đẩy xuống — vẫn nằm trong DOM.

const SR: Record<StepState, string> = { done: "xong", active: "đang làm", failed: "chưa được" };

function Mark({ state }: { state: StepState }) {
  if (state === "done") {
    return (
      <span className="inline-flex size-5 items-center justify-center rounded-full bg-done text-white motion-safe:animate-pop-in">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12.5l4.5 4.5L19 7.5" />
        </svg>
      </span>
    );
  }
  if (state === "failed") {
    return <span className="inline-flex size-5 items-center justify-center rounded-full bg-orange-bg text-label font-semibold text-orange-ink">!</span>;
  }
  return (
    <span className="relative inline-flex size-5 items-center justify-center">
      <span className="absolute inset-0 rounded-full border-2 border-fpt-blue/15" />
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="absolute inset-0 motion-safe:animate-spin">
        <path d="M10 2a8 8 0 0 1 8 8" stroke="var(--color-fpt-blue)" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <span className="size-1.5 rounded-full bg-fpt-blue" />
    </span>
  );
}

export function ProgressStepper({ steps, collapsed = false }: { steps: readonly StepItem[]; collapsed?: boolean }) {
  if (steps.length === 0) return null;
  return (
    <div
      className="grid transition-[grid-template-rows,opacity] duration-300 ease-soft motion-reduce:transition-none"
      style={{ gridTemplateRows: collapsed ? "0fr" : "1fr", opacity: collapsed ? 0 : 1 }}
      aria-hidden={collapsed || undefined}
    >
      <div className="min-h-0 overflow-hidden">
        <ol aria-label="Tiến trình xử lý" data-testid="progress-stepper" className="flex flex-col px-4 pt-1 pb-3.5 text-secondary">
          {steps.map((item, i) => (
            <li
              key={item.step}
              data-step={item.step}
              data-state={item.state}
              className="relative flex items-start gap-3 pb-2.5 last:pb-0 motion-safe:animate-rise-in"
            >
              {i < steps.length - 1 ? (
                <span aria-hidden="true" className={`absolute top-6 bottom-0.5 left-[9.5px] w-px ${item.state === "done" ? "bg-done/40" : "bg-line"}`} />
              ) : null}
              <span aria-hidden="true" className="mt-px shrink-0">
                <Mark state={item.state} />
              </span>
              <span className={item.state === "active" ? "shimmer-text font-semibold" : item.state === "failed" ? "text-orange-ink" : "text-ink-2"}>
                {item.label}
              </span>
              <span className="sr-only">({SR[item.state]})</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
