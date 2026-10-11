import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import type { Client } from "../api/client.ts";
import { api, subscribeSessionEnd } from "../api/http.ts";
import type { Me } from "../api/types.ts";
import { AuthContext, type AuthState, type AuthValue, type SignInResult } from "./context.ts";

type AuthProviderProps = {
  children: ReactNode;
  /** Mặc định client dùng chung; test truyền client giả. */
  client?: Client;
  subscribe?: (listener: () => void) => () => void;
  /** Dọn dữ liệu đã tải của người cũ (vd cache TanStack Query) khi đăng xuất / hết phiên. */
  onSignedOut?: () => void;
};

// Phiên đăng nhập của cả ứng dụng: tải trang → `restore()` (refresh bằng cookie) → `/api/auth/me`.
// Hết phiên (client báo) → signedOut; <RequireAuth> đưa về /login.
export function AuthProvider({ children, client = api, subscribe = subscribeSessionEnd, onSignedOut }: AuthProviderProps) {
  const [state, setState] = useState<AuthState>({ status: "checking" });

  const fetchMe = useCallback(async () => (await client.request<Me>("/api/auth/me")).data, [client]);

  useEffect(() => {
    let alive = true;
    // StrictMode chạy effect 2 lần: `restore()` là single-flight nên vẫn chỉ MỘT lời gọi refresh.
    void (async () => {
      // Chỉ đổi khi vẫn đang "checking" — không ghi đè kết quả của một lần đăng nhập xảy ra trong lúc chờ.
      const settle = (next: AuthState) => setState((prev) => (prev.status === "checking" ? next : prev));
      const restored = await client.restore();
      if (!alive) return;
      if (!restored) {
        settle({ status: "signedOut" });
        return;
      }
      try {
        const me = await fetchMe();
        if (alive) settle({ status: "signedIn", me });
      } catch {
        if (alive) settle({ status: "signedOut" });
      }
    })();
    return () => {
      alive = false;
    };
  }, [client, fetchMe]);

  useEffect(
    () =>
      subscribe(() => {
        setState({ status: "signedOut" });
        onSignedOut?.();
      }),
    [subscribe, onSignedOut],
  );

  const signIn = useCallback(
    async (username: string, password: string, otp?: string): Promise<SignInResult> => {
      const result = await client.login(username, password, otp);
      if (!result.ok) return result;
      try {
        const me = await fetchMe();
        setState({ status: "signedIn", me });
        return { ok: true, me, subject: result.subject };
      } catch {
        return { ok: false, kind: "profile_error" }; // mật khẩu ĐÚNG — không được báo "sai mật khẩu"
      }
    },
    [client, fetchMe],
  );

  const signOut = useCallback(async () => {
    const done = await client.logout();
    if (done) {
      setState({ status: "signedOut" });
      onSignedOut?.();
    }
    return done;
  }, [client, onSignedOut]);

  const value = useMemo<AuthValue>(() => ({ state, signIn, signOut }), [state, signIn, signOut]);
  return <AuthContext value={value}>{children}</AuthContext>;
}
