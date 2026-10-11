import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, errorMessage, type Issue, routeMissing } from "../../api/errors.ts";
import type { Client } from "../../api/client.ts";
import { api } from "../../api/http.ts";
import { POLICY_MAX_BYTES, policyQuery, policyVersionsQuery, putPolicy, restorePolicyVersion, utf8Bytes } from "../../api/policy.ts";
import type { PolicySaved, PolicyVersionItem } from "../../api/types.ts";
import { hasPerm } from "../../auth/permissions.ts";
import { useMe } from "../../auth/useAuth.ts";
import { Modal } from "../../components/Modal.tsx";
import { Segmented } from "../../components/Segmented.tsx";
import { useReauthRetry } from "../../components/useReauthRetry.tsx";
import { Forbidden } from "../Forbidden.tsx";
import { POLICY_MISSING_TITLE } from "./metrics.ts";
import { MissingPanel, MockNote } from "./panels.tsx";
import { PolicyHistory } from "./PolicyHistory.tsx";
import { PolicyTable } from "./PolicyTable.tsx";
import {
  checkPolicyText,
  duplicateText,
  formatPolicy,
  lineAt,
  locLine,
  restoreConfirmText,
  syntaxText,
  TOO_LARGE_TEXT,
  VERSION_CONFLICT_TEXT,
} from "./policyText.ts";

// B4MgrPolicy (P10 §3.3; F5 P7). Route CHƯA CÓ — Phase 7 (MSW ở dev:mock; dev thật → 404 → "Chính sách có từ Phase 7").
// - Tab "JSON" = ô sửa có cột số dòng (không thư viện editor). Tab "Bảng" chỉ xem. Kiểm phía máy khách CHỈ cú pháp
//   (JSON.parse quyết; vị trí từ policyText.ts) → nút Lưu khoá. Kiểm nghĩa là của server: 422 `invalid_policy`
//   `errors[{loc, msg}]` → đánh dấu đúng dòng theo `loc`.
// - PUT gửi `base_version_id` = bản mà nháp dựa trên (giữ nguyên khi dữ liệu tải lại ngầm); 409 `version_conflict` →
//   báo, KHÔNG ghi đè, không tự gửi lại.
// - Lưu / quay lui: 403 `reauth_required` → đăng nhập lại (luồng F1, có OTP) → gửi lại ĐÚNG 1 lần (useReauthRetry).
// - Quay lui = TẠO phiên bản mới chép nội dung bản chọn (Q-fe-26). Không tự lưu, không lưu nháp vào bộ nhớ trình
//   duyệt; rời trang khi có nháp → mất nháp (PLAN-fe mục 7 #21).

type Tab = "table" | "json";
const TABS: readonly { key: Tab; label: string }[] = [
  { key: "table", label: "Bảng" },
  { key: "json", label: "JSON" },
];

/** Nháp: `base` = version_id mà nháp dựa trên; `original` = văn bản lúc nạp (so để biết có thay đổi). */
type Draft = { base: number; original: string; text: string };
type Message = { tone: "ok" | "error"; text: string };

const MISSING_TEXT = "Máy chủ chưa có chức năng chính sách. Khi Phase 7 làm xong, màn này tự dùng dữ liệu thật — không cần sửa giao diện.";
const LINE_PX = 26; // leading-6.5

function saveErrorMessage(e: unknown): string {
  if (routeMissing(e)) return `${POLICY_MISSING_TITLE} — máy chủ chưa có chức năng này.`;
  if (e instanceof ApiError && e.status === 413) return TOO_LARGE_TEXT;
  return errorMessage(e instanceof ApiError ? e : null);
}

