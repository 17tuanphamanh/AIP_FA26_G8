import { useQuery } from "@tanstack/react-query";
import { policyQuery } from "../../api/policy.ts";
import { NhanMa } from "../../components/MaNhan.tsx";
import { GOI_Y_TRONG_SO, luatIT, MA_KET_THUC } from "../../lib/nhan.ts";
import type { BusinessCountedTam as Business, BusinessMetrics, E3Cases, GroupCountTam } from "../../api/types.ts";
import { labelOf, ownEntry } from "../../lib/lookup.ts";
import {
  countedRateText,
  DECIDED_BY_LABEL,
  E1_LABEL,
  E3_TRUNCATED_TEXT,
  EMPTY_TEXT,
  formatRate,
  fractionText,
  INSUFFICIENT_TEXT,
  insufficientText,
  type MetricKind,
  type MetricText,
  metricText,
  WEIGHT_GROUP_LABEL,
} from "./metrics.ts";
import { vnDate } from "./range.ts";

// B4MgrDashboard — dashboard nghiệp vụ (backend/app/api/dashboard.py `BusinessAllMetrics`, tên trường giữ nguyên; chỉ
// số nằm trong `data.metrics`). Component này CHỈ vẽ dữ liệu đã tải thành công; trạng thái tải/lỗi do DashboardPage lo
// (lỗi → không gọi tới đây → không còn số cũ). Mọi ô số đi qua `metricText`: unavailable → "Chưa có dữ liệu", null → "—",
// 0 thật → "0" (F5 P3). Số đếm D13 (`min_sample`, `counts`): tỉ lệ kèm "(a/b)", mẫu < min_sample → "chưa đủ dữ liệu
// (n=b)" thay cho %; weighted không có tử tổng → chỉ cỡ mẫu + a/b theo nhóm. Thiếu counts (backend cũ) → như trước.

type Name = keyof BusinessMetrics;
/** Giá trị của một chỉ số; khoá thiếu → undefined ("Máy chủ không trả chỉ số này" — nhánh phòng thủ). */
const metric = <K extends Name>(data: Business, name: K): BusinessMetrics[K] | undefined => data.metrics[name];

function Kpi({
  data,
  name,
  value,
  label,
  kind,
  extra,
  goiY,
  text,
}: {
  data: Business;
  name: Name;
  value: unknown;
  label: string;
  kind: MetricKind;
  extra?: string;
  goiY?: string;
  /** Chữ đã tính sẵn (tỉ lệ có số đếm); không có → `metricText`. */
  text?: MetricText;
}) {
  const m = text ?? metricText(name, value, data.unavailable, kind);
  return (
    <div data-testid="kpi" data-metric={name} data-state={m.state} className="flex flex-col gap-0.5 rounded-group bg-group px-5 py-4.5">
      <span className="text-secondary text-ink-2" title={goiY} data-testid={goiY ? "kpi-goi-y" : undefined}>
        {label}
        {goiY ? <span className="sr-only"> ({goiY})</span> : null}
      </span>
      <span data-testid="kpi-value" className={m.state === "value" ? "text-title tabular-nums" : "text-heading text-ink-2"}>
        {m.text}
      </span>
      <span className="text-label font-normal text-ink-2">
        {m.note ?? <span className="font-mono">{name}</span>}
        {extra ? ` · ${extra}` : ""}
      </span>
    </div>
  );
}

/** Đầu khối: nhãn tiếng Việt + tên trường API (Bản 4: "Ai quyết định mức rủi ro · decided_by_distribution"). */
function Heading({ id, text, field, ma }: { id: string; text: string; field: string; ma?: string }) {
  return (
    <h2 id={id} className="pl-1 text-label text-ink-2">
      {text}
      {ma ? (
        <>
          {" · "}
          <span className="font-mono font-normal">{ma}</span>
        </>
      ) : null}{" "}
      · <span className="font-mono font-normal">{field}</span>
    </h2>
  );
}

