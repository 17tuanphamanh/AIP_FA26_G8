import type { BusinessDashboard as Business, E3Case } from "../../api/types.ts";
import { DECIDED_BY_LABEL, E1_LABEL, type MetricKind, metricText } from "./metrics.ts";
import { vnDate } from "./range.ts";

// B4MgrDashboard — dashboard nghiệp vụ (ke-hoach-m9-monitor.md §5.1, tên trường giữ nguyên). Component này CHỈ vẽ dữ
// liệu đã tải thành công; trạng thái tải/lỗi do DashboardPage lo (lỗi → không gọi tới đây → không còn số cũ).
// Mọi ô số đi qua `metricText`: unavailable → "Chưa có dữ liệu", null → "—", 0 thật → "0" (F5 P3).

function Kpi({ data, name, label, kind, extra }: { data: Business; name: keyof Business; label: string; kind: MetricKind; extra?: string }) {
  const m = metricText(name, data[name], data.unavailable, kind);
  return (
    <div data-testid="kpi" data-metric={name} data-state={m.state} className="flex flex-col gap-0.5 rounded-group bg-group px-5 py-4.5">
      <span className="text-secondary text-ink-2">{label}</span>
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
function Heading({ id, text, field }: { id: string; text: string; field: string }) {
  return (
    <h2 id={id} className="pl-1 text-label text-ink-2">
      {text} · <span className="font-mono font-normal">{field}</span>
    </h2>
  );
}

/** Khối có thể "chưa có dữ liệu" / null (không ca) — chỉ hiện nội dung khi có giá trị. */
function StateLine({ data, name }: { data: Business; name: keyof Business }) {
  const m = metricText(name, data[name], data.unavailable, "number");
  return (
    <p data-testid={`metric-${name}`} data-state={m.state} className="rounded-group border border-line px-5 py-3.5 text-secondary text-ink-2">
      {m.text}
      {m.note ? ` · ${m.note}` : ""}
    </p>
  );
}

const usable = (data: Business, name: keyof Business) => !data.unavailable.includes(name) && data[name] !== null && data[name] !== undefined;

function Bars({ values, labels }: { values: Record<string, number>; labels: Record<string, string> }) {
  const entries = Object.entries(values);
  const total = entries.reduce((sum, [, n]) => sum + (Number.isFinite(n) ? n : 0), 0);
  if (entries.length === 0 || total === 0) return <p className="px-5 py-3.5 text-secondary text-ink-2">Không có ticket trong khoảng này.</p>;
  return (
    <div className="flex flex-col gap-3.5 px-5 py-4.5">
      {entries.map(([key, n], i) => (
        <div key={key} data-testid="bar-row" data-key={key} className="grid grid-cols-[120px_minmax(0,1fr)_56px] items-center gap-3">
          <span className="truncate text-secondary">{labels[key] ?? key}</span>
          <span className="h-2.5 rounded-full bg-button-2">
            <span className={`block h-2.5 rounded-full ${i === 0 ? "bg-fpt-blue" : "bg-send"}`} style={{ width: `${Math.round((n / total) * 100)}%` }} />
          </span>
          <span className="text-right text-secondary tabular-nums">{metricText(key, n, [], "count").text}</span>
        </div>
      ))}
    </div>
  );
}

function E3List({ cases }: { cases: E3Case[] }) {
  if (cases.length === 0) return <p className="px-4 py-3 text-secondary text-ink-2">Không có ca E3 trong khoảng này.</p>;
  return (
    <ul aria-label="Ca thiếu tài liệu">
      {cases.map((c) => (
        <li key={c.ticket_id} data-testid="e3-case" className="flex flex-col border-t border-line px-4 py-2.5 first:border-t-0">
          {/* Chữ thô (React tự thoát) — request_excerpt có "<b>" vẫn hiện nguyên văn. */}
          <span data-testid="e3-excerpt" className="truncate text-secondary">
            “{c.request_excerpt}”
          </span>
          <span className="truncate text-label font-normal text-ink-2">
            {c.intent} · {vnDate(c.created_at)} · KB {c.kb_version} · <span className="font-mono">{c.ticket_id}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function BusinessKpis({ data }: { data: Business }) {
  const raw = metricText("escalation_rate_raw", data.escalation_rate_raw, data.unavailable, "rate");
  return (
    <div className="grid grid-cols-4 gap-4">
      <Kpi data={data} name="automation_rate" label="Tự xử lý" kind="rate" />
      <Kpi data={data} name="escalation_rate_weighted" label="Chuyển L2 (có trọng số)" kind="rate" extra={`thô ${raw.text}`} />
      <Kpi data={data} name="deflection_rate" label="Trả lời bằng tài liệu" kind="rate" />
      <Kpi data={data} name="approval_expired_count" label="Hết hạn duyệt" kind="count" extra="tự chuyển L2" />
    </div>
  );
}

/** Cột trái của B4MgrDashboard. */
export function BusinessSections({ data }: { data: Business }) {
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <section aria-labelledby="decided-by" className="flex flex-col gap-2">
        <Heading id="decided-by" text="Ai quyết định mức rủi ro" field="decided_by_distribution" />
        {usable(data, "decided_by_distribution") ? (
          <div className="rounded-group border border-line">
            <Bars values={data.decided_by_distribution!} labels={DECIDED_BY_LABEL} />
          </div>
        ) : (
          <StateLine data={data} name="decided_by_distribution" />
        )}
      </section>

      <section aria-labelledby="top-rules" className="flex flex-col gap-2">
        <Heading id="top-rules" text="Luật khớp nhiều nhất" field="top_matched_rules" />
        {usable(data, "top_matched_rules") ? (
          data.top_matched_rules!.length === 0 ? (
            <p className="rounded-group border border-line px-5 py-3.5 text-secondary text-ink-2">Không có luật nào khớp trong khoảng này.</p>
          ) : (
            <ul className="overflow-hidden rounded-group border border-line">
              {data.top_matched_rules!.map((r) => (
                <li key={r.rule_id} data-testid="rule-row" className="flex h-11 items-center gap-3 border-t border-line px-5 first:border-t-0">
                  <span className="grow font-mono text-label font-normal">{r.rule_id}</span>
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
        <Heading id="e1-split" text="Ca không xác định được ý định (E1)" field="e1_split" />
        {usable(data, "e1_split") ? (
          <div className="rounded-group border border-line">
            <Bars values={data.e1_split!} labels={E1_LABEL} />
          </div>
        ) : (
          <StateLine data={data} name="e1_split" />
        )}
      </section>
    </div>
  );
}

/** Bản 4: "Số lần L1 ghi đè: chưa có dữ liệu (nguồn có từ Phase 4)." */
function OverrideLine({ data }: { data: Business }) {
  const m = metricText("override_count", data.override_count, data.unavailable, "count");
  return (
    <p data-testid="metric-override_count" data-state={m.state} className="pl-1 text-label font-normal text-ink-2">
      Số lần L1 ghi đè: <span data-testid="metric-value">{m.text}</span>
      {m.note ? ` (${m.note})` : ""}
    </p>
  );
}

/** Khối "Ca thiếu tài liệu (E3)" ở cột phải. */
export function E3Section({ data }: { data: Business }) {
  return (
    <section aria-labelledby="e3-cases" className="flex flex-col gap-2">
      <Heading id="e3-cases" text="Ca thiếu tài liệu (E3)" field="e3_cases" />
      {usable(data, "e3_cases") ? (
        <div className="overflow-hidden rounded-group border border-line">
          <E3List cases={data.e3_cases!} />
        </div>
      ) : (
        <StateLine data={data} name="e3_cases" />
      )}
    </section>
  );
}
