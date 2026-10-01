import type { AiDashboard as Ai } from "../../api/types.ts";
import { FlatTable } from "../../components/ActionView.tsx";
import { AI_METRICS, metricText } from "./metrics.ts";

// Dashboard AI/LLMOps (ke-hoach-m9-monitor.md §5.2; KH 12.2 [Đề xuất]: Bản 4 chưa vẽ → bảng tên chỉ số + giá trị).
// Hình dạng từng trường là [Suy luận] → hiện theo DỮ LIỆU nhận được: số → định dạng theo loại; chuỗi → chữ mono;
// object / mảng (vd `latency_p95_by_step`, `cost_per_day`) → bảng khoá–giá trị chung, chữ thô. Không đoán cấu trúc sâu.

function Value({ data, name, kind }: { data: Ai; name: string; kind: (typeof AI_METRICS)[number]["kind"] }) {
  const value = (data as Record<string, unknown>)[name];
  if (value !== null && value !== undefined && typeof value === "object" && !data.unavailable.includes(name)) {
    return (
      <div data-state="value" className="min-w-0 overflow-hidden rounded-xl border border-line">
        <FlatTable value={value} testId="ai-detail-row" />
      </div>
    );
  }
  if (typeof value === "string" && !data.unavailable.includes(name)) {
    return (
      <span data-state="value" className="font-mono text-secondary break-all">
        {value}
      </span>
    );
  }
  const m = metricText(name, value, data.unavailable, kind);
  return (
    <span data-state={m.state} className="flex flex-col items-end">
      <span className={m.state === "value" ? "tabular-nums" : "text-ink-2"}>{m.text}</span>
      {m.note ? <span className="text-label font-normal text-ink-2">{m.note}</span> : null}
    </span>
  );
}

export function AiDashboardView({ data }: { data: Ai }) {
  return (
    <ul aria-label="Chỉ số AI" className="overflow-hidden rounded-group border border-line">
      {AI_METRICS.map((metric) => (
        <li
          key={metric.name}
          data-testid="ai-metric"
          data-metric={metric.name}
          className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] items-start gap-6 border-t border-line px-5 py-3 first:border-t-0"
        >
          <span className="flex flex-col">
            <span>{metric.label}</span>
            <span className="font-mono text-label font-normal text-ink-2">{metric.name}</span>
          </span>
          <span className="flex justify-end text-right">
            <Value data={data} name={metric.name} kind={metric.kind} />
          </span>
        </li>
      ))}
    </ul>
  );
}
