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

/** Chỉ số biết trước khi nào có nguồn (ke-hoach-m9-monitor.md §1.3, §5.2; backend monitor/metrics.py "pending"). */
const SOURCE_HINT: Record<string, string> = {
  multi_intent_first_stop_to_reply_s: "Nguồn có từ Phase 5",
  multi_intent_messages_per_turn: "Nguồn có từ Phase 5",
};

/**
 * Tra bảng theo khoá RIÊNG của bảng (`Object.hasOwn`), không đi qua prototype: khoá do server trả hoặc người gõ (severity,
 * rule_id, audience, khoá map…) như "__proto__" / "constructor" / "toString" mà tra `X[k]` sẽ ra object/hàm của
 * Object.prototype → React vỡ màn hoặc hiện "function …". Không có → `fallback`.
 */
export function ownEntry<T>(table: Readonly<Record<string, T>>, key: string, fallback: NoInfer<T>): T {
  return Object.hasOwn(table, key) ? (table[key] as T) : fallback;
}
/** Nhãn theo khoá; khoá lạ → hiện nguyên khoá. */
export const labelOf = (table: Readonly<Record<string, string>>, key: string): string => ownEntry(table, key, key);

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

const usd = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 4 });

/** Chi phí USD: tối đa 4 chữ số thập phân; 0 thật → "0"; khác 0 mà làm tròn ra 0 → "< 0,0001". */
export function formatUsd(value: number): string {
  if (value !== 0 && Math.abs(value) < 0.00005) return `<${NBSP}0,0001`;
  return usd.format(value);
}

/** Độ trễ: làm tròn tới ms; khác 0 mà làm tròn ra 0 → "< 1 ms". */
export function formatMs(value: number): string {
  if (value !== 0 && Math.abs(value) < 0.5) return `<${NBSP}1${NBSP}ms`;
  return `${integer.format(Math.round(value))}${NBSP}ms`;
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
  if (unavailable.includes(name)) return { state: "unavailable", text: UNAVAILABLE_TEXT, note: ownEntry<string | null>(SOURCE_HINT, name, null) };
  if (value === undefined) return { state: "unavailable", text: UNAVAILABLE_TEXT, note: "Máy chủ không trả chỉ số này" };
  if (value === null) return { state: "empty", text: EMPTY_TEXT, note: EMPTY_NOTE };
  if (typeof value === "number" && Number.isFinite(value)) return { state: "value", text: formatNumber(value, kind), note: null };
  return { state: "value", text: JSON.stringify(value), note: null };
}

/** `decided_by` (domain/ticket_state.py RiskDecision: "rule" | "llm"); khoá lạ → hiện nguyên. */
export const DECIDED_BY_LABEL: Record<string, string> = { rule: "Luật cứng", llm: "Lớp AI" };

/** Lý do E1 (backend monitor/metrics.py E1_REASONS + "other") [Suy luận nhãn]; khoá lạ → hiện nguyên. */
export const E1_LABEL: Record<string, string> = {
  out_of_scope: "Ngoài phạm vi hỗ trợ",
  intent_low_confidence: "Chưa chắc ý định",
  multi_intent_not_enabled: "Nhiều ý (chưa bật)",
  intent_not_enabled: "Ý định chưa bật",
  other: "Lý do khác",
};

/**
 * Nhóm rủi ro của `escalation_rate_weighted.by_group`. Nhãn KHÔNG ghi con số trọng số — trọng số là của backend
 * (monitor/metrics.py), frontend không chép (chép là sớm muộn lệch). Khoá lạ → hiện nguyên.
 */
export const WEIGHT_GROUP_LABEL: Record<string, string> = { routine: "Thường", approval: "Cần duyệt", sensitive: "Nhạy cảm" };

