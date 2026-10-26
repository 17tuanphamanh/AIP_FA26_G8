// Các luật khớp (hợp đồng N-PA §3) — kiểm HÌNH DẠNG dùng chung cho ApprovalView (khoá gốc) và TicketTrace (khối `policy`
// của bước B13/B14). Chỉ kiểm kiểu từng phần tử (đúng 4 khoá); số phần tử `applied` sai (≠ 1 khi mảng khác rỗng) KHÔNG
// phải lỗi hình dạng — màn tự báo "lỗi dữ liệu" tại bảng (routes/shared/matchedRules.ts), phiếu vẫn duyệt được (Q-fe-N2).
const RULE_KEYS = ["rule_id", "description", "decision", "applied"] as const;
const DECISIONS = ["allow", "approval_required", "deny"];

export function isMatchedRule(v: unknown): boolean {
  if (v === null || typeof v !== "object" || Array.isArray(v)) return false;
  const r = v as Record<string, unknown>;
  const keys = Object.keys(r);
  return (
    keys.length === RULE_KEYS.length &&
    RULE_KEYS.every((k) => Object.hasOwn(r, k)) &&
    typeof r.rule_id === "string" &&
    (r.description === null || typeof r.description === "string") &&
    DECISIONS.includes(r.decision as string) &&
    typeof r.applied === "boolean"
  );
}

/** Khoá vắng (`undefined`) hợp lệ = chưa có dữ liệu; có mặt thì phải là mảng các luật đúng dạng. */
export const isMatchedRulesField = (v: unknown): boolean => v === undefined || (Array.isArray(v) && v.every(isMatchedRule));
