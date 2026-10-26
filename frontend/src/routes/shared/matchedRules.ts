// Bảng "Các luật khớp" (hợp đồng N-PA §3; Q-fe-N3) — hàm thuần. Chỉ dùng ở màn L1/L2/Trưởng BP IT (phiếu duyệt, nhật ký
// quyết định); KHÔNG BAO GIỜ ở màn nhân viên. Kết quả mỗi dòng:
// - luật `applied` → "áp dụng (chặt nhất)";
// - luật thua có quyết định KHÁC luật applied → "khớp nhưng bị luật chặt hơn thay thế";
// - luật thua CÙNG quyết định với luật applied → "khớp, cùng mức với luật được áp dụng".
// Mảng khác rỗng mà số luật `applied` ≠ 1, HOẶC luật `applied` không phải luật chặt nhất (có luật thua mức cao hơn: deny >
// approval_required > allow) → lỗi dữ liệu (không hiện bảng — tránh xác nhận sai "bị luật chặt hơn thay thế" cho một luật
// thật ra chặt hơn); phiếu vẫn duyệt được (Q-fe-N2).
import type { MatchedRule } from "../../api/types.ts";
import { labelOf } from "../../lib/lookup.ts";

export const MATCHED_HEADING = "Các luật khớp";
export const NO_RULE_TEXT = "Không có luật nào khớp";
export const NO_DATA_TEXT = "Chưa có dữ liệu luật khớp";
export const BAD_DATA_TEXT =
  "Dữ liệu luật khớp không hợp lệ (số luật được áp dụng khác một, hoặc luật được áp dụng không phải luật chặt nhất) — không hiển thị để tránh hiểu sai.";
export const APPLIED_TEXT = "áp dụng (chặt nhất)";
export const REPLACED_TEXT = "khớp nhưng bị luật chặt hơn thay thế";
export const SAME_LEVEL_TEXT = "khớp, cùng mức với luật được áp dụng";

const DECISION: Record<string, string> = { allow: "Cho phép", approval_required: "Cần duyệt", deny: "Cấm" };
/** Mức chặt của quyết định (P1 "chặt nhất thắng"); parser đã chặn giá trị ngoài 3 mức. */
const RANK: Record<MatchedRule["decision"], number> = { allow: 0, approval_required: 1, deny: 2 };
export const decisionText = (d: string): string => labelOf(DECISION, d);

export type MatchedRow = { ruleId: string; description: string; decision: string; result: string; applied: boolean };
export type MatchedView =
  | { kind: "missing" }
  | { kind: "empty" }
  | { kind: "invalid" }
  | { kind: "rows"; rows: MatchedRow[] };

/** `undefined` = server không trả khoá (chưa có dữ liệu) ≠ `[]` (đã xét, không luật nào khớp). Giữ thứ tự server. */
export function matchedView(rules: readonly MatchedRule[] | undefined): MatchedView {
  if (rules === undefined) return { kind: "missing" };
  if (rules.length === 0) return { kind: "empty" };
  const applied = rules.filter((r) => r.applied);
  if (applied.length !== 1) return { kind: "invalid" };
  const winner = applied[0]!.decision;
  if (rules.some((r) => !r.applied && RANK[r.decision] > RANK[winner])) return { kind: "invalid" };
  return {
    kind: "rows",
    rows: rules.map((r) => ({
      ruleId: r.rule_id,
      description: r.description ?? "—",
      decision: decisionText(r.decision),
      result: r.applied ? APPLIED_TEXT : r.decision === winner ? SAME_LEVEL_TEXT : REPLACED_TEXT,
      applied: r.applied,
    })),
  };
}