/** Khối có thể "chưa có dữ liệu" / null (không ca) — chỉ hiện nội dung khi có giá trị. */
function StateLine({ data, name }: { data: Business; name: Name }) {
  const m = metricText(name, metric(data, name), data.unavailable, "number");
  return (
    <p data-testid={`metric-${name}`} data-state={m.state} className="rounded-group border border-line px-5 py-3.5 text-secondary text-ink-2">
      {m.text}
      {m.note ? ` · ${m.note}` : ""}
    </p>
  );
}

const usable = (data: Business, name: Name) => !data.unavailable.includes(name) && metric(data, name) !== null && metric(data, name) !== undefined;

/** Tỉ lệ có thể null (nhóm 0 lá) → "—"; KHÔNG BAO GIỜ "0 %" cho null. */
const rateOrEmpty = (value: number | null) => (value === null ? EMPTY_TEXT : formatRate(value));

function Bars({ values, labels }: { values: Record<string, number>; labels: Record<string, string> }) {
  const entries = Object.entries(values);
  const total = entries.reduce((sum, [, n]) => sum + (Number.isFinite(n) ? n : 0), 0);
  if (entries.length === 0 || total === 0) return <p className="px-5 py-3.5 text-secondary text-ink-2">Không có yêu cầu trong khoảng này.</p>;
  return (
    <div className="flex flex-col gap-3.5 px-5 py-4.5">
      {entries.map(([key, n], i) => (
        <div key={key} data-testid="bar-row" data-key={key} className="grid grid-cols-[120px_minmax(0,1fr)_56px] items-center gap-3">
          <span className="truncate text-secondary">{labelOf(labels, key)}</span>
          <span className="h-2.5 rounded-full bg-button-2">
            <span className={`block h-2.5 rounded-full ${i === 0 ? "bg-fpt-blue" : "bg-send"}`} style={{ width: `${Math.round((n / total) * 100)}%` }} />
          </span>
          <span className="text-right text-secondary tabular-nums">{metricText(key, n, [], "count").text}</span>
        </div>
      ))}
    </div>
  );
}

function E3List({ cases }: { cases: E3Cases }) {
  if (cases.items.length === 0) return <p className="px-4 py-3 text-secondary text-ink-2">Không có ca thiếu tài liệu hướng dẫn trong khoảng này.</p>;
  return (
    <>
      <ul aria-label="Ca thiếu tài liệu">
        {cases.items.map((c) => (
          <li key={c.ticket_id} data-testid="e3-case" className="flex flex-col border-t border-line px-4 py-2.5 first:border-t-0">
            {/* Chữ thô (React tự thoát) — request_excerpt có "<b>" vẫn hiện nguyên văn. */}
            <span data-testid="e3-excerpt" className="truncate text-secondary">
              “{c.request_excerpt}”
            </span>
            <span className="truncate text-label font-normal text-ink-2">
              {c.intent ?? "chưa rõ ý định"} · {vnDate(c.created_at)}
              {c.kb_version ? ` · KB ${c.kb_version}` : ""} · <span className="font-mono">{c.ticket_id}</span>
            </span>
          </li>
        ))}
      </ul>
      {cases.truncated ? (
        <p role="status" data-testid="e3-truncated" className="border-t border-line px-4 py-2.5 text-label font-normal text-ink-2">
          {E3_TRUNCATED_TEXT}
        </p>
      ) : null}
    </>
  );
}

type Simple = "automation_rate" | "escalation_rate_raw" | "deflection_rate";
const rateText = (data: Business, name: Simple) => countedRateText(name, metric(data, name), data.counts?.[name], data.min_sample, data.unavailable);

/** Cỡ mẫu weighted (`counts.escalation_rate_weighted.den`) < min_sample? Thiếu số đếm → false (như trước D13). */
function weightedTooSmall(data: Business): boolean {
  const count = data.counts?.escalation_rate_weighted;
  return !!count && data.min_sample !== undefined && count.den < data.min_sample;
}

