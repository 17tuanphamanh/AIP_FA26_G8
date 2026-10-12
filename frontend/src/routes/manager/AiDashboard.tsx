import type { AiDashboard as Ai, DayCost } from "../../api/types.ts";
import {
  AI_METRICS,
  AI_NO_DATA_TEXT,
  DAY_OPEN_NOTE,
  EMPTY_TEXT,
  formatMs,
  formatUsd,
  INTENT_MODEL_MISSING_NOTE,
  type MetricState,
  metricText,
} from "./metrics.ts";
import { vnDate } from "./range.ts";

// Dashboard AI/LLMOps (backend/app/api/dashboard.py `AiMetrics` — 14 khoá, chỉ số nằm trong `data.metrics`; KH 12.2
// [Đề xuất]: Bản 4 chưa vẽ → danh sách tên chỉ số + giá trị). `cost_per_day` = một dòng mỗi ngày giờ VN; `latency_p95_by_step`
// = một dòng mỗi bước. Mọi chữ từ server hiện thô (React tự thoát), không HTML.

const DAY_MS = 86_400_000;
const valueOf = (data: Ai, name: string): unknown => (data.metrics as Record<string, unknown>)[name];

/** Trạng thái của dòng (cùng thứ tự với `metricText`): unavailable / thiếu khoá → "unavailable"; null → "empty". */
function stateOf(data: Ai, name: string): MetricState {
  const value = valueOf(data, name);
  if (data.unavailable.includes(name) || value === undefined) return "unavailable";
  return value === null ? "empty" : "value";
}

function Plain({ data, name, kind }: { data: Ai; name: string; kind: (typeof AI_METRICS)[number]["kind"] }) {
  const m = metricText(name, valueOf(data, name), data.unavailable, kind);
  return (
    <span className="flex flex-col items-end">
      <span className={m.state === "value" ? "tabular-nums" : "text-ink-2"}>{m.text}</span>
      {m.note ? <span className="text-label font-normal text-ink-2">{m.note}</span> : null}
    </span>
  );
}

/** Mỗi điểm một dòng "dd/MM · số USD"; ngày chưa trọn trong cửa sổ (`day_start` + 24 giờ > `to`) → "· chưa hết ngày". */
function CostPerDay({ points, to }: { points: DayCost[]; to: string }) {
  if (points.length === 0) return <span className="text-ink-2">{AI_NO_DATA_TEXT}</span>;
  const end = Date.parse(to);
  return (
    <ul className="flex flex-col items-end">
      {points.map((p) => (
        <li key={p.day_start} data-testid="ai-cost-day" data-day={p.day_start} className="tabular-nums">
          {vnDate(p.day_start)} · {formatUsd(p.cost_usd)}
          {Date.parse(p.day_start) + DAY_MS > end ? <span className="text-ink-2"> · {DAY_OPEN_NOTE}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function LatencyByStep({ steps }: { steps: Record<string, number> }) {
  const entries = Object.entries(steps);
  if (entries.length === 0) return <span className="text-ink-2">{AI_NO_DATA_TEXT}</span>;
  return (
    <ul className="flex flex-col items-end">
      {entries.map(([step, ms]) => (
        <li key={step} data-testid="ai-latency-step" data-key={step} className="tabular-nums">
          <span className="font-mono">{step}</span> · {formatMs(ms)}
        </li>
      ))}
    </ul>
  );
}

function Value({ data, name, kind }: { data: Ai; name: string; kind: (typeof AI_METRICS)[number]["kind"] }) {
  if (stateOf(data, name) !== "value") {
    if (name === "intent_model_version" && stateOf(data, name) === "empty") {
      return (
        <span className="flex flex-col items-end">
          <span className="text-ink-2">{EMPTY_TEXT}</span>
          <span className="text-label font-normal text-ink-2">{INTENT_MODEL_MISSING_NOTE}</span>
        </span>
      );
    }
    return <Plain data={data} name={name} kind={kind} />;
  }
  const m = data.metrics;
  if (name === "cost_per_day" && m.cost_per_day) return <CostPerDay points={m.cost_per_day} to={data.to} />;
  if (name === "latency_p95_by_step" && m.latency_p95_by_step) return <LatencyByStep steps={m.latency_p95_by_step} />;
  const value = valueOf(data, name);
  if (typeof value === "string") return <span className="font-mono text-secondary break-all">{value}</span>;
  return <Plain data={data} name={name} kind={kind} />;
}

export function AiDashboardView({ data }: { data: Ai }) {
  return (
    <ul aria-label="Chỉ số AI" className="overflow-hidden rounded-group border border-line">
      {AI_METRICS.map((metric) => (
        <li
          key={metric.name}
          data-testid="ai-metric"
          data-metric={metric.name}
          data-state={stateOf(data, metric.name)}
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
