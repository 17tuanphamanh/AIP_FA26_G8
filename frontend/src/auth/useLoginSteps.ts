import { type FormEvent, useState } from "react";
import { flushSync } from "react-dom";
import { GENERIC_LOGIN_ERROR, loginErrorMessage, USERNAME_HINT } from "../api/errors.ts";
import { OTP_LENGTH } from "../components/OtpInput.tsx";
import type { SignInResult } from "./context.ts";
import { useAuth } from "./useAuth.ts";

const EMPTY_OTP = Array<string>(OTP_LENGTH).fill("");

export type SignedIn = Extract<SignInResult, { ok: true }>;

/** Đăng nhập lại (Q-fe-25): cùng người = `sub` của token VỪA cấp trùng `user_id` cũ. Không đọc được `sub` → coi là khác. */
export const sameUser = (result: SignedIn, userId: string): boolean => result.subject !== null && result.subject === userId;

/**
 * Luồng đăng nhập DUY NHẤT của giao diện (B4Login, P6 §4): bước mật khẩu → (401 `mfa_required`) bước OTP 6 số → `signIn`
 * của AuthProvider → `client.login` (token chỉ trong bộ nhớ, phát sang tab khác qua BroadcastChannel — Q-fe-13). Mọi lỗi
 * 401 khác là MỘT câu chung. Dùng cho màn đăng nhập (F1) và hộp xác nhận lại đăng nhập (F4, Q-fe-25).
 * Mật khẩu / OTP chỉ nằm trong state của component đang dùng hook; đăng nhập thành công → tự xoá trắng; `wipe()` cho
 * các đường đóng khác (huỷ hộp thoại).
 */
export function useLoginSteps(onSignedIn?: (result: SignedIn) => void) {
  const { signIn } = useAuth();
  const [step, setStep] = useState<"password" | "otp">("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [digits, setDigits] = useState<string[]>(EMPTY_OTP);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Nút hiện/ẩn mật khẩu (fe-login-sua). Mặc định ẩn; về lại ẩn khi gửi form, có kết quả (lỗi / OTP / xong), quay lại,
  // xoá trắng (đóng hộp) — an toàn khi quay màn hình / trình chiếu demo.
  const [passwordShown, setPasswordShown] = useState(false);

  function show(result: SignInResult, fromOtp: boolean) {
    setPasswordShown(false);
    if (result.ok) {
      wipe(); // đã dùng xong: mật khẩu / OTP không nằm lại trong state
      onSignedIn?.(result);
      return;
    }
    if (result.kind === "otp_required") {
      if (fromOtp) {
        setError(GENERIC_LOGIN_ERROR);
      } else {
        setStep("otp");
        setDigits(EMPTY_OTP);
        setError(null);
      }
      return;
    }
    if (result.kind === "invalid_username") setError(USERNAME_HINT);
    else if (result.kind === "profile_error") setError("Đăng nhập được nhưng chưa tải được thông tin tài khoản. Thử lại sau giây lát.");
    else setError(loginErrorMessage(result.error));
  }

  async function attempt(otp: string | undefined) {
    setBusy(true);
    try {
      show(await signIn(username, password, otp), otp !== undefined);
    } catch {
      setPasswordShown(false);
      setError(loginErrorMessage(null));
    } finally {
      setBusy(false);
    }
  }

  async function submitPassword(event: FormEvent) {
    event.preventDefault();
    // Ẩn NGAY trên DOM trước khi gọi đăng nhập (flushSync) — không đợi nhịp render sau phản hồi.
    flushSync(() => setPasswordShown(false));
    setError(null);
    await attempt(undefined);
  }

  async function submitOtp(event: FormEvent) {
    event.preventDefault();
    const otp = digits.join("");
    if (otp.length !== OTP_LENGTH) {
      setError(`Nhập đủ ${OTP_LENGTH} chữ số.`);
      return;
    }
    setError(null);
    await attempt(otp);
  }

  function backToPassword() {
    setStep("password");
    setPasswordShown(false);
    setPassword("");
    setDigits(EMPTY_OTP);
    setError(null);
  }

  /** Xoá trắng mật khẩu + OTP. */
  function wipe() {
    setPasswordShown(false);
    setPassword("");
    setDigits(EMPTY_OTP);
  }

  return {
    step,
    username,
    setUsername,
    password,
    setPassword,
    passwordShown,
    togglePassword: () => setPasswordShown((v) => !v),
    digits,
    setDigits,
    error,
    busy,
    submitPassword,
    submitOtp,
    backToPassword,
    wipe,
  };
}
