// t220–t226: nút hiện/ẩn mật khẩu (gói fe-login-sua) ở màn đăng nhập (F1) và hộp xác nhận lại đăng nhập (F4).
// Client thật + backend giả (fetch truyền qua tham số). Mutation MLS1 (bỏ tự ẩn khi gửi), MLS2 (nút type submit),
// MLS3 (bỏ aria-pressed) phải làm đỏ ít nhất một test ở đây.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createClient } from "../api/client.ts";
import { GENERIC_LOGIN_ERROR } from "../api/errors.ts";
import { ReauthDialog } from "../components/ReauthDialog.tsx";
import { AuthProvider } from "./AuthProvider.tsx";
import { LoginPage } from "./LoginPage.tsx";

afterEach(cleanup);

const json = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
const jwt = (sub: string) => `${b64({ alg: "HS256" })}.${b64({ sub })}.sig`;
const ME = { user_id: "an.nv", role: "employee", permissions: [] };

type Where = "login" | "reauth";
const INPUT_ID: Record<Where, string> = { login: "login-password", reauth: "reauth-password" };
const SUBMIT: Record<Where, string> = { login: "Đăng nhập", reauth: "Đăng nhập lại" };

function setup(where: Where, loginResponse: () => Response | Promise<Response>) {
  const typeAtLogin: string[] = [];
  const fetch = vi.fn(async (url: string) => {
    if (url === "/api/auth/refresh") return json(401, { detail: "unauthorized" });
    if (url === "/api/auth/login") {
      typeAtLogin.push((document.getElementById(INPUT_ID[where]) as HTMLInputElement | null)?.type ?? "(không có ô)");
      return loginResponse();
    }
    if (url === "/api/auth/me") return json(200, ME);
    return json(404, { detail: "not_found" });
  });
  const client = createClient({ fetch, readCookie: () => null, locks: null, onSessionEnd: vi.fn() });
  const onDone = vi.fn();
  render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider client={client} subscribe={() => () => {}}>
        {where === "login" ? <LoginPage /> : <ReauthDialog userId="an.nv" onDone={onDone} />}
      </AuthProvider>
    </MemoryRouter>,
  );
  return { fetch, typeAtLogin, onDone, loginCalls: () => fetch.mock.calls.filter(([u]) => u === "/api/auth/login").length };
}

const field = async (where: Where) => {
  await screen.findByLabelText("Tên đăng nhập");
  return document.getElementById(INPUT_ID[where]) as HTMLInputElement;
};
const toggle = () => screen.getByRole("button", { name: /^(Hiện|Ẩn) mật khẩu$/ });

async function fillAndShow(where: Where, password = "Mk@2026!") {
  const input = await field(where);
  fireEvent.change(screen.getByLabelText("Tên đăng nhập"), { target: { value: "an.nv" } });
  fireEvent.change(input, { target: { value: password } });
  fireEvent.click(toggle());
  expect(input.type).toBe("text");
  return input;
}