export function BusinessKpis({ data }: { data: Business }) {
  const raw = rateText(data, "escalation_rate_raw");
  const weighted = metric(data, "escalation_rate_weighted");
  const weightedCount = data.counts?.escalation_rate_weighted;
  const weightedText: MetricText | undefined =
    weightedTooSmall(data) && weightedCount && !data.unavailable.includes("escalation_rate_weighted")
      ? { state: "insufficient", text: insufficientText(weightedCount.den), note: null }
      : undefined;
  return (
    <div className="grid grid-cols-4 gap-4">
      <Kpi data={data} name="automation_rate" value={metric(data, "automation_rate")} label="Tự xử lý" kind="rate" text={rateText(data, "automation_rate")} />
      <Kpi
        data={data}
        name="escalation_rate_weighted"
        value={weighted ? weighted.weighted : weighted}
        label="Chuyển L2 (có trọng số)"
        goiY={GOI_Y_TRONG_SO}
        kind="rate"
        text={weightedText}
        extra={`${weightedCount ? `n=${weightedCount.den} · ` : ""}thô ${raw.text}`}
      />
      <Kpi
        data={data}
        name="deflection_rate"
        value={metric(data, "deflection_rate")}
        label="Trả lời bằng tài liệu"
        kind="rate"
        text={rateText(data, "deflection_rate")}
      />
      <Kpi data={data} name="approval_expired_count" value={metric(data, "approval_expired_count")} label="Hết hạn duyệt" kind="count" extra="tự chuyển L2" />
    </div>
  );
}

/** Tỉ lệ chuyển L2 theo từng nhóm rủi ro + độ nhạy của trọng số (`escalation_rate_weighted.by_group`, `.sensitivity`). */
function WeightedGroups({ data }: { data: Business }) {
  const weighted = metric(data, "escalation_rate_weighted");
  if (!usable(data, "escalation_rate_weighted") || !weighted) return <StateLine data={data} name="escalation_rate_weighted" />;
  const groups = Object.entries(weighted.by_group);
  const sensitivity = Object.entries(weighted.sensitivity);
  const counts = data.counts?.escalation_rate_weighted?.by_group;
  const tooSmall = weightedTooSmall(data);
  /** Nhóm có số đếm: "a/b", thêm % khi den ≥ min_sample và tỉ lệ khác null → "25 % (5/20)". Không số đếm → như cũ. */
  const groupText = (key: string, rate: number | null) => {
    const count = counts ? ownEntry<GroupCountTam | null>(counts, key, null) : null;
    if (!count || data.min_sample === undefined) return rateOrEmpty(rate);
    const fraction = fractionText(count.num, count.den);
    return count.den >= data.min_sample && rate !== null ? `${formatRate(rate)} (${fraction})` : fraction;
  };
  return (
    <div className="flex flex-col gap-2">
      {groups.length === 0 ? (
        <p className="rounded-group border border-line px-5 py-3.5 text-secondary text-ink-2">Không có yêu cầu trong khoảng này.</p>
      ) : (
        <ul className="overflow-hidden rounded-group border border-line">
          {groups.map(([key, rate]) => (
            <li key={key} data-testid="weighted-group" data-key={key} className="flex h-11 items-center gap-3 border-t border-line px-5 first:border-t-0">
              <span className="grow text-secondary">{labelOf(WEIGHT_GROUP_LABEL, key)}</span>
              <span className="text-secondary text-ink-2 tabular-nums">{groupText(key, rate)}</span>
            </li>
          ))}
        </ul>
      )}
      {sensitivity.length > 0 ? (
        <p data-testid="weighted-sensitivity" className="pl-1 text-label font-normal text-ink-2">
          Độ nhạy trọng số: {tooSmall ? INSUFFICIENT_TEXT : sensitivity.map(([key, rate]) => `${key}: ${rateOrEmpty(rate)}`).join(" · ")}
        </p>
      ) : null}
    </div>
  );
}

/** `rules[].id → description` của nội dung chính sách đang chạy (chỉ mục đúng dạng; khoá lạ bỏ qua). */
function ruleDescriptionMap(content: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  const rules = content.rules;
  if (!Array.isArray(rules)) return out;
  for (const r of rules) {
    if (r && typeof r === "object" && typeof (r as { id?: unknown }).id === "string" && typeof (r as { description?: unknown }).description === "string") {
      Object.defineProperty(out, (r as { id: string }).id, { value: (r as { description: string }).description, enumerable: true });
    }
  }
  return out;
}

