// t7–t8: màn đăng nhập (B4Login, P6 §4) với client thật + backend giả (fetch truyền qua tham số).
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createClient } from "../api/client.ts";
import { GENERIC_LOGIN_ERROR, USERNAME_HINT } from "../api/errors.ts";
import { AuthProvider } from "./AuthProvider.tsx";
import { LoginPage } from "./LoginPage.tsx";

afterEach(cleanup);

const json = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function renderLogin(loginResponse: () => Response) {
  const fetch = vi.fn(async (url: string) => {
    if (url === "/api/auth/refresh") return json(401, { detail: "unauthorized" }); // chưa có phiên
    if (url === "/api/auth/login") return loginResponse();
    return json(404, { detail: "not_found" });
  });
  const client = createClient({ fetch, readCookie: () => null, locks: null, onSessionEnd: vi.fn() });
  render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider client={client} subscribe={() => () => {}}>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>,
  );
  return { loginCalls: () => fetch.mock.calls.filter(([url]) => url === "/api/auth/login").length };
}

async function submit(username: string, password: string) {
  fireEvent.change(await screen.findByLabelText("Tên đăng nhập"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("Mật khẩu"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
}

describe("LoginPage", () => {
  it("t7a: 401 mfa_required → chuyển sang bước OTP (6 ô)", async () => {
    const { loginCalls } = renderLogin(() => json(401, { detail: "mfa_required" }));
    await submit("quan.tm", "pw");
    expect(await screen.findByRole("heading", { name: "Nhập mã xác thực" })).toBeTruthy();
    expect(screen.getAllByLabelText(/^Chữ số \d$/)).toHaveLength(6);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(loginCalls()).toBe(1);
  });

  it.each(["unauthorized", "Tên đăng nhập hoặc mật khẩu không đúng", "account_disabled"])(
    't7b: 401 "%s" → MỘT thông báo chung, không sang bước OTP',
    async (detail) => {
      renderLogin(() => json(401, { detail }));
      await submit("an.nv", "pw");
      expect((await screen.findByRole("alert")).textContent).toBe(GENERIC_LOGIN_ERROR);
      expect(screen.queryByRole("heading", { name: "Nhập mã xác thực" })).toBeNull();
    },
  );

  it.each(["An.NV", "an nv", "Secret123", "an.nv@fpt"])('t8: username sai mẫu "%s" → không gửi request', async (username) => {
    const { loginCalls } = renderLogin(() => json(200, {}));
    await submit(username, "pw");
    expect((await screen.findByRole("alert")).textContent).toBe(USERNAME_HINT);
    expect(loginCalls()).toBe(0);
  });
});
