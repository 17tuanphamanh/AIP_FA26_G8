import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, routeMissing } from "../../api/errors.ts";
import { Segmented } from "../../components/Segmented.tsx";
import { Forbidden } from "../Forbidden.tsx";
import { AiDashboardView } from "./AiDashboard.tsx";
import { OpenAlertsBlock } from "./Alerts.tsx";
import { BusinessKpis, BusinessSections, E3Section } from "./BusinessDashboard.tsx";
import { DASH_SOURCES, DASHBOARD_MISSING_TITLE, sourceViewText, WINDOW_INVALID_TEXT } from "./metrics.ts";
import { LoadError, MissingPanel } from "./panels.tsx";
import { aiQuery, businessQuery, DEFAULT_RANGE, RANGES, type RangeKey, strategiesQuery, vnDateTime } from "./range.ts";
import { StrategyCompareTab } from "./StrategyCompare.tsx";
import type { DashboardSource, StrategySource } from "../../api/types.ts";

// B4MgrDashboard — trang đầu của Trưởng BP IT (`dashboard:read:all`, 12b Q-fe-8). Tab "Nghiệp vụ | AI | So sánh phương án"
// trong CÙNG trang (F5 P1; N-PA P3 — tab thứ 3 dùng chung khoảng thời gian, route chưa có → khối báo TRONG tab, giữ hàng tab). Route thật M9 A3 (không còn MSW). Backend cũ chưa có route → 404 "Not Found" → "Tổng quan có từ M9 (chặng A3)"
// (không khối lỗi đỏ). Lỗi (503 `monitor_unavailable`, 422 cửa sổ, 500…) → CHỈ hiện lỗi, KHÔNG số cũ: TanStack Query giữ
// `data` cũ khi tải lại cùng khoá thất bại → luôn kiểm `isError` TRƯỚC khi đọc `data` (F5 P5; KH mục 5).

type Tab = "business" | "ai" | "strategies";
const TABS: readonly { key: Tab; label: string }[] = [
  { key: "business", label: "Nghiệp vụ" },
  { key: "ai", label: "AI" },
  { key: "strategies", label: "So sánh phương án" },
];

const MISSING_TEXT = "Máy chủ chưa có số liệu tổng quan. Khi chặng A3 của M9 được gộp, màn này tự hiện số thật — không cần sửa giao diện.";

export function DashboardPage() {
  const queryClient = useQueryClient();
  const [range, setRange] = useState<RangeKey>(DEFAULT_RANGE);
  const [tab, setTab] = useState<Tab>("business");
  // B1: nguồn ticket của Nghiệp vụ / AI (mặc định chỉ ticket thật). Tab So sánh có ô nguồn real|sim riêng.
  const [dashSource, setDashSource] = useState<DashboardSource>("real");
  const business = useQuery({ ...businessQuery(range, dashSource), enabled: tab === "business" });
  const ai = useQuery({ ...aiQuery(range, dashSource), enabled: tab === "ai" });
  const [source, setSource] = useState<StrategySource>("real");
  const strategies = useQuery({ ...strategiesQuery(range, source), enabled: tab === "strategies" });
  const active = tab === "business" ? business : tab === "ai" ? ai : strategies;

  if (active.error instanceof ApiError && active.error.status === 403) return <Forbidden />;
  // Route chưa có: Nghiệp vụ / AI → cả trang báo chưa có (như cũ); So sánh phương án → báo trong tab, giữ hàng tab.
  const missing = tab !== "strategies" && routeMissing(active.error);
  const shown = active.isError ? null : (active.data ?? null);
  const viewing = tab !== "strategies" && shown && "source" in shown ? sourceViewText(shown.source as DashboardSource | undefined) : null;

  function reload() {
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["alerts"] });
  }

  return (
    <section className="flex flex-col gap-6 px-12 py-10 max-lg:px-4 max-lg:py-6">
      <div className="flex items-end gap-6 max-lg:flex-wrap max-lg:items-start max-lg:gap-3">
        <div className="flex min-w-0 grow flex-col gap-1 max-lg:basis-full">
          <h1 className="text-title">Tổng quan</h1>
          <p data-testid="dashboard-window" className="text-ink-2">
            {shown
              ? `Từ ${vnDateTime(shown.from)} đến ${vnDateTime(shown.to)} (giờ Việt Nam) · chỉ tính yêu cầu lá đã kết thúc.`
              : "Giờ Việt Nam · chỉ tính yêu cầu lá đã kết thúc."}
          </p>
          {viewing ? (
            <p data-testid="dashboard-source" className="text-ink-2">
              {viewing}
            </p>
          ) : null}
        </div>
        {missing ? null : <Segmented label="Khoảng thời gian" options={RANGES} value={range} onChange={setRange} />}
      </div>

      {missing ? (
        <MissingPanel testId="dashboard-missing" title={DASHBOARD_MISSING_TITLE} text={MISSING_TEXT} />
      ) : (
        <>
          <div className="flex items-center gap-3 max-lg:flex-wrap">
            <Segmented label="Loại số liệu" options={TABS} value={tab} onChange={setTab} />
            {tab === "strategies" ? null : (
              <Segmented label="Nguồn ticket" options={DASH_SOURCES} value={dashSource} onChange={setDashSource} />
            )}
            <button
              type="button"
              onClick={reload}
              disabled={active.isFetching}
              className="h-7.5 rounded-full bg-button-2 px-3.5 text-label text-fpt-blue disabled:opacity-60 max-lg:min-h-11"
            >
              {active.isFetching ? "Đang tải…" : "Tải lại"}
            </button>
          </div>
          {tab === "business" ? (
            <BusinessTab query={business} range={range} />
          ) : tab === "ai" ? (
            <AiTab query={ai} />
          ) : (
            <StrategyCompareTab query={strategies} source={source} onSource={setSource} />
          )}
        </>
      )}
    </section>
  );
}

type Q<T> = { isError: boolean; error: unknown; isPending: boolean; data: T | undefined };

function BusinessTab({ query, range }: { query: Q<Parameters<typeof BusinessKpis>[0]["data"]>; range: RangeKey }) {
  // Lỗi → chỉ khối lỗi (KHÔNG BAO GIỜ kèm số cũ); đang tải lần đầu → chữ chờ.
  const data = query.isError ? null : (query.data ?? null);
  return (
    <>
      {query.isError ? (
        <LoadError error={query.error} what="số liệu" invalid={WINDOW_INVALID_TEXT} />
      ) : data ? (
        <BusinessKpis data={data} />
      ) : (
        <p className="text-ink-2 motion-safe:animate-pulse">Đang tải số liệu…</p>
      )}
      <div className="grid grid-cols-[minmax(0,1fr)_400px] gap-6 max-lg:grid-cols-1">
        {data ? <BusinessSections data={data} /> : <div />}
        <div className="flex min-w-0 flex-col gap-5">
          <OpenAlertsBlock range={range} />
          {data ? <E3Section data={data} /> : null}
        </div>
      </div>
    </>
  );
}

function AiTab({ query }: { query: Q<Parameters<typeof AiDashboardView>[0]["data"]> }) {
  if (query.isError) return <LoadError error={query.error} what="số liệu AI" invalid={WINDOW_INVALID_TEXT} />;
  if (query.data === undefined) return <p className="text-ink-2 motion-safe:animate-pulse">Đang tải số liệu…</p>;
  return <AiDashboardView data={query.data} />;
}
