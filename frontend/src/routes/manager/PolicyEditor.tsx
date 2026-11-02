import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, errorMessage, type Issue, routeMissing } from "../../api/errors.ts";
import type { Client } from "../../api/client.ts";
import { api } from "../../api/http.ts";
import { POLICY_MAX_BYTES, policyQuery, policyVersionsQuery, utf8Bytes, validateBodyBytes, validatePolicy } from "../../api/policy.ts";
import { hasPerm } from "../../auth/permissions.ts";
import { useMe } from "../../auth/useAuth.ts";
import { Segmented } from "../../components/Segmented.tsx";
import { Forbidden } from "../Forbidden.tsx";
import { POLICY_MISSING_TITLE } from "./metrics.ts";
import { MissingPanel } from "./panels.tsx";
import { PolicyHistory } from "./PolicyHistory.tsx";
import { PolicyTable } from "./PolicyTable.tsx";
import { StrategySection } from "./StrategySection.tsx";
import {
  checkFailure,
  checkPolicyText,
  duplicateText,
  formatPolicy,
  lineAt,
  locLine,
  NOT_OBJECT_TEXT,
  syntaxText,
  TOO_LARGE_TEXT,
  VALID_TEXT,
} from "./policyText.ts";

// B4MgrPolicy (P10 §3.3; F7 route THẬT — N-POL1): XEM chính sách đang chạy + lịch sử phiên bản, KIỂM bản đang sửa. Đầu
// trang: khối "Cách xử lý của hệ thống" (D-67, N-PA P2 — StrategySection.tsx, route riêng, đổi được khi có policy:edit).
// - Tab "JSON" = ô sửa có cột số dòng (không thư viện editor). Tab "Bảng" chỉ xem. Kiểm phía máy khách CHỈ cú pháp
//   (JSON.parse quyết; vị trí từ policyText.ts) + gốc phải là object + trần 64 KB của thân → nút Kiểm tra khoá. Kiểm
//   NGHĨA là của server: `POST /api/policy/validate` → 422 `invalid_policy` `errors[{loc, msg}]` → đánh dấu đúng dòng
//   theo `loc` (đường dẫn cấu trúc từ gốc nội dung).
// - Kiểm tra cần `policy:edit` (route validate); chỉ `policy:read` → chỉ xem, ô JSON chỉ đọc, không nút.
// - 403 → câu "không có quyền"; 5xx / lỗi mạng / thân sai dạng → câu chung, KHÔNG hiện chi tiết máy chủ.
// - KHÔNG có Lưu / Quay lui / Mô phỏng: backend chưa có route (PUT /api/policy → 405; …/restore, /simulate → 404). Nút
//   cũ (PUT + restore theo [Đề xuất F5]) đã gỡ cùng hàm gọi API — N-POL2 thêm lại theo hợp đồng thật. Nội dung sửa trong
//   ô chỉ để kiểm, không lưu đi đâu (rời trang → mất).

type Tab = "table" | "json";
const TABS: readonly { key: Tab; label: string }[] = [
  { key: "table", label: "Bảng" },
  { key: "json", label: "JSON" },
];

/** Nháp: `base` = `version` mà nháp dựa trên; `original` = văn bản lúc nạp (so để biết có thay đổi). */
type Draft = { base: string; original: string; text: string };
type Message = { tone: "ok" | "error"; text: string };

const MISSING_TEXT = "Máy chủ chưa có chức năng chính sách. Khi máy chủ có, màn này tự dùng dữ liệu thật — không cần sửa giao diện.";
const LINE_PX = 26; // leading-6.5

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);

