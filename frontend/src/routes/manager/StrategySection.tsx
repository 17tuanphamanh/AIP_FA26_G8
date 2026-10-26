import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import type { Client } from "../../api/client.ts";
import { ApiError, errorMessage, routeMissing } from "../../api/errors.ts";
import { api } from "../../api/http.ts";
import { putStrategy, REASON_MAX, reasonLength, strategyHistoryQuery, strategyQuery } from "../../api/strategy.ts";
import type { RuntimeStrategy, StrategyChange, StrategyIn, StrategyView } from "../../api/types.ts";
import { hasPerm } from "../../auth/permissions.ts";
import { useMe } from "../../auth/useAuth.ts";
import { useReauthRetry } from "../../components/useReauthRetry.tsx";
import { vnDateTime } from "./range.ts";
import {
  appliedText,
  EVAL_MODE_TEXT,
  HISTORY_EMPTY_TEXT,
  HISTORY_HEADING,
  HISTORY_TRUNCATED_TEXT,
  NOT_SELECTABLE_TEXT,
  READONLY_TEXT,
  REASON_LABEL,
  reasonProblem,
  SAME_AS_CURRENT_TEXT,
  showUncalibrated,
  STRATEGY_HEADING,
  STRATEGY_MISSING_TEXT,
  STRATEGY_OPTIONS,
  strategyName,
  UNCALIBRATED_TEXT,
  UNCONFIRMED_TEXT,
} from "./strategyText.ts";

// Khối "Cách xử lý của hệ thống" (D-60; hợp đồng N-PA §1) ở đầu trang Chính sách — route CHƯA CÓ ở backend (be-tuan8):
// dev:mock dùng MSW, backend chưa có route → 404 → câu trung tính (route này không có 404 nào khác trong hợp đồng). Đọc cần `policy:read` (cổng trang); đổi cần
// `policy:edit` + đăng nhập gần đây (403 `reauth_required` → useReauthRetry: cùng người → gửi lại ĐÚNG một lần). Chữ từ
// server (người đổi, lý do) hiện thô — React tự thoát, không Markdown/HTML. Không câu nào khen/chê một phương án.

const NONE = "—";
const BOX = "overflow-hidden rounded-group border border-line";

/** `client` mặc định là client dùng chung (CÙNG client với đăng nhập lại); test truyền client riêng. */
export function StrategySection({ client = api }: { client?: Client }) {
  const current = useQuery(strategyQuery(client));
  // Câu báo nằm NGOÀI form: form dựng lại theo bản mới của server (khoá theo strategy + changed_at) mà câu vẫn còn.
  const [message, setMessage] = useState<Message | null>(null);
  return (
    <section aria-labelledby="strategy-heading" data-testid="strategy-section" className="flex flex-col gap-3">
      <h2 id="strategy-heading" className="text-heading">
        {STRATEGY_HEADING}
      </h2>
      {routeMissing(current.error) || (current.error instanceof ApiError && current.error.status === 404) ? (
        <p data-testid="strategy-missing" className="rounded-group bg-group px-5 py-4 text-ink-2">
          {STRATEGY_MISSING_TEXT}
        </p>
      ) : current.isError ? (
        <p role="alert" data-testid="strategy-error" className="text-danger">
          Chưa tải được cách xử lý: {errorMessage(current.error instanceof ApiError ? current.error : null)}
        </p>
      ) : current.data === undefined ? (
        <p className="text-ink-2">Đang tải cách xử lý…</p>
      ) : (
        <>
          <StrategyForm
            key={`${current.data.strategy}|${current.data.changed_at ?? ""}`}
            view={current.data}
            client={client}
            setMessage={setMessage}
          />
          {message ? (
            <p
              role={message.tone === "ok" ? "status" : "alert"}
              data-testid="strategy-message"
              className={`text-secondary ${message.tone === "ok" ? "text-ink-2" : "text-danger"}`}
            >
              {message.text}
            </p>
          ) : null}
          <StrategyHistoryBlock client={client} />
        </>
      )}
    </section>
  );
}

type Message = { tone: "ok" | "error"; text: string };

