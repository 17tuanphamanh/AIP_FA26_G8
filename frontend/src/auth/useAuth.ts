import { useContext } from "react";
import type { Me } from "../api/types.ts";
import { AuthContext, type AuthValue } from "./context.ts";

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth phải nằm trong <AuthProvider>");
  return value;
}

/** Người đang đăng nhập (`/api/auth/me`). Chỉ gọi bên trong <RequireAuth>. */
export function useMe(): Me {
  const { state } = useAuth();
  if (state.status !== "signedIn") throw new Error("useMe chỉ dùng khi đã đăng nhập (bọc bằng <RequireAuth>)");
  return state.me;
}
