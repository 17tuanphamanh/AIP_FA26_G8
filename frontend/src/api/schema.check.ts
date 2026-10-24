// Soát LÚC BIÊN DỊCH (N-A3 PHẦN 2): kiểu VIẾT TAY của 4 route M9 A3 (contracts-tam.ts, đọc qua types.ts) phải gán được
// HAI CHIỀU với kiểu sinh từ openapi (schema.gen.ts — `npm run gen:api`; sinh lại ở N-POL1 từ openapi của be8239d, lấy
// offline bằng `create_app().openapi()`). Lệch → `npm run typecheck` đỏ ngay tại dòng soát, lỗi nêu tên khoá ("Types of
// property 'x' are incompatible"). Không sửa kiểu viết tay cho xanh khi chưa biết lệch do ai; không nới bằng
// any/unknown/ép kiểu. File chỉ có kiểu — không mã chạy, không ai import.
// Xoá khi: gen:api thành nguồn kiểu cho 4 route (xoá cùng khối "Route ĐÃ CÓ — M9 A3" ở contracts-tam.ts).
import type { components, operations } from "./schema.gen.ts";
import type {
  AiDashboard,
  AiMetrics,
  AlertItem,
  AlertList,
  ApprovalAffected,
  ApprovalManagerRef,
  ApprovalRiskView,
  ApprovalViewP4,
  BusinessDashboard,
  BusinessMetrics,
  DayCost,
  E1Split,
  E3Case,
  E3Cases,
  PolicyInvalid,
  PolicyValidateOk,
  PolicyVersionItem,
  PolicyView,
  RuleCount,
  TicketView,
  WeightedRate,
} from "./types.ts";

type S = components["schemas"];
/** Thân 200 `application/json` của một operation — nối tên schema với ĐÚNG route. */
type Ok200<Op> = Op extends { responses: { 200: { content: { "application/json": infer B } } } } ? B : never;
/** Thân 422 `application/json` của một operation. */
type Err422<Op> = Op extends { responses: { 422: { content: { "application/json": infer B } } } } ? B : never;

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

// ---------------------------------------------------------------- Chính sách (N-POL1)
// Kiểu ở types.ts LÀ kiểu sinh (không viết tay) — soát ở đây chỉ nối tên schema với ĐÚNG route: `/versions` trả MẢNG
// TRẦN (không phải `{items}`), 422 của validate có nhánh `invalid_policy`.

export type PolicyOk = [
  Expect<Mutual<PolicyView, Ok200<operations["current_policy_api_policy_get"]>>>,
  Expect<Mutual<PolicyVersionItem[], Ok200<operations["policy_versions_api_policy_versions_get"]>>>,
  Expect<Mutual<PolicyValidateOk, Ok200<operations["validate_policy_api_policy_validate_post"]>>>,
  Expect<Mutual<PolicyInvalid, Extract<Err422<operations["validate_policy_api_policy_validate_post"]>, { error: "invalid_policy" }>>>,
];

// ---------------------------------------------------------------- Duyệt L1 + ticket (F6 #76, R3 #76)
// `ApprovalView.status` của openapi là `string` (cột DB), kiểu viết tay là enum chặt hơn → không soi cả object được; soi
// TỪNG KHOÁ MỚI (hai chiều) + tập khoá (không thiếu / thừa khoá nào) bằng `PerKey` của object bỏ `status`.
// `TicketView.conversation` là list[dict] (viết tay `unknown[]`) và `children_progress` viết tay chặt hơn → soi riêng `deadline`.

type ApprovalGen = S["ApprovalView"];
export type ApprovalViewOk = [
  Expect<Same<ApprovalAffected, S["AffectedView"]>>,
  Expect<Same<ApprovalManagerRef, S["ManagerRef"]>>,
  Expect<Same<ApprovalRiskView, S["RiskView"]>>,
  Expect<Mutual<ApprovalViewP4["affected"], ApprovalGen["affected"]>>,
  Expect<Mutual<ApprovalViewP4["risk_view"], ApprovalGen["risk_view"]>>,
  Expect<Mutual<ApprovalViewP4["role_as"], ApprovalGen["role_as"]>>,
  Expect<Mutual<ApprovalViewP4["procedure"], ApprovalGen["procedure"]>>,
  Expect<Mutual<ApprovalViewP4["requester"], ApprovalGen["requester"]>>,
  Expect<Mutual<ApprovalViewP4["deadline"], ApprovalGen["deadline"]>>,
  Expect<Mutual<ApprovalViewP4["risk"], ApprovalGen["risk"]>>,
  // Cùng tập khoá: bỏ `status` ở cả hai rồi so từng khoá (khoá chỉ ở một bên → lỗi biên dịch).
  Expect<Same<Omit<ApprovalViewP4, "status" | "action" | "facts" | "risk">, Omit<ApprovalGen, "status" | "action" | "facts" | "risk">>>,
  Expect<Mutual<ApprovalViewP4, Ok200<operations["view_approval_api_approvals__approval_id__get"]> & { status: ApprovalViewP4["status"] }>>,
];
export type TicketDeadlineOk = [
  Expect<Mutual<Exclude<TicketView["deadline"], undefined>, S["TicketView"]["deadline"]>>,
  Expect<Mutual<S["TicketView"], Ok200<operations["read_ticket_api_tickets__ticket_id__get"]>>>,
];
