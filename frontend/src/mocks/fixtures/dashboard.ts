// Dữ liệu GIẢ cho Tổng quan (F5 P8) — chỉ nạp khi dev:mock. Tên trường đúng ke-hoach-m9-monitor.md §5.1–5.2; số là
// minh hoạ (B4MgrDashboard). Đủ các ca bắt buộc của P3:
//   - `override_count` nằm trong `unavailable` (nguồn có từ Phase 4 chặng 4d) → "Chưa có dữ liệu";
//   - 7 ngày: `escalation_rate_weighted` = null KHÔNG nằm trong `unavailable` (một nhóm N3 không có ticket → không tính
//     được tỉ lệ có trọng số — mẫu số 0, §4.3) → "—"; `approval_expired_count` = 0 THẬT → "0";
//   - Hôm nay: không có ticket → mọi tỉ lệ null, mọi số đếm 0 thật.
// Ca E3 dùng mã `tkt-demo-e3-*` (check:dist chặn chuỗi `tkt-demo-` lọt bản build — Q-fe-29).
// Xoá khi: M9 A3 merge (gen:api) — xoá cùng mocks/handlers/dashboard.ts.
import type { AiDashboard, BusinessDashboard, E3Case } from "../../api/types.ts";

const DAY = 86_400_000;

/** Số ngày lịch (VN) của cửa sổ — để số liệu đổi theo khoảng (1 / 7 / 30). */
const spanDays = (from: string, to: string) => Math.max(1, Math.round((Date.parse(to) - Date.parse(from)) / DAY));

const E3: readonly Omit<E3Case, "created_at">[] = [
  { ticket_id: "tkt-demo-e3-01", intent: "software", kb_version: "v12", request_excerpt: "Máy in mạng tầng 3 không nhận lệnh in từ máy tính của phòng Kế toán…" },
  { ticket_id: "tkt-demo-e3-02", intent: "access", kb_version: "v12", request_excerpt: "Đổi mật khẩu Wi-Fi khách cho đối tác đến họp chiều nay…" },
  { ticket_id: "tkt-demo-e3-03", intent: "software", kb_version: "v11", request_excerpt: "Đồng bộ lịch Outlook trên điện thoại bị lệch 1 tiếng…" },
];

export function buildBusiness(from: string, to: string): BusinessDashboard {
  const days = spanDays(from, to);
  const base = { from, to, override_count: null, unavailable: ["override_count"] };
  if (days <= 1) {
    return {
      ...base,
      automation_rate: null,
      escalation_rate_raw: null,
      escalation_rate_weighted: null,
      deflection_rate: null,
      approval_expired_count: 0,
      decided_by_distribution: {},
      top_matched_rules: [],
      e1_split: {},
      e3_cases: [],
    };
  }
  const k = days / 7;
  const n = (x: number) => Math.round(x * k);
  const toMs = Date.parse(to);
  return {
    ...base,
    automation_rate: days >= 30 ? 0.61 : 0.63,
    escalation_rate_raw: days >= 30 ? 0.17 : 0.16,
    escalation_rate_weighted: days >= 30 ? 0.15 : null,
    deflection_rate: 0.21,
    approval_expired_count: days >= 30 ? 2 : 0,
    decided_by_distribution: { rule: n(223), llm: n(63) },
    top_matched_rules: [
      { rule_id: "R20", count: n(96) },
      { rule_id: "R16", count: n(71) },
      { rule_id: "R17", count: n(22) },
      { rule_id: "R18", count: n(14) },
    ],
    e1_split: { out_of_scope: n(9), intent_low_confidence: n(4), multi_intent_not_enabled: n(2), intent_not_enabled: 0 },
    e3_cases: E3.map((c, i) => ({ ...c, created_at: new Date(toMs - (i + 1) * DAY).toISOString() })),
  };
}

export function buildAi(from: string, to: string): AiDashboard {
  const days = Math.min(spanDays(from, to), 30);
  const toMs = Date.parse(to);
  return {
    from,
    to,
    tokens_per_ticket: 1850,
    // [Suy luận hình dạng] — màn hiện theo dữ liệu (mảng → bảng khoá–giá trị).
    cost_per_day: Array.from({ length: Math.min(days, 3) }, (_, i) => ({
      day: new Date(toMs - i * DAY).toISOString().slice(0, 10),
      cost_usd: [0.42, 0.37, 0.51][i],
    })),
    latency_p95_by_step: { B2: 140, B3: 820, B9: 310, B10: 2400 },
    cache_hit_rate: 0.31,
    json_invalid_first_try_rate: 0, // 0 thật
    fallback_rate: 0.02,
    e2_llm_count: 1,
    e9_count: 0,
    b2_llm_rate: 0.12,
    intent_filter_fallback_rate: null, // chưa có nguồn (minh hoạ) → "Chưa có dữ liệu"
    b3_llm_rate: 1,
    intent_model_version: "intent-clf-2026.09.20",
    unavailable: ["intent_filter_fallback_rate"],
  };
}
