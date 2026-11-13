import { Ma } from "../../components/MaNhan.tsx";
import type { AiDashboard as Ai, DayCost } from "../../api/types.ts";
import {
  AI_METRICS,
  AI_NO_DATA_TEXT,
  DAY_OPEN_NOTE,
  EMPTY_TEXT,
  formatLatency,
  formatUsd,
  INTENT_MODEL_MISSING_NOTE,
  type MetricState,
  metricText,
  stepLabel,
  WAIT_STEP,
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
    <span className="flex flex-col">
      <span className={m.state === "value" ? "text-heading tabular-nums" : "text-ink-2"}>{m.text}</span>
      {m.note ? <span className="text-label font-normal text-ink-2">{m.note}</span> : null}
    </span>
  );
}

/**
 * Gọn 13/11 (TA): tổng chi phí cả khoảng (số lớn) + mỗi ngày một dòng nhỏ "dd/MM · USD" kèm thanh tỉ lệ; ngày chưa trọn trong
 * cửa sổ (`day_start` + 24 giờ > `to`) → "· chưa hết ngày".
 */
function CostPerDay({ points, to }: { points: DayCost[]; to: string }) {
  if (points.length === 0) return <span className="text-ink-2">{AI_NO_DATA_TEXT}</span>;
  const end = Date.parse(to);
  const total = points.reduce((sum, p) => sum + (Number.isFinite(p.cost_usd) ? p.cost_usd : 0), 0);
  const max = Math.max(...points.map((p) => (Number.isFinite(p.cost_usd) ? p.cost_usd : 0)), 0);
  return (
    <span className="flex flex-col gap-2">
      <span data-testid="ai-cost-total" className="text-heading tabular-nums">
        {formatUsd(total)} USD
      </span>
      <ul className="flex flex-col gap-1">
        {points.map((p) => (
          <li key={p.day_start} data-testid="ai-cost-day" data-day={p.day_start} className="grid grid-cols-[minmax(0,9rem)_minmax(2rem,1fr)] items-center gap-3 text-label font-normal tabular-nums">
            <span>
              {vnDate(p.day_start)} · {formatUsd(p.cost_usd)}
              {Date.parse(p.day_start) + DAY_MS > end ? <span className="text-ink-2"> · {DAY_OPEN_NOTE}</span> : null}
            </span>
            <span className="h-1.5 rounded-full bg-button-2" aria-hidden="true">
              <span className="block h-1.5 rounded-full bg-fpt-blue" style={{ width: `${max > 0 ? Math.round((p.cost_usd / max) * 100) : 0}%` }} />
            </span>
          </li>
        ))}
      </ul>
    </span>
  );
}

/** Số bước chậm nhất hiện trên tab AI. */
export const LATENCY_TOP = 5;

/** Gọn 13/11 (TA): chỉ các bước hệ thống tự chạy (bỏ bước chờ người), xếp chậm → nhanh, 5 bước đầu kèm thanh. */
function LatencyByStep({ steps }: { steps: Record<string, number> }) {
  const entries = Object.entries(steps)
    .filter(([step]) => !Object.hasOwn(WAIT_STEP, step.replace(/^node:/, "")))
    .sort((a, b) => b[1] - a[1])
    .slice(0, LATENCY_TOP);
  if (entries.length === 0) return <span className="text-ink-2">{AI_NO_DATA_TEXT}</span>;
  const max = Math.max(...entries.map(([, ms]) => ms), 0);
  return (
    <ul className="flex flex-col gap-1.5">
      {entries.map(([step, ms]) => {
        const l = stepLabel(step);
        return (
          <li key={step} data-testid="ai-latency-step" data-key={step} title={step} className="grid grid-cols-[minmax(0,1fr)_minmax(3rem,8rem)] items-center gap-3 tabular-nums">
            <span className="min-w-0">
              {l.nhan ? (
                <>
                  {l.nhan} · <Ma ma={l.ma} />
                </>
              ) : (
                <span className="font-mono">{step}</span>
              )}{" "}
              · {formatLatency(ms)}
            </span>
            <span className="h-1.5 rounded-full bg-button-2" aria-hidden="true">
              <span className="block h-1.5 rounded-full bg-send" style={{ width: `${max > 0 ? Math.round((ms / max) * 100) : 0}%` }} />
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function Value({ data, name, kind }: { data: Ai; name: string; kind: (typeof AI_METRICS)[number]["kind"] }) {
  if (stateOf(data, name) !== "value") {
    if (name === "intent_model_version" && stateOf(data, name) === "empty") {
      return (
        <span className="flex flex-col">
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

/** Gọn 13/11 (TA): nhóm chỉ số thành ô (như tab Nghiệp vụ) thay vì một danh sách dài. Mỗi khoá vẫn đúng một `ai-metric`. */
const GROUPS: readonly { title: string; names: readonly string[]; wide?: boolean }[] = [
  { title: "Lỗi và độ tin cậy", names: ["e2_llm_count", "e9_count", "json_invalid_first_try_rate", "fallback_rate"] },
  { title: "Mức dùng AI", names: ["b3_llm_rate", "b2_llm_rate", "intent_filter_fallback_rate", "cache_hit_rate"] },
  { title: "Chi phí", names: ["tokens_per_ticket", "cost_per_day"] },
  { title: `Độ trễ p95 — ${LATENCY_TOP} bước chậm nhất`, names: ["latency_p95_by_step"], wide: true },
  { title: "Khác", names: ["intent_model_version", "multi_intent_first_stop_to_reply_s", "multi_intent_messages_per_turn"] },
];
/** Chỉ số chỉ hiện khi có số (chưa có ca nhiều ý → ẩn, không chiếm chỗ). */
const HIDE_UNLESS_VALUE = new Set(["multi_intent_first_stop_to_reply_s", "multi_intent_messages_per_turn"]);
const META = new Map(AI_METRICS.map((m) => [m.name, m]));

export function AiDashboardView({ data }: { data: Ai }) {
  return (
    <div className="flex flex-col gap-5">
      {GROUPS.map((group) => {
        const metrics = group.names
          .map((n) => META.get(n))
          .filter((m): m is (typeof AI_METRICS)[number] => !!m && !(HIDE_UNLESS_VALUE.has(m.name) && stateOf(data, m.name) !== "value"));
        if (metrics.length === 0) return null;
        return (
          <section key={group.title} aria-label={group.title} className="flex flex-col gap-2">
            <h2 className="pl-1 text-label text-ink-2">{group.title}</h2>
            <ul aria-label="Chỉ số AI" className={`grid gap-4 ${group.wide ? "grid-cols-1" : "grid-cols-4 max-lg:grid-cols-2"}`}>
              {metrics.map((metric) => (
                <li
                  key={metric.name}
                  data-testid="ai-metric"
                  data-metric={metric.name}
                  data-state={stateOf(data, metric.name)}
                  title={metric.name}
                  className={`flex min-w-0 flex-col gap-1 rounded-group bg-group px-5 py-4 ${metric.name === "cost_per_day" ? "col-span-3 max-lg:col-span-2" : ""}`}
                >
                  <span className="text-secondary text-ink-2">
                    {metric.label}
                    {metric.ma ? (
                      <>
                        {" · "}
                        <Ma ma={metric.ma} />
                      </>
                    ) : null}
                  </span>
                  <span className="flex min-w-0">
                    <Value data={data} name={metric.name} kind={metric.kind} />
                  </span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
