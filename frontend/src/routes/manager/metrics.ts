// Hàm thuần cho Tổng quan + Cảnh báo (F5 P3, P6). Không gọi mạng, không đọc đồng hồ.
// Chỉ số (ke-hoach-m9-monitor.md §4.3 [Chốt]): "chưa có nguồn" (tên trong `unavailable`) ≠ "đã đo, không có ca" (null)
// ≠ "đã đo, bằng 0" (0). KHÔNG BAO GIỜ hiện 0 thay cho null/unavailable — 0 là sai sự thật và che lỗ hổng.
import type { AlertItem, RatioCountTam } from "../../api/types.ts";
import { labelOf, ownEntry } from "../../lib/lookup.ts";
import { BEN_QUYET_DINH, KHAC } from "../../lib/nhan.ts";
import { vnDate } from "./range.ts";

export type MetricKind = "rate" | "count" | "number";
/** `insufficient` (D13): đã đo nhưng mẫu < `min_sample` → không hiện tỉ lệ. */
export type MetricState = "value" | "empty" | "unavailable" | "insufficient";
export type MetricText = { state: MetricState; text: string; note: string | null };

export const UNAVAILABLE_TEXT = "Chưa có dữ liệu";
export const EMPTY_TEXT = "—";
export const EMPTY_NOTE = "Không có yêu cầu trong khoảng này";
export const MONITOR_DOWN_TEXT = "Số liệu tạm thời không có";
export const DASHBOARD_MISSING_TITLE = "Tổng quan có từ M9 (chặng A3)";
export const ALERTS_MISSING_TITLE = "Cảnh báo có từ M9 (chặng A3)";
export const POLICY_MISSING_TITLE = "Chưa có chức năng chính sách";

