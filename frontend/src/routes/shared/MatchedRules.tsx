import type { MatchedRule } from "../../api/types.ts";
import { BAD_DATA_TEXT, MATCHED_HEADING, matchedView, NO_DATA_TEXT, NO_RULE_TEXT } from "./matchedRules.ts";

// Bảng "Các luật khớp" — phiếu duyệt L1 (ApprovalDetail) và bước B13/B14 của nhật ký quyết định. Chữ từ server (mã luật,
// mô tả) hiện thô. Không tô màu theo quyết định. KHÔNG dùng ở màn nhân viên.
export function MatchedRules({ rules, headingLevel = 2 }: { rules: readonly MatchedRule[] | undefined; headingLevel?: 2 | 3 }) {
  const view = matchedView(rules);
  const Heading = headingLevel === 2 ? "h2" : "h4";
  return (
    <section data-testid="matched-rules" data-state={view.kind} className="flex flex-col gap-2">
      <Heading className="pl-1 text-label text-ink-2">{MATCHED_HEADING}</Heading>
      {view.kind === "rows" ? (
        <div className="overflow-x-auto rounded-group border border-line">
          <table className="w-full text-left text-secondary">
            <thead className="text-label text-ink-2">
              <tr>
                <th scope="col" className="px-5 py-2.5 font-normal">Luật</th>
                <th scope="col" className="px-5 py-2.5 font-normal">Mô tả</th>
                <th scope="col" className="px-5 py-2.5 font-normal">Quyết định của luật</th>
                <th scope="col" className="px-5 py-2.5 font-normal">Kết quả</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((r, i) => (
                <tr key={`${r.ruleId}-${i}`} data-testid="matched-rule" data-rule={r.ruleId} data-applied={r.applied} className="border-t border-line align-top">
                  <td className="px-5 py-2.5 font-mono">{r.ruleId}</td>
                  <td className="px-5 py-2.5 break-words">{r.description}</td>
                  <td className="px-5 py-2.5">{r.decision}</td>
                  <td data-testid="matched-result" className={`px-5 py-2.5 ${r.applied ? "font-semibold" : ""}`}>
                    {r.result}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p role={view.kind === "invalid" ? "alert" : undefined} data-testid="matched-note" className={`rounded-group border border-line px-5 py-3 ${view.kind === "invalid" ? "text-danger" : "text-ink-2"}`}>
          {view.kind === "missing" ? NO_DATA_TEXT : view.kind === "empty" ? NO_RULE_TEXT : BAD_DATA_TEXT}
        </p>
      )}
    </section>
  );
}
