import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link } from "react-router";
import { type AlertFilter, alertsQuery } from "../../api/alerts.ts";
import { ApiError, routeMissing } from "../../api/errors.ts";
import type { AlertItem } from "../../api/types.ts";
import { hasPerm } from "../../auth/permissions.ts";
import { useMe } from "../../auth/useAuth.ts";
import { AlertRow } from "../../components/AlertRow.tsx";
import { Segmented } from "../../components/Segmented.tsx";
import { Forbidden } from "../Forbidden.tsx";
import { ALERTS_MISSING_TITLE, ALERTS_TRUNCATED_TEXT, DASHBOARD_ALERT_LIMIT, MONITOR_DOWN_TEXT, rule1WindowNote, sortAlerts } from "./metrics.ts";
import { LoadError, MissingPanel } from "./panels.tsx";
import { openAlertsQuery, type RangeKey } from "./range.ts";
import { type AckNotice, useAlertAck } from "./useAlertAck.ts";

// Cảnh báo (P10 §3.3, P9 §7): `GET /api/alerts?status=open` | "Tất cả" (không tham số — Q-fe-27) + "Đã xem"
// (`POST /api/alerts/{id}/ack`). Route thật M9 A3 (không còn MSW): thân `{items, truncated}` — server chỉ trả 200 cảnh
// báo mới nhất, `truncated` → băng báo (không phân trang). Bản 4 chưa vẽ màn riêng → theo khối "Cảnh báo đang mở" của
// B4MgrDashboard. Cảnh báo chỉ báo người — không thao tác nào đổi hành vi hệ thống.

const FILTERS: readonly { key: AlertFilter; label: string }[] = [
  { key: "open", label: "Đang mở" },
  { key: "all", label: "Tất cả" },
];

const MISSING_TEXT = "Máy chủ chưa có danh sách cảnh báo. Khi chặng A3 của M9 được gộp, màn này tự hiện cảnh báo thật — không cần sửa giao diện.";

function Notice({ notice }: { notice: AckNotice | null }) {
  if (!notice) return null;
  return notice.tone === "ok" ? (
    <p role="status" data-testid="ack-notice" className="text-secondary text-ink-2">
      {notice.text}
    </p>
  ) : (
    <p role="alert" data-testid="ack-notice" className="text-secondary text-danger">
      {notice.text}
    </p>
  );
}

function AlertList({ items, filter, canAck, ack }: { items: AlertItem[]; filter: AlertFilter; canAck: boolean; ack: ReturnType<typeof useAlertAck> }) {
  if (items.length === 0) {
    return (
      <p className="rounded-group bg-group px-5 py-4 text-ink-2">{filter === "open" ? "Không có cảnh báo đang mở." : "Chưa có cảnh báo nào."}</p>
    );
  }
  return (
    <ul aria-label="Cảnh báo" className="overflow-hidden rounded-group border border-line">
      {items.map((alert) => (
        <AlertRow key={alert.alert_id} alert={alert} onAck={canAck ? ack.ack : undefined} acking={ack.pending.has(alert.alert_id)} />
      ))}
    </ul>
  );
}

export function Alerts() {
  const me = useMe();
  const canAck = hasPerm(me, "alert:read"); // P9 §7: ack dùng cùng quyền alert:read
  const [filter, setFilter] = useState<AlertFilter>("open");
  const query = useQuery(alertsQuery(filter));
  const ack = useAlertAck();

  if (query.error instanceof ApiError && query.error.status === 403) return <Forbidden />;
  const missing = routeMissing(query.error);

  return (
    <section className="flex flex-col gap-6 px-12 py-10">
      <div className="flex items-end gap-6">
        <div className="flex min-w-0 grow flex-col gap-1">
          <h1 className="text-title">Cảnh báo</h1>
          <p className="text-ink-2">Cảnh báo chỉ báo người — hệ thống không tự đổi hành vi vì cảnh báo.</p>
        </div>
        {missing ? null : <Segmented label="Lọc cảnh báo" options={FILTERS} value={filter} onChange={setFilter} />}
      </div>
      <Notice notice={ack.notice} />
      {missing ? (
        <MissingPanel testId="alerts-missing" title={ALERTS_MISSING_TITLE} text={MISSING_TEXT} />
      ) : query.isError ? (
        <LoadError error={query.error} what="cảnh báo" />
      ) : query.isPending ? (
        <p className="text-ink-2 motion-safe:animate-pulse">Đang tải cảnh báo…</p>
      ) : (
        <>
          {query.data.truncated ? (
            <p role="status" data-testid="alerts-truncated" className="rounded-group bg-group px-5 py-3 text-secondary text-ink-2">
              {ALERTS_TRUNCATED_TEXT}
            </p>
          ) : null}
          <AlertList items={sortAlerts(query.data.items)} filter={filter} canAck={canAck} ack={ack} />
        </>
      )}
    </section>
  );
}

