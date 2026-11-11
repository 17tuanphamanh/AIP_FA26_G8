import { createContext } from "react";
import type { LoginResult } from "../api/client.ts";
import type { Me } from "../api/types.ts";

/** `reason: "logout"` = người dùng tự bấm "Đăng xuất" (kiểm thử 12/11): <RequireAuth> KHÔNG nhớ trang đang mở — người
 *  đăng nhập kế tiếp (có thể là người khác, vai khác) về trang chủ của mình, không rơi vào trang 403/ticket của người trước.
 *  Hết phiên / chưa có phiên (không `reason`) vẫn nhớ trang để quay lại. */
export type AuthState =
  | { status: "checking" }
  | { status: "signedOut"; reason?: "logout" }
  | { status: "signedIn"; me: Me };

/** Như `LoginResult`; thành công kèm `me` vừa tải + `subject` (`sub` của token mới — hộp đăng nhập lại F4 so với
 *  `user_id` cũ trước khi gửi lại, Q-fe-25). */
export type SignInResult = Exclude<LoginResult, { ok: true }> | { ok: true; me: Me; subject: string | null };

export type AuthValue = {
  state: AuthState;
  signIn: (username: string, password: string, otp?: string) => Promise<SignInResult>;
  /** false = chưa đăng xuất được (mạng/5xx) — phiên vẫn sống, phải báo người dùng. */
  signOut: () => Promise<boolean>;
};

export const AuthContext = createContext<AuthValue | null>(null);
