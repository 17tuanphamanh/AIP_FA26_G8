import { useQueryClient } from "@tanstack/react-query";
import { useContext, useRef, useState, type FormEvent } from "react";
import { ApiError } from "../../api/errors.ts";
import { claimEscalation, raiseEscalation, RAISE_NOTE_MAX, type QueueItem, type QueueTier } from "../../api/escalations.ts";
import type { EscalationRaiseTarget } from "../../api/types.ts";
import { AuthContext } from "../../auth/context.ts";
import { CLAIM_DONE_TEXT, flowErrorText, holderText, RAISE_TARGETS } from "./queue.ts";

// D-99 (17/11, Tuấn Anh chốt phần 1–5): khối "Ai đang giữ ca" ở màn chi tiết ca MỞ.
// - "Nhận ca": ca chưa ai nhận → `POST /claim`. Ca người khác giữ → chỉ báo, không nút (backend cũng chặn 409 `already_claimed`).
// - "Chuyển lên cấp cao hơn" (chỉ cấp 2): chọn nơi chuyển + ghi chú lý do (nội bộ, đã che ở server) → `POST /raise`. Thành công →
//   `onRaised` (màn chi tiết giữ bản chụp + câu báo, vì ca rời hàng đợi cấp 2).
// Không hiện mã lỗi; câu lỗi theo `flowErrorText`.

type Claim = (id: number) => Promise<void>;
type Raise = (id: number, body: { target: EscalationRaiseTarget; note: string }) => Promise<void>;

export function HandlingActions({
  item,
  tier,
  onRaised,
  claim = claimEscalation,
  raise = raiseEscalation,
}: {
  item: QueueItem;
  tier: QueueTier;
  onRaised: () => void;
  claim?: Claim;
  raise?: Raise;
}) {
  // Đọc mềm: màn chi tiết luôn nằm trong <RequireAuth>; test cũ dựng màn không có AuthProvider → coi như chưa biết người dùng.
  const auth = useContext(AuthContext);
  const me = auth?.state.status === "signedIn" ? auth.state.me : null;
  const queryClient = useQueryClient();
  const reload = () => void queryClient.invalidateQueries({ queryKey: ["escalations", "queue"] });
  const [claimed, setClaimed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const holder = claimed ? (me?.user_id ?? null) : item.assigned_to;
  const mine = holder !== null && holder !== undefined && holder === me?.user_id;
  const other = holder !== null && holder !== undefined && !mine;

  async function run(action: () => Promise<void>, done: () => void) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
      reload();
      done();
    } catch (e) {
      const api = e instanceof ApiError ? e : null;
      setError(flowErrorText(api?.status ?? 0, api?.code ?? null));
      if (api?.status === 409) reload();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="holder-heading" data-testid="handling-actions" className="flex flex-col gap-2">
      <h2 id="holder-heading" className="pl-1 text-label text-ink-2">
        Người xử lý
      </h2>
      <div className="flex flex-col gap-3 rounded-group border border-line px-5 py-3">
        <p data-testid="holder-text">{mine ? "Bạn đang xử lý ca này" : holderText({ ...item, assigned_to: holder ?? null })}</p>
        {claimed ? (
          <p role="status" data-testid="claim-done" className="text-secondary text-ink-2">
            {CLAIM_DONE_TEXT}
          </p>
        ) : null}
        {holder ? null : (
          <button
            type="button"
            data-testid="claim-button"
            disabled={busy}
            onClick={() => void run(() => claim(item.escalation_id), () => setClaimed(true))}
            className="h-10 self-start rounded-full bg-fpt-blue px-5 font-semibold text-white disabled:opacity-60 max-lg:min-h-11"
          >
            {busy ? "Đang gửi…" : "Nhận ca"}
          </button>
        )}
        {other ? <p className="text-secondary text-ink-2">Chỉ người đang giữ ca được chuyển cấp hoặc đóng ca.</p> : null}
      </div>
      {error ? (
        <p role="alert" data-testid="handling-error" className="text-secondary text-danger">
          {error}
        </p>
      ) : null}
      {tier === 2 && !other ? (
        <RaiseForm busy={busy} onSubmit={(body) => run(() => raise(item.escalation_id, body), onRaised)} />
      ) : null}
    </section>
  );
}

function RaiseForm({ busy, onSubmit }: { busy: boolean; onSubmit: (body: { target: EscalationRaiseTarget; note: string }) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<EscalationRaiseTarget | null>(null);
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (target === null) return setProblem("Chọn nơi chuyển.");
    if (!note.trim()) return setProblem("Ghi lý do chuyển (bắt buộc).");
    setProblem(null);
    void onSubmit({ target, note: note.trim() });
  }

  if (!open) {
    return (
      <button
        type="button"
        data-testid="raise-open"
        onClick={() => setOpen(true)}
        className="h-9 self-start rounded-full bg-button-2 px-4 text-secondary font-semibold text-fpt-blue max-lg:min-h-11"
      >
        Chuyển lên cấp cao hơn…
      </button>
    );
  }
  return (
    <form onSubmit={submit} data-testid="raise-form" aria-labelledby="raise-heading" className="flex flex-col gap-2" noValidate>
      <h3 id="raise-heading" className="pl-1 text-label text-ink-2">
        Chuyển lên cấp cao hơn
      </h3>
      <div role="radiogroup" aria-label="Nơi chuyển" className="overflow-hidden rounded-group border border-line">
        {RAISE_TARGETS.map((t) => {
          const on = target === t.key;
          return (
            <button
              key={t.key}
              type="button"
              role="radio"
              aria-checked={on}
              data-value={t.key}
              onClick={() => setTarget(t.key)}
              className={`flex w-full flex-col border-t border-line px-5 py-3 text-left first:border-t-0 ${on ? "bg-selected" : "bg-white hover:bg-group"}`}
            >
              <span>{t.label}</span>
              <span className="text-label font-normal text-ink-2">{t.hint}</span>
            </button>
          );
        })}
      </div>
      <label htmlFor="raise-note" className="sr-only">
        Lý do chuyển
      </label>
      <textarea
        id="raise-note"
        data-testid="raise-note"
        rows={3}
        maxLength={RAISE_NOTE_MAX}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Lý do chuyển (nội bộ, bắt buộc) — người gửi chỉ thấy câu báo chung"
        className="resize-none rounded-group border border-line px-5 py-3"
      />
      {problem ? (
        <p role="alert" data-testid="raise-problem" className="text-secondary text-danger">
          {problem}
        </p>
      ) : null}
      <button type="submit" disabled={busy} className="h-10 rounded-full bg-fpt-blue font-semibold text-white disabled:opacity-60 max-lg:min-h-11">
        {busy ? "Đang gửi…" : "Chuyển"}
      </button>
    </form>
  );
}
