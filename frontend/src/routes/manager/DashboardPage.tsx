import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, routeMissing } from "../../api/errors.ts";
import { Segmented } from "../../components/Segmented.tsx";
import { Forbidden } from "../Forbidden.tsx";
import { AiDashboardView } from "./AiDashboard.tsx";
import { OpenAlertsBlock } from "./Alerts.tsx";
import { BusinessKpis, BusinessSections, E3Section } from "./BusinessDashboard.tsx";
import { DASHBOARD_MISSING_TITLE } from "./metrics.ts";
import { LoadError, MissingPanel, MockNote } from "./panels.tsx";
import { aiQuery, businessQuery, DEFAULT_RANGE, RANGES, type RangeKey, vnDateTime } from "./range.ts";

// B4MgrDashboard — trang đầu của Trưởng BP IT (`dashboard:read:all`, 12b Q-fe-8). Tab "Nghiệp vụ | AI" trong CÙNG trang
// (F5 P1). Route CHƯA CÓ — M9 A3: MSW ở dev:mock; dev thật → 404 "Not Found" → "Tổng quan có từ M9 (chặng A3)" (không
// khối lỗi đỏ). Lỗi (vd 503 `monitor_unavailable`) → CHỈ hiện lỗi, KHÔNG số cũ: TanStack Query giữ `data` cũ khi tải lại
// cùng khoá thất bại → luôn kiểm `isError` TRƯỚC khi đọc `data` (F5 P5; KH mục 5).

type Tab = "business" | "ai";
const TABS: readonly { key: Tab; label: string }[] = [
  { key: "business", label: "Nghiệp vụ" },
  { key: "ai", label: "AI" },
];

const MISSING_TEXT = "Máy chủ chưa có số liệu tổng quan. Khi chặng A3 của M9 được gộp, màn này tự hiện số thật — không cần sửa giao diện.";

export function DashboardPage() {
  const queryClient = useQueryClient();
  const [range, setRange] = useState<RangeKey>(DEFAULT_RANGE);
  const [tab, setTab] = useState<Tab>("business");
  const business = useQuery({ ...businessQuery(range), enabled: tab === "business" });
  const ai = useQuery({ ...aiQuery(range), enabled: tab === "ai" });
  const active = tab === "business" ? business : ai;

  if (active.error instanceof ApiError && active.error.status === 403) return <Forbidden />;
  const missing = routeMissing(active.error);
  const shown = active.isError ? null : (active.data ?? null);

  function reload() {
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["alerts"] });
  }

  return (
    <section className="flex flex-col gap-6 px-12 py-10">
      <div className="flex items-end gap-6">
        <div className="flex min-w-0 grow flex-col gap-1">
          <h1 className="text-title">Tổng quan</h1>
          <p data-testid="dashboard-window" className="text-ink-2">
            {shown
              ? `Từ ${vnDateTime(shown.from)} đến ${vnDateTime(shown.to)} (giờ Việt Nam) · chỉ tính ticket lá.`
              : "Giờ Việt Nam · chỉ tính ticket lá."}
          </p>
        </div>
        {missing ? null : <Segmented label="Khoảng thời gian" options={RANGES} value={range} onChange={setRange} />}
      </div>

      {missing ? (
        <MissingPanel testId="dashboard-missing" title={DASHBOARD_MISSING_TITLE} text={MISSING_TEXT} />
      ) : (
        <>
          <div className="flex items-center gap-3">
            <Segmented label="Loại số liệu" options={TABS} value={tab} onChange={setTab} />
            <button
              type="button"
              onClick={reload}
              disabled={active.isFetching}
              className="h-7.5 rounded-full bg-button-2 px-3.5 text-label text-fpt-blue disabled:opacity-60"
            >
              {active.isFetching ? "Đang tải…" : "Tải lại"}
            </button>
            <span className="grow" />
            <MockNote text="số liệu thật có từ M9 (chặng A3)" />
          </div>
          {tab === "business" ? <BusinessTab query={business} /> : <AiTab query={ai} />}
        </>
      )}
    </section>
  );
}

type Q<T> = { isError: boolean; error: unknown; isPending: boolean; data: T | undefined };

function BusinessTab({ query }: { query: Q<Parameters<typeof BusinessKpis>[0]["data"]> }) {
  // Lỗi → chỉ khối lỗi (KHÔNG BAO GIỜ kèm số cũ); đang tải lần đầu → chữ chờ.
  const data = query.isError ? null : (query.data ?? null);
  return (
    <>
      {query.isError ? (
        <LoadError error={query.error} what="số liệu" />
      ) : data ? (
        <BusinessKpis data={data} />
      ) : (
        <p className="text-ink-2">Đang tải số liệu…</p>
      )}
      <div className="grid grid-cols-[minmax(0,1fr)_400px] gap-6">
        {data ? <BusinessSections data={data} /> : <div />}
        <div className="flex min-w-0 flex-col gap-5">
          <OpenAlertsBlock />
          {data ? <E3Section data={data} /> : null}
        </div>
      </div>
    </>
  );
}

function AiTab({ query }: { query: Q<Parameters<typeof AiDashboardView>[0]["data"]> }) {
  if (query.isError) return <LoadError error={query.error} what="số liệu AI" />;
  if (query.data === undefined) return <p className="text-ink-2">Đang tải số liệu…</p>;
  return <AiDashboardView data={query.data} />;
}
