import type { Issue } from "../../api/errors.ts";
import { FlatTable } from "../../components/ActionView.tsx";
import { ownEntry } from "../../lib/lookup.ts";
import type { PolicyCheck } from "./policyText.ts";

// Tab "Bảng" của B4MgrPolicy — CHỈ XEM (sửa ở tab JSON; PLAN-fe mục 7 #21), dựng từ JSON ĐANG có trong ô sửa. Giá trị
// lấy từ `JSON.parse` (khoá trùng → giá trị sau cùng, giống server). JSON lỗi cú pháp → không hiện bản cũ (Q-fe-31).
// Dòng có lỗi 422 của server (theo `loc`) được tô đỏ kèm câu của server. Chữ thô — không Markdown/HTML.

/** Nhãn hằng số (config/policy.json `constants`); khoá lạ → hiện nguyên khoá. */
const CONSTANT_LABEL: Record<string, string> = {
  MAX_LOOPS: "Số vòng xử lý tối đa",
  MAX_CLARIFICATION_TURNS: "Hỏi lại tối đa (lượt)",
  TOOL_RETRY: "Thử lại công cụ (lần)",
  BACKOFF_BASE_SECONDS: "Chờ cơ sở khi thử lại (giây)",
  MAX_AUTH_FAILURES: "Đăng nhập sai tối đa",
  AUTH_FAILURE_WINDOW_MINUTES: "Cửa sổ đếm đăng nhập sai (phút)",
  SLA_MINUTES: "Hạn duyệt (phút)",
  THRESHOLD_LOW: "Ngưỡng dưới",
  THRESHOLD_HIGH: "Ngưỡng trên",
  RETRIEVAL_THRESHOLD: "Ngưỡng truy hồi tài liệu",
  TAU_INTENT: "Ngưỡng tin cậy ý định",
  CLARIFY_TIMEOUT_HOURS: "Chờ người dùng bổ sung (giờ)",
  CONFIRM_TIMEOUT_HOURS: "Chờ người dùng xác nhận (giờ)",
};

type RuleType = { label: string; tone: string };
const RULE_TYPE: Record<string, RuleType> = {
  allow: { label: "Cho phép", tone: "text-ink-2" },
  approval_required: { label: "Cần duyệt", tone: "font-semibold text-orange-ink" },
  deny: { label: "Cấm", tone: "font-semibold text-danger" },
};

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const raw = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

/** Câu lỗi của server cho đúng đường dẫn (so `loc` từ đầu). */
function issuesAt(issues: readonly Issue[], ...prefix: (string | number)[]): string[] {
  return issues.filter((i) => prefix.every((p, k) => String(i.loc[k]) === String(p))).map((i) => i.msg);
}

function Flag({ messages }: { messages: string[] }) {
  if (messages.length === 0) return null;
  return <span className="text-label font-normal text-danger">{messages.join(" · ")}</span>;
}

export function PolicyTable({ check, issues }: { check: PolicyCheck; issues: readonly Issue[] }) {
  if (!check.valid) {
    return (
      <p data-testid="table-invalid" className="rounded-group bg-group px-5 py-4 text-ink-2">
        JSON đang lỗi cú pháp — sửa ở tab JSON rồi xem lại bảng.
      </p>
    );
  }
  const value = check.value;
  if (!isRecord(value)) {
    return (
      <div className="overflow-hidden rounded-group border border-line">
        <FlatTable value={value} testId="policy-other-row" />
      </div>
    );
  }
  const { constants, rules, ...rest } = value;
  return (
    <div className="flex flex-col gap-5">
      <section aria-labelledby="policy-constants" className="flex flex-col gap-2">
        <h2 id="policy-constants" className="pl-1 text-label text-ink-2">
          Hằng số
        </h2>
        {isRecord(constants) ? (
          <ul className="overflow-hidden rounded-group border border-line">
            {Object.entries(constants).map(([key, v]) => {
              const flags = issuesAt(issues, "constants", key);
              const label = ownEntry<string | null>(CONSTANT_LABEL, key, null); // khoá chưa có nhãn → chỉ hiện khoá một lần (L3)
              return (
                <li
                  key={key}
                  data-testid="constant-row"
                  data-key={key}
                  data-flagged={flags.length > 0}
                  className={`flex items-center justify-between gap-4 border-t border-line px-5 py-3 first:border-t-0 ${flags.length ? "bg-danger-bg" : ""}`}
                >
                  <span className="flex min-w-0 flex-col">
                    <span className={label === null ? "font-mono" : undefined}>{label ?? key}</span>
                    {label !== null ? <span className="font-mono text-label font-normal text-ink-2">{key}</span> : null}
                    <Flag messages={flags} />
                  </span>
                  <span className={`shrink-0 font-mono ${flags.length ? "font-semibold text-danger" : "text-ink-2"}`}>{raw(v)}</span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="rounded-group border border-line px-5 py-3 text-ink-2">Không có khối hằng số (constants).</p>
        )}
        {/* Lỗi của cả khối (loc = ["constants"], vd kiểm chéo hai ngưỡng ở mức model). */}
        <Flag messages={issues.filter((i) => i.loc.length === 1 && i.loc[0] === "constants").map((i) => i.msg)} />
      </section>

      <section aria-labelledby="policy-rules" className="flex flex-col gap-2">
        <h2 id="policy-rules" className="pl-1 text-label text-ink-2">
          Luật{Array.isArray(rules) ? ` · ${rules.length}` : ""}
        </h2>
        {Array.isArray(rules) ? (
          <ul className="overflow-hidden rounded-group border border-line">
            {rules.map((rule, index) => {
              const r = isRecord(rule) ? rule : {};
              // Khoá riêng (Object.hasOwn): type "constructor" / "__proto__" phải ra "Không hợp lệ", không phải hàm của prototype.
              const type = ownEntry<RuleType | undefined>(RULE_TYPE, String(r.type), undefined);
              const flags = issuesAt(issues, "rules", index);
              return (
                <li
                  key={index}
                  data-testid="rule-row"
                  data-flagged={flags.length > 0}
                  className={`grid grid-cols-[48px_minmax(0,1fr)_auto] items-center gap-4 border-t border-line px-5 py-2.5 first:border-t-0 ${flags.length ? "bg-danger-bg" : ""}`}
                >
                  <span className="font-mono text-label font-normal text-ink-2">{raw(r.id ?? "?")}</span>
                  <span className="flex min-w-0 flex-col">
                    <span className="text-secondary">{typeof r.description === "string" ? r.description : "(không có mô tả)"}</span>
                    <Flag messages={flags} />
                  </span>
                  <span className={`text-secondary ${type ? type.tone : "font-semibold text-danger"}`}>
                    {type ? type.label : `Không hợp lệ (${raw(r.type)})`}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="rounded-group border border-line px-5 py-3 text-ink-2">Không có danh sách luật (rules).</p>
        )}
      </section>

      {Object.keys(rest).length > 0 ? (
        <section aria-labelledby="policy-other" className="flex flex-col gap-2">
          <h2 id="policy-other" className="pl-1 text-label text-ink-2">
            Khác
          </h2>
          <div className="overflow-hidden rounded-group border border-line">
            <FlatTable value={rest} testId="policy-other-row" />
          </div>
        </section>
      ) : null}
    </div>
  );
}
