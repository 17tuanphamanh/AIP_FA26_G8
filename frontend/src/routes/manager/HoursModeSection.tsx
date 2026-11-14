import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { Client } from "../../api/client.ts";
import { ApiError, errorMessage } from "../../api/errors.ts";
import { HOURS_MODE_HINT, HOURS_MODE_LABEL, HOURS_MODES, type HoursMode, type HoursModeView, hoursModeQuery, putHoursMode } from "../../api/hoursMode.ts";
import { api } from "../../api/http.ts";
import { hasPerm } from "../../auth/permissions.ts";
import { useMe } from "../../auth/useAuth.ts";
import { useReauthRetry } from "../../components/useReauthRetry.tsx";
import { vnDateTime } from "./range.ts";

// Khối "Giả lập giờ hành chính" (D-97, TA chốt 14/11) trên trang Chính sách: Trưởng BP chọn theo giờ thật / giả lập ngoài giờ / giả
// lập trong giờ để demo luật VPN ngoài giờ (R18) với LLM thật mà không phải chờ tới tối. Đổi cần `policy:edit` + đăng nhập gần đây
// (403 `reauth_required` → useReauthRetry). Mỗi lần đổi ghi nhật ký an ninh và hiện ở màn Cảnh báo.

const BOX = "overflow-hidden rounded-group border border-line";
const NONE = "—";

type Message = { tone: "ok" | "error"; text: string };

export function HoursModeSection({ client = api }: { client?: Client }) {
  const current = useQuery(hoursModeQuery(client));
  const [message, setMessage] = useState<Message | null>(null);
  // Backend cũ chưa có route (mọi 404) → không hiện khối — route thật không bao giờ trả 404.
  if (current.error instanceof ApiError && current.error.status === 404) return null;
  return (
    <section aria-labelledby="hours-mode-heading" data-testid="hours-mode-section" className="flex flex-col gap-3 border-t border-line pt-6">
      <h2 id="hours-mode-heading" className="text-heading">
        Giả lập giờ hành chính (demo)
      </h2>
      <p className="text-secondary text-ink-2">
        Chỉ đổi cách luật hiểu "trong / ngoài giờ hành chính". Đồng hồ hệ thống, mã OTP và hạn duyệt vẫn theo giờ thật. Khi đang giả
        lập, mọi màn hiện dải báo.
      </p>
      {current.isError ? (
        <p role="alert" data-testid="hours-mode-error" className="text-danger">
          Chưa tải được chế độ: {errorMessage(current.error instanceof ApiError ? current.error : null)}
        </p>
      ) : current.data === undefined ? (
        <p className="text-secondary text-ink-2 motion-safe:animate-pulse">Đang tải…</p>
      ) : (
        <HoursModeForm key={`${current.data.mode}|${current.data.changed_at ?? ""}`} view={current.data} client={client} setMessage={setMessage} />
      )}
      {message ? (
        <p role={message.tone === "error" ? "alert" : "status"} data-testid="hours-mode-message" className={message.tone === "error" ? "text-danger" : ""}>
          {message.text}
        </p>
      ) : null}
    </section>
  );
}

function HoursModeForm({ view, client, setMessage }: { view: HoursModeView; client: Client; setMessage: (m: Message | null) => void }) {
  const me = useMe();
  const canEdit = hasPerm(me, "policy:edit");
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<HoursMode>(view.mode);
  const changed = selected !== view.mode;

  const retry = useReauthRetry<HoursMode, HoursModeView>({
    send: (mode) => putHoursMode(mode, client),
    onSuccess: (next) => {
      queryClient.setQueryData(hoursModeQuery(client).queryKey, next);
      setMessage({ tone: "ok", text: `Đã chuyển sang: ${HOURS_MODE_LABEL[next.mode]}. Áp dụng cho các yêu cầu được xét từ bây giờ.` });
    },
    onFailure: (e) => {
      const err = e instanceof ApiError ? e : null;
      if (err?.status === 409 && err.code === "same_as_current") {
        setMessage({ tone: "error", text: "Chế độ này đang được áp dụng rồi." });
      } else {
        setMessage({ tone: "error", text: errorMessage(err) });
      }
      void queryClient.invalidateQueries({ queryKey: hoursModeQuery(client).queryKey });
    },
    onCancelled: () => setMessage({ tone: "error", text: "Chưa áp dụng — đăng nhập lại chưa xong." }),
    otherUserFlash: "policy_other_user",
  });

  const blocked = !canEdit || !changed || retry.sending;
  function apply() {
    if (blocked || retry.busy()) return;
    setMessage(null);
    retry.run(selected);
  }

  return (
    <div className="flex flex-col gap-3">
      <dl className={`${BOX} text-secondary`}>
        <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-4 px-5 py-3 max-lg:grid-cols-1 max-lg:gap-1">
          <dt className="text-ink-2">Đang áp dụng</dt>
          <dd data-testid="hours-mode-current">{HOURS_MODE_LABEL[view.mode]}</dd>
        </div>
        <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-4 border-t border-line px-5 py-3 max-lg:grid-cols-1 max-lg:gap-1">
          <dt className="text-ink-2">Người đổi</dt>
          <dd data-testid="hours-mode-changed-by">{view.changed_by ?? NONE}</dd>
        </div>
        <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-4 border-t border-line px-5 py-3 max-lg:grid-cols-1 max-lg:gap-1">
          <dt className="text-ink-2">Lúc đổi</dt>
          <dd data-testid="hours-mode-changed-at">{view.changed_at ? vnDateTime(view.changed_at) : NONE}</dd>
        </div>
      </dl>
      {view.eval_mode ? (
        <p role="note" className="rounded-group bg-group px-5 py-3.5">
          Đang chạy đánh giá: hệ thống luôn dùng giờ thật, chế độ giả lập không có tác dụng.
        </p>
      ) : null}
      <div role="radiogroup" aria-label="Giả lập giờ hành chính" className={BOX}>
        {HOURS_MODES.map((mode) => {
          const on = selected === mode;
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={on}
              aria-disabled={canEdit ? undefined : true}
              data-key={mode}
              data-testid="hours-mode-option"
              onClick={() => {
                if (!canEdit) return;
                setSelected(mode);
                setMessage(null);
              }}
              className={`flex w-full flex-col items-start gap-0.5 border-t border-line px-5 py-3 text-left first:border-t-0 focus-visible:outline-2 focus-visible:outline-fpt-blue ${
                canEdit ? "bg-white hover:bg-group" : "cursor-not-allowed bg-group"
              } ${on ? "font-semibold" : ""}`}
            >
              <span>
                {on ? "● " : "○ "}
                {HOURS_MODE_LABEL[mode]}
              </span>
              <span className="text-secondary font-normal text-ink-2">{HOURS_MODE_HINT[mode]}</span>
            </button>
          );
        })}
      </div>
      {canEdit ? (
        <button
          type="button"
          onClick={apply}
          aria-disabled={blocked ? true : undefined}
          data-testid="hours-mode-apply"
          className={`h-11 self-start rounded-full px-5 font-semibold ${blocked ? "cursor-not-allowed bg-line text-ink-2" : "bg-fpt-blue text-white"}`}
        >
          {retry.sending ? "Đang áp dụng…" : "Áp dụng"}
        </button>
      ) : (
        <p className="text-secondary text-ink-2">Chỉ Trưởng bộ phận IT được đổi chế độ này.</p>
      )}
      {retry.dialog}
    </div>
  );
}
