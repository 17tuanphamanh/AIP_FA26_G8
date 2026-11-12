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
  BusinessCountedTam,
  BusinessCountsTam,
  BusinessMetrics,
  DayCost,
  E1Split,
  E3Case,
  E3Cases,
  ErrorDetail,
  GroupCountTam,
  EscalationCloseResult,
  InvalidRequestBody,
  MatchedRule,
  NotificationPage,
  NotificationView,
  PolicyInvalid,
  PolicyValidateOk,
  PolicyVersionItem,
  PolicyView,
  RatioCountTam,
  RuleCount,
  TicketList,
  TicketListItem,
  TicketView,
  WeightedCountTam,
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
// D13 (lô N, N3 hướng B): openapi có `min_sample` + `counts` BẮT BUỘC; kiểu viết tay giữ chúng TUỲ CHỌN (`BusinessCountedTam`,
// tương thích backend trước D13 — bộ đọc và d13.test.tsx không đổi) → so bản bắt-buộc-hết-trường với openapi.

type BusinessMetricsGen = S["BusinessAllMetrics"];
type BusinessCountedFull = Required<BusinessCountedTam>;
export type BusinessDashboardOk = [
  Expect<Same<BusinessCountedFull, S["BusinessAll"]>>,
  Expect<Mutual<BusinessCountedFull, Extract<Ok200<operations["dashboard_business_api_dashboard_business_get"]>, { scope: "all" }>>>,
  // 4 kiểu *Tam của D13, từng khoá hai chiều.
  Expect<Same<BusinessCountsTam, S["BusinessAllCounts"]>>,
  Expect<Same<RatioCountTam, S["RatioCount"]>>,
  Expect<Same<GroupCountTam, S["GroupCount"]>>,
  Expect<Same<WeightedCountTam, S["WeightedCount"]>>,
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
  Expect<Mutual<ApprovalViewP4["requester"], ApprovalGen["requester"]>>, // Q3 (12/11): + user_id, full_name
  Expect<Mutual<ApprovalViewP4["affected"], ApprovalGen["affected"]>>,
  Expect<Mutual<ApprovalViewP4["risk_view"], ApprovalGen["risk_view"]>>,
  Expect<Mutual<ApprovalViewP4["role_as"], ApprovalGen["role_as"]>>,
  Expect<Mutual<ApprovalViewP4["procedure"], ApprovalGen["procedure"]>>,
  Expect<Mutual<ApprovalViewP4["requester"], ApprovalGen["requester"]>>,
  Expect<Mutual<ApprovalViewP4["deadline"], ApprovalGen["deadline"]>>,
  Expect<Mutual<ApprovalViewP4["risk"], ApprovalGen["risk"]>>,
  // Cùng tập khoá: bỏ `status` ở cả hai rồi so từng khoá (khoá chỉ ở một bên → lỗi biên dịch). `matched_rules` (N-PA) đã
  // có trong openapi (gen:api từ be-thong-bao 56ea4d9) nhưng khai `list[MatchedRule] | None = None` → openapi `| null`; route
  // THẬT không bao giờ gửi null (không có dữ liệu → BỎ khoá — backend/app/api/approvals.py `view_approval`). Kiểu viết tay
  // giữ chặt hơn (null → 502 ở api/approvals.ts) → soi riêng: bỏ `null` phía openapi rồi so hai chiều.
  Expect<Same<Omit<ApprovalViewP4, "status" | "action" | "facts" | "risk" | "matched_rules">, Omit<ApprovalGen, "status" | "action" | "facts" | "risk" | "matched_rules">>>,
  Expect<Mutual<ApprovalViewP4["matched_rules"], Exclude<ApprovalGen["matched_rules"], null>>>,
  Expect<Same<MatchedRule, S["MatchedRule"]>>,
  Expect<
    Mutual<
      Omit<ApprovalViewP4, "matched_rules">,
      Omit<Ok200<operations["view_approval_api_approvals__approval_id__get"]>, "status" | "matched_rules"> & { status: ApprovalViewP4["status"] }
    >
  >,
];
// TicketView (N-TB): `deadline` + `server_now` LẤY từ openapi (types.ts) nhưng để TUỲ CHỌN có chủ ý (thân cũ thiếu khoá) →
// so hai chiều sau khi bỏ `undefined`; tập khoá viết tay ≡ tập khoá openapi (không thiếu / thừa khoá nào).
type TicketGen = S["TicketView"];
export type TicketViewOk = [
  Expect<Mutual<Exclude<TicketView["deadline"], undefined>, TicketGen["deadline"]>>,
  Expect<Mutual<Exclude<TicketView["server_now"], undefined>, TicketGen["server_now"]>>,
  // Q13b (D-79): `can_follow_up` (backend mặc định false → openapi ghi bắt buộc) TUỲ CHỌN ở FE như `deadline` — thân cũ thiếu khoá = không có ô.
  Expect<Mutual<Exclude<TicketView["can_follow_up"], undefined>, TicketGen["can_follow_up"]>>,
  Expect<Mutual<keyof TicketView, keyof TicketGen>>,
  Expect<Mutual<TicketView["waiting_for"], TicketGen["waiting_for"]>>,
  Expect<
    Same<
      Omit<TicketView, "conversation" | "children_progress" | "deadline" | "server_now" | "can_follow_up">,
      Omit<TicketGen, "conversation" | "children_progress" | "deadline" | "server_now" | "can_follow_up">
    >
  >,
  Expect<Mutual<TicketGen, Ok200<operations["read_ticket_api_tickets__ticket_id__get"]>>>,
];
// P3 "Gần đây": GET /api/tickets — nối tên schema với ĐÚNG route; đúng 6 khoá mà parser (api/tickets.ts `parseTicketList`) kiểm.
type MyTickets = operations["list_tickets_api_tickets_get"];
export type TicketListOk = [
  Expect<Mutual<TicketList, Ok200<MyTickets>>>,
  Expect<Mutual<TicketList["items"][number], TicketListItem>>,
  Expect<
    Same<
      TicketListItem,
      {
        ticket_id: string;
        request_text: string | null;
        final_state: string | null;
        exit_code: string | null;
        created_at: string;
        closed_at: string | null;
      }
    >
  >,
  Expect<Mutual<MyTickets["parameters"]["query"], { limit?: number } | undefined>>,
];