/** Cột trái của B4MgrDashboard. */
export function BusinessSections({ data }: { data: Business }) {
  // Mô tả luật (NGU-10): BE chưa trả trong `top_matched_rules` → tra `GET /api/policy` (Trưởng BP có policy:read); lỗi / chưa có
  // → "Luật chưa có mô tả · R…" (không chặn khối).
  const policy = useQuery(policyQuery());
  const ruleDescriptions = policy.data ? ruleDescriptionMap(policy.data.content) : null;
  const decidedBy = metric(data, "decided_by_distribution");
  const rules = metric(data, "top_matched_rules");
  const e1 = metric(data, "e1_split");
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <section aria-labelledby="decided-by" className="flex flex-col gap-2">
        <Heading id="decided-by" text="Ai quyết định mức rủi ro" field="decided_by_distribution" />
        {usable(data, "decided_by_distribution") && decidedBy ? (
          <div className="rounded-group border border-line">
            <Bars values={decidedBy} labels={DECIDED_BY_LABEL} />
          </div>
        ) : (
          <StateLine data={data} name="decided_by_distribution" />
        )}
      </section>

      <section aria-labelledby="weighted-groups" className="flex flex-col gap-2">
        <Heading id="weighted-groups" text="Chuyển L2 theo nhóm rủi ro" field="escalation_rate_weighted" />
        <WeightedGroups data={data} />
      </section>

      <section aria-labelledby="top-rules" className="flex flex-col gap-2">
        <Heading id="top-rules" text="Luật khớp nhiều nhất" field="top_matched_rules" />
        {usable(data, "top_matched_rules") && rules ? (
          rules.length === 0 ? (
            <p className="rounded-group border border-line px-5 py-3.5 text-secondary text-ink-2">Không có luật nào khớp trong khoảng này.</p>
          ) : (
            <ul className="overflow-hidden rounded-group border border-line">
              {rules.map((r) => (
                <li key={r.rule_id} data-testid="rule-row" className="flex h-11 items-center gap-3 border-t border-line px-5 first:border-t-0">
                  <span data-testid="rule-name" className="grow text-secondary">
                    <NhanMa {...luatIT(r.rule_id, ruleDescriptions ? ownEntry<string | null>(ruleDescriptions, r.rule_id, null) : null)} />
                  </span>
                  <span className="text-secondary text-ink-2 tabular-nums">{metricText(r.rule_id, r.count, [], "count").text}</span>
                </li>
              ))}
            </ul>
          )
        ) : (
          <StateLine data={data} name="top_matched_rules" />
        )}
        <OverrideLine data={data} />
      </section>

      <section aria-labelledby="e1-split" className="flex flex-col gap-2">
        <Heading id="e1-split" text={MA_KET_THUC.E1!.nhan} ma="E1" field="e1_split" />
        {usable(data, "e1_split") && e1 ? (
          <div className="rounded-group border border-line">
            <Bars values={e1.counts} labels={E1_LABEL} />
          </div>
        ) : (
          <StateLine data={data} name="e1_split" />
        )}
      </section>
    </div>
  );
}

/** Bản 4: "Số lần L1 ghi đè: …" — nguồn thật từ Phase 4 (4d); 0 thật → "0". */
function OverrideLine({ data }: { data: Business }) {
  const m = metricText("override_count", metric(data, "override_count"), data.unavailable, "count");
  return (
    <p data-testid="metric-override_count" data-state={m.state} className="pl-1 text-label font-normal text-ink-2">
      Số lần L1 ghi đè: <span data-testid="metric-value">{m.text}</span>
      {m.note ? ` (${m.note})` : ""}
    </p>
  );
}

/** Khối "Ca thiếu tài liệu (E3)" ở cột phải. */
export function E3Section({ data }: { data: Business }) {
  const cases = metric(data, "e3_cases");
  return (
    <section aria-labelledby="e3-cases" className="flex flex-col gap-2">
      <Heading id="e3-cases" text={MA_KET_THUC.E3!.nhan} ma="E3" field="e3_cases" />
      {usable(data, "e3_cases") && cases ? (
        <div className="overflow-hidden rounded-group border border-line">
          <E3List cases={cases} />
        </div>
      ) : (
        <StateLine data={data} name="e3_cases" />
      )}
    </section>
  );
}
