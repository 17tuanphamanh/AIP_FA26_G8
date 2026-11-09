// t227–t236: tái hiện "lỗi giữ phiên" (ĐP 31/10 21:50 — chưa có mô tả triệu chứng) bằng trình duyệt giả + backend giả
// bám backend thật (backend/app/api/auth.py, backend/app/auth/service.py):
// - login tạo HỌ token mới (token_family_id); refresh xoay vòng trong họ, dòng cũ `rotated`; trình lại token đã xoay →
//   thu hồi cả họ (reuse_detected); access token gắn đúng dòng `sessions` (validate_access); hạn tuyệt đối 8 giờ.
// - cookie `refresh` (Path=/api/auth, HttpOnly) + `csrf` (Path=/) đều `Secure; SameSite=Strict`: trình duyệt ở ngữ cảnh
//   KHÔNG an toàn (http://<IP LAN>, http://<tên máy>…) bỏ cả hai cookie.
// - mọi tab chung MỘT hũ cookie, chung khoá Web Locks, chung BroadcastChannel (giao bất đồng bộ, có thể "đóng băng" một tab).
// Mỗi test khẳng định hành vi ĐÚNG — đỏ = lỗi thật ở client.ts. Test ghi "(theo thiết kế)" mô tả cơ chế dẫn tới triệu chứng.
import { describe, expect, it, vi } from "vitest";
import { type AuthChannel, createClient, type Locks } from "./client.ts";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const json = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const b64url = (s: string) => btoa(s).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");

const ACCESS_TTL = 15 * 60;
const REFRESH_TTL = 8 * 3600;

type Session = { sid: string; fam: number; user: string; refresh: string; revoked: null | "rotated" | "reuse" | "logout"; exp: number };