/** `client` mặc định là client dùng chung — CÙNG client với đăng nhập lại (test truyền client riêng, như t48). */
export function PolicyEditor({ client = api }: { client?: Client }) {
  const me = useMe();
  const canEdit = hasPerm(me, "policy:edit");
  const queryClient = useQueryClient();
  const policy = useQuery(policyQuery(client));
  const versions = useQuery(policyVersionsQuery(client));
  const [tab, setTab] = useState<Tab>("table");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [message, setMessage] = useState<Message | null>(null);
  const [conflict, setConflict] = useState(false);
  const [confirming, setConfirming] = useState<PolicyVersionItem | null>(null);
  const [jump, setJump] = useState<{ line: number } | null>(null);
  const [sentText, setSentText] = useState<string | null>(null); // văn bản của lần PUT gần nhất — định vị 422 khi ô sửa lỗi cú pháp

  // Nạp / làm mới nháp từ server: lần đầu, hoặc khi server có bản mới mà nháp CHƯA sửa. Đang tải lại → chờ (không nạp
  // dữ liệu cũ). Nháp đã sửa → giữ nguyên, kể cả `base` (bản mới của người khác → PUT sẽ 409, không ghi đè).
  if (policy.data && !policy.isFetching && (draft === null || (draft.text === draft.original && draft.base !== policy.data.version_id))) {
    const original = formatPolicy(policy.data.content);
    setDraft({ base: policy.data.version_id, original, text: original });
  }

  const text = draft?.text ?? "";
  const dirty = draft !== null && draft.text !== draft.original;
  const check = useMemo(() => checkPolicyText(text), [text]);
  const bytes = useMemo(() => utf8Bytes(text), [text]);
  const tooLarge = bytes > POLICY_MAX_BYTES;

  const reloadAll = () => void queryClient.invalidateQueries({ queryKey: ["policy"] });

  const save = useReauthRetry({
    send: async (p: { body: { content: Record<string, unknown>; base_version_id: number }; text: string }) => ({
      saved: await putPolicy(p.body, client),
      text: p.text,
    }),
    onSuccess: ({ saved, text: savedText }: { saved: PolicySaved; text: string }) => {
      setIssues([]);
      setSentText(null);
      setDraft({ base: saved.version_id, original: savedText, text: savedText });
      setMessage({ tone: "ok", text: `Đã lưu thành bản ${saved.version}.` });
      reloadAll();
    },
    onFailure: (e) => {
      if (e instanceof ApiError && e.status === 422 && (e.code === "invalid_policy" || e.issues.length > 0)) {
        setIssues(e.issues.length > 0 ? e.issues : [{ loc: [], msg: errorMessage(e) }]);
        setMessage({ tone: "error", text: "Chưa lưu — chính sách chưa hợp lệ, xem các dòng được đánh dấu." });
      } else if (e instanceof ApiError && e.status === 409 && e.code === "version_conflict") {
        setConflict(true);
        setMessage({ tone: "error", text: VERSION_CONFLICT_TEXT });
      } else {
        setMessage({ tone: "error", text: saveErrorMessage(e) });
      }
    },
    onCancelled: () => setMessage({ tone: "error", text: "Chưa lưu — cần đăng nhập lại để xác nhận thao tác này." }),
    otherUserFlash: "policy_other_user",
  });

  const restore = useReauthRetry({
    send: async (v: PolicyVersionItem) => ({ saved: await restorePolicyVersion(v.version_id, client), from: v.version }),
    onSuccess: ({ saved, from }: { saved: PolicySaved; from: string }) => {
      setIssues([]);
      setConflict(false);
      setSentText(null);
      setMessage({ tone: "ok", text: `Đã áp dụng lại nội dung bản ${from} thành bản ${saved.version}.` });
      reloadAll();
      setDraft(null); // nạp lại từ bản mới (đang tải → chờ, không nạp bản cũ)
    },
    onFailure: (e) => setMessage({ tone: "error", text: saveErrorMessage(e) }),
    onCancelled: () => setMessage({ tone: "error", text: "Chưa quay lui — cần đăng nhập lại để xác nhận thao tác này." }),
    otherUserFlash: "policy_other_user",
  });

  const busy = save.sending || restore.sending;

  if (policy.error instanceof ApiError && policy.error.status === 403) return <Forbidden />;
  if (routeMissing(policy.error)) {
    return (
      <section className="flex flex-col gap-6 px-12 py-10">
        <h1 className="text-title">Chính sách</h1>
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
  if (tooLarge) problems.push({ line: null, text: `${TOO_LARGE_TEXT} — ${Math.ceil(bytes / 1024)} KB, tối đa ${POLICY_MAX_BYTES / 1024} KB` });
  for (const issue of issues) {
    const line = issueLine(issue.loc);
    problems.push({ line, text: `${line === null ? "Toàn tệp" : `Dòng ${line}`} · ${issue.msg}` });
  }
  const warnings = check.valid ? check.duplicates.map((d) => ({ line: d.lines[d.lines.length - 1]!, lines: d.lines, text: duplicateText(d) })) : [];
  const errorLines = new Set(problems.flatMap((p) => (p.line === null ? [] : [p.line])));
  const warnLines = new Set(warnings.flatMap((w) => w.lines));
  const blocking = (check.valid ? 0 : 1) + (tooLarge ? 1 : 0);
  const canSave = canEdit && draft !== null && dirty && check.valid && !tooLarge && !busy;

  function onSave() {
    if (!canSave || !check.valid || draft === null || save.busy()) return;
    setMessage(null);
    setConflict(false);
    setSentText(text);
    save.run({ body: { content: check.value as Record<string, unknown>, base_version_id: draft.base }, text });
  }

  function reloadLatest() {
    setConflict(false);
    setIssues([]);
    setMessage(null);
    setSentText(null);
    reloadAll();
    setDraft(null);
  }

  function edit(next: string) {
    setDraft((d) => (d ? { ...d, text: next } : d));
  }

  const current = policy.data;
  return (
    <section className="flex flex-col gap-6 px-12 py-10">
      <div className="flex items-end gap-3">
        <div className="flex min-w-0 grow flex-col gap-1">
          <h1 className="text-title">Chính sách</h1>
          <p className="flex items-center gap-2 text-ink-2">
            {current ? `Đang áp dụng bản ${current.version}` : "Đang tải chính sách…"}
            {dirty ? (
              <span data-testid="draft-mark" className="inline-flex items-center gap-1.5 text-orange-ink">
                <span className="size-1.75 rounded-full bg-fpt-orange" aria-hidden="true" />
                Bản nháp chưa lưu
              </span>
            ) : null}
          </p>
        </div>
        <Segmented label="Cách hiển thị chính sách" options={TABS} value={tab} onChange={setTab} />
        {canEdit ? (
          <button
            type="button"
            onClick={onSave}
            disabled={!canSave}
            className="h-11 rounded-full bg-fpt-blue px-5 font-semibold text-white disabled:bg-line disabled:text-ink-2"
          >
            {save.sending ? "Đang lưu…" : blocking > 0 ? `Lưu · còn ${blocking} lỗi` : "Lưu"}
          </button>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <MockNote text="chính sách thật có từ Phase 7" />
        {canEdit ? null : <span className="text-secondary text-ink-2">Bạn chỉ có quyền xem chính sách.</span>}
      </div>

      {message ? (
        <div className="flex items-center gap-3">
          <p role={message.tone === "ok" ? "status" : "alert"} data-testid="policy-message" className={`text-secondary ${message.tone === "ok" ? "text-ink-2" : "text-danger"}`}>
            {message.text}
          </p>
          {conflict ? (
            <button type="button" onClick={reloadLatest} className="h-7.5 shrink-0 rounded-full bg-button-2 px-3.5 text-label text-fpt-blue">
              Tải bản mới nhất (bỏ bản nháp)
            </button>
          ) : null}
        </div>
      ) : null}

      {policy.isError ? (
        <p role="alert" className="text-danger">
          Chưa tải được chính sách: {errorMessage(policy.error instanceof ApiError ? policy.error : null)}
        </p>
      ) : draft === null ? (
        <p className="text-ink-2">Đang tải chính sách…</p>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-6">
          <div className="min-w-0">
            {tab === "table" ? (
              <PolicyTable check={check} issues={issues} />
            ) : (
              <JsonEditor
                text={text}
                onChange={edit}
                readOnly={!canEdit || busy}
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
                  Cần sửa trước khi lưu
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
                  Lưu ý (không chặn lưu)
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
                <p className="rounded-group border border-line px-4 py-3 text-secondary text-ink-2">Chưa tải được lịch sử phiên bản.</p>
              ) : versions.data ? (
                <PolicyHistory versions={versions.data} dirty={dirty} canEdit={canEdit} busy={busy} onRestore={setConfirming} />
              ) : (
                <p className="px-1 text-secondary text-ink-2">Đang tải lịch sử…</p>
              )}
              {canEdit ? (
                <span className="px-1 text-label font-normal text-ink-2">Lưu hoặc quay lui cần nhập lại mã 6 số nếu đã quá 10 phút.</span>
              ) : null}
            </section>
          </aside>
        </div>
      )}

      {confirming ? (
        <Modal label="Áp dụng lại phiên bản" onClose={() => setConfirming(null)}>
          <h2 className="text-center text-heading">Quay lui bản {confirming.version}?</h2>
          <p data-testid="restore-confirm-text" className="text-center text-ink-2">
            {restoreConfirmText(confirming.version)}
          </p>
          {dirty ? <p className="text-center text-secondary text-orange-ink">Bản nháp chưa lưu sẽ bị thay bằng nội dung mới.</p> : null}
          <div className="grid grid-cols-2 gap-3">
            <button type="button" onClick={() => setConfirming(null)} className="h-11 rounded-full bg-button-2 font-semibold">
              Huỷ
            </button>
            <button
              type="button"
              onClick={() => {
                const target = confirming;
                setConfirming(null);
                setMessage(null);
                restore.run(target);
              }}
              className="h-11 rounded-full bg-fpt-blue font-semibold text-white"
            >
              Áp dụng lại
            </button>
          </div>
        </Modal>
      ) : null}
      {save.dialog}
      {restore.dialog}
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
