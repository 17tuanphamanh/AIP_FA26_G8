// Soát LÚC BIÊN DỊCH (N-A3 PHẦN 2): kiểu VIẾT TAY của 4 route M9 A3 (contracts-tam.ts, đọc qua types.ts) phải gán được
// HAI CHIỀU với kiểu sinh từ openapi (schema.gen.ts — `npm run gen:api`, openapi của a463150). Lệch → `npm run typecheck`
// đỏ ngay tại dòng soát, lỗi nêu tên khoá ("Types of property 'x' are incompatible"). Không sửa kiểu viết tay cho xanh
// khi chưa biết lệch do ai; không nới bằng any/unknown/ép kiểu. File chỉ có kiểu — không mã chạy, không ai import.
// Xoá khi: gen:api thành nguồn kiểu cho 4 route (xoá cùng khối "Route ĐÃ CÓ — M9 A3" ở contracts-tam.ts).
import type { components, operations } from "./schema.gen.ts";
import type {
  AiDashboard,
  AiMetrics,
  AlertItem,
  AlertList,
  BusinessDashboard,
  BusinessMetrics,
  DayCost,
  E1Split,
  E3Case,
  E3Cases,
  RuleCount,
  WeightedRate,
} from "./types.ts";

type S = components["schemas"];
/** Thân 200 `application/json` của một operation — nối tên schema với ĐÚNG route. */
type Ok200<Op> = Op extends { responses: { 200: { content: { "application/json": infer B } } } } ? B : never;

/** `true` khi A gán được cho B VÀ B gán được cho A (bọc `[…]` để không phân phối qua union). */
type Mutual<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
/** Từng khoá của hai object: `true` = hai chiều; khoá chỉ có ở một bên → chuỗi nêu bên đó. */
type PerKey<A, B> = {
  [K in keyof A | keyof B]-?: K extends keyof A
    ? K extends keyof B
      ? Mutual<A[K], B[K]>
      : "chỉ có ở kiểu viết tay"
    : "chỉ có ở openapi";
};
type Expect<T extends true> = T;
/**
 * Hai object khớp từng khoá VÀ cả object hai chiều → `true`. Khoá lệch → trả bảng `PerKey` (lỗi biên dịch in bảng đó,
 * khoá lệch mang `false` hoặc tên bên có khoá).
 */
type Same<A, B> =
  PerKey<A, B> extends Record<string, true> ? (Mutual<A, B> extends true ? true : "lệch cả object dù từng khoá khớp") : PerKey<A, B>;

// ---------------------------------------------------------------- Cảnh báo

export type AlertItemOk = [
  Expect<Same<AlertItem, S["AlertView"]>>,
  Expect<Mutual<AlertItem, Ok200<operations["ack_api_alerts__alert_id__ack_post"]>>>,
];
export type AlertListOk = [
  Expect<Same<AlertList, S["AlertList"]>>,
  Expect<Same<AlertList["items"][number], S["AlertList"]["items"][number]>>,
  Expect<Mutual<AlertList, Ok200<operations["alerts_api_alerts_get"]>>>,
];

// ---------------------------------------------------------------- Tổng quan — Nghiệp vụ
// Route trả `BusinessAll | BusinessOwn`; kiểu viết tay chỉ dựng nhánh `scope: "all"` (dashboard:read:all) — nhánh "own"
// (L1) chưa dùng, parseBusiness trả 502 khi scope ≠ "all".

type BusinessMetricsGen = S["BusinessAllMetrics"];
export type BusinessDashboardOk = [
  Expect<Same<BusinessDashboard, S["BusinessAll"]>>,
  Expect<Mutual<BusinessDashboard, Extract<Ok200<operations["dashboard_business_api_dashboard_business_get"]>, { scope: "all" }>>>,
  Expect<Same<BusinessMetrics, BusinessMetricsGen>>,
  // Object con: cả trường (gồm `| null`) lẫn phần không null, từng khoá.
  Expect<Mutual<BusinessMetrics["escalation_rate_weighted"], BusinessMetricsGen["escalation_rate_weighted"]>>,
  Expect<Same<WeightedRate, S["WeightedRate"]>>,
  Expect<Mutual<BusinessMetrics["e1_split"], BusinessMetricsGen["e1_split"]>>,
  Expect<Same<E1Split, S["E1Split"]>>,
  Expect<Mutual<BusinessMetrics["e3_cases"], BusinessMetricsGen["e3_cases"]>>,
  Expect<Same<E3Cases, S["E3Cases"]>>,
  Expect<Same<E3Case, S["E3Case"]>>,
  Expect<Mutual<BusinessMetrics["top_matched_rules"], BusinessMetricsGen["top_matched_rules"]>>,
  Expect<Same<RuleCount, S["RuleCount"]>>,
];

// ---------------------------------------------------------------- Tổng quan — AI

type AiMetricsGen = S["AiMetrics"];
export type AiDashboardOk = [
  Expect<Same<AiDashboard, S["AiDashboard"]>>,
  Expect<Mutual<AiDashboard, Ok200<operations["dashboard_ai_api_dashboard_ai_get"]>>>,
  Expect<Same<AiMetrics, AiMetricsGen>>,
  Expect<Mutual<AiMetrics["cost_per_day"], AiMetricsGen["cost_per_day"]>>,
  Expect<Same<DayCost, S["DayCost"]>>,
  Expect<Mutual<AiMetrics["latency_p95_by_step"], AiMetricsGen["latency_p95_by_step"]>>,
];
