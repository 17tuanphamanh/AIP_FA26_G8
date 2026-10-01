// Hàm thuần cho Tổng quan + Cảnh báo (F5 P3, P6). Không gọi mạng, không đọc đồng hồ.
// Chỉ số (ke-hoach-m9-monitor.md §4.3 [Chốt]): "chưa có nguồn" (tên trong `unavailable`) ≠ "đã đo, không có ca" (null)
// ≠ "đã đo, bằng 0" (0). KHÔNG BAO GIỜ hiện 0 thay cho null/unavailable — 0 là sai sự thật và che lỗ hổng.
import type { AlertItem } from "../../api/types.ts";

export type MetricKind = "rate" | "count" | "number";
export type MetricState = "value" | "empty" | "unavailable";
export type MetricText = { state: MetricState; text: string; note: string | null };

export const UNAVAILABLE_TEXT = "Chưa có dữ liệu";
export const EMPTY_TEXT = "—";
export const EMPTY_NOTE = "Không có ticket trong khoảng này";
export const MONITOR_DOWN_TEXT = "Số liệu tạm thời không có";
export const DASHBOARD_MISSING_TITLE = "Tổng quan có từ M9 (chặng A3)";
export const ALERTS_MISSING_TITLE = "Cảnh báo có từ M9 (chặng A3)";
export const POLICY_MISSING_TITLE = "Chính sách có từ Phase 7";

/** Chỉ số biết trước khi nào có nguồn (ke-hoach-m9-monitor.md §1.3, §5.1–5.2). */
const SOURCE_HINT: Record<string, string> = {
  override_count: "Nguồn có từ Phase 4 (chặng 4d)",
};

const NBSP = " ";
const decimal = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 });
const integer = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 });
const plain = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 2 });

/** Tỉ lệ 0..1 → "63 %", "12,5 %", "0 %". Khác 0 mà làm tròn ra 0 → "< 0,1 %" (không hiện 0 cho số khác 0). */
export function formatRate(value: number): string {
  const pct = value * 100;
  if (pct !== 0 && Math.abs(pct) < 0.05) return `<${NBSP}0,1${NBSP}%`;
  return `${decimal.format(pct)}${NBSP}%`;
}

export function formatNumber(value: number, kind: MetricKind): string {
  if (kind === "rate") return formatRate(value);
  if (kind === "count") return integer.format(value);
  return plain.format(value);
}

/**
 * Chữ hiện cho một chỉ số. Thứ tự: tên trong `unavailable` → "Chưa có dữ liệu" (+ nguồn có từ đâu nếu biết); thiếu
 * trường → cũng "Chưa có dữ liệu" (fail-closed, không bịa 0); null → "—" + "Không có ticket trong khoảng này"; số → định
 * dạng theo loại (0 thật → "0" / "0 %").
 */
export function metricText(name: string, value: unknown, unavailable: readonly string[], kind: MetricKind): MetricText {
  if (unavailable.includes(name)) return { state: "unavailable", text: UNAVAILABLE_TEXT, note: SOURCE_HINT[name] ?? null };
  if (value === undefined) return { state: "unavailable", text: UNAVAILABLE_TEXT, note: "Máy chủ không trả chỉ số này" };
  if (value === null) return { state: "empty", text: EMPTY_TEXT, note: EMPTY_NOTE };
  if (typeof value === "number" && Number.isFinite(value)) return { state: "value", text: formatNumber(value, kind), note: null };
  return { state: "value", text: JSON.stringify(value), note: null };
}

/** `decided_by` (domain/ticket_state.py RiskDecision: "rule" | "llm"); khoá lạ → hiện nguyên. */
export const DECIDED_BY_LABEL: Record<string, string> = { rule: "Luật cứng", llm: "Lớp AI" };

/** Lý do E1 (ke-hoach-m9-monitor.md §1.4 — 4 lý do của B3/B4) [Suy luận nhãn]; khoá lạ → hiện nguyên. */
export const E1_LABEL: Record<string, string> = {
  out_of_scope: "Ngoài phạm vi hỗ trợ",
  intent_low_confidence: "Chưa chắc ý định",
  multi_intent_not_enabled: "Nhiều ý (chưa bật)",
  intent_not_enabled: "Ý định chưa bật",
};

