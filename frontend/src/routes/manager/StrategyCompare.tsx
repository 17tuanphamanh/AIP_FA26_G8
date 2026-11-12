import { BAD_STRATEGIES, SOURCE_MISMATCH } from "../../api/dashboard.ts";
import { ApiError, errorMessage, routeMissing } from "../../api/errors.ts";
import type { StrategiesDashboard, StrategySource } from "../../api/types.ts";
import { Segmented } from "../../components/Segmented.tsx";
import { COMPARE_MISSING_TEXT, COMPARE_NOTE, cellText, intentCell, intentKeys, SIM_BAND, SOURCES, UNAVAILABLE_CELL } from "./compare.ts";
import { WINDOW_INVALID_TEXT } from "./metrics.ts";
import { LoadError, MissingPanel } from "./panels.tsx";
import { intentLabel, metricHint, metricLabel } from "./strategyLabels.ts";
import { strategyName } from "./strategyText.ts";

// Tab "So sánh phương án" (D-67 "Đo hiệu quả"; hợp đồng N-PA §2). Một cột mỗi `strategies[i]`, một dòng mỗi `metrics[j]` —
// ĐÚNG thứ tự server, không sắp. Không màu trạng thái, không mũi tên, không điểm tổng; chi phí LLM là một dòng như mọi
// dòng. Lỗi → chỉ khối lỗi, KHÔNG số cũ (không đọc `data` khi `isError`).

type Q = { isError: boolean; error: unknown; data: StrategiesDashboard | undefined };

export function StrategyCompareTab({ query, source, onSource }: { query: Q; source: StrategySource; onSource: (s: StrategySource) => void }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 self-start max-lg:flex-wrap">
        <span className="text-secondary text-ink-2">Nguồn số liệu</span>
        <Segmented label="Nguồn số liệu" options={SOURCES} value={source} onChange={onSource} />
      </div>
      <CompareBody query={query} />
    </div>
  );
}

function CompareBody({ query }: { query: Q }) {
  if (query.isError) {
    if (routeMissing(query.error)) return <MissingPanel testId="compare-missing" title="So sánh phương án" text={COMPARE_MISSING_TEXT} />;
    const api = query.error instanceof ApiError ? query.error : null;
    if (api?.status === 502 && (api.code === SOURCE_MISMATCH || api.code === BAD_STRATEGIES)) {
      return (
        <p role="alert" data-testid="compare-data-error" className="rounded-group bg-danger-bg px-5 py-4 text-danger-ink">
          {errorMessage(api)}
        </p>
      );
    }
    return <LoadError error={query.error} what="số liệu so sánh" invalid={WINDOW_INVALID_TEXT} />;
  }
  if (query.data === undefined) return <p className="text-ink-2 motion-safe:animate-pulse">Đang tải số liệu…</p>;
  return <CompareTable data={query.data} />;
}

const TH = "px-4 py-2.5 text-left font-normal text-ink-2";
const TD = "px-4 py-2.5 tabular-nums";

export function CompareTable({ data }: { data: StrategiesDashboard }) {
  const unavailable = new Set(data.unavailable);
  const intents = intentKeys(data.strategies, data.intent_mix);
  const shownKeys = new Set(data.metrics.map((m) => m.key));
  const extraUnavailable = data.unavailable.filter((k) => !shownKeys.has(k));
  return (
    <div data-testid="compare" data-source={data.source} className="flex flex-col gap-4">
      {data.source === "sim" ? (
        <p data-testid="compare-sim-band" className="rounded-group bg-orange-bg px-5 py-2.5 text-center font-semibold text-orange-ink">
          {SIM_BAND}
        </p>
      ) : null}
      <div className="overflow-x-auto rounded-group border border-line">
        <table data-testid="compare-table" className="w-full text-secondary max-lg:min-w-xl">
          <thead>
            <tr>
              <th scope="col" className={TH}>
                Chỉ số
              </th>
              {data.strategies.map((s) => (
                <th key={s} scope="col" data-testid="compare-col" data-strategy={s} className={TH}>
                  {strategyName(s)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.metrics.map((m, i) => (
              <tr key={`${m.key}-${i}`} data-testid="compare-row" data-key={m.key} className="border-t border-line">
                <th scope="row" className="px-4 py-2.5 text-left font-normal">
                  <span data-testid="metric-label">{metricLabel(m.key)}</span>
                  {metricHint(m.key) ? (
                    <span data-testid="metric-hint" className="block text-secondary text-ink-2">
                      {metricHint(m.key)}
                    </span>
                  ) : null}
                </th>
                {data.strategies.map((s) => (
                  <td key={s} data-testid="compare-cell" data-strategy={s} className={TD}>
                    {unavailable.has(m.key) ? UNAVAILABLE_CELL : cellText(m, Object.hasOwn(m.values, s) ? m.values[s]! : null)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {extraUnavailable.length > 0 ? (
        <p data-testid="compare-unavailable" className="text-secondary text-ink-2">
          {UNAVAILABLE_CELL}: {extraUnavailable.map(metricLabel).join(", ")}
        </p>
      ) : null}
      <p data-testid="compare-note" className="text-secondary text-ink-2">
        {COMPARE_NOTE}
      </p>

      <section aria-labelledby="intent-mix-heading" className="flex flex-col gap-2">
        <h3 id="intent-mix-heading" className="pl-1 text-label text-ink-2">
          Thành phần yêu cầu theo loại
        </h3>
        {intents.length === 0 ? (
          <p className="pl-1 text-secondary text-ink-2">Không có yêu cầu nào trong khoảng này.</p>
        ) : (
          <div className="overflow-x-auto rounded-group border border-line">
            <table data-testid="intent-mix" className="w-full text-secondary max-lg:min-w-xl">
              <thead>
                <tr>
                  <th scope="col" className={TH}>
                    Loại yêu cầu
                  </th>
                  {data.strategies.map((s) => (
                    <th key={s} scope="col" className={TH}>
                      {strategyName(s)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {intents.map((k) => (
                  <tr key={k} data-testid="intent-row" data-key={k} className="border-t border-line">
                    <th scope="row" className="px-4 py-2.5 text-left font-normal">
                      {intentLabel(k)}
                    </th>
                    {data.strategies.map((s) => (
                      <td key={s} data-testid="intent-cell" data-strategy={s} className={TD}>
                        {intentCell(data.intent_mix, s, k)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
