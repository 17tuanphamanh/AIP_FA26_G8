import type { Me } from "../api/types.ts";
import { sameUser, useLoginSteps } from "../auth/useLoginSteps.ts";
import { Modal } from "./Modal.tsx";
import { OtpInput } from "./OtpInput.tsx";

export type ReauthOutcome = { kind: "ok" } | { kind: "cancel" } | { kind: "other_user"; me: Me };

type ReauthDialogProps = {
  /** `user_id` của phiên hiện tại. `sub` của token mới khác (hoặc không đọc được) → người khác → KHÔNG gửi lại thao tác. */
  userId: string;
  onDone: (outcome: ReauthOutcome) => void;
};

// Xác nhận lại đăng nhập (P6 §4, 12b Q-fe-4, Q-fe-25): backend trả 403 `reauth_required` cho thao tác cần đăng nhập ≤ 10
// phút (ghi đè — 4d P1). Đi ĐÚNG luồng đăng nhập của F1 (`useLoginSteps` — cùng hook với màn đăng nhập, gồm bước OTP khi
// 401 `mfa_required`; token mới chỉ trong bộ nhớ, phát sang tab khác qua BroadcastChannel). `me` không có tên đăng nhập
// (user_id ≠ username — nợ API #5) → hỏi cả tên đăng nhập. Mật khẩu / OTP chỉ nằm trong state của hộp này: đóng hộp (huỷ,
// thành công, người khác) → xoá trắng; không log, không vào URL (form không có action, luôn preventDefault).
export function ReauthDialog({ userId, onDone }: ReauthDialogProps) {
  // Thành công: hook đã xoá trắng mật khẩu / OTP trước khi gọi lại đây.
  const steps = useLoginSteps((result) =>
    onDone(sameUser(result, userId) ? { kind: "ok" } : { kind: "other_user", me: result.me }),
  );
  const { step, username, setUsername, password, setPassword, digits, setDigits, error, busy } = steps;

  function cancel() {
    steps.wipe();
    onDone({ kind: "cancel" });
  }

  return (
    <Modal label="Xác nhận lại đăng nhập" onClose={busy ? undefined : cancel}>
      <form onSubmit={(e) => void (step === "otp" ? steps.submitOtp(e) : steps.submitPassword(e))} noValidate className="flex flex-col gap-4">
        <h2 className="text-center text-heading">Xác nhận lại đăng nhập</h2>
        <p className="text-center text-secondary text-ink-2">
          {step === "otp"
            ? "Nhập mã 6 số trong ứng dụng xác thực."
            : "Thao tác này cần đăng nhập trong 10 phút gần nhất. Nhập lại tài khoản của bạn — sau đó hệ thống gửi lại đúng một lần."}
        </p>
        {step === "otp" ? (
          <div className="flex justify-center">
            <OtpInput digits={digits} onChange={setDigits} disabled={busy} />
          </div>
        ) : (
          <div className="overflow-hidden rounded-group border border-line">
            <label htmlFor="reauth-username" className="sr-only">
              Tên đăng nhập
            </label>
            <input
              id="reauth-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Tên đăng nhập"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              autoFocus
              className="h-13 w-full border-b border-line px-4 placeholder:text-ink-2"
            />
            <label htmlFor="reauth-password" className="sr-only">
              Mật khẩu
            </label>
            <input
              id="reauth-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Mật khẩu"
              autoComplete="current-password"
              className="h-13 w-full px-4 placeholder:text-ink-2"
            />
          </div>
        )}
        {error ? (
          <p role="alert" className="rounded-xl bg-danger-bg px-4 py-3 text-secondary text-danger-ink">
            {error}
          </p>
        ) : null}
        <div className="grid grid-cols-2 gap-3">
          <button type="button" onClick={cancel} disabled={busy} className="h-11 rounded-full bg-button-2 font-semibold disabled:opacity-60">
            Huỷ
          </button>
          <button type="submit" disabled={busy} className="h-11 rounded-full bg-fpt-blue font-semibold text-white disabled:opacity-60">
            {step === "otp" ? "Xác nhận" : "Đăng nhập lại"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
