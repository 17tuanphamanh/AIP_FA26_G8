import { Navigate, useLocation } from "react-router";
import { EMPTY_PASSWORD, EMPTY_USERNAME, USERNAME_HINT } from "../api/errors.ts";
import fptLogoUrl from "../assets/fpt-university-logo.png";
import logoUrl from "../assets/logo.svg";
import { OtpInput } from "../components/OtpInput.tsx";
import { PasswordField } from "../components/PasswordField.tsx";
import { DEMO_TOOLS, MOCK_CONSOLE_URL } from "../lib/demoTools.ts";
import { LoginArt } from "./LoginArt.tsx";
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
  const { step, username, setUsername, password, setPassword, passwordShown, togglePassword, digits, setDigits, otpFocus, error, busy, submitPassword, submitOtp, backToPassword } =
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
  // L1 (soát 01/11): lỗi nhập của một ô → viền đỏ + câu ngay dưới ô đó; lỗi của server vẫn là một câu chung dưới form.
  const fieldError = otp ? null : error === EMPTY_USERNAME || error === USERNAME_HINT ? "username" : error === EMPTY_PASSWORD ? "password" : null;
  const fieldMessage = (field: "username" | "password") =>
    fieldError === field ? (
      <p id={`login-${field}-error`} role="alert" className="px-1 text-secondary text-danger">
        {error}
      </p>
    ) : null;
  const alert = error && fieldError === null ? (
    <p role="alert" className="rounded-xl bg-danger-bg px-4 py-3 text-secondary text-danger-ink">
      {error}
    </p>
  ) : null;

  return (
    <main className="grid min-h-full bg-white lg:grid-cols-2">
      {/* Cột trái (màn rộng): giới thiệu + tranh minh hoạ. Thuần trang trí, ẩn trên màn hẹp. */}
      <section
        aria-hidden="true"
        className="relative hidden flex-col justify-between overflow-hidden bg-linear-to-br from-fpt-blue via-fpt-blue to-ink p-12 text-white lg:flex"
      >
        <span className="pointer-events-none absolute -top-24 -right-24 size-80 rounded-full bg-white/5" />
        <span className="pointer-events-none absolute -bottom-32 -left-20 size-96 rounded-full bg-white/5" />
        <div className="relative flex items-center gap-3">
          <img src={logoUrl} alt="" width={40} height={40} className="rounded-xl ring-2 ring-white/20" />
          <span className="text-heading">ServiceDesk AI</span>
        </div>
        <LoginArt className="relative mx-auto w-full max-w-140 motion-safe:animate-rise-in motion-safe:[animation-delay:120ms]" />
        <div className="relative flex max-w-140 flex-col gap-3">
          <p className="text-title">Hỗ trợ IT cấp 1, nhanh và an toàn</p>
          <ul className="flex flex-col gap-2 text-secondary text-white/80">
            <li className="flex items-center gap-2">
              <span className="size-2 shrink-0 rounded-full bg-done" />
              Tự xử lý các yêu cầu thường gặp và an toàn
            </li>
            <li className="flex items-center gap-2">
              <span className="size-2 shrink-0 rounded-full bg-fpt-orange" />
              Việc nhạy cảm luôn có IT kiểm tra
            </li>
            <li className="flex items-center gap-2">
              <span className="size-2 shrink-0 rounded-full bg-white" />
              Chuyển kỹ thuật viên khi cần
            </li>
          </ul>
        </div>
      </section>

      {/* Cột phải: form. */}
      <div className="flex min-h-full flex-col bg-white px-6 sm:px-12">
        <div className="flex flex-1 items-center justify-center py-12">
          <div key={otp ? "otp" : "password"} className="flex w-100 max-w-full flex-col gap-8 motion-safe:animate-rise-in">
            <div className="flex flex-col gap-3">
              <img src={logoUrl} alt="" width={48} height={48} className="mb-2 lg:hidden" />
              <h1 className="text-title">{otp ? "Nhập mã xác thực" : "Đăng nhập"}</h1>
              <p className="text-ink-2">
                {otp ? "Mã 6 số trong ứng dụng xác thực trên điện thoại." : "Dùng tài khoản công ty (AD) của bạn."}
              </p>
            </div>

            {otp ? (
              <form onSubmit={(e) => void submitOtp(e)} noValidate className="flex flex-col items-stretch gap-4">
                <div className="flex">
                  <OtpInput digits={digits} onChange={setDigits} disabled={busy} focusKey={otpFocus} />
                </div>
                {alert}
                <button
                  type="submit"
                  disabled={busy}
                  className="h-12 w-full rounded-xl bg-fpt-blue font-semibold text-white shadow-input transition-colors hover:bg-fpt-blue/90 disabled:opacity-60"
                >
                  Xác nhận
                </button>
                <button type="button" onClick={backToPassword} className="h-11 px-4 text-fpt-blue">
                  Quay lại
                </button>
              </form>
            ) : (
              <form onSubmit={(e) => void submitPassword(e)} noValidate className="flex flex-col gap-5">
                <div className="flex flex-col gap-2">
                  <label htmlFor="login-username" className="text-label text-ink">
                    Tên đăng nhập
                  </label>
                  <div className={fieldError === "username" ? FIELD_BAD : FIELD}>
                    <UserIcon />
                    <input
                      id="login-username"
                      name="username"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="Tài khoản công ty"
                      autoComplete="username"
                      autoCapitalize="none"
                      spellCheck={false}
                      autoFocus
                      aria-invalid={fieldError === "username" || undefined}
                      aria-describedby={fieldError === "username" ? "login-username-error" : undefined}
                      className="h-12 min-w-0 flex-1 bg-white pr-4 outline-none placeholder:text-ink-3"
                    />
                  </div>
                  {fieldMessage("username")}
                </div>
                <div className="flex flex-col gap-2">
                  <label htmlFor="login-password" className="text-label text-ink">
                    Mật khẩu
                  </label>
                  <div className={fieldError === "password" ? FIELD_BAD : FIELD}>
                    <LockIcon />
                    <div className="min-w-0 flex-1">
                      <PasswordField
                        id="login-password"
                        name="password"
                        value={password}
                        onChange={setPassword}
                        shown={passwordShown}
                        onToggle={togglePassword}
                        inputClassName="h-12 bg-white outline-none placeholder:text-ink-3"
                        invalidId={fieldError === "password" ? "login-password-error" : undefined}
                      />
                    </div>
                  </div>
                  {fieldMessage("password")}
                </div>
                {alert}
                <button
                  type="submit"
                  disabled={busy}
                  className="mt-1 h-12 rounded-xl bg-fpt-blue font-semibold text-white shadow-input transition-colors hover:bg-fpt-blue/90 disabled:opacity-60"
                >
                  Đăng nhập
                </button>
                <p className="text-center text-secondary text-ink-2">Quên mật khẩu? Liên hệ bộ phận IT để được cấp lại.</p>
                {DEMO_TOOLS ? (
                  <p className="text-center text-label font-normal text-ink-2" data-testid="login-demo-tools">
                    Bản demo:{" "}
                    <a href={MOCK_CONSOLE_URL} target="_blank" rel="noopener noreferrer" className="font-semibold text-fpt-blue hover:underline">
                      mở hệ thống giả lập ↗
                    </a>{" "}
                    (điện thoại nhân viên, AD, VPN)
                  </p>
                ) : null}
              </form>
            )}
          </div>
        </div>

        {/* Logo FPT (gói fe-logo-fpt): ảnh chính thức nguyên byte, chỉ đặt chiều cao 40 px, rộng theo tỉ lệ (330×93). */}
        <footer className="flex flex-col items-center gap-2 border-t border-line py-6">
          <img src={fptLogoUrl} alt="Trường Đại học FPT" width={330} height={93} className="h-10 w-auto" />
          <span className="text-label font-normal text-ink-2">Đồ án tốt nghiệp · Trường Đại học FPT</span>
        </footer>
      </div>
    </main>
  );
}

// Khung ô nhập: viền mảnh, bo góc, viền xanh khi đang gõ (focus-within) — outline giữ cho bàn phím.
const FIELD_BASE = "flex items-center gap-3 overflow-hidden rounded-xl border bg-white pl-4 transition-colors focus-within:outline-2";
const FIELD = `${FIELD_BASE} border-line focus-within:border-fpt-blue focus-within:outline-fpt-blue/20`;
const FIELD_BAD = `${FIELD_BASE} border-danger focus-within:outline-danger/20`;

function UserIcon() {
  return (
    <svg viewBox="0 0 20 20" className="size-5 shrink-0 fill-none stroke-ink-3" strokeWidth="1.6" aria-hidden="true" focusable="false">
      <circle cx="10" cy="7" r="3.5" />
      <path d="M3.5 17c.8-3 3.4-5 6.5-5s5.7 2 6.5 5" strokeLinecap="round" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg viewBox="0 0 20 20" className="size-5 shrink-0 fill-none stroke-ink-3" strokeWidth="1.6" aria-hidden="true" focusable="false">
      <rect x="4" y="9" width="12" height="8" rx="2" />
      <path d="M7 9V6.5a3 3 0 0 1 6 0V9" strokeLinecap="round" />
    </svg>
  );
}
