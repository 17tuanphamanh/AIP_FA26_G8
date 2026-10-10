import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { Forbidden } from "../routes/Forbidden.tsx";
import { hasPerm } from "./permissions.ts";
import { useAuth, useMe } from "./useAuth.ts";

/** Chưa đăng nhập → /login (nhớ trang đang mở để quay lại sau khi đăng nhập). */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "checking") {
    return (
      <div role="status" className="flex h-full items-center justify-center text-ink-2">
        Đang kiểm tra phiên đăng nhập…
      </div>
    );
  }
  if (state.status === "signedOut") {
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }
  return children;
}

/** Thiếu quyền → trang 403. Chỉ để tiện dùng — backend vẫn kiểm quyền ở từng route (KH 4.1 #8). */
export function RequirePerm({ perm, children }: { perm: string; children: ReactNode }) {
  const me = useMe();
  return hasPerm(me, perm) ? children : <Forbidden />;
}