/** `client` mặc định là client dùng chung (test truyền client riêng). */
export function PolicyEditor({ client = api }: { client?: Client }) {
  const me = useMe();
  const canCheck = hasPerm(me, "policy:edit");
  const policy = useQuery(policyQuery(client));
  const versions = useQuery(policyVersionsQuery(client));
  const [tab, setTab] = useState<Tab>("table");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [message, setMessage] = useState<Message | null>(null);
  const [jump, setJump] = useState<{ line: number } | null>(null);
  const [checking, setChecking] = useState(false);
  const [sentText, setSentText] = useState<string | null>(null); // văn bản của lần kiểm gần nhất — định vị 422 khi ô sửa lỗi cú pháp
  const run = useRef(0); // lần kiểm mới nhất — kết quả của lần cũ về muộn bị bỏ

  // Nạp / làm mới nháp từ server: lần đầu, hoặc khi server có bản mới mà nháp CHƯA sửa. Đang tải lại → chờ (không nạp
  // dữ liệu cũ). Nháp đã sửa → giữ nguyên.
  if (policy.data && !policy.isFetching && (draft === null || (draft.text === draft.original && draft.base !== policy.data.version))) {
    const original = formatPolicy(policy.data.content);
    setDraft({ base: policy.data.version, original, text: original });
  }

  const text = draft?.text ?? "";
  const dirty = draft !== null && draft.text !== draft.original;
  const check = useMemo(() => checkPolicyText(text), [text]);
  const notObject = check.valid && !isRecord(check.value);
  const bytes = useMemo(() => (check.valid && isRecord(check.value) ? validateBodyBytes(check.value) : utf8Bytes(text)), [check, text]);
  const tooLarge = bytes > POLICY_MAX_BYTES;

  if (policy.error instanceof ApiError && policy.error.status === 403) return <Forbidden />;
  if (routeMissing(policy.error)) {
    return (
      <section className="flex flex-col gap-6 px-12 py-10">
        <h1 className="text-title">Chính sách</h1>
        <StrategySection client={client} />
        <MissingPanel testId="policy-missing" title={POLICY_MISSING_TITLE} text={MISSING_TEXT} />
      </section>
    );
  }

  // Dòng của lỗi 422: theo cây của văn bản ĐANG có (loc là đường dẫn cấu trúc → sửa chỗ khác không lệch dòng); văn bản
  // đang lỗi cú pháp → theo văn bản đã gửi.
  const issueLine = (loc: readonly (string | number)[]) =>
    check.valid && check.root ? lineAt(check.root, loc) : sentText !== null ? locLine(sentText, loc) : null;
  const problems: { line: number | null; text: string }[] = [];
  if (!check.valid) problems.push({ line: check.line, text: syntaxText(check) });
  if (notObject) problems.push({ line: null, text: `Toàn tệp · ${NOT_OBJECT_TEXT}` });
  if (tooLarge) problems.push({ line: null, text: `${TOO_LARGE_TEXT} — ${Math.ceil(bytes / 1024)} KB, tối đa ${POLICY_MAX_BYTES / 1024} KB` });
  for (const issue of issues) {
    const line = issueLine(issue.loc);
    problems.push({ line, text: `${line === null ? "Toàn tệp" : `Dòng ${line}`} · ${issue.msg}` });
  }
  const warnings = check.valid ? check.duplicates.map((d) => ({ line: d.lines[d.lines.length - 1]!, lines: d.lines, text: duplicateText(d) })) : [];
  const errorLines = new Set(problems.flatMap((p) => (p.line === null ? [] : [p.line])));
  const warnLines = new Set(warnings.flatMap((w) => w.lines));
  const blocking = (check.valid ? 0 : 1) + (notObject ? 1 : 0) + (tooLarge ? 1 : 0);
  const canSend = canCheck && draft !== null && check.valid && !notObject && !tooLarge && !checking;

  async function onCheck() {
    if (!canSend || !check.valid || !isRecord(check.value)) return;
    const mine = ++run.current;
    setMessage(null);
    setIssues([]);
    setSentText(text);
    setChecking(true);
    try {
      await validatePolicy(check.value, client);
      if (mine === run.current) setMessage({ tone: "ok", text: VALID_TEXT });
    } catch (e) {
      if (mine !== run.current) return;
      const failure = checkFailure(e);
      setIssues(failure.issues);
      setMessage({ tone: "error", text: failure.text });
    } finally {
      if (mine === run.current) setChecking(false);
    }
  }

  function edit(next: string) {
    setDraft((d) => (d ? { ...d, text: next } : d));
    if (message?.tone === "ok") setMessage(null); // "hợp lệ" chỉ đúng cho văn bản đã kiểm
  }

  const current = policy.data;
  // Soát 01/11 M4 (ĐP 02/11): chưa có dữ liệu mà tải lỗi → CHỈ câu lỗi + "Thử lại" (không "Đang tải…", không nút Kiểm tra,
  // không tab Bảng/JSON — trước đây hiện cùng lúc ba trạng thái mâu thuẫn).
  const loadFailed = policy.isError && draft === null;
  return (
    <section className="flex flex-col gap-6 px-12 py-10">
      <h1 className="text-title">Chính sách</h1>
      {/* N-PA P2: cách xử lý của hệ thống (D-67) — độc lập với nội dung chính sách bên dưới. */}
      <StrategySection client={client} />
      <div className="flex items-end gap-3 border-t border-line pt-6">
        <div className="flex min-w-0 grow flex-col gap-1">
          <h2 className="text-heading">Nội dung chính sách</h2>
          {loadFailed ? null : (
            <p className="flex items-center gap-2 text-ink-2">
              {current ? `Đang áp dụng bản ${current.version}` : "Đang tải chính sách…"}
              {dirty ? (
                <span data-testid="draft-mark" className="inline-flex items-center gap-1.5 text-orange-ink">
                  <span className="size-1.75 rounded-full bg-fpt-orange" aria-hidden="true" />
                  Đã sửa — chưa lưu
                </span>
              ) : null}
            </p>
          )}
        </div>
        {loadFailed ? null : <Segmented label="Cách hiển thị chính sách" options={TABS} value={tab} onChange={setTab} />}
        {canCheck && !loadFailed ? (
          <button
            type="button"
            onClick={() => void onCheck()}
            disabled={!canSend}
            className="h-11 rounded-full bg-fpt-blue px-5 font-semibold text-white disabled:bg-line disabled:text-ink-2"
          >
            {checking ? "Đang kiểm tra…" : blocking > 0 ? `Kiểm tra · còn ${blocking} lỗi` : "Kiểm tra"}
          </button>
        ) : null}
      </div>

      {loadFailed ? null : (
        <p data-testid="policy-mode" className="text-secondary text-ink-2">
          {canCheck
            ? "Màn này chỉ xem và kiểm tra chính sách — chưa lưu được thay đổi từ đây."
            : "Bạn chỉ có quyền xem chính sách."}
        </p>
      )}

      {message ? (
        <p role={message.tone === "ok" ? "status" : "alert"} data-testid="policy-message" className={`text-secondary ${message.tone === "ok" ? "text-ink-2" : "text-danger"}`}>
          {message.text}
        </p>
      ) : null}

      {policy.isError ? (
        <div className="flex flex-col items-start gap-3">
          <p role="alert" data-testid="policy-load-error" className="text-danger">
            Chưa tải được chính sách: {errorMessage(policy.error instanceof ApiError ? policy.error : null)}
          </p>
          <button
            type="button"
            data-testid="policy-retry"
            onClick={() => void policy.refetch()}
            disabled={policy.isFetching}
            className="h-9 rounded-full bg-button-2 px-5 text-secondary font-semibold text-fpt-blue disabled:opacity-60"
          >
            {policy.isFetching ? "Đang tải lại…" : "Thử lại"}
          </button>
        </div>
      ) : draft === null ? (
        <p className="text-ink-2 motion-safe:animate-pulse">Đang tải chính sách…</p>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-6">
          <div className="min-w-0">
            {tab === "table" ? (
              <PolicyTable check={check} issues={issues} />
            ) : (
              <JsonEditor
                text={text}
                onChange={edit}
                readOnly={!canCheck || checking}
                invalid={!check.valid}
                errorLines={errorLines}
                warnLines={warnLines}
                jump={jump}
              />
            )}
          </div>
          <aside className="flex min-w-0 flex-col gap-5">
            {problems.length > 0 ? (
              <section aria-labelledby="policy-problems-heading" className="flex flex-col gap-2">
                <h2 id="policy-problems-heading" className="pl-1 text-label text-ink-2">
                  Cần sửa
                </h2>
                <ul id="policy-problems" data-testid="policy-problems" className="flex flex-col gap-1.5 rounded-group bg-danger-bg px-4 py-3.5 text-secondary text-danger-ink">
                  {problems.map((p, k) => (
                    <li key={k} data-testid="policy-problem" data-line={p.line ?? ""}>
                      <ProblemText line={p.line} text={p.text} onJump={(line) => { setTab("json"); setJump({ line }); }} />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            {warnings.length > 0 ? (
              <section aria-labelledby="policy-warnings-heading" className="flex flex-col gap-2">
                <h2 id="policy-warnings-heading" className="pl-1 text-label text-ink-2">
                  Lưu ý (không chặn kiểm tra)
                </h2>
                <ul data-testid="policy-warnings" className="flex flex-col gap-1.5 rounded-group bg-orange-bg px-4 py-3.5 text-secondary text-orange-ink">
                  {warnings.map((w, k) => (
                    <li key={k} data-testid="policy-warning" data-line={w.line}>
                      {w.text}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            <section aria-labelledby="policy-history-heading" className="flex flex-col gap-2">
              <h2 id="policy-history-heading" className="pl-1 text-label text-ink-2">
                Lịch sử phiên bản
              </h2>
              {versions.isError ? (
                <p data-testid="versions-error" className="rounded-group border border-line px-4 py-3 text-secondary text-ink-2">
                  Chưa tải được lịch sử phiên bản.
                </p>
              ) : versions.data ? (
                <PolicyHistory versions={versions.data} dirty={dirty} />
              ) : (
                <p className="px-1 text-secondary text-ink-2 motion-safe:animate-pulse">Đang tải lịch sử…</p>
              )}
            </section>
          </aside>
        </div>
      )}
    </section>
  );
}

function ProblemText({ line, text, onJump }: { line: number | null; text: string; onJump: (line: number) => void }) {
  if (line === null) return <>{text}</>;
  return (
    <button type="button" onClick={() => onJump(line)} className="text-left hover:underline">
      {text}
    </button>
  );
}

/** Ô sửa JSON có cột số dòng (B4MgrPolicy tab JSON). Dòng lỗi → số đỏ; dòng khoá trùng → số cam. Chữ thô. */
function JsonEditor({
  text,
  onChange,
  readOnly,
  invalid,
  errorLines,
  warnLines,
  jump,
}: {
  text: string;
  onChange: (text: string) => void;
  readOnly: boolean;
  invalid: boolean;
  errorLines: ReadonlySet<number>;
  warnLines: ReadonlySet<number>;
  jump: { line: number } | null;
}) {
  const gutter = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const count = text.split("\n").length;

  // Bấm một lỗi ở cột phải → đưa con trỏ tới đầu dòng đó.
  useEffect(() => {
    const el = area.current;
    if (!jump || !el) return;
    const start = text.split("\n").slice(0, jump.line - 1).reduce((sum, l) => sum + l.length + 1, 0);
    el.focus();
    el.setSelectionRange(start, start);
    el.scrollTop = Math.max(0, (jump.line - 3) * LINE_PX);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chỉ chạy khi có yêu cầu nhảy mới
  }, [jump]);

  return (
    <div className="flex h-140 overflow-hidden rounded-group border border-line font-mono text-label leading-6.5 font-normal">
      <div ref={gutter} aria-hidden="true" className="w-12 shrink-0 overflow-hidden py-2 select-none">
        {Array.from({ length: count }, (_, k) => {
          const n = k + 1;
          const mark = errorLines.has(n) ? "error" : warnLines.has(n) ? "warn" : undefined;
          return (
            <div
              key={n}
              data-testid="gutter-line"
              data-line={n}
              data-mark={mark}
              className={`pr-4 text-right ${mark === "error" ? "bg-danger-bg font-semibold text-danger" : mark === "warn" ? "bg-orange-bg font-semibold text-orange-ink" : "text-ink-3"}`}
            >
              {n}
            </div>
          );
        })}
      </div>
      <textarea
        ref={area}
        value={text}
        onChange={(e) => onChange(e.target.value)}
        onScroll={(e) => {
          if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop;
        }}
        readOnly={readOnly}
        spellCheck={false}
        autoCapitalize="none"
        autoComplete="off"
        wrap="off"
        aria-label="Nội dung chính sách (JSON)"
        aria-invalid={invalid || undefined}
        aria-describedby={invalid ? "policy-problems" : undefined}
        className="min-w-0 grow resize-none overflow-auto py-2 pr-4 pl-2 whitespace-pre outline-none"
      />
    </div>
  );
}
