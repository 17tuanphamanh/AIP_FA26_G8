import { useId, useRef, useState } from "react";
import { Link } from "react-router";
import { NOTE_MAX, TEXT_MAX } from "../api/tickets.ts";
import type { DigestItem, ParentReplyIn } from "../api/types.ts";
import logoUrl from "../assets/logo.svg";
import {
  checkDigest,
  digestLead,
  digestReplyBody,
  type DraftItem,
  EMPTY_DRAFT,
  itemLabel,
  replyErrorView,
} from "../routes/employee/multi.ts";
import type { Digest } from "./messages.ts";
import { SafeMarkdown } from "./SafeMarkdown.tsx";
import { Sources } from "./Sources.tsx";

// B4EmpDigest — tin tổng hợp của yêu cầu nhiều ý (D-31, P1 §8.2): MỘT tin mỗi lượt, mỗi ý một khối "Ý n – …", MỘT nút
// "Gửi phản hồi" cho mọi khối. Có `form` (tin round lớn nhất khi `waiting_for = "reply"`) → khối cần người dùng có nút
// "Đã ổn"/"Chưa ổn" (+ ghi chú khi "Chưa ổn") hoặc ô trả lời (+ nút gợi ý điền vào ô); không có → chỉ đọc. Nội dung
// từng khối qua SafeMarkdown (không HTML thô). Lỗi (thiếu trả lời, 422) hiện NGAY dưới đúng khối.

/** Kết quả gửi do màn chat trả về (màn lo notices, tải lại, 409); tin này chỉ lo lỗi theo khối. */
export type SendResult = { ok: true } | { ok: false; error: unknown };
export type DigestForm = { sending: boolean; onSend: (body: ParentReplyIn) => Promise<SendResult> };

type Props = {
  digest: Digest;
  /** `outcome` theo `child_id` từ dải tiến độ — ý bị chặn hiện nhãn trung tính. */
  outcomes?: Readonly<Record<string, string | null>>;
  form?: DigestForm;
  /** Khối "IT chưa duyệt" có link "Tạo yêu cầu mới" (chỉ màn của nhân viên — màn IT xem hội thoại thì không). */
  newRequestLink?: boolean;
};

const pill = (pressed: boolean) =>
  `h-9 rounded-full px-4 text-secondary font-semibold disabled:opacity-60 ${
    pressed ? "bg-fpt-blue text-white" : "bg-button-2 text-ink"
  }`;
const option = (pressed: boolean) =>
  `h-9 rounded-full border border-fpt-blue px-4 text-secondary font-semibold disabled:opacity-60 ${
    pressed ? "bg-fpt-blue text-white" : "bg-white text-fpt-blue"
  }`;
const field =
  "w-full resize-none rounded-group border border-line bg-white px-4 py-2.5 placeholder:text-ink-2 focus-visible:outline-2 focus-visible:outline-fpt-blue aria-[invalid=true]:border-danger";