function StrategyForm({ view, client, setMessage }: { view: StrategyView; client: Client; setMessage: (m: Message | null) => void }) {
  const me = useMe();
  const canEdit = hasPerm(me, "policy:edit");
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<RuntimeStrategy>(view.strategy);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [choiceError, setChoiceError] = useState<string | null>(null);
  const changed = selected !== view.strategy;

  const reloadCurrent = () => void queryClient.invalidateQueries({ queryKey: strategyQuery(client).queryKey });
  const reloadHistory = () => void queryClient.invalidateQueries({ queryKey: strategyHistoryQuery(client).queryKey });

  const retry = useReauthRetry<StrategyIn, StrategyView>({
    send: (body) => putStrategy(body, client),
    onSuccess: (next) => {
      queryClient.setQueryData(strategyQuery(client).queryKey, next); // khoá form đổi theo bản mới → form dựng lại sạch
      reloadHistory();
      setMessage({ tone: "ok", text: appliedText(next.strategy) });
    },
    onFailure: (e) => {
      const err = e instanceof ApiError ? e : null;
      if (err?.status === 409 && err.code === "same_as_current") {
        setMessage({ tone: "error", text: SAME_AS_CURRENT_TEXT });
        reloadCurrent();
        reloadHistory();
        return;
      }
      // PUT có thể ĐÃ ghi nhưng trả 2xx khác 200 / 200 thân sai hình (client đặt 502): không biết phương án nào đang áp dụng →
      // KHÔNG báo thành công, KHÔNG giữ phương án cũ là "đang áp dụng" — tải lại trạng thái + lịch sử từ server.
      if (err?.status === 502 && (err.code === "unexpected_strategy_status" || err.code === "invalid_strategy_body")) {
        setMessage({ tone: "error", text: UNCONFIRMED_TEXT });
        reloadCurrent();
        reloadHistory();
        return;
      }
      if (err?.status === 422 && err.fields.length > 0) {
        if (err.fields.includes("reason")) setReasonError("Máy chủ không nhận lý do này — cần 10–500 ký tự sau khi bỏ khoảng trắng.");
        if (err.fields.includes("strategy")) setChoiceError(NOT_SELECTABLE_TEXT);
        if (!err.fields.includes("reason") && !err.fields.includes("strategy")) setMessage({ tone: "error", text: errorMessage(err) });
        return;
      }
      setMessage({ tone: "error", text: errorMessage(err) }); // không bao giờ dội lại nội dung lý do
    },
    onCancelled: () => setMessage({ tone: "error", text: "Chưa áp dụng — đăng nhập lại chưa xong." }),
    otherUserFlash: "policy_other_user",
  });

  const selectable = new Set<string>(view.selectable);
  const locked = (key: RuntimeStrategy) => !canEdit || !selectable.has(key);
  const applyBlocked = view.eval_mode || retry.sending;

  function pick(key: RuntimeStrategy) {
    if (locked(key)) return; // không chọn được — kể cả bằng bàn phím
    setSelected(key);
    setChoiceError(null);
    setMessage(null);
  }

  function apply() {
    if (!canEdit || !changed || applyBlocked || retry.busy()) return;
    const problem = reasonProblem(reason);
    setReasonError(problem);
    if (problem !== null) return;
    setMessage(null);
    retry.run({ strategy: selected, reason });
  }

  return (
    <div className="flex flex-col gap-3">
      <dl data-testid="strategy-current" className={`${BOX} text-secondary`}>
        <Row label="Đang áp dụng" testId="strategy-current-name">
          {strategyName(view.strategy)}
        </Row>
        <Row label="Người đổi" testId="strategy-changed-by">
          {view.changed_by ?? NONE}
        </Row>
        <Row label="Lúc đổi" testId="strategy-changed-at">
          {view.changed_at ? vnDateTime(view.changed_at) : NONE}
        </Row>
        <Row label="Lý do" testId="strategy-reason">
          {view.reason ?? NONE}
        </Row>
      </dl>

      {view.eval_mode ? (
        <p role="note" data-testid="strategy-eval-mode" className="rounded-group bg-group px-5 py-3.5">
          {EVAL_MODE_TEXT}
        </p>
      ) : null}
      {!canEdit ? (
        <p data-testid="strategy-readonly" className="text-secondary text-ink-2">
          {READONLY_TEXT}
        </p>
      ) : null}

      <div role="radiogroup" aria-label={STRATEGY_HEADING} aria-describedby={choiceError ? "strategy-choice-error" : undefined} className={BOX}>
        {STRATEGY_OPTIONS.map((option) => {
          const off = locked(option.key);
          const on = selected === option.key;
          const reasonOff = canEdit && !selectable.has(option.key) ? NOT_SELECTABLE_TEXT : null;
          return (
            <button
              key={option.key}
              type="button"
              role="radio"
              aria-checked={on}
              aria-disabled={off ? true : undefined}
              data-key={option.key}
              data-testid="strategy-option"
              onClick={() => pick(option.key)}
              className={`flex w-full items-start gap-3 border-t border-line px-5 py-3 text-left first:border-t-0 focus-visible:outline-2 focus-visible:outline-fpt-blue ${
                off ? "cursor-not-allowed bg-group" : "bg-white hover:bg-group"
              }`}
            >
              <span className="flex min-w-0 grow flex-col gap-0.5">
                <span className="flex flex-wrap items-center gap-2">
                  <span className={on ? "font-semibold" : ""}>{option.title}</span>
                  {view.strategy === option.key ? <span className="text-label font-normal text-ink-2">· đang áp dụng</span> : null}
                  {showUncalibrated(option.key, view.llm_calibrated) ? (
                    <span data-testid="strategy-uncalibrated" className="rounded-full bg-orange-bg px-2 text-label text-orange-ink">
                      {UNCALIBRATED_TEXT}
                    </span>
                  ) : null}
                </span>
                <span className="text-label font-normal text-ink-2">{option.desc}</span>
                {reasonOff ? (
                  <span data-testid="strategy-not-selectable" className="text-label font-normal text-ink-2">
                    {reasonOff}
                  </span>
                ) : null}
              </span>
              <span className={`shrink-0 font-semibold text-fpt-blue ${on ? "visible" : "invisible"}`} aria-hidden="true">
                ✓
              </span>
            </button>
          );
        })}
      </div>
      {choiceError ? (
        <p id="strategy-choice-error" role="alert" data-testid="strategy-choice-error" className="text-secondary text-danger">
          {choiceError}
        </p>
      ) : null}

      {canEdit && changed ? (
        <div className="flex flex-col gap-2">
          <label htmlFor="strategy-reason-input" className="pl-1 text-label text-ink-2">
            {REASON_LABEL}
          </label>
          <textarea
            id="strategy-reason-input"
            rows={3}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
              setReasonError(null);
            }}
            aria-invalid={reasonError ? true : undefined}
            aria-describedby={reasonError ? "strategy-reason-error" : undefined}
            className="resize-none rounded-group border border-line px-5 py-3"
          />
          <span className="self-end text-label font-normal text-ink-2">
            {reasonLength(reason)}/{REASON_MAX}
          </span>
          {reasonError ? (
            <p id="strategy-reason-error" role="alert" data-testid="strategy-reason-error" className="text-secondary text-danger">
              {reasonError}
            </p>
          ) : null}
          <button
            type="button"
            onClick={apply}
            aria-disabled={applyBlocked ? true : undefined}
            data-testid="strategy-apply"
            className={`h-11 self-start rounded-full px-5 font-semibold ${applyBlocked ? "cursor-not-allowed bg-line text-ink-2" : "bg-fpt-blue text-white"}`}
          >
            {retry.sending ? "Đang áp dụng…" : "Áp dụng"}
          </button>
        </div>
      ) : null}

      {retry.dialog}
    </div>
  );
}

