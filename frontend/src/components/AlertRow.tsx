import { useState } from "react";
import type { AlertItem } from "../api/types.ts";
import { alertLabel, alertMa, audienceLabel, formatNumber, severityDot, severityLabel } from "../routes/manager/metrics.ts";
import { Ma } from "./MaNhan.tsx";
import { vnDateTime } from "../routes/manager/range.ts";
import { FlatTable } from "./ActionView.tsx";

// Một dòng cảnh báo (B4MgrDashboard khối "Cảnh báo đang mở"; màn Cảnh báo). Nhãn tiếng Việt theo `rule_id` (lạ → mã
// nguyên); chấm màu theo severity (chỉ token); `subject` là id → hiện nguyên; `detail` (JSONB) → bảng khoá–giá trị CHỮ
// THÔ (không Markdown/HTML). `audience` → nhãn người nhận (chỉ bản đầy đủ; nhãn, không lọc). Nút "Đã xem" chỉ khi còn mở
// và người xem được ack.
export function AlertRow({
  alert,
  onAck,
  acking = false,
  compact = false,
}: {
  alert: AlertItem;
  onAck?: (id: number) => void;
  acking?: boolean;
  compact?: boolean;
}) {
  const [showDetail, setShowDetail] = useState(false);
  const detailId = `alert-detail-${alert.alert_id}`;
  const detailEmpty = alert.detail === null || typeof alert.detail !== "object" || Object.keys(alert.detail).length === 0;
  return (
    <li
      data-testid="alert-row"
      data-alert-id={alert.alert_id}
      data-severity={alert.severity}
      data-status={alert.status}
      className="border-t border-line first:border-t-0 motion-safe:animate-rise-in"
    >
      <div className="grid grid-cols-[7px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3">
        <span className={`size-1.75 rounded-full ${severityDot(alert.severity)}`} aria-hidden="true" />
        <span className="flex min-w-0 flex-col">
          <span className="text-secondary">
            {alertLabel(alert.rule_id)}
            {alertMa(alert.rule_id) ? (
              <>
                {" · "}
                <Ma ma={alertMa(alert.rule_id)!} />
              </>
            ) : null}
            <span className="sr-only"> — mức {severityLabel(alert.severity)}</span>
          </span>
          <span className="truncate text-label font-normal text-ink-2">
            <span className="font-mono">{alert.rule_id}</span>
            {alert.subject ? (
              <>
                {" · "}
                <span className="font-mono">{alert.subject}</span>
              </>
            ) : null}
            {" · "}
            {vnDateTime(alert.window_start)}
            {typeof alert.value === "number" ? ` · giá trị ${formatNumber(alert.value, "number")}` : ""}
          </span>
          {!compact && alert.audience.length > 0 ? (
            <span data-testid="alert-audience" className="text-label font-normal text-ink-2">
              Người nhận: {alert.audience.map(audienceLabel).join(", ")}
            </span>
          ) : null}
          {alert.status === "acked" ? (
            <span data-testid="alert-acked" className="text-label font-normal text-ink-2">
              Đã xem{alert.acked_by ? ` · ${alert.acked_by}` : ""}
              {alert.acked_at ? ` · ${vnDateTime(alert.acked_at)}` : ""}
            </span>
          ) : null}
        </span>
        <span className="flex items-center gap-2">
          {compact ? null : (
            <button
              type="button"
              aria-expanded={showDetail}
              aria-controls={detailId}
              onClick={() => setShowDetail((v) => !v)}
              className="h-7.5 rounded-full px-3 text-label text-fpt-blue hover:bg-group"
            >
              Chi tiết
            </button>
          )}
          {alert.status === "open" && onAck ? (
            <button
              type="button"
              disabled={acking}
              onClick={() => onAck(alert.alert_id)}
              className="h-7.5 rounded-full bg-button-2 px-3 text-label text-fpt-blue disabled:opacity-60"
            >
              {acking ? "Đang gửi…" : "Đã xem"}
            </button>
          ) : null}
        </span>
      </div>
      {!compact && showDetail ? (
        <div id={detailId} data-testid="alert-detail" className="border-t border-line bg-group">
          {detailEmpty ? (
            <p className="px-5 py-2.5 text-secondary text-ink-2">Không có chi tiết.</p>
          ) : (
            <FlatTable value={alert.detail} testId="alert-detail-row" />
          )}
        </div>
      ) : null}
    </li>
  );
}
