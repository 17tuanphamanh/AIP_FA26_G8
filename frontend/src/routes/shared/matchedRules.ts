// Bảng "Các luật khớp" (hợp đồng N-PA §3; Q-fe-N3) — hàm thuần. Chỉ dùng ở màn L1/L2/Trưởng BP IT (phiếu duyệt, nhật ký
// quyết định); KHÔNG BAO GIỜ ở màn nhân viên. Kết quả mỗi dòng:
// - luật `applied` → "áp dụng (chặt nhất)";
// - luật thua có quyết định KHÁC luật applied → "khớp nhưng bị luật chặt hơn thay thế";
// - luật thua CÙNG quyết định với luật applied → "khớp, cùng mức với luật được áp dụng".
// - 0 luật `applied` (hợp đồng sửa 21:15: quyết định cuối không do luật, vd hybrid_guarded + AI lỗi → E5) → mọi luật "khớp"
//   + một dòng dưới bảng;
// - luật có `decision` null (đã xoá khỏi chính sách) → cột Quyết định "—", kết quả "khớp" nếu không applied; bỏ qua khi so
//   mức chặt (không có mức để so).
// > 1 luật `applied`, HOẶC luật `applied` không phải luật chặt nhất (có luật thua mức cao hơn: deny > approval_required >
// allow) → lỗi dữ liệu (không hiện bảng — tránh xác nhận sai); phiếu vẫn duyệt được (Q-fe-N2).
import type { MatchedRule } from "../../api/types.ts";
import { labelOf } from "../../lib/lookup.ts";

export const MATCHED_HEADING = "Các luật khớp";
export const NO_RULE_TEXT = "Không có luật nào khớp";
export const NO_DATA_TEXT = "Chưa có dữ liệu luật khớp";
export const BAD_DATA_TEXT =
  "Dữ liệu luật khớp không hợp lệ (nhiều hơn một luật được áp dụng, hoặc luật được áp dụng không phải luật chặt nhất) — không hiển thị để tránh hiểu sai.";
export const APPLIED_TEXT = "Áp dụng (chặt nhất)";
export const REPLACED_TEXT = "Khớp nhưng bị luật chặt hơn thay thế";
export const SAME_LEVEL_TEXT = "Khớp, cùng mức với luật được áp dụng";
/** Luật khớp mà không so được với luật applied (không có luật applied, hoặc một bên `decision` null). */
export const MATCHED_ONLY_TEXT = "Khớp";
export const UNDECIDED_TEXT = "Quyết định cuối không do luật — xem lý do ở bước đánh giá rủi ro";

const DECISION: Record<string, string> = { allow: "Cho phép", approval_required: "Cần duyệt", deny: "Cấm" };
/** Mức chặt của quyết định (P1 "chặt nhất thắng"); parser đã chặn giá trị ngoài 3 mức. */
const RANK: Record<string, number> = { allow: 0, approval_required: 1, deny: 2 };
export const decisionText = (d: string | null): string => (d === null ? "—" : labelOf(DECISION, d));

export type MatchedRow = { ruleId: string; description: string; decision: string; result: string; applied: boolean };
export type MatchedView =
  | { kind: "missing" }
  | { kind: "empty" }
  | { kind: "invalid" }
  | { kind: "rows"; rows: MatchedRow[]; /** 0 luật applied — quyết định cuối không do luật. */ undecided: boolean };

/** `undefined` = server không trả khoá (chưa có dữ liệu) ≠ `[]` (đã xét, không luật nào khớp). Giữ thứ tự server. */
export function matchedView(rules: readonly MatchedRule[] | undefined): MatchedView {
  if (rules === undefined) return { kind: "missing" };
  if (rules.length === 0) return { kind: "empty" };
  const applied = rules.filter((r) => r.applied);
  if (applied.length > 1) return { kind: "invalid" };
  const winner = applied.length === 1 ? applied[0]!.decision : null;
  // Luật thua chặt hơn luật applied → dữ liệu sai. `decision` null (luật đã xoá) không có mức → bỏ qua khi so.
  if (winner !== null && rules.some((r) => !r.applied && r.decision !== null && RANK[r.decision]! > RANK[winner]!)) {
    return { kind: "invalid" };
  }
  const result = (r: MatchedRule): string => {
    if (r.applied) return APPLIED_TEXT;
    if (winner === null || r.decision === null) return MATCHED_ONLY_TEXT;
    return r.decision === winner ? SAME_LEVEL_TEXT : REPLACED_TEXT;
  };
  return {
    kind: "rows",
    rows: rules.map((r) => ({
      ruleId: r.rule_id,
      description: r.description ?? "—",
      decision: decisionText(r.decision),
      result: result(r),
      applied: r.applied,
    })),
    undecided: applied.length === 0,
  };
}
