// t1–t6: client.ts (KH 4.1 #1–#4, P6 §4). Backend giả truyền qua tham số `fetch` — không gọi mạng thật.
import { describe, expect, it, vi } from "vitest";
import {
  type AuthChannel,
  CHANNEL_SETTLE_MS,
  createClient,
  FUTURE_TOLERANCE_MS,
  type Locks,
  parseAuthMessage,
  REFRESH_LOCK,
} from "./client.ts";
import { ApiError } from "./errors.ts";

const json = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const tokenBody = (access: string) =>
  json(200, { access_token: access, token_type: "bearer", expires_in: 900, csrf_token: "c" });
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const bearer = (init: RequestInit) => new Headers(init.headers).get("Authorization");
const now = () => Date.now(); // cùng đồng hồ với `stamp()` của client

/** Web Locks giả dùng chung giữa các "tab": một khoá, chạy tuần tự. */
function sharedLocks(): Locks {
  let tail: Promise<unknown> = Promise.resolve();
  return {
    request: <T,>(_name: string, callback: () => Promise<T>) => {
      const run = tail.then(callback);
      tail = run.catch(() => undefined);
      return run;
    },
  };
}

// Chặn vòng lặp vô hạn (vd mutation "bỏ giới hạn thử lại"): quá giới hạn → fetch ném lỗi, test đỏ ngay.
const CALL_LIMIT = 20;

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

function fakeBackend(handler: Handler) {
  const calls: { url: string; headers: Headers }[] = [];
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    if (calls.length >= CALL_LIMIT) throw new Error(`quá ${CALL_LIMIT} lời gọi fetch — vòng lặp thử lại?`);
    calls.push({ url, headers: new Headers(init.headers) });
    return handler(url, init);
  });
  const count = (url: string) => calls.filter((c) => c.url === url).length;
  return { fetch, calls, count };
}

function setup(
  handler: Handler,
  options: { cookie?: () => string | null; locks?: Locks | null; channel?: AuthChannel | null } = {},
) {
  const backend = fakeBackend(handler);
  const onSessionEnd = vi.fn();
  // `cookie` trả null = trình duyệt không có cookie `csrf` (chưa đăng nhập / cookie đã hết hạn).
  const readCookie = vi.fn((name: string) => (name !== "csrf" ? null : options.cookie ? options.cookie() : "csrf-1"));
  const client = createClient({
    fetch: backend.fetch,
    readCookie,
    locks: options.locks ?? null,
    channel: options.channel ?? null,
    onSessionEnd,
  });
  return { client, backend, onSessionEnd, readCookie };
}

// Backend chuẩn: đăng nhập cấp token "old" (đã hết hạn); refresh cấp "new" sau 10 ms; route dữ liệu chỉ nhận "new".
const expiredThenRenewed: Handler = async (url, init) => {
  if (url === "/api/auth/login") return tokenBody("old");
  if (url === "/api/auth/refresh") {
    await sleep(10);
    return tokenBody("new");
  }
  return bearer(init) === "Bearer new" ? json(200, { ok: true }) : json(401, { detail: "unauthorized" });
};

