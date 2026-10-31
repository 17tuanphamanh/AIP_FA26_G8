// Dữ liệu MINH HOẠ cho N-PA (chỉ dev:mock + vitest; plugin `no-mocks-in-build` + check:dist chặn lọt build). Hình dạng theo
// hợp đồng chốt ĐP 26/10 17:30 §1–2. Mã đánh dấu `npa-demo` để check:dist bắt nếu lọt.
import type { StrategiesDashboard, StrategyChange, StrategySource, StrategyView } from "../../api/types.ts";

export const NPA_DEMO_MARK = "npa-demo";

/** Trạng thái đầu: chưa ai đổi (mặc định `hybrid`), không ở chế độ đánh giá, lớp LLM CHƯA hiệu chỉnh (D-38). */
export const initialStrategy = (): StrategyView => ({
  strategy: "hybrid",
  selectable: ["rule_only", "hybrid", "hybrid_guarded"],
  llm_calibrated: false,
  eval_mode: false,
  changed_by: null,
  changed_at: null,
  reason: null,
});

/** Lịch sử minh hoạ (mới nhất trước) — người đổi mang mã đánh dấu. */
export const initialHistory = (now: number): StrategyChange[] => [
  {
    changed_at: new Date(now - 26 * 3_600_000).toISOString(),
    changed_by: `${NPA_DEMO_MARK}.quan.tm`,
    strategy_from: "rule_only",
    strategy_to: "hybrid",
    reason: "Quay về mặc định sau tuần thử chỉ dùng luật (minh hoạ).",
  },
  {
    changed_at: new Date(now - 8 * 86_400_000).toISOString(),
    changed_by: `${NPA_DEMO_MARK}.quan.tm`,
    strategy_from: "hybrid",
    strategy_to: "rule_only",
    reason: "Thử một tuần chỉ dùng luật để so khối lượng việc của L1 (minh hoạ).",
  },
];

/** 17 khoá chốt, ĐÚNG thứ tự hợp đồng §2. */
export const METRIC_KEYS = [
  "tickets",
  "auto_rate",
  "hitl_rate",
  "l2_rate",
  "confirmed_rate",
  "no_response_rate",
  "unresolved_rate",
  "l1_reject_rate",
  "quick_approve_rate",
  "system_time_p50",
  "system_time_p90",
  "human_wait_p50",
  "human_minutes_per_100",
  "e5_recheck_failed",
  "overrides",
  "rollbacks",
  "llm_cost_per_ticket",
] as const;

const STRATEGIES = ["rule_only", "hybrid", "hybrid_guarded"] as const;
type S = (typeof STRATEGIES)[number];
type Cell = { num: number; den: number } | { value: number | null; n?: number } | null;

/** Số liệu minh hoạ theo nguồn: `sim` (dữ liệu thử) lớn gấp ~3 lần. Đủ 4 dạng ô của hợp đồng sửa lần 3 (ĐP 26/10 23:51):
 *  - ratio thường `{num, den}` (không khoá `unit`); ô `l1_reject_rate` của hybrid_guarded có mẫu 12 (< 20);
 *  - ratio mẫu 0 `{num: 0, den: 0}`: `quick_approve_rate` của hybrid_guarded;
 *  - value không tính được `{value: null, n: 0}`: chi phí LLM của rule_only (không gọi LLM);
 *  - cả ô `null` CHỈ khi phương án có 0 lá: nguồn `sim` chưa chạy hybrid_guarded → mọi ô của cột đó null, không có ở intent_mix. */
