import { createContext } from "react";
import type { LoginResult } from "../api/client.ts";
import type { Me } from "../api/types.ts";

export type AuthState = { status: "checking" } | { status: "signedOut" } | { status: "signedIn"; me: Me };

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
