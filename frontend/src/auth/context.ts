import { createContext } from "react";
import type { LoginResult } from "../api/client.ts";
import type { Me } from "../api/types.ts";

export type AuthState = { status: "checking" } | { status: "signedOut" } | { status: "signedIn"; me: Me };

export type AuthValue = {
  state: AuthState;
  signIn: (username: string, password: string, otp?: string) => Promise<LoginResult>;
  /** false = chưa đăng xuất được (mạng/5xx) — phiên vẫn sống, phải báo người dùng. */
  signOut: () => Promise<boolean>;
};

export const AuthContext = createContext<AuthValue | null>(null);