function Row({ label, testId, children }: { label: string; testId: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-4 border-t border-line px-5 py-3 first:border-t-0">
      <dt className="text-ink-2">{label}</dt>
      <dd data-testid={testId} className="min-w-0 break-words whitespace-pre-line">
        {children}
      </dd>
    </div>
  );
}

function StrategyHistoryBlock({ client }: { client: Client }) {
  const history = useQuery(strategyHistoryQuery(client));
  return (
    <section aria-labelledby="strategy-history-heading" className="flex flex-col gap-2">
      <h3 id="strategy-history-heading" className="pl-1 text-label text-ink-2">
        {HISTORY_HEADING}
      </h3>
      {history.isError ? (
        <p role="alert" data-testid="strategy-history-error" className="text-secondary text-danger">
          Chưa tải được lịch sử: {errorMessage(history.error instanceof ApiError ? history.error : null)}
        </p>
      ) : history.data === undefined ? (
        <p className="pl-1 text-secondary text-ink-2">Đang tải lịch sử…</p>
      ) : history.data.items.length === 0 ? (
        <p data-testid="strategy-history-empty" className="pl-1 text-secondary text-ink-2">
          {HISTORY_EMPTY_TEXT}
        </p>
      ) : (
        <>
          <HistoryTable items={history.data.items} />
          {history.data.truncated ? (
            <p data-testid="strategy-history-truncated" className="pl-1 text-secondary text-ink-2">
              {HISTORY_TRUNCATED_TEXT}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

/** Thứ tự server (mới nhất trước) — không sắp lại. */
function HistoryTable({ items }: { items: readonly StrategyChange[] }) {
  return (
    <div className={BOX}>
      <table className="w-full text-left text-secondary">
        <thead className="text-label text-ink-2">
          <tr>
            <th scope="col" className="px-5 py-2.5 font-normal">Lúc</th>
            <th scope="col" className="px-5 py-2.5 font-normal">Người đổi</th>
            <th scope="col" className="px-5 py-2.5 font-normal">Từ → sang</th>
            <th scope="col" className="px-5 py-2.5 font-normal">Lý do</th>
          </tr>
        </thead>
        <tbody>
          {items.map((c, i) => (
            <tr key={i} data-testid="strategy-history-row" className="border-t border-line align-top">
              <td className="px-5 py-2.5 whitespace-nowrap tabular-nums">{vnDateTime(c.changed_at)}</td>
              <td className="px-5 py-2.5 font-mono">{c.changed_by}</td>
              <td className="px-5 py-2.5">
                {strategyName(c.strategy_from)} → {strategyName(c.strategy_to)}
              </td>
              <td className="px-5 py-2.5 break-words whitespace-pre-line">{c.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