/** Tab AI (§5.2; backend api/dashboard.py `AiMetrics` — đủ 14 khoá, đúng thứ tự): nhãn + loại. */
export const AI_METRICS: readonly { name: string; label: string; kind: MetricKind }[] = [
  { name: "tokens_per_ticket", label: "Token mỗi ticket", kind: "number" },
  { name: "cost_per_day", label: "Chi phí theo ngày (USD)", kind: "number" },
  { name: "latency_p95_by_step", label: "Độ trễ p95 theo bước", kind: "number" },
  { name: "cache_hit_rate", label: "Tỉ lệ trúng cache", kind: "rate" },
  { name: "json_invalid_first_try_rate", label: "JSON lỗi ở lần gọi đầu", kind: "rate" },
  { name: "fallback_rate", label: "Phải dùng model dự phòng", kind: "rate" },
  { name: "e2_llm_count", label: "Ca E2 do LLM lỗi", kind: "count" },
  { name: "e9_count", label: "Ca E9 (lỗi chưa lường trước)", kind: "count" },
  { name: "b2_llm_rate", label: "B2 phải xuống LLM (lớp 4)", kind: "rate" },
  { name: "intent_filter_fallback_rate", label: "B8 phải nới bộ lọc ý định", kind: "rate" },
  { name: "b3_llm_rate", label: "B3 phải xuống LLM", kind: "rate" },
  { name: "intent_model_version", label: "Phiên bản model ý định", kind: "number" },
  { name: "multi_intent_first_stop_to_reply_s", label: "Nhiều ý: từ lúc dừng đầu tới câu trả lời (giây)", kind: "number" },
  { name: "multi_intent_messages_per_turn", label: "Nhiều ý: số tin mỗi lượt", kind: "number" },
];
export const AI_NO_DATA_TEXT = "Không có dữ liệu trong khoảng này.";
export const INTENT_MODEL_MISSING_NOTE = "Chưa ghi nhận phiên bản model";
export const DAY_OPEN_NOTE = "chưa hết ngày";
export const E3_TRUNCATED_TEXT = "Chỉ hiện 100 ca mới nhất.";
export const WINDOW_INVALID_TEXT = "Khoảng thời gian không hợp lệ — kiểm tra ngày giờ của máy rồi tải lại.";

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
export const alertLabel = (ruleId: string): string => labelOf(ALERT_LABEL, ruleId);

const SEVERITY_RANK: Record<string, number> = { critical: 0, warning: 1, info: 2 };
export const SEVERITY_LABEL: Record<string, string> = { critical: "Nghiêm trọng", warning: "Cần chú ý", info: "Thông tin" };
/** Chỉ token (tokens.css): critical → danger, warning → cam, info/lạ → xám. */
export const SEVERITY_DOT: Record<string, string> = { critical: "bg-danger", warning: "bg-fpt-orange", info: "bg-ink-3" };
export const severityDot = (severity: string): string => ownEntry(SEVERITY_DOT, severity, "bg-ink-3");
export const severityLabel = (severity: string): string => labelOf(SEVERITY_LABEL, severity);

/** Q-fe-27: critical → warning → info (lạ xuống cuối), rồi `window_start` giảm dần — ca nghiêm trọng luôn ở trên. */
export function sortAlerts(items: readonly AlertItem[]): AlertItem[] {
  const rank = (a: AlertItem) => ownEntry(SEVERITY_RANK, a.severity, 3);
  const at = (a: AlertItem) => {
    const t = Date.parse(a.window_start);
    return Number.isNaN(t) ? Number.NEGATIVE_INFINITY : t;
  };
  return [...items].sort((a, b) => rank(a) - rank(b) || at(b) - at(a) || b.alert_id - a.alert_id);
}

/** `audience` (backend monitor/rules.py) — NHÃN người nhận, không lọc, không phải quyền. Giá trị lạ → hiện nguyên. */
export const AUDIENCE_LABEL: Record<string, string> = { manager: "Trưởng BP IT", dev: "Dev", ops: "Vận hành" };
export const audienceLabel = (audience: string): string => labelOf(AUDIENCE_LABEL, audience);

export const ALERTS_TRUNCATED_TEXT = "Chỉ hiện 200 cảnh báo mới nhất — còn cảnh báo cũ hơn chưa hiện.";
export const ACK_UNREADABLE_TEXT = "Đã gửi xác nhận nhưng không đọc được phản hồi — danh sách đã tải lại.";
export const ACK_CONFLICT_TEXT = "Cảnh báo này đã được xác nhận trước đó";
export const ACK_GONE_TEXT = "Cảnh báo không còn";
export const ACK_DONE_TEXT = "Đã xác nhận cảnh báo";
export const DASHBOARD_ALERT_LIMIT = 5;