/**
 * Khối "Cảnh báo đang mở" của Tổng quan (B4MgrDashboard): tối đa 5 dòng, link "Tất cả" → /alerts. Đếm ở tiêu đề = số
 * server trả; `truncated` → "200+" (còn cảnh báo mở ngoài 200 — không nói "200" khi thật ra nhiều hơn). D13: chỉ cảnh báo
 * có `window_start` trong khung đang chọn (`from`/`to` như số liệu). API không cho biết số cảnh báo ngoài khung → không hiện
 * dòng "còn N ngoài khung". Cảnh báo luật 1 kèm một dòng ghi cửa sổ đo của luật (không theo khung đang chọn).
 */
export function OpenAlertsBlock({ range }: { range: RangeKey }) {
  const me = useMe();
  const canAck = hasPerm(me, "alert:read");
  const query = useQuery({ ...openAlertsQuery(range), enabled: canAck });
  const ack = useAlertAck();
  if (!canAck) return null;
  const forbidden = query.error instanceof ApiError && query.error.status === 403;
  if (forbidden) return null;

  let body;
  if (routeMissing(query.error)) {
    body = <p className="px-4 py-3 text-secondary text-ink-2">{ALERTS_MISSING_TITLE}.</p>;
  } else if (query.isError) {
    body = (
      <p role="alert" className="px-4 py-3 text-secondary text-danger">
        {query.error instanceof ApiError && query.error.status === 503 ? MONITOR_DOWN_TEXT : "Chưa tải được cảnh báo."}
      </p>
    );
  } else if (query.isPending) {
    body = <p className="px-4 py-3 text-secondary text-ink-2 motion-safe:animate-pulse">Đang tải cảnh báo…</p>;
  } else if (query.data.items.length === 0) {
    body = <p className="px-4 py-3 text-secondary text-ink-2">Không có cảnh báo đang mở.</p>;
  } else {
    body = (
      <ul aria-label="Cảnh báo đang mở">
        {sortAlerts(query.data.items)
          .slice(0, DASHBOARD_ALERT_LIMIT)
          .map((alert) => {
            const note = rule1WindowNote(alert);
            return (
              <Fragment key={alert.alert_id}>
                <AlertRow alert={alert} onAck={ack.ack} acking={ack.pending.has(alert.alert_id)} compact />
                {note ? (
                  <li data-testid="rule1-window-note" className="px-4 pb-3 text-label font-normal text-ink-2">
                    {note}
                  </li>
                ) : null}
              </Fragment>
            );
          })}
      </ul>
    );
  }

  return (
    <section aria-labelledby="open-alerts-heading" data-testid="open-alerts" className="flex flex-col gap-2">
      <div className="flex items-center px-1">
        <h2 id="open-alerts-heading" className="grow text-label text-ink-2">
          Cảnh báo đang mở{query.data && !query.isError ? ` · ${query.data.items.length}${query.data.truncated ? "+" : ""}` : ""}
        </h2>
        <Link to="/alerts" className="text-label text-fpt-blue">
          Tất cả
        </Link>
      </div>
      <div className="overflow-hidden rounded-group border border-line">{body}</div>
      <Notice notice={ack.notice} />
    </section>
  );
}