/** Trình duyệt (hũ cookie) + backend giả. `t` = giờ server (giây), test tự đẩy. */
function world(opts: { secureContext?: boolean; latency?: number; refreshLatency?: number } = {}) {
  const secureContext = opts.secureContext ?? true;
  const latency = opts.latency ?? 2;
  const refreshLatency = opts.refreshLatency ?? latency;
  const jar: { refresh?: string; csrf?: string } = {};
  const sessions = new Map<string, Session>();
  const byRefresh = new Map<string, Session>();
  let t = 1_000_000;
  let seq = 0;
  let fam = 0;
  const stats = { rotations: 0, reuse: 0, refreshCalls: 0 };
  /** true → phản hồi refresh kế tiếp bị "mất" ở trình duyệt (trang tải lại giữa chừng): server đã xoay, cookie không đổi. */
  let dropNextRefreshResponse = false;

  // Claim giống backend/app/auth/tokens.py (7 claim). `jti` chứa ký tự cho ra `-`/`_` trong base64url.
  const accessFor = (s: Session) =>
    `${b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }))}.${b64url(
      JSON.stringify({ sub: s.user, role: "employee", sid: s.sid, tv: 1, iat: t, exp: t + ACCESS_TTL, jti: `>>?~${++seq}??` }),
    )}.c2lnbmF0dXJl`;
  const claims = (token: string) => JSON.parse(atob((token.split(".")[1] ?? "").replace(/-/g, "+").replace(/_/g, "/"))) as { sid: string; exp: number };

  const tokens: string[] = [];
  function issue(s: Session) {
    sessions.set(s.sid, s);
    byRefresh.set(s.refresh, s);
    const csrf = `c${seq}`;
    const token = accessFor(s);
    tokens.push(token);
    return { token, cookies: { refresh: s.refresh, csrf } };
  }
  function setCookies(c: { refresh: string; csrf: string }) {
    if (!secureContext) return; // `Secure` trên http không an toàn → trình duyệt bỏ cookie
    jar.refresh = c.refresh;
    jar.csrf = c.csrf;
  }
  function validAccess(init: RequestInit): Session | null {
    const auth = new Headers(init.headers).get("Authorization");
    if (!auth?.startsWith("Bearer ")) return null;
    const c = claims(auth.slice(7));
    const s = sessions.get(c.sid);
    if (!s || s.revoked || t >= c.exp || t >= s.exp) return null;
    return s;
  }
  const tokenBody = (token: string) => json(200, { access_token: token, token_type: "bearer", expires_in: ACCESS_TTL, csrf_token: "x" });

  const fetch = vi.fn(async (url: string, init: RequestInit = {}): Promise<Response> => {
    if (url === "/api/auth/login") {
      const { username, password } = JSON.parse(String(init.body)) as { username: string; password: string };
      await sleep(latency);
      if (password !== "pw") return json(401, { detail: "unauthorized" });
      const { token, cookies } = issue({ sid: `s${++seq}`, fam: ++fam, user: username, refresh: `r${++seq}`, revoked: null, exp: t + REFRESH_TTL });
      setCookies(cookies);
      return tokenBody(token);
    }
    if (url === "/api/auth/refresh") {
      stats.refreshCalls += 1;
      const presented = { refresh: jar.refresh, csrf: jar.csrf }; // trình duyệt gắn cookie lúc gửi
      const header = new Headers(init.headers).get("X-CSRF-Token");
      await sleep(refreshLatency);
      if (!presented.csrf || presented.csrf !== header) return json(403, { detail: "csrf" });
      const old = presented.refresh ? byRefresh.get(presented.refresh) : undefined;
      if (!old) return json(401, { detail: "unauthorized" });
      if (old.revoked) {
        if (old.revoked === "rotated") {
          stats.reuse += 1;
          for (const s of sessions.values()) if (s.fam === old.fam) s.revoked = "reuse";
        }
        return json(401, { detail: "unauthorized" });
      }
      if (t >= old.exp) return json(401, { detail: "unauthorized" });
      old.revoked = "rotated";
      stats.rotations += 1;
      const { token, cookies } = issue({ ...old, sid: `s${++seq}`, refresh: `r${++seq}`, revoked: null });
      if (dropNextRefreshResponse) {
        dropNextRefreshResponse = false;
        throw new TypeError("Failed to fetch"); // trang đã tải lại: phản hồi (và Set-Cookie) không tới trình duyệt
      }
      setCookies(cookies);
      return tokenBody(token);
    }
    const s = validAccess(init);
    if (!s) return json(401, { detail: "unauthorized" });
    if (url === "/api/auth/logout") {
      s.revoked = "logout";
      delete jar.refresh;
      delete jar.csrf;
      return new Response(null, { status: 204 });
    }
    if (url === "/api/auth/me") return json(200, { user_id: s.user, role: "employee", permissions: [] });
    return json(200, { ok: true });
  });

  // Web Locks giả: một khoá, tuần tự.
  let tail: Promise<unknown> = Promise.resolve();
  const locks: Locks = {
    request: <T,>(_n: string, cb: () => Promise<T>) => {
      const run = tail.then(cb);
      tail = run.catch(() => undefined);
      return run;
    },
  };

  // BroadcastChannel giả: giao bất đồng bộ, không gửi lại cho chính người gửi; tab "đóng băng" không nhận (tab ẩn bị
  // trình duyệt freeze / tab bị loại khỏi bộ nhớ).
  const listeners = new Map<number, (m: unknown) => void>();
  const frozen = new Set<number>();
  let ids = 0;

  function tab() {
    const id = ++ids;
    const channel: AuthChannel = {
      post: (m) => {
        for (const [other, l] of listeners) if (other !== id && !frozen.has(other)) setTimeout(() => l(structuredClone(m)), 0);
      },
      subscribe: (l) => void listeners.set(id, l),
    };
    const onSessionEnd = vi.fn();
    const client = createClient({ fetch, readCookie: (n) => (n === "csrf" ? (jar.csrf ?? null) : null), locks, channel, onSessionEnd });
    return {
      client,
      onSessionEnd,
      freeze: () => frozen.add(id),
      thaw: () => frozen.delete(id),
      /** Đóng tab / tải lại: tab cũ thôi nghe kênh. */
      close: () => listeners.delete(id),
    };
  }

  return {
    tab,
    jar,
    stats,
    tokens,
    fetch,
    advance: (seconds: number) => void (t += seconds),
    dropNextRefreshResponse: () => void (dropNextRefreshResponse = true),
  };
}

async function waitForRefreshSent(w: ReturnType<typeof world>) {
  for (let i = 0; i < 200 && w.stats.refreshCalls === 0; i += 1) await sleep(1);
  expect(w.stats.refreshCalls).toBe(1);
}

/** Tải lại trang = đóng tab cũ, mở tab mới cùng hũ cookie, chạy `restore()` rồi `/api/auth/me` như AuthProvider. */
async function reload(w: ReturnType<typeof world>, old: ReturnType<ReturnType<typeof world>["tab"]>) {
  old.close();
  const next = w.tab();
  const restored = await next.client.restore();
  const me = restored ? (await next.client.request<{ user_id: string }>("/api/auth/me")).data.user_id : null;
  return { tab: next, restored, me };
}