describe.each<Where>(["login", "reauth"])("nút hiện/ẩn mật khẩu — %s", (where) => {
  it("t220: mặc định ẩn; bấm đổi password ↔ text; aria-label + aria-pressed đổi theo; giá trị giữ nguyên", async () => {
    setup(where, () => json(500));
    const input = await field(where);
    expect(input.type).toBe("password");
    expect(input.autocomplete).toBe("current-password");
    const btn = screen.getByRole("button", { name: "Hiện mật khẩu" });
    expect(btn.getAttribute("aria-pressed")).toBe("false");
    expect(btn.getAttribute("aria-controls")).toBe(INPUT_ID[where]);
    fireEvent.change(input, { target: { value: "abc 123" } });

    fireEvent.click(btn);
    expect(input.type).toBe("text");
    expect(input.value).toBe("abc 123");
    expect(input.autocomplete).toBe("current-password");
    const hide = screen.getByRole("button", { name: "Ẩn mật khẩu" });
    expect(hide.getAttribute("aria-pressed")).toBe("true");
    expect(document.getElementById(INPUT_ID[where])).toBe(input); // cùng phần tử, không dựng lại

    fireEvent.click(hide);
    expect(input.type).toBe("password");
    expect(input.value).toBe("abc 123");
    expect(screen.getByRole("button", { name: "Hiện mật khẩu" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("t221: nút là type=button, có tiêu điểm bàn phím, bấm KHÔNG gửi form", async () => {
    const { loginCalls } = setup(where, () => json(500));
    const input = await field(where);
    fireEvent.change(screen.getByLabelText("Tên đăng nhập"), { target: { value: "an.nv" } });
    fireEvent.change(input, { target: { value: "pw" } });
    const btn = toggle();
    expect(btn.getAttribute("type")).toBe("button");
    expect(btn.tabIndex).toBe(0);
    btn.focus();
    expect(document.activeElement).toBe(btn);
    fireEvent.click(btn);
    fireEvent.click(toggle());
    await Promise.resolve();
    expect(loginCalls()).toBe(0);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("t222: gửi form → ô về ẨN trên DOM TRƯỚC khi gọi /api/auth/login", async () => {
    let release: (r: Response) => void = () => {};
    const { typeAtLogin } = setup(where, () => new Promise<Response>((r) => (release = r)));
    const input = await fillAndShow(where);
    fireEvent.click(screen.getByRole("button", { name: SUBMIT[where] }));
    await waitFor(() => expect(typeAtLogin).toHaveLength(1));
    expect(typeAtLogin[0]).toBe("password");
    expect(input.type).toBe("password");
    release(json(401, { detail: "unauthorized" }));
    await screen.findByRole("alert");
  });

  it("t223: lỗi đăng nhập → vẫn ẩn, kể cả khi bấm hiện lại trong lúc chờ; mật khẩu (sai) vẫn giữ để sửa", async () => {
    let release: (r: Response) => void = () => {};
    setup(where, () => new Promise<Response>((r) => (release = r)));
    const input = await fillAndShow(where, "sai-mk");
    fireEvent.click(screen.getByRole("button", { name: SUBMIT[where] }));
    await waitFor(() => expect(input.type).toBe("password"));
    fireEvent.click(toggle()); // bấm hiện trong lúc đang chờ phản hồi
    expect(input.type).toBe("text");
    release(json(401, { detail: "unauthorized" }));
    expect((await screen.findByRole("alert")).textContent).toBe(GENERIC_LOGIN_ERROR);
    expect(input.type).toBe("password");
    expect(input.value).toBe("sai-mk");
    expect(toggle().getAttribute("aria-pressed")).toBe("false");
  });

  it("t224: sang bước OTP rồi quay lại → ô mật khẩu mặc định ẩn; ô OTP không có nút hiện/ẩn", async () => {
    setup(where, () => json(401, { detail: "mfa_required" }));
    await fillAndShow(where);
    fireEvent.click(screen.getByRole("button", { name: SUBMIT[where] }));
    await screen.findAllByLabelText(/^Chữ số \d$/);
    expect(screen.queryByRole("button", { name: /mật khẩu$/ })).toBeNull();
    if (where === "login") {
      fireEvent.click(screen.getByRole("button", { name: "Quay lại" }));
      expect((await field(where)).type).toBe("password");
    }
  });

  it("t225: giữ vị trí con trỏ / vùng chọn khi đổi", async () => {
    setup(where, () => json(500));
    const input = await field(where);
    fireEvent.change(input, { target: { value: "abcdef" } });
    input.setSelectionRange(2, 4);
    fireEvent.click(toggle());
    expect(input.type).toBe("text");
    expect([input.selectionStart, input.selectionEnd]).toEqual([2, 4]);
    input.setSelectionRange(3, 3);
    fireEvent.click(toggle());
    expect([input.selectionStart, input.selectionEnd]).toEqual([3, 3]);
  });
});

describe("hộp xác nhận lại đăng nhập — tự ẩn khi đóng / xong", () => {
  it.each(["Huỷ", "Escape"])("t226a: đóng hộp (%s) → ô về ẩn, mật khẩu xoá trắng", async (how) => {
    const { onDone } = setup("reauth", () => json(500));
    const input = await fillAndShow("reauth");
    if (how === "Huỷ") fireEvent.click(screen.getByRole("button", { name: "Huỷ" }));
    else fireEvent.keyDown(input, { key: "Escape" });
    expect(onDone).toHaveBeenCalledWith({ kind: "cancel" });
    expect(input.type).toBe("password");
    expect(input.value).toBe("");
  });

  it("t226b: đăng nhập lại xong → ô về ẩn, mật khẩu xoá trắng", async () => {
    const { onDone } = setup("reauth", () => json(200, { access_token: jwt("an.nv") }));
    const input = await fillAndShow("reauth");
    fireEvent.click(screen.getByRole("button", { name: "Đăng nhập lại" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith({ kind: "ok" }));
    expect(input.type).toBe("password");
    expect(input.value).toBe("");
  });
});