export function buildStrategies(source: StrategySource, from: string, to: string): StrategiesDashboard {
  const k = source === "sim" ? 3 : 1;
  const tickets: Record<S, number> = { rule_only: 120 * k, hybrid: 340 * k, hybrid_guarded: 95 * k };
  const ratio = (num: number, den: number): Cell => ({ num, den });
  const table: Record<(typeof METRIC_KEYS)[number], { kind: "ratio" | "value"; unit?: string; cells: Record<S, Cell> }> = {
    tickets: { kind: "value", unit: "count", cells: { rule_only: { value: tickets.rule_only }, hybrid: { value: tickets.hybrid }, hybrid_guarded: { value: tickets.hybrid_guarded } } },
    auto_rate: { kind: "ratio", cells: { rule_only: ratio(41 * k, 120 * k), hybrid: ratio(190 * k, 340 * k), hybrid_guarded: ratio(30 * k, 95 * k) } },
    hitl_rate: { kind: "ratio", cells: { rule_only: ratio(62 * k, 120 * k), hybrid: ratio(110 * k, 340 * k), hybrid_guarded: ratio(48 * k, 95 * k) } },
    l2_rate: { kind: "ratio", cells: { rule_only: ratio(17 * k, 120 * k), hybrid: ratio(40 * k, 340 * k), hybrid_guarded: ratio(17 * k, 95 * k) } },
    confirmed_rate: { kind: "ratio", cells: { rule_only: ratio(80 * k, 103 * k), hybrid: ratio(250 * k, 300 * k), hybrid_guarded: ratio(60 * k, 78 * k) } },
    no_response_rate: { kind: "ratio", cells: { rule_only: ratio(15 * k, 103 * k), hybrid: ratio(35 * k, 300 * k), hybrid_guarded: ratio(12 * k, 78 * k) } },
    unresolved_rate: { kind: "ratio", cells: { rule_only: ratio(8 * k, 103 * k), hybrid: ratio(15 * k, 300 * k), hybrid_guarded: ratio(6 * k, 78 * k) } },
    l1_reject_rate: { kind: "ratio", cells: { rule_only: ratio(9 * k, 62 * k), hybrid: ratio(14 * k, 110 * k), hybrid_guarded: ratio(2, 12) } },
    quick_approve_rate: { kind: "ratio", cells: { rule_only: ratio(5 * k, 62 * k), hybrid: ratio(9 * k, 110 * k), hybrid_guarded: ratio(0, 0) } },
    system_time_p50: { kind: "value", unit: "s", cells: { rule_only: { value: 6.2, n: 120 * k }, hybrid: { value: 9.8, n: 340 * k }, hybrid_guarded: { value: 12.4, n: 95 * k } } },
    system_time_p90: { kind: "value", unit: "s", cells: { rule_only: { value: 14.1, n: 120 * k }, hybrid: { value: 21.7, n: 340 * k }, hybrid_guarded: { value: 26.3, n: 95 * k } } },
    human_wait_p50: { kind: "value", unit: "min", cells: { rule_only: { value: 18, n: 79 * k }, hybrid: { value: 14.5, n: 150 * k }, hybrid_guarded: { value: 16, n: 65 * k } } },
    human_minutes_per_100: { kind: "value", unit: "min", cells: { rule_only: { value: 310, n: 120 * k }, hybrid: { value: 190, n: 340 * k }, hybrid_guarded: { value: 260, n: 95 * k } } },
    e5_recheck_failed: { kind: "value", unit: "count", cells: { rule_only: { value: 1 * k }, hybrid: { value: 3 * k }, hybrid_guarded: { value: 1 * k } } },
    overrides: { kind: "value", unit: "count", cells: { rule_only: { value: 4 * k }, hybrid: { value: 6 * k }, hybrid_guarded: { value: 2 * k } } },
    rollbacks: { kind: "value", unit: "count", cells: { rule_only: { value: 0 }, hybrid: { value: 2 * k }, hybrid_guarded: { value: 1 * k } } },
    llm_cost_per_ticket: { kind: "value", unit: "usd", cells: { rule_only: { value: null, n: 0 }, hybrid: { value: 0.0042, n: 340 * k }, hybrid_guarded: { value: 0.0071, n: 95 * k } } },
  };
  const noLeaves = source === "sim"; // hybrid_guarded 0 lá ở dữ liệu thử
  return {
    source,
    from,
    to,
    strategies: [...STRATEGIES],
    intent_mix: {
      rule_only: { vpn: 70 * k, account: 30 * k, software: 20 * k },
      hybrid: { vpn: 180 * k, account: 90 * k, access: 40 * k, software: 30 * k },
      ...(noLeaves ? {} : { hybrid_guarded: { account: 45 * k, vpn: 40 * k, access: 10 * k } }),
    },
    metrics: METRIC_KEYS.map((key) => ({
      key,
      kind: table[key].kind,
      ...(table[key].unit ? { unit: table[key].unit } : {}),
      values: { ...table[key].cells, ...(noLeaves ? { hybrid_guarded: null } : {}) },
    })),
    unavailable: [],
  };
}