describe("tái hiện lỗi giữ phiên (ĐP 31/10 21:50)", () => {
  it("t227 (i): F5 ở ngữ cảnh an toàn (http://localhost, https) → khôi phục phiên, không phải đăng nhập lại; F5 nhiều lần liên tiếp vẫn giữ", async () => {
    const w = world();
    let a = w.tab();
    expect(await a.client.login("an.nv", "pw")).toMatchObject({ ok: true, subject: "an.nv" });
    for (let i = 0; i < 3; i += 1) {
      const r = await reload(w, a);
      expect(r).toMatchObject({ restored: true, me: "an.nv" });
      a = r.tab;
    }
    expect(w.stats.reuse).toBe(0);
    expect(a.onSessionEnd).not.toHaveBeenCalled();
  });

  it("t228 (i, theo thiết kế): ngữ cảnh KHÔNG an toàn (http://<IP LAN>/<tên máy>) → đăng nhập vẫn dùng được, F5 → về trang đăng nhập, 0 lời gọi refresh", async () => {
    const w = world({ secureContext: false });
    const a = w.tab();
    expect(await a.client.login("an.nv", "pw")).toMatchObject({ ok: true });
    expect((await a.client.request("/api/x")).status).toBe(200); // token trong bộ nhớ: chạy bình thường tới khi F5
    expect(w.jar).toEqual({}); // trình duyệt đã bỏ cookie Secure
    const r = await reload(w, a);
    expect(r.restored).toBe(false);
    expect(w.stats.refreshCalls).toBe(0); // Q-fe-17: không có cookie csrf → không gọi refresh
  });

  it("t229 (ii, Q-fe-15 đã chấp nhận): F5 đúng lúc refresh đang chạy → cookie mới mất → lần sau bị coi là dùng lại → cả họ token bị thu hồi", async () => {
    const w = world();
    const a = w.tab();
    const b = w.tab();
    await a.client.login("an.nv", "pw");
    await sleep(5);
    w.dropNextRefreshResponse();
    expect(await reload(w, a)).toMatchObject({ restored: false }); // lần khôi phục bị cắt giữa chừng
    const again = await reload(w, a);
    expect(again.restored).toBe(false);
    expect(w.stats.reuse).toBe(1);
    w.advance(ACCESS_TTL + 1);
    await expect(b.client.request("/api/x")).rejects.toMatchObject({ status: 401 });
    expect(b.onSessionEnd).toHaveBeenCalledTimes(1); // tab còn lại cũng bị đăng xuất
  });

  it("t230 (iii): 2 tab, access hết hạn cả hai, gọi đồng thời nhiều request → đúng 1 lần xoay, không tab nào bị đăng xuất; F5 sau đó vẫn giữ", async () => {
    const w = world();
    const a = w.tab();
    const b = w.tab();
    await a.client.login("an.nv", "pw");
    await sleep(5);
    w.advance(ACCESS_TTL + 1);
    const all = await Promise.all([1, 2, 3].flatMap(() => [a.client.request("/api/x"), b.client.request("/api/y")]));
    expect(all.every((r) => r.status === 200)).toBe(true);
    expect(w.stats.rotations).toBe(1);
    expect(w.stats.reuse).toBe(0);
    expect(a.onSessionEnd).not.toHaveBeenCalled();
    expect(b.onSessionEnd).not.toHaveBeenCalled();
    expect(await reload(w, b)).toMatchObject({ restored: true, me: "an.nv" });
  });

  it("t231 (iii): mở tab mới (restore) trong lúc tab cũ đang giữ khoá refresh → tab mới dùng token tab cũ vừa lấy, không xoay thêm", async () => {
    const w = world({ latency: 2, refreshLatency: 40 });
    const a = w.tab();
    await a.client.login("an.nv", "pw");
    w.advance(ACCESS_TTL + 1);
    const pending = a.client.request("/api/x"); // 401 → refresh (giữ khoá tới khi phản hồi về)
    await waitForRefreshSent(w);
    const c = w.tab();
    expect(await c.client.restore()).toBe(true);
    expect((await pending).status).toBe(200);
    expect((await c.client.request("/api/z")).status).toBe(200);
    expect(w.stats.rotations).toBe(1);
    expect(a.onSessionEnd).not.toHaveBeenCalled();
    expect(c.onSessionEnd).not.toHaveBeenCalled();
  });

  describe("t232 (iv): hộp đăng nhập lại (login CÙNG người — họ token mới) không làm tab nào mất phiên", () => {
    it("tab B đang rảnh → nhận token mới qua kênh, request sau OK; F5 ở cả hai tab vẫn giữ", async () => {
      const w = world();
      const a = w.tab();
      const b = w.tab();
      await a.client.login("an.nv", "pw");
      await sleep(5);
      expect(await a.client.login("an.nv", "pw")).toMatchObject({ ok: true, subject: "an.nv" }); // đăng nhập lại
      await sleep(5);
      expect((await b.client.request("/api/x")).status).toBe(200);
      expect((await a.client.request("/api/x")).status).toBe(200);
      w.advance(ACCESS_TTL + 1);
      expect((await b.client.request("/api/x")).status).toBe(200);
      expect((await a.client.request("/api/x")).status).toBe(200);
      expect(await reload(w, a)).toMatchObject({ restored: true, me: "an.nv" });
      expect(w.stats.reuse).toBe(0);
      expect(b.onSessionEnd).not.toHaveBeenCalled();
    });

    it.each(["tab B", "chính tab A"] as const)("đăng nhập lại khi %s đang refresh dở (cookie họ cũ đã gửi đi) → không ai bị đăng xuất, F5 vẫn giữ", async (who) => {
      const w = world({ latency: 5, refreshLatency: 60 });
      const a = w.tab();
      const b = w.tab();
      await a.client.login("an.nv", "pw");
      await sleep(5);
      w.advance(ACCESS_TTL + 1);
      const refresher = who === "tab B" ? b : a;
      const pending = refresher.client.request("/api/x"); // 401 → refresh bằng cookie họ cũ
      await waitForRefreshSent(w);
      // Phản hồi login (Set-Cookie họ MỚI) về TRƯỚC phản hồi refresh (Set-Cookie họ CŨ đã xoay) — cookie cuối là họ cũ.
      expect(await a.client.login("an.nv", "pw")).toMatchObject({ ok: true });
      expect(w.stats.rotations).toBe(0); // refresh vẫn đang dở
      expect((await pending).status).toBe(200);
      await sleep(5);
      for (const x of [a, b]) expect((await x.client.request("/api/y")).status).toBe(200);
      w.advance(ACCESS_TTL + 1);
      for (const x of [a, b]) expect((await x.client.request("/api/y")).status).toBe(200);
      expect(await reload(w, b)).toMatchObject({ restored: true, me: "an.nv" });
      expect(w.stats.reuse).toBe(0);
      expect(a.onSessionEnd).not.toHaveBeenCalled();
      expect(b.onSessionEnd).not.toHaveBeenCalled();
    });
  });

  it("t233 (v): tab ẩn lâu bị đóng băng (không nhận tin kênh) trong khi tab khác xoay token nhiều lần → quay lại vẫn giữ phiên", async () => {
    const w = world();
    const a = w.tab();
    const b = w.tab();
    await a.client.login("an.nv", "pw");
    await sleep(5);
    b.freeze();
    for (let i = 0; i < 4; i += 1) {
      w.advance(ACCESS_TTL + 1);
      expect((await a.client.request("/api/x")).status).toBe(200);
    }
    b.thaw();
    expect((await b.client.request("/api/x")).status).toBe(200); // token cũ chết → refresh bằng cookie hiện hành
    await sleep(5);
    expect((await a.client.request("/api/x")).status).toBe(200);
    expect(w.stats.reuse).toBe(0);
    expect(a.onSessionEnd).not.toHaveBeenCalled();
    expect(b.onSessionEnd).not.toHaveBeenCalled();
  });

  it("t234 (v, theo thiết kế): quá hạn tuyệt đối 8 giờ kể từ đăng nhập → hết phiên dù vẫn dùng đều", async () => {
    const w = world();
    const a = w.tab();
    await a.client.login("an.nv", "pw");
    for (let h = 0; h < 7; h += 1) {
      w.advance(3600);
      expect((await a.client.request("/api/x")).status).toBe(200);
    }
    w.advance(3600);
    await expect(a.client.request("/api/x")).rejects.toMatchObject({ status: 401 });
    expect(a.onSessionEnd).toHaveBeenCalledTimes(1);
  });

  it("t235 (vi): JWT dạng thật (base64url có -/_, không đệm =) → đọc được `sub`; đăng nhập lại cùng người KHÔNG bị coi là người khác", async () => {
    const w = world();
    const a = w.tab();
    const first = await a.client.login("an.nv", "pw");
    expect(w.tokens[0]?.split(".")[1]).toMatch(/[-_]/); // dữ liệu thử thật sự có ký tự base64url
    expect(w.tokens[0]).not.toContain("=");
    const again = await a.client.login("an.nv", "pw");
    expect(first).toEqual({ ok: true, subject: "an.nv" });
    expect(again).toEqual({ ok: true, subject: "an.nv" });
  });

  it("t236 (theo thiết kế): tab đã hết phiên (vd sau đăng xuất) không tự nhận token khi tab khác đăng nhập lại — phải tải lại / đăng nhập ở tab đó", async () => {
    const w = world();
    const a = w.tab();
    const b = w.tab();
    await a.client.login("an.nv", "pw");
    await sleep(5);
    expect(await a.client.logout()).toBe(true);
    await sleep(5);
    expect(b.onSessionEnd).toHaveBeenCalledTimes(1);
    await a.client.login("an.nv", "pw");
    await sleep(5);
    await expect(b.client.request("/api/x")).rejects.toMatchObject({ status: 401 });
    expect(await reload(w, b)).toMatchObject({ restored: true, me: "an.nv" }); // F5 ở tab đó → có lại phiên
  });
});
