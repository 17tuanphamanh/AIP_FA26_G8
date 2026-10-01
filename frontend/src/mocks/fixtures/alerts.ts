// Dữ liệu GIẢ cho Cảnh báo (F5 P8) — chỉ nạp khi dev:mock. Cột theo bảng `alerts` (backend/app/db/models.py `Alert`),
// `rule_id` theo ke-hoach-m9-monitor.md mục 6; `subject` theo bảng subject của mục 6 (ticket_id / user_id / "" cho luật
// tổng hợp); `detail` chỉ id, số đếm, ngưỡng (§4.4.5). Ticket dùng mã `tkt-demo-*` (check:dist chặn lọt bản build).
// Hai id ĐẶC BIỆT (nằm trong "Đang mở"):
//   ALERT_ACKED_ELSEWHERE_ID → ack trả 409 (người khác vừa xác nhận ở tab khác) — sau đó danh sách thấy đã xem;
//   ALERT_GONE_ID            → ack trả 404 (cảnh báo không còn) — sau đó biến khỏi danh sách.
// Xoá khi: M9 A3 merge (gen:api) — xoá cùng mocks/handlers/alerts.ts.
import type { AlertItem } from "../../api/types.ts";

export const ALERT_ACKED_ELSEWHERE_ID = 9409;
export const ALERT_GONE_ID = 9404;

const MIN = 60_000;

export function buildAlerts(now: number): AlertItem[] {
  const at = (minutesAgo: number) => new Date(now - minutesAgo * MIN).toISOString();
  const open = (alert_id: number, rule_id: string, subject: string, severity: string, minutesAgo: number, value: number | null, detail: Record<string, unknown>): AlertItem => ({
    alert_id,
    rule_id,
    subject,
    severity,
    value,
    window_start: at(minutesAgo),
    status: "open",
    detail,
    acked_by: null,
    acked_at: null,
    created_at: at(minutesAgo - 1),
  });
  return [
    open(1001, "password_bruteforce", "nv004", "critical", 25, 5, { failures: 5, window_minutes: 10, source: "auth" }),
    open(1002, "escalation_rate_high", "", "warning", 300, 0.43, { threshold: 0.4, window_days: 7 }),
    open(1003, "injection_detected", "tkt-demo-e0-01", "critical", 95, null, { exit_code: "E0", block_reason: "injection_detected" }),
    open(1004, "e9_spike", "", "warning", 140, 7, { count: 7, median_7d: 1, factor: 3 }),
    open(1005, "policy_saved", "13", "info", 1500, null, { version: "13" }),
    open(1006, "execution_failed", "tkt-demo-e7-01", "critical", 60, null, { reason_detail: "exec_interrupted" }),
    open(1007, "custom_rule_x", "", "info", 2000, null, {}), // rule_id lạ → giao diện hiện nguyên mã
    open(ALERT_ACKED_ELSEWHERE_ID, "refresh_reuse", "nv002", "critical", 40, null, { revoked_sessions: 2 }),
    open(ALERT_GONE_ID, "permission_denied_burst", "nv005", "warning", 180, 12, { count: 12, window_minutes: 5 }),
    {
      ...open(1008, "llm_budget", "", "critical", 2900, 30.4, { cap_usd: 38, warn_ratio: 0.8 }),
      status: "acked",
      acked_by: "it_mgr01",
      acked_at: at(2800),
    },
  ];
}