// ---------------------------------------------------------------- Thông báo (N-TB, be-thong-bao 56ea4d9)
// Kiểu ở types.ts LÀ kiểu sinh — soát nối tên schema với ĐÚNG route + thân lỗi dùng chung (401/403/503 `ErrorDetail`,
// 422 `InvalidRequestBody`); `kind`/`result` của openapi ≡ đúng 2/5 giá trị parser chấp nhận (api/notifications.ts).
type Notif = operations["my_notifications_api_me_notifications_get"];
type Err<Op, C extends number> = Op extends { responses: { [K in C]: { content: { "application/json": infer B } } } } ? B : never;
export type NotificationOk = [
  Expect<Mutual<NotificationPage, Ok200<Notif>>>,
  Expect<Mutual<NotificationPage["items"][number], NotificationView>>,
  Expect<Mutual<NotificationView["kind"], "approval_decided" | "escalation_closed">>,
  Expect<Mutual<NotificationView["result"], "approved" | "rejected" | "completed" | "confirmed_denial" | "reopened_as_new">>,
  Expect<Mutual<Extract<NotificationView["result"], "completed" | "confirmed_denial" | "reopened_as_new">, EscalationCloseResult>>,
  Expect<Mutual<NotificationView["new_ticket_id"], string | null>>,
  Expect<Mutual<NotificationPage["next_cursor"], string | null>>,
  Expect<Mutual<Err<Notif, 401>, ErrorDetail>>,
  Expect<Mutual<Err<Notif, 403>, ErrorDetail>>,
  Expect<Mutual<Err422<Notif>, InvalidRequestBody>>,
  Expect<Mutual<Err<Notif, 503>, ErrorDetail>>,
  Expect<Mutual<Notif["parameters"]["query"], { limit?: number; after?: string | null } | undefined>>,
];
