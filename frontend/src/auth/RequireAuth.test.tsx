// Kiểm thử 12/11 trên máy demo: L2 bấm "Đăng xuất" ở /escalations → an.nv đăng nhập → bị đưa về /escalations (403);
// L1 đăng nhập sau an.nv → bị đưa vào /chat/<ticket của an.nv>. Tự đăng xuất thì KHÔNG nhớ trang của người trước.
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Client } from "../api/client.ts";
import type { Me } from "../api/types.ts";
import { AuthProvider } from "./AuthProvider.tsx";
import { type AuthState, AuthContext } from "./context.ts";
import { useAuth } from "./useAuth.ts";
import { RequireAuth } from "./RequireAuth.tsx";

afterEach(cleanup);

function LoginProbe() {
  const location = useLocation();
  return <output data-testid="login-state">{JSON.stringify(location.state ?? null)}</output>;
}

function renderAt(path: string, state: AuthState) {
  render(
    <AuthContext.Provider value={{ state, signIn: vi.fn(), signOut: vi.fn(async () => true) }}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginProbe />} />
          <Route
            path="*"
            element={
              <RequireAuth>
                <p>trang được bảo vệ</p>
              </RequireAuth>
            }
          />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
  return JSON.parse(screen.getByTestId("login-state").textContent ?? "null") as { from?: string } | null;
}

describe("RequireAuth — nhớ trang để quay lại", () => {
  it("chưa có phiên / hết phiên (không reason) → /login NHỚ trang đang mở (deep link, đăng nhập lại)", () => {
    expect(renderAt("/chat/abc?x=1", { status: "signedOut" })).toStrictEqual({ from: "/chat/abc?x=1" });
  });

  it("tự bấm Đăng xuất (reason logout) → /login KHÔNG mang trang của người trước", () => {
    expect(renderAt("/escalations", { status: "signedOut", reason: "logout" })).toBeNull();
  });
});

describe("AuthProvider.signOut → reason logout", () => {
  it("đăng xuất thành công → state signedOut kèm reason 'logout' (để RequireAuth không nhớ trang)", async () => {
    const me = { user_id: "l2_01", username: "long.nh", role: "l2", permissions: [] } as unknown as Me;
    const client = {
      restore: vi.fn(async () => true),
      request: vi.fn(async () => ({ data: me })),
      logout: vi.fn(async () => true),
      login: vi.fn(),
    } as unknown as Client;
    function Grab() {
      const { state, signOut } = useAuth();
      return (
        <>
          <output data-testid="st">{JSON.stringify(state.status === "signedIn" ? "in" : state)}</output>
          <button type="button" onClick={() => void signOut()}>
            Đăng xuất
          </button>
        </>
      );
    }
    render(
      <AuthProvider client={client} subscribe={() => () => {}}>
        <Grab />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("st").textContent).toBe(JSON.stringify("in")));
    await act(async () => {
      screen.getByRole("button", { name: "Đăng xuất" }).click();
    });
    await waitFor(() => expect(screen.getByTestId("st").textContent).not.toBe(JSON.stringify("in")));
    expect(JSON.parse(screen.getByTestId("st").textContent ?? "null")).toStrictEqual({ status: "signedOut", reason: "logout" });
  });
});