export function DigestMessage({ digest, outcomes = {}, form, newRequestLink = false }: Props) {
  const active = form !== undefined;
  const [drafts, setDrafts] = useState<Record<string, DraftItem>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string | null>(null);
  const inFlight = useRef(false); // chặn bấm 2 lần trong cùng một nhịp (state `sending` chưa kịp cập nhật)

  function update(childId: string, patch: Partial<DraftItem>) {
    setDrafts((d) => ({ ...d, [childId]: { ...(d[childId] ?? EMPTY_DRAFT), ...patch } }));
    setErrors((e) => {
      if (!(childId in e)) return e;
      const rest = { ...e };
      delete rest[childId];
      return rest;
    });
  }

  async function submit() {
    if (!form || form.sending || inFlight.current) return;
    setGeneral(null);
    const problems = checkDigest(digest.items, drafts);
    setErrors(problems);
    if (Object.keys(problems).length > 0) return; // thiếu → báo tại khối, KHÔNG gửi
    inFlight.current = true;
    try {
      const result = await form.onSend(digestReplyBody(digest.items, drafts));
      if (!result.ok) {
        const view = replyErrorView(result.error, digest.items.map((i) => i.child_id));
        setErrors(view.byChild);
        setGeneral(view.general);
      }
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <div className="flex flex-col gap-3" data-testid="digest" data-round={digest.round} data-active={active}>
      <div className="flex items-start gap-2.5">
        <img src={logoUrl} alt="" width={24} height={24} className="mt-0.5 shrink-0" />
        <p>{digestLead(digest.items.length, active)}</p>
      </div>
      <div className="ml-8.5 rounded-sheet bg-group p-1.5">
        <div className="overflow-hidden rounded-group bg-white">
          {digest.items.map((item) => (
            <DigestBlock
              key={item.child_id}
              item={item}
              outcome={outcomes[item.child_id]}
              active={active}
              sending={form?.sending ?? false}
              draft={drafts[item.child_id] ?? EMPTY_DRAFT}
              error={errors[item.child_id] ?? null}
              onChange={(patch) => update(item.child_id, patch)}
              newRequestLink={newRequestLink}
            />
          ))}
        </div>
        {active || general ? (
          <div className="flex flex-col items-end gap-2 px-1.5 pt-2.5 pb-1">
            {active ? (
              <button
                type="button"
                onClick={() => void submit()}
                disabled={form.sending}
                className="h-11 rounded-full bg-fpt-blue px-6 font-semibold text-white disabled:opacity-60"
              >
                {form.sending ? "Đang gửi…" : "Gửi phản hồi"}
              </button>
            ) : null}
            {general ? (
              <p role="alert" data-testid="digest-error" className="text-label font-normal text-danger">
                {general}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

type BlockProps = {
  item: DigestItem;
  outcome: string | null | undefined;
  active: boolean;
  sending: boolean;
  draft: DraftItem;
  error: string | null;
  onChange: (patch: Partial<DraftItem>) => void;
  newRequestLink: boolean;
};

function DigestBlock({ item, outcome, active, sending, draft, error, onChange, newRequestLink }: BlockProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const described = error ? errorId : undefined;
  const asks = active && item.needs !== "none";
  const urgent = active && item.kind === "question";
  return (
    <section
      data-testid="digest-item"
      data-child={item.child_id}
      aria-labelledby={`${id}-title`}
      className="flex flex-col gap-2.5 border-t border-line px-5 py-4 first:border-t-0"
    >
      <div className="flex items-baseline gap-3">
        <h3 id={`${id}-title`} className="min-w-0 grow font-semibold">
          Ý {item.index} – {item.title}
        </h3>
        <span className={`shrink-0 text-secondary ${urgent ? "text-orange-ink" : "text-ink-2"}`}>{itemLabel(item, outcome)}</span>
      </div>
      {item.text.trim() ? <SafeMarkdown text={item.text} /> : null}
      {item.sources?.length ? <Sources sources={item.sources} /> : null}

      {asks && item.needs === "confirm" ? (
        <>
          <div role="group" aria-label={`Xác nhận ý ${item.index}`} aria-describedby={described} className="flex flex-wrap gap-2">
            <button type="button" aria-pressed={draft.choice === true} disabled={sending} onClick={() => onChange({ choice: true })} className={pill(draft.choice === true)}>
              Đã ổn
            </button>
            <button type="button" aria-pressed={draft.choice === false} disabled={sending} onClick={() => onChange({ choice: false })} className={pill(draft.choice === false)}>
              Chưa ổn
            </button>
          </div>
          {draft.choice === false ? (
            <>
              <label htmlFor={`${id}-note`} className="sr-only">
                Ghi chú cho ý {item.index} (không bắt buộc)
              </label>
              <textarea
                id={`${id}-note`}
                rows={2}
                value={draft.note}
                maxLength={NOTE_MAX}
                disabled={sending}
                onChange={(e) => onChange({ note: e.target.value })}
                placeholder="Ghi chú thêm nếu cần (không bắt buộc)…"
                className={field}
              />
            </>
          ) : null}
        </>
      ) : null}

      {asks && item.needs === "answer" ? (
        <>
          {item.options?.length ? (
            <div role="group" aria-label={`Gợi ý trả lời ý ${item.index}`} className="flex flex-wrap gap-2">
              {item.options.map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={draft.answer.trim() === value}
                  disabled={sending}
                  onClick={() => onChange({ answer: value })}
                  className={option(draft.answer.trim() === value)}
                >
                  {value}
                </button>
              ))}
            </div>
          ) : null}
          <label htmlFor={`${id}-answer`} className="sr-only">
            Trả lời ý {item.index}
          </label>
          <textarea
            id={`${id}-answer`}
            rows={1}
            value={draft.answer}
            maxLength={TEXT_MAX}
            disabled={sending}
            onChange={(e) => onChange({ answer: e.target.value })}
            placeholder={item.options?.length ? "Chọn ở trên hoặc nhập câu trả lời…" : "Nhập câu trả lời…"}
            aria-invalid={error ? true : undefined}
            aria-describedby={described}
            className={field}
          />
        </>
      ) : null}

      {newRequestLink && item.kind === "rejection" ? (
        <Link to="/chat" className="self-start text-secondary font-semibold text-fpt-blue">
          Tạo yêu cầu mới
        </Link>
      ) : null}

      {error ? (
        <p id={errorId} role="alert" data-testid="digest-item-error" className="text-label font-normal text-danger">
          {error}
        </p>
      ) : null}
    </section>
  );
}