/** Tab AI (§5.2): thứ tự + nhãn + loại. Trường có hình dạng [Suy luận] (map, mảng) hiện theo dữ liệu. */
export const AI_METRICS: readonly { name: string; label: string; kind: MetricKind }[] = [
  { name: "tokens_per_ticket", label: "Token mỗi ticket", kind: "number" },
  { name: "cost_per_day", label: "Chi phí theo ngày (USD)", kind: "number" },
  { name: "latency_p95_by_step", label: "Độ trễ p95 theo bước (ms)", kind: "number" },
  { name: "cache_hit_rate", label: "Tỉ lệ trúng cache", kind: "rate" },
  { name: "json_invalid_first_try_rate", label: "JSON lỗi ở lần gọi đầu", kind: "rate" },
  { name: "fallback_rate", label: "Phải dùng model dự phòng", kind: "rate" },
  { name: "e2_llm_count", label: "Ca E2 do LLM lỗi", kind: "count" },
  { name: "e9_count", label: "Ca E9 (lỗi chưa lường trước)", kind: "count" },
  { name: "b2_llm_rate", label: "B2 phải xuống LLM (lớp 4)", kind: "rate" },
  { name: "intent_filter_fallback_rate", label: "B8 phải nới bộ lọc ý định", kind: "rate" },
  { name: "b3_llm_rate", label: "B3 phải xuống LLM", kind: "rate" },
  { name: "intent_model_version", label: "Phiên bản model ý định", kind: "number" },
];

// ---------------------------------------------------------------- cảnh báo

/** 16 luật của ke-hoach-m9-monitor.md mục 6 — một bảng hằng. `rule_id` lạ → hiện nguyên mã. */
export const ALERT_LABEL: Record<string, string> = {
  escalation_rate_high: "Tỉ lệ chuyển L2 (có trọng số) vượt 40%",
  injection_detected: "Yêu cầu bị chặn vì nghi chèn lệnh (E0)",
  password_bruteforce: "Dò mật khẩu — tài khoản bị khoá",
  e9_spike: "Lỗi chưa lường trước (E9) tăng đột biến",
  breaker_open: "Hệ thống bên ngoài lỗi liên tiếp — ngắt mạch mở",
  e6_spike: "Phiếu duyệt hết hạn (E6) tăng đột biến",
  reflex_approval: "Duyệt theo phản xạ (xem dưới 5 giây)",
  drift: "Phân bố dữ liệu lệch so với tuần mốc",
  refresh_reuse: "Phiên đăng nhập bị dùng lại",
  permission_denied_burst: "Bị từ chối quyền dồn dập",
  policy_saved: "Chính sách vừa được lưu",
  b2_degraded: "Sàng lọc B2 xuống LLM quá 30%",
  b3_degraded: "Phân loại B3 xuống LLM quá 30%",
  llm_budget: "Sắp hết ngân sách LLM",
  finalize_failed: "Ghi kết thúc ticket thất bại",
  execution_failed: "Thực thi thất bại (E7)",
};
export const alertLabel = (ruleId: string): string => ALERT_LABEL[ruleId] ?? ruleId;

const SEVERITY_RANK: Record<string, number> = { critical: 0, warning: 1, info: 2 };
export const SEVERITY_LABEL: Record<string, string> = { critical: "Nghiêm trọng", warning: "Cần chú ý", info: "Thông tin" };
/** Chỉ token (tokens.css): critical → danger, warning → cam, info/lạ → xám. */
export const SEVERITY_DOT: Record<string, string> = { critical: "bg-danger", warning: "bg-fpt-orange", info: "bg-ink-3" };
export const severityDot = (severity: string): string => SEVERITY_DOT[severity] ?? "bg-ink-3";
export const severityLabel = (severity: string): string => SEVERITY_LABEL[severity] ?? severity;

/** Q-fe-27: critical → warning → info (lạ xuống cuối), rồi `window_start` giảm dần — ca nghiêm trọng luôn ở trên. */
export function sortAlerts(items: readonly AlertItem[]): AlertItem[] {
  const rank = (a: AlertItem) => SEVERITY_RANK[a.severity] ?? 3;
  const at = (a: AlertItem) => {
    const t = Date.parse(a.window_start);
    return Number.isNaN(t) ? Number.NEGATIVE_INFINITY : t;
  };
  return [...items].sort((a, b) => rank(a) - rank(b) || at(b) - at(a) || b.alert_id - a.alert_id);
}

export const ACK_CONFLICT_TEXT = "Cảnh báo này đã được xác nhận trước đó";
export const ACK_GONE_TEXT = "Cảnh báo không còn";
export const ACK_DONE_TEXT = "Đã xác nhận cảnh báo";
export const DASHBOARD_ALERT_LIMIT = 5;