describe("client.ts", () => {
  it("t1: 2 request cùng bị 401 → đúng 1 lời gọi refresh, cả 2 gửi lại thành công", async () => {
    const { client, backend } = setup(expiredThenRenewed);
    await client.login("an.nv", "pw");
    const [a, b] = await Promise.all([client.request("/api/a"), client.request("/api/b")]);
    expect(backend.count("/api/auth/refresh")).toBe(1);
    expect([a.status, b.status]).toEqual([200, 200]);
  });

  it("t2: X-CSRF-Token đọc từ cookie NGAY lúc gọi (cookie đổi giữa 2 lần refresh → header đổi theo)", async () => {
    let cookie = "csrf-1";
    let valid = "old";
    let issued = 0;
    const { client, backend, readCookie } = setup(
      (url, init) => {
        if (url === "/api/auth/login") return tokenBody("old");
        if (url === "/api/auth/refresh") {
          issued += 1;
          valid = `t${issued}`;
          return tokenBody(valid);
        }
        return bearer(init) === `Bearer ${valid}` ? json(200) : json(401);
      },
      { cookie: () => cookie },
    );
    await client.login("an.nv", "pw");
    valid = "hết hạn";
    await client.request("/api/x"); // 401 → refresh #1
    cookie = "csrf-2"; // backend xoay cookie csrf sau lần refresh trước
    valid = "hết hạn lần nữa";
    await client.request("/api/x"); // 401 → refresh #2
    const sent = backend.calls.filter((c) => c.url === "/api/auth/refresh").map((c) => c.headers.get("X-CSRF-Token"));
    expect(sent).toEqual(["csrf-1", "csrf-2"]);
    expect(readCookie).toHaveBeenCalledTimes(2);
  });

  describe("t3: 401 → refresh → gửi lại đúng 1 lần", () => {
    it("refresh OK → gửi lại 1 lần, thành công", async () => {
      const { client, backend, onSessionEnd } = setup(expiredThenRenewed);
      await client.login("an.nv", "pw");
      const res = await client.request("/api/x");
      expect(res.status).toBe(200);
      expect(backend.count("/api/x")).toBe(2);
      expect(backend.count("/api/auth/refresh")).toBe(1);
      expect(onSessionEnd).not.toHaveBeenCalled();
    });

    it("gửi lại vẫn 401 → onSessionEnd 1 lần, tổng lời gọi có giới hạn", async () => {
      let issued = 0;
      const { client, backend, onSessionEnd } = setup((url) => {
        if (url === "/api/auth/login") return tokenBody("old");
        if (url === "/api/auth/refresh") return tokenBody(`t${++issued}`);
        return json(401, { detail: "unauthorized" }); // route luôn từ chối
      });
      await client.login("an.nv", "pw");
      await expect(client.request("/api/x")).rejects.toMatchObject({ status: 401 });
      expect(onSessionEnd).toHaveBeenCalledTimes(1);
      expect(backend.count("/api/x")).toBe(2);
      expect(backend.count("/api/auth/refresh")).toBe(1);
      expect(backend.calls).toHaveLength(4); // login + gửi + refresh + gửi lại
    });
  });

  it.each([
    ["401", () => json(401, { detail: "unauthorized" })],
    ['403 "csrf"', () => json(403, { detail: "csrf" })],
  ])("t4: refresh trả %s → onSessionEnd, không refresh lại", async (_label, refreshResponse) => {
    const { client, backend, onSessionEnd } = setup((url) => {
      if (url === "/api/auth/login") return tokenBody("old");
      if (url === "/api/auth/refresh") return refreshResponse();
      return json(401, { detail: "unauthorized" });
    });
    await client.login("an.nv", "pw");
    await expect(client.request("/api/x")).rejects.toMatchObject({ status: 401 });
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
    expect(backend.count("/api/auth/refresh")).toBe(1);
    expect(backend.count("/api/x")).toBe(1); // không gửi lại
    // Request sau đó cũng không kích refresh nữa (phiên đã hết tới khi đăng nhập lại).
    await expect(client.request("/api/y")).rejects.toBeInstanceOf(ApiError);
    expect(backend.count("/api/auth/refresh")).toBe(1);
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
  });

  it("t5: 0 lời gọi Storage.setItem / IndexedDB suốt đăng nhập → refresh → đăng xuất → khôi phục", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const idb = { open: vi.fn(), deleteDatabase: vi.fn(), databases: vi.fn() };
    vi.stubGlobal("indexedDB", idb);
    const { client } = setup(async (url, init) => {
      if (url === "/api/auth/logout") return new Response(null, { status: 204 });
      return expiredThenRenewed(url, init);
    });
    await client.login("an.nv", "pw");
    await client.request("/api/x");
    await client.logout();
    await client.restore();
    expect(setItem).not.toHaveBeenCalled();
    expect(idb.open).not.toHaveBeenCalled();
    expect(idb.deleteDatabase).not.toHaveBeenCalled();
    // Spy thật sự bắt được ghi Storage (tránh test rỗng).
    window.localStorage.setItem("probe", "1");
    expect(setItem).toHaveBeenCalledTimes(1);
  });

  describe("t6: khoá refresh xuyên tab", () => {
    it(`có navigator.locks → refresh chạy BÊN TRONG locks.request("${REFRESH_LOCK}")`, async () => {
      let insideLock = false;
      const refreshSeenInsideLock: boolean[] = [];
      const request = vi.fn(async (_name: string, callback: () => Promise<unknown>) => {
        insideLock = true;
        try {
          return await callback();
        } finally {
          insideLock = false;
        }
      });
      const locks: Locks = { request: request as Locks["request"] };
      const { client } = setup(
        async (url, init) => {
          if (url === "/api/auth/refresh") refreshSeenInsideLock.push(insideLock);
          return expiredThenRenewed(url, init);
        },
        { locks },
      );
      await client.login("an.nv", "pw");
      await Promise.all([client.request("/api/a"), client.request("/api/b")]);
      expect(request).toHaveBeenCalledTimes(1);
      expect(request).toHaveBeenCalledWith(REFRESH_LOCK, expect.any(Function));
      expect(refreshSeenInsideLock).toEqual([true]);
    });

    it("không có navigator.locks → vẫn single-flight trong tab", async () => {
      const { client, backend } = setup(expiredThenRenewed, { locks: null });
      await client.login("an.nv", "pw");
      await Promise.all([client.request("/api/a"), client.request("/api/b"), client.request("/api/c")]);
      expect(backend.count("/api/auth/refresh")).toBe(1);
    });

    // Mô phỏng đúng lý do cần khoá: refresh token xoay vòng, cookie dùng chung giữa 2 tab; trình bày token đã xoay
    // → backend coi là dùng lại và thu hồi cả họ (backend/app/auth/service.py refresh()).
    function rotatingServer() {
      const jar = { refresh: "r0" };
      let current = "r0";
      let issued = 0;
      let revoked = false;
      const fetch = async (url: string, init: RequestInit = {}) => {
        if (url !== "/api/auth/refresh") return bearer(init) && !revoked ? json(200) : json(401);
        const presented = jar.refresh; // trình duyệt gắn cookie lúc GỬI
        await sleep(5);
        if (revoked || presented !== current) {
          revoked = true;
          return json(401, { detail: "unauthorized" });
        }
        current = `r${++issued}`;
        jar.refresh = current; // Set-Cookie
        return tokenBody(`a${issued}`);
      };
      return { fetch, isRevoked: () => revoked };
    }

    const tab = (server: ReturnType<typeof rotatingServer>, locks: Locks | null) =>
      createClient({ fetch: server.fetch, readCookie: () => "csrf", locks, onSessionEnd: vi.fn() });

    it("2 tab tải lại cùng lúc, chung khoá → refresh tuần tự, cả 2 giữ phiên; không khoá → họ token bị thu hồi", async () => {
      const locked = rotatingServer();
      const shared = sharedLocks();
      expect(await Promise.all([tab(locked, shared).restore(), tab(locked, shared).restore()])).toEqual([true, true]);
      expect(locked.isRevoked()).toBe(false);

      const unlocked = rotatingServer();
      const results = await Promise.all([tab(unlocked, null).restore(), tab(unlocked, null).restore()]);
      expect(results).toContain(false);
      expect(unlocked.isRevoked()).toBe(true);
    });
  });

  // Q-fe-13. Backend thật: access token gắn với ĐÚNG dòng `sessions`; refresh thu hồi dòng cũ (service.py
  // validate_access, store.py rotate_session) → tab A refresh thì token của tab B chết ngay. Các tab chia sẻ token
  // mới qua kênh (chỉ trong bộ nhớ); tin có kiểm dạng.
  describe("kênh giữa các tab (Q-fe-13)", () => {
    const jwt = (id: string, sub: string) => `h.${btoa(JSON.stringify({ sub, jti: id })).replace(/=+$/, "")}.s`;

    function sessionBoundServer(sub = "nv001") {
      const jar = { refresh: "r0" };
      let current = "r0";
      let issued = 0;
      let live: string | null = null;
      let revoked = false;
      const stats = { rotations: 0 };
      const calls: { url: string; auth: string | null }[] = [];
      const fetch = async (url: string, init: RequestInit = {}) => {
        calls.push({ url, auth: bearer(init) });
        if (url === "/api/auth/refresh") {
          const presented = jar.refresh;
          await sleep(3);
          if (revoked || presented !== current) {
            revoked = true;
            return json(401, { detail: "unauthorized" });
          }
          current = `r${++issued}`;
          jar.refresh = current;
          live = jwt(`a${issued}`, sub);
          stats.rotations += 1;
          return tokenBody(live);
        }
        if (url === "/api/auth/logout") {
          revoked = true;
          live = null;
          return new Response(null, { status: 204 });
        }
        // Chỉ token của phiên MỚI NHẤT còn sống.
        return !revoked && live !== null && bearer(init) === `Bearer ${live}` ? json(200) : json(401);
      };
      return { fetch, stats, calls, liveToken: () => live };
    }

    /** BroadcastChannel giả: giao bản sao (structuredClone) bất đồng bộ, không gửi lại cho chính người gửi. */
    function hub() {
      const listeners = new Set<(message: unknown) => void>();
      const sent: unknown[] = [];
      const connect = () => {
        let own: ((message: unknown) => void) | null = null;
        const postRaw = (message: unknown) => {
          sent.push(message);
          for (const listener of listeners) if (listener !== own) setTimeout(() => listener(structuredClone(message)), 0);
        };
        const channel: AuthChannel & { postRaw: typeof postRaw } = {
          post: postRaw,
          postRaw,
          subscribe: (listener) => {
            own = listener;
            listeners.add(listener);
          },
        };
        return channel;
      };
      return { connect, sent };
    }

    function twoTabs(withChannel: boolean) {
      const server = sessionBoundServer();
      const locks = sharedLocks();
      const { connect, sent } = hub();
      const make = () => {
        const onSessionEnd = vi.fn();
        const client = createClient({
          fetch: server.fetch,
          readCookie: () => "csrf",
          locks,
          channel: withChannel ? connect() : null,
          onSessionEnd,
        });
        return { client, onSessionEnd };
      };
      return { server, connect, sent, a: make(), b: make() };
    }

    async function pollAlternately(a: { client: ReturnType<typeof createClient> }, b: typeof a, rounds: number) {
      for (let i = 0; i < rounds; i += 1) {
        await a.client.request("/api/poll").catch(() => undefined);
        await b.client.request("/api/poll").catch(() => undefined);
      }
    }

    it("t9a: có kênh — 2 tab mở cùng lúc rồi gọi xen kẽ 12 lần → không refresh qua lại, không tab nào bị đăng xuất", async () => {
      const { server, a, b } = twoTabs(true);
      expect(await Promise.all([a.client.restore(), b.client.restore()])).toEqual([true, true]);
      const afterRestore = server.stats.rotations;
      expect(afterRestore).toBeLessThanOrEqual(2);
      await pollAlternately(a, b, 6);
      expect(server.stats.rotations).toBe(afterRestore);
      expect(a.onSessionEnd).not.toHaveBeenCalled();
      expect(b.onSessionEnd).not.toHaveBeenCalled();
    });

    it("t9b: đối chứng — không kênh: gọi xen kẽ → refresh qua lại mỗi lượt (lý do cần kênh)", async () => {
      const { server, a, b } = twoTabs(false);
      await Promise.all([a.client.restore(), b.client.restore()]);
      const afterRestore = server.stats.rotations;
      await pollAlternately(a, b, 6);
      expect(server.stats.rotations - afterRestore).toBeGreaterThanOrEqual(6);
    });

    it("t9c: tin hợp lệ nhưng user_id KHÁC (tab khác đăng nhập tài khoản khác) → tab này hết phiên", async () => {
      const { connect, a } = twoTabs(true);
      await a.client.restore(); // phiên của nv001
      const other = connect();
      other.subscribe(() => undefined);
      other.post({ type: "token", user_id: "l1_01", token: jwt("x", "l1_01"), issued_at: now() });
      await sleep(5);
      expect(a.onSessionEnd).toHaveBeenCalledTimes(1);
    });

    it("t9d: tin sai dạng / thừa khoá / user_id không khớp token / cũ hơn → bị bỏ; token và phiên giữ nguyên", async () => {
      const { server, connect, a } = twoTabs(true);
      await a.client.restore();
      const good = server.liveToken();
      const forged = jwt("f", "nv001");
      const later = now() + 1_000;
      const bad: unknown[] = [
        null,
        "token",
        [],
        { type: "token", user_id: "nv001", token: forged }, // thiếu issued_at
        { type: "token", user_id: "nv001", token: forged, issued_at: later, csrf: "c" }, // thừa khoá
        { type: "token", user_id: "nv001", token: forged, issued_at: String(later) }, // sai kiểu
        { type: "token", user_id: "nv001", token: "khong-phai-jwt", issued_at: later },
        { type: "token", user_id: "l1_01", token: forged, issued_at: later }, // user_id ≠ sub của token
        { type: "token", user_id: "nv001", token: forged, issued_at: 1 }, // cũ hơn token đang có
        { type: "logout", reason: "x" }, // logout thừa khoá
        { type: "refresh", token: forged },
      ];
      const other = connect();
      other.subscribe(() => undefined);
      for (const message of bad) other.postRaw(message);
      await sleep(5);
      const rotations = server.stats.rotations;
      await a.client.request("/api/poll");
      expect(server.calls.at(-1)).toEqual({ url: "/api/poll", auth: `Bearer ${good}` }); // vẫn token cũ
      expect(server.stats.rotations).toBe(rotations);
      expect(a.onSessionEnd).not.toHaveBeenCalled();
    });

    it("t9e: tin gửi đi chỉ gồm type, user_id, token, issued_at — không CSRF, không refresh token", async () => {
      const { sent, a } = twoTabs(true);
      await a.client.restore();
      await a.client.logout();
      expect(sent.length).toBeGreaterThanOrEqual(2);
      for (const message of sent) {
        expect(["type", "issued_at,token,type,user_id"]).toContain(Object.keys(message as object).sort().join(","));
        const text = JSON.stringify(message);
        expect(text).not.toContain("csrf");
        expect(text).not.toMatch(/"r\d+"/); // giá trị refresh token của server giả
      }
    });

    it("t12: trong khoá, token hiện tại đã khác token vừa bị 401 → gửi lại bằng token hiện tại, KHÔNG refresh", async () => {
      let release!: () => void;
      const held = new Promise<void>((resolve) => (release = resolve));
      const locks: Locks = {
        request: async <T,>(_name: string, callback: () => Promise<T>) => {
          await held; // khoá đang bị tab khác giữ
          return callback();
        },
      };
      const { connect } = hub();
      const T1 = jwt("1", "nv001");
      const T2 = jwt("2", "nv001");
      const { client, backend, onSessionEnd } = setup(
        (url, init) => {
          if (url === "/api/auth/login") return tokenBody(T1);
          if (url === "/api/auth/refresh") return tokenBody(jwt("3", "nv001"));
          return bearer(init) === `Bearer ${T2}` ? json(200) : json(401); // tab kia vừa refresh: chỉ T2 còn sống
        },
        { locks, channel: connect() },
      );
      await client.login("an.nv", "pw");
      const pending = client.request("/api/x"); // 401 với T1 → chờ khoá
      await sleep(5);
      const other = connect();
      other.subscribe(() => undefined);
      other.post({ type: "token", user_id: "nv001", token: T2, issued_at: now() });
      await sleep(5); // tin tới trong lúc còn chờ khoá
      const releasedAt = performance.now();
      release();
      expect((await pending).status).toBe(200);
      expect(performance.now() - releasedAt).toBeLessThan(CHANNEL_SETTLE_MS); // nhờ kiểm chính, không nhờ lớp chờ 50 ms
      expect(backend.count("/api/auth/refresh")).toBe(0);
      const sentAuth = backend.calls.filter((c) => c.url === "/api/x").map((c) => c.headers.get("Authorization"));
      expect(sentAuth).toEqual([`Bearer ${T1}`, `Bearer ${T2}`]);
      expect(onSessionEnd).not.toHaveBeenCalled();
    });

    it('t13: đăng xuất phát {type:"logout"} → tab khác xoá token: request sau không mang Authorization, không refresh', async () => {
      const { server, sent, a, b } = twoTabs(true);
      await Promise.all([a.client.restore(), b.client.restore()]);
      await sleep(5);
      const rotations = server.stats.rotations;
      expect(await a.client.logout()).toBe(true);
      expect(sent.at(-1)).toEqual({ type: "logout" });
      await sleep(5);
      expect(b.onSessionEnd).toHaveBeenCalledTimes(1);
      expect(a.onSessionEnd).not.toHaveBeenCalled(); // A tự đăng xuất — giao diện của A tự cập nhật
      await expect(b.client.request("/api/poll")).rejects.toMatchObject({ status: 401 });
      expect(server.calls.at(-1)).toEqual({ url: "/api/poll", auth: null });
      expect(server.stats.rotations).toBe(rotations);
    });

    // Các test dưới: sửa theo lượt soát security-reviewer (F1, F2, F4) của phần Q-fe-13.
    it("t9f: parseAuthMessage chặn ca biên — khoá __proto__, token > 4096, issued_at quá xa / NaN / Infinity / âm, user_id rỗng, sub không đọc được", () => {
      const token = jwt("1", "nv001");
      const at = now();
      // Đối chứng: tin đúng được nhận (test không rỗng).
      expect(parseAuthMessage({ type: "token", user_id: "nv001", token, issued_at: at })).toEqual({
        type: "token",
        user_id: "nv001",
        token,
        issued_at: at,
      });
      const bad: unknown[] = [
        JSON.parse(`{"type":"token","user_id":"nv001","token":"${token}","issued_at":${at},"__proto__":{"x":1}}`),
        { type: "token", user_id: "nv001", token: `${token}${"a".repeat(4097)}`, issued_at: at },
        { type: "token", user_id: "nv001", token, issued_at: 1e308 }, // mốc cực lớn → tab bỏ mọi tin thật về sau
        { type: "token", user_id: "nv001", token, issued_at: at + FUTURE_TOLERANCE_MS + 1_000 },
        { type: "token", user_id: "nv001", token, issued_at: Number.NaN },
        { type: "token", user_id: "nv001", token, issued_at: Number.POSITIVE_INFINITY },
        { type: "token", user_id: "nv001", token, issued_at: -1 },
        { type: "token", user_id: "", token: jwt("2", ""), issued_at: at },
        { type: "token", user_id: "nv001", token: "h.khong-phai-base64.s", issued_at: at },
      ];
      for (const message of bad) expect(parseAuthMessage(message)).toBeNull();
    });

    describe("t15: phiên hết TRONG LÚC chờ khoá → không refresh", () => {
      it.each(["đăng xuất", "đăng nhập người khác"] as const)(
        "tab khác %s lúc tab này đang chờ khoá → 0 refresh, request lỗi 401, báo hết phiên 1 lần",
        async (kind) => {
          let release!: () => void;
          const held = new Promise<void>((resolve) => (release = resolve));
          const locks: Locks = {
            request: async <T,>(_name: string, callback: () => Promise<T>) => {
              await held; // tab khác đang giữ khoá
              return callback();
            },
          };
          const { connect } = hub();
          const { client, backend, onSessionEnd } = setup(
            (url) => {
              if (url === "/api/auth/login") return tokenBody(jwt("1", "nv001"));
              if (url === "/api/auth/refresh") return tokenBody(jwt("2", "nv001"));
              return json(401);
            },
            { locks, channel: connect() },
          );
          await client.login("an.nv", "pw");
          const pending = client.request("/api/x"); // 401 → chờ khoá
          await sleep(5);
          const other = connect();
          other.subscribe(() => undefined);
          other.post(
            kind === "đăng xuất"
              ? { type: "logout" }
              : { type: "token", user_id: "l1_01", token: jwt("y", "l1_01"), issued_at: now() },
          );
          await sleep(5);
          release();
          await expect(pending).rejects.toMatchObject({ status: 401 });
          expect(backend.count("/api/auth/refresh")).toBe(0); // không xoay phiên của người đang giữ cookie
          expect(backend.count("/api/x")).toBe(1);
          expect(onSessionEnd).toHaveBeenCalledTimes(1);
        },
      );
    });

    it("t16: tin của NGƯỜI KHÁC dù mốc cũ hơn token đang có → vẫn hết phiên (kiểm danh tính trước kiểm cũ)", async () => {
      const { connect, a } = twoTabs(true);
      await a.client.restore(); // phiên của nv001
      const other = connect();
      other.subscribe(() => undefined);
      // Mốc 1 = "cũ" (vd tab gửi có đồng hồ lệch) — trước đây bị bỏ như tin cũ, tab giữ token nv001 tới lần refresh sau.
      other.post({ type: "token", user_id: "l1_01", token: jwt("x", "l1_01"), issued_at: 1 });
      await sleep(5);
      expect(a.onSessionEnd).toHaveBeenCalledTimes(1);
    });
  });
  it("t10: token chỉ gửi tới /api/… cùng origin — URL tuyệt đối / //host bị từ chối, không fetch", async () => {
    const { client, backend } = setup(expiredThenRenewed);
    await client.login("an.nv", "pw");
    for (const url of ["https://evil.example/api/x", "//evil.example/api/x", "/\\evil.example", "/other"]) {
      await expect(client.request(url)).rejects.toThrow(/cùng origin/);
    }
    expect(backend.calls.map((c) => c.url)).toEqual(["/api/auth/login"]);
  });

  it("t11: đăng xuất lỗi mạng / 5xx → trả false (chưa đăng xuất được), phiên trong tab còn nguyên", async () => {
    let down = true;
    const { client, backend } = setup((url, init) => {
      if (url === "/api/auth/logout") return down ? json(503, { detail: "auth_unavailable" }) : new Response(null, { status: 204 });
      if (url === "/api/auth/login") return tokenBody("new");
      return expiredThenRenewed(url, init);
    });
    await client.login("an.nv", "pw");
    expect(await client.logout()).toBe(false);
    expect((await client.request("/api/x")).status).toBe(200); // token vẫn dùng được
    down = false;
    expect(await client.logout()).toBe(true);
    expect(backend.count("/api/auth/logout")).toBe(2);
  });

  // Q-fe-17: backend `csrf_matches` đòi CẢ cookie lẫn header → thiếu cookie `csrf` thì refresh chắc chắn 403. Không gọi.
  describe("t14: không có cookie csrf → không gọi refresh", () => {
    it("tải trang khi chưa đăng nhập: restore() → false, 0 lời gọi mạng, không báo hết phiên", async () => {
      const { client, backend, onSessionEnd } = setup(expiredThenRenewed, { cookie: () => null });
      expect(await client.restore()).toBe(false);
      expect(backend.calls).toHaveLength(0);
      expect(onSessionEnd).not.toHaveBeenCalled(); // chưa đăng nhập ≠ hết phiên
    });

    it("đang dùng mà cookie csrf mất: 401 → hết phiên ngay, không refresh, không gửi lại", async () => {
      let cookie: string | null = "csrf-1";
      const { client, backend, onSessionEnd } = setup(expiredThenRenewed, { cookie: () => cookie });
      await client.login("an.nv", "pw");
      cookie = null;
      await expect(client.request("/api/x")).rejects.toMatchObject({ status: 401 });
      expect(backend.count("/api/auth/refresh")).toBe(0);
      expect(backend.count("/api/x")).toBe(1);
      expect(onSessionEnd).toHaveBeenCalledTimes(1);
    });
  });

  it("t17: refresh trả 200 nhưng thiếu access_token → lỗi; không nhận token rỗng, không coi là hết phiên (soát F3)", async () => {
    const { client, backend, onSessionEnd } = setup((url) => {
      if (url === "/api/auth/login") return tokenBody("old");
      if (url === "/api/auth/refresh") return json(200, { token_type: "bearer" });
      return json(401);
    });
    await client.login("an.nv", "pw");
    await expect(client.request("/api/x")).rejects.toThrow(/thiếu access_token/);
    expect(backend.count("/api/x")).toBe(1); // không gửi lại với token rỗng
    expect(onSessionEnd).not.toHaveBeenCalled();
  });

  it("t52 (F5 P9): refresh trả token của NGƯỜI KHÁC (cookie bị ghi đè ở tab khác) → hết phiên, KHÔNG nhận token, không gửi lại", async () => {
    // client.ts takeRefreshed: `sub` token mới ≠ người của phiên → endSession, không đổi danh tính lặng lẽ.
    const jwt = (id: string, sub: string) => `h.${btoa(JSON.stringify({ sub, jti: id })).replace(/=+$/, "")}.s`;
    const MINE = jwt("a", "l1_01");
    const OTHERS = jwt("b", "nv001");
    const posted: unknown[] = [];
    const channel: AuthChannel = { post: (m) => posted.push(m), subscribe: () => {} };
    const { client, backend, onSessionEnd } = setup(
      (url, init) => {
        if (url === "/api/auth/login") return tokenBody(MINE);
        if (url === "/api/auth/refresh") return tokenBody(OTHERS);
        // Backend nhận token người khác (đó là phiên hợp lệ của NGƯỜI KHÁC) — nếu client lỡ nhận thì request sẽ "thành công".
        return bearer(init) === `Bearer ${OTHERS}` ? json(200, { owner: "nv001" }) : json(401, { detail: "unauthorized" });
      },
      { channel },
    );
    const login = await client.login("ha.lt", "pw");
    expect(login).toStrictEqual({ ok: true, subject: "l1_01" });
    await expect(client.request("/api/x")).rejects.toMatchObject({ status: 401 });
    expect(backend.count("/api/auth/refresh")).toBe(1);
    expect(backend.count("/api/x")).toBe(1); // không gửi lại bằng token của người khác
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
    expect(backend.calls.some((c) => c.headers.get("Authorization") === `Bearer ${OTHERS}`)).toBe(false);
    expect(posted).not.toContainEqual(expect.objectContaining({ token: OTHERS })); // không phát token đó sang tab khác
    // Phiên đã hết: request sau không mang token nào, không refresh thêm.
    await expect(client.request("/api/y")).rejects.toMatchObject({ status: 401 });
    expect(backend.calls.find((c) => c.url === "/api/y")?.headers.get("Authorization")).toBeNull();
    expect(backend.count("/api/auth/refresh")).toBe(1);
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
  });
});
