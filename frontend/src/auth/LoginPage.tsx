import { Navigate, useLocation } from "react-router";
import logoUrl from "../assets/logo.svg";
import { OtpInput } from "../components/OtpInput.tsx";
import { PasswordField } from "../components/PasswordField.tsx";
import { homePath } from "./permissions.ts";
import { useAuth } from "./useAuth.ts";
import { useLoginSteps } from "./useLoginSteps.ts";

/** Trang cũ người dùng đang mở trước khi bị đưa về /login — chỉ nhận đường dẫn nội bộ. */
function returnPath(state: unknown): string | null {
  const from = (state as { from?: unknown } | null)?.from;
  return typeof from === "string" && from.startsWith("/") && !from.startsWith("//") && !from.includes("\\") && from !== "/login"
    ? from
    : null;
}

// B4Login: bước mật khẩu → (401 `mfa_required`) bước OTP 6 số (luồng ở useLoginSteps — dùng chung với hộp xác nhận lại
// đăng nhập F4). Mọi lỗi 401 khác là MỘT câu chung (P6 §4). Tên đăng nhập sai mẫu bị chặn trong `client.login` — không
// gửi request (mật khẩu gõ nhầm vào ô này không rời máy). Thành công → AuthProvider chuyển sang signedIn → <Navigate>.
export function LoginPage() {
  const { state } = useAuth();
  const location = useLocation();
  const { step, username, setUsername, password, setPassword, passwordShown, togglePassword, digits, setDigits, error, busy, submitPassword, submitOtp, backToPassword } =
    useLoginSteps();

  if (state.status === "signedIn") {
    return <Navigate to={returnPath(location.state) ?? homePath(state.me)} replace />;
  }
  // Chưa biết còn phiên hay không → chưa hiện form: trình quản lý mật khẩu tự điền + tự gửi lúc này sẽ đua với
  // `restore()` đang chạy.
  if (state.status === "checking") {
    return (
      <main role="status" className="flex min-h-full items-center justify-center bg-group text-ink-2">
        Đang kiểm tra phiên đăng nhập…
      </main>
    );
  }

  const otp = step === "otp";
  const alert = error ? (
    <p role="alert" className="rounded-xl bg-danger-bg px-4 py-3 text-secondary text-danger-ink">
      {error}
    </p>
  ) : null;

  return (
    <main className="relative flex min-h-full flex-col items-center justify-center gap-8 bg-group px-4 pt-16 pb-28">
      <div className="flex flex-col items-center gap-4 text-center">
        <img src={logoUrl} alt="" width={64} height={64} />
        <h1 className="text-title">{otp ? "Nhập mã xác thực" : "Đăng nhập"}</h1>
        <p className="text-ink-2">
          {otp ? "Mã 6 số trong ứng dụng xác thực trên điện thoại." : "Dùng tài khoản công ty (AD) của bạn."}
        </p>
      </div>

      {otp ? (
        <form onSubmit={(e) => void submitOtp(e)} noValidate className="flex w-100 max-w-full flex-col items-center gap-4">
          <OtpInput digits={digits} onChange={setDigits} disabled={busy} />
          {alert}
          <button type="submit" disabled={busy} className="h-11 w-full rounded-full bg-fpt-blue font-semibold text-white disabled:opacity-60">
            Xác nhận
          </button>
          <button type="button" onClick={backToPassword} className="h-11 px-4 text-fpt-blue">
            Quay lại
          </button>
        </form>
      ) : (
        <form onSubmit={(e) => void submitPassword(e)} noValidate className="flex w-100 max-w-full flex-col gap-4">
          <div className="overflow-hidden rounded-group border border-line bg-white">
            <label htmlFor="login-username" className="sr-only">
              Tên đăng nhập
            </label>
            <input
              id="login-username"
              name="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Tên đăng nhập"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              autoFocus
              className="h-13 w-full border-b border-line bg-white px-4 placeholder:text-ink-2 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fpt-blue"
            />
            <label htmlFor="login-password" className="sr-only">
              Mật khẩu
            </label>
            <PasswordField
              id="login-password"
              name="password"
              value={password}
              onChange={setPassword}
              shown={passwordShown}
              onToggle={togglePassword}
              inputClassName="h-13 bg-white px-4 placeholder:text-ink-2 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fpt-blue"
            />
          </div>
          {alert}
          <button type="submit" disabled={busy} className="h-11 rounded-full bg-fpt-blue font-semibold text-white disabled:opacity-60">
            Đăng nhập
          </button>
        </form>
      )}

      <footer className="absolute bottom-8 flex items-center gap-4">
        <span className="flex h-9 w-28 items-center justify-center rounded-lg border border-dashed border-line text-label font-normal text-ink-2">
          Logo đơn vị
        </span>
        <span className="text-label font-normal text-ink-2">Đồ án tốt nghiệp — Trường Đại học FPT</span>
      </footer>
    </main>
  );
}
