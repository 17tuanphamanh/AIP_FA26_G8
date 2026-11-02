// t7–t8: màn đăng nhập (B4Login, P6 §4) với client thật + backend giả (fetch truyền qua tham số).
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createClient } from "../api/client.ts";
import { EMPTY_PASSWORD, EMPTY_USERNAME, GENERIC_LOGIN_ERROR, OTP_WRONG, USERNAME_HINT } from "../api/errors.ts";
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

  // ---- Soát 01/11 M1–M3 (ĐP 02/11)
  it.each(["", "   "])('M1: tên đăng nhập trống "%s" → "Nhập tên đăng nhập.", không gửi', async (username) => {
    const { loginCalls } = renderLogin(() => json(200, {}));
    await submit(username, "pw");
    expect((await screen.findByRole("alert")).textContent).toBe(EMPTY_USERNAME);
    expect(loginCalls()).toBe(0);
  });

  it("M1: cả hai ô trống → báo tên trước; L1: ô tên viền đỏ + câu gắn đúng ô, ô mật khẩu không", async () => {
    const { loginCalls } = renderLogin(() => json(200, {}));
    await submit("", "");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(EMPTY_USERNAME);
    expect(loginCalls()).toBe(0);
    const user = screen.getByLabelText("Tên đăng nhập");
    expect(user.getAttribute("aria-invalid")).toBe("true");
    expect(user.getAttribute("aria-describedby")).toBe(alert.id);
    expect(screen.getByLabelText("Mật khẩu").getAttribute("aria-invalid")).toBeNull();
    fireEvent.change(user, { target: { value: "an.nv" } });
    fireEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
    const pwAlert = await screen.findByText(EMPTY_PASSWORD);
    expect(screen.getByLabelText("Mật khẩu").getAttribute("aria-describedby")).toBe(pwAlert.id);
    expect(screen.getByLabelText("Tên đăng nhập").getAttribute("aria-invalid")).toBeNull();
  });

  it('M2: mật khẩu trống → "Nhập mật khẩu.", không gửi; mật khẩu chỉ khoảng trắng vẫn gửi (server quyết)', async () => {
    const { loginCalls } = renderLogin(() => json(401, { detail: "unauthorized" }));
    await submit("an.nv", "");
    expect((await screen.findByRole("alert")).textContent).toBe(EMPTY_PASSWORD);
    expect(loginCalls()).toBe(0);
    await submit("an.nv", " ");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(GENERIC_LOGIN_ERROR));
    expect(loginCalls()).toBe(1);
  });

  async function toOtpStep(after: () => Response) {
    let n = 0;
    const ctl = renderLogin(() => (n++ === 0 ? json(401, { detail: "mfa_required" }) : after()));
    await submit("quan.tm", "pw");
    await screen.findByRole("heading", { name: "Nhập mã xác thực" });
    const boxes = screen.getAllByLabelText(/^Chữ số \d$/) as HTMLInputElement[];
    for (const [i, d] of [..."123456"].entries()) fireEvent.change(boxes[i]!, { target: { value: d } });
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận" }));
    return { ...ctl, boxes };
  }

  it.each([
    ["401 invalid_login", () => json(401, { error: "invalid_login" })],
    ["401 unauthorized", () => json(401, { detail: "unauthorized" })],
    ["server lại đòi mã (mfa_required)", () => json(401, { detail: "mfa_required" })],
  ])("M3: sai mã OTP (%s) → câu riêng, xoá trắng 6 ô, con trỏ về ô đầu, vẫn ở bước OTP", async (_name, wrong) => {
    const { boxes, loginCalls } = await toOtpStep(wrong);
    expect((await screen.findByRole("alert")).textContent).toBe(OTP_WRONG);
    expect(boxes.map((b) => b.value).join("")).toBe("");
    await waitFor(() => expect(document.activeElement).toBe(boxes[0]));
    expect(screen.getByRole("heading", { name: "Nhập mã xác thực" })).toBeTruthy();
    expect(loginCalls()).toBe(2);
    expect(document.body.textContent).not.toContain(GENERIC_LOGIN_ERROR);
  });

  it("M3: lỗi khác ở bước OTP (429) → giữ câu cũ, không đổi thành câu sai mã", async () => {
    const { boxes } = await toOtpStep(() => json(429, { detail: "too_many_requests" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Bạn đã thử quá nhiều lần. Vui lòng đợi vài phút rồi thử lại.");
    expect(boxes.map((b) => b.value).join("")).toBe("123456");
  });
});