/** Chỉ số biết trước khi nào có nguồn (ke-hoach-m9-monitor.md §1.3, §5.2; backend monitor/metrics.py "pending"). */
const SOURCE_HINT: Record<string, string> = {
  multi_intent_first_stop_to_reply_s: "Nguồn có từ Phase 5",
  multi_intent_messages_per_turn: "Nguồn có từ Phase 5",
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
 * trường → cũng "Chưa có dữ liệu" (fail-closed, không bịa 0); null → "—" + "Không có yêu cầu trong khoảng này"; số → định
 * dạng theo loại (0 thật → "0" / "0 %").
 */
export function metricText(name: string, value: unknown, unavailable: readonly string[], kind: MetricKind): MetricText {
  if (unavailable.includes(name)) return { state: "unavailable", text: UNAVAILABLE_TEXT, note: ownEntry<string | null>(SOURCE_HINT, name, null) };
  if (value === undefined) return { state: "unavailable", text: UNAVAILABLE_TEXT, note: "Máy chủ không trả chỉ số này" };
  if (value === null) return { state: "empty", text: EMPTY_TEXT, note: EMPTY_NOTE };
  if (typeof value === "number" && Number.isFinite(value)) return { state: "value", text: formatNumber(value, kind), note: null };
  return { state: "value", text: JSON.stringify(value), note: null };
}

// ---------------------------------------------------------------- số đếm tử/mẫu (D13)
// Quy tắc chung của trang Tổng quan (khớp ô tab So sánh — compare.ts `cellText`): unavailable → "Chưa có dữ liệu"; không có
// số đếm nào → "—"; có số đếm mà mẫu < ngưỡng (kể cả 0) → "chưa đủ dữ liệu (n=mẫu)"; đủ mẫu → "x % (a/b)". Ngưỡng: `min_sample`
// của server (tab So sánh: `MIN_SAMPLE` của compare.ts tới khi route gửi ngưỡng). Ngoại lệ có chủ đích (phiếu D13): dòng NHÓM
// của tỉ lệ có trọng số luôn hiện "a/b" (số đếm thành phần, tổng đã bị chặn ở KPI), chỉ thêm % khi nhóm đủ mẫu.

export const INSUFFICIENT_TEXT = "chưa đủ dữ liệu";
/** "chưa đủ dữ liệu (n=19)" — mẫu nhỏ hơn `min_sample` của backend (cùng chữ với `few` của compare.ts). */
export const insufficientText = (den: number): string => `${INSUFFICIENT_TEXT} (n=${integer.format(den)})`;
/** "13/20". */
export const fractionText = (num: number, den: number): string => `${integer.format(num)}/${integer.format(den)}`;

/**
 * Tỉ lệ đơn kèm tử/mẫu. unavailable / thiếu trường → như `metricText`; thiếu `count` hoặc `minSample` (backend trước D13)
 * → như `metricText` (chỉ %); `den < minSample` → "chưa đủ dữ liệu (n=den)" — kể cả den 0 (tỉ lệ null): KHÔNG "0 %",
 * KHÔNG "—"; còn lại "65 % (13/20)" (`formatRate` sẵn có — lệch nhỏ so với mẫu "xx,x%" của phiếu, để đồng bộ cả trang).
 */
export function countedRateText(
  name: string,
  value: unknown,
  count: RatioCountTam | null | undefined,
  minSample: number | undefined,
  unavailable: readonly string[],
): MetricText {
  const plainText = metricText(name, value, unavailable, "rate");
  if (plainText.state === "unavailable" || !count || minSample === undefined) return plainText;
  if (count.den < minSample) return { state: "insufficient", text: insufficientText(count.den), note: null };
  if (plainText.state !== "value") return plainText;
  return { ...plainText, text: `${plainText.text} (${fractionText(count.num, count.den)})` };
}

/** `decided_by` (rule / llm / model) — nhãn từ src/lib/nhan.ts (bảng ĐP 26/10 23:10); khoá lạ → hiện nguyên. */
export const DECIDED_BY_LABEL: Readonly<Record<string, string>> = BEN_QUYET_DINH;

/** Lý do E1 (backend monitor/metrics.py E1_REASONS + "other") [Suy luận nhãn]; khoá lạ → hiện nguyên. */
export const E1_LABEL: Record<string, string> = {
  out_of_scope: "Ngoài phạm vi hỗ trợ",
  intent_low_confidence: "Chưa chắc ý định",
  multi_intent_not_enabled: "Nhiều ý (chưa bật)",
  intent_not_enabled: "Ý định chưa bật",
  split_span_invalid: "Tách ý không hợp lệ",
  reverse_action_requested: "Xin thu hồi / khoá / gỡ / huỷ", // D-84 (12/11)
  other: "Lý do khác",
};

/**
 * Nhóm rủi ro của `escalation_rate_weighted.by_group`. Nhãn KHÔNG ghi con số trọng số — trọng số là của backend
 * (monitor/metrics.py), frontend không chép (chép là sớm muộn lệch). Khoá lạ → hiện nguyên.
 */
export const WEIGHT_GROUP_LABEL: Record<string, string> = { routine: "Thường", approval: "Cần duyệt", sensitive: "Nhạy cảm" };

/** Tab AI (§5.2; backend api/dashboard.py `AiMetrics` — đủ 14 khoá, đúng thứ tự): nhãn + loại. */
/** `ma`: mã bước / mã kết thúc liên quan — hiện SAU nhãn, chữ nhỏ (bảng ĐP 23:10: nhãn không chứa mã). */
export const AI_METRICS: readonly { name: string; label: string; kind: MetricKind; ma?: string }[] = [
  { name: "tokens_per_ticket", label: "Token mỗi yêu cầu", kind: "number" },
  { name: "cost_per_day", label: "Chi phí theo ngày (USD)", kind: "number" },
  { name: "latency_p95_by_step", label: "Độ trễ p95 theo bước", kind: "number" },
  { name: "cache_hit_rate", label: "Tỉ lệ trúng cache", kind: "rate" },
  { name: "json_invalid_first_try_rate", label: "JSON lỗi ở lần gọi đầu", kind: "rate" },
  { name: "fallback_rate", label: "Phải dùng model dự phòng", kind: "rate" },
  { name: "e2_llm_count", label: "Ca lỗi khi xử lý do AI", kind: "count", ma: "E2" },
  { name: "e9_count", label: "Ca lỗi hệ thống bất ngờ", kind: "count", ma: "E9" },
  { name: "b2_llm_rate", label: "Kiểm tra tấn công phải dùng AI (lớp 4)", kind: "rate", ma: "B2" },
  { name: "intent_filter_fallback_rate", label: "Tra cứu tài liệu phải nới bộ lọc loại yêu cầu", kind: "rate", ma: "B8" },
  { name: "b3_llm_rate", label: "Phân loại phải dùng AI", kind: "rate", ma: "B3" },
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
  injection_detected: "Yêu cầu bị chặn vì nghi tấn công",
  password_bruteforce: "Dò mật khẩu — tài khoản bị khoá",
  e9_spike: "Lỗi hệ thống bất ngờ tăng đột biến",
  breaker_open: "Hệ thống bên ngoài lỗi liên tiếp — ngắt mạch mở",
  e6_spike: "Phiếu duyệt quá hạn tăng đột biến",
  reflex_approval: "Duyệt theo phản xạ (xem dưới 5 giây)",
  drift: "Phân bố dữ liệu lệch so với tuần mốc",
  refresh_reuse: "Phiên đăng nhập bị dùng lại",
  permission_denied_burst: "Bị từ chối quyền dồn dập",
  policy_saved: "Chính sách vừa được lưu",
  b2_degraded: "Kiểm tra tấn công phải dùng AI quá 30%",
  b3_degraded: "Phân loại phải dùng AI quá 30%",
  llm_budget: "Sắp hết ngân sách LLM",
  finalize_failed: "Ghi kết thúc yêu cầu thất bại",
  execution_failed: "Thực hiện không thành công",
};
/** Mã bước / mã kết thúc liên quan của luật cảnh báo — hiện SAU nhãn, chữ nhỏ (bảng ĐP 23:10). */
export const ALERT_MA: Readonly<Record<string, string>> = {
  injection_detected: "E0",
  e9_spike: "E9",
  e6_spike: "E6",
  b2_degraded: "B2",
  b3_degraded: "B3",
  execution_failed: "E7",
};
/** Luật cảnh báo lạ → "Khác" (mã luật vẫn hiện chữ nhỏ ở dòng dưới). */
export const alertLabel = (ruleId: string): string => ownEntry(ALERT_LABEL, ruleId, KHAC);
export const alertMa = (ruleId: string): string | null => ownEntry<string | null>(ALERT_MA, ruleId, null);

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

const RULE1_ID = "escalation_rate_high";
const DAY_MS = 86_400_000;
// Chữ hiện KHÔNG gọi "luật 1" (N-NGU: không hiện số hiệu nội bộ) — dòng nằm ngay dưới cảnh báo đó.
export const RULE1_NOTE_GENERIC = "Đo trên các ngày trọn (giờ VN) trước ngày ghi cảnh báo, không theo khoảng đang chọn.";

/**
 * Ghi chú cửa sổ đo của luật 1 (D13) — chỉ để đọc, KHÔNG đổi luật. Nguồn: backend/app/monitor/rules.py `rolling_7d_window`
 * + `escalation_rate_high`: cửa sổ `[window_start − days, window_start)`, `window_start` = 00:00 VN ngày ghi, `detail.days`.
 * Luật khác → null; `days` không phải số nguyên dương / ngoài miền Date → câu chung không ngày.
 */
export function rule1WindowNote(alert: AlertItem): string | null {
  if (alert.rule_id !== RULE1_ID) return null;
  const end = Date.parse(alert.window_start);
  const days = alert.detail.days;
  if (Number.isNaN(end) || typeof days !== "number" || !Number.isSafeInteger(days) || days < 1) return RULE1_NOTE_GENERIC;
  const start = new Date(end - days * DAY_MS);
  if (Number.isNaN(start.getTime())) return RULE1_NOTE_GENERIC;
  const last = new Date(end - 1).toISOString();
  return `Đo trên ${days} ngày trọn ${vnDate(start.toISOString())}–${vnDate(last)} (giờ VN), không theo khoảng đang chọn.`;
}
