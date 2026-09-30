// Client HTTP (KH 4.1 #1–#4, P6 §4, P10 §4). Nhận mọi phụ thuộc qua tham số để test được không cần trình duyệt:
//   fetch, readCookie (đọc cookie `csrf`), locks (navigator.locks hoặc null), channel (kênh giữa các tab hoặc null),
//   onSessionEnd (phiên hết → về đăng nhập).
// - Access token CHỈ trong biến của closure — không Storage, không IndexedDB. Tải lại trang → `restore()` gọi refresh.
// - Refresh: single-flight trong tab + `locks.request("auth-refresh")` xuyên tab. Refresh token xoay vòng: hai tab
//   gửi cùng một refresh cũ thì backend coi là DÙNG LẠI và thu hồi cả họ token → mọi tab bị đăng xuất.
// - Access token gắn với ĐÚNG dòng `sessions` lúc cấp; refresh thu hồi dòng cũ (backend/app/auth/service.py
//   validate_access). Nên tab vừa refresh gửi token mới qua `channel` (chỉ trong bộ nhớ, cùng origin) cho tab khác;
//   tab đang chờ khoá mà đã nhận token mới thì dùng luôn, không xoay tiếp → không refresh qua lại giữa các tab.
// - `X-CSRF-Token` đọc từ cookie `csrf` NGAY lúc gọi refresh (cookie xoay vòng sau mỗi lần refresh). Không có cookie
//   → không gọi refresh (backend chắc chắn 403) — mở trang khi chưa đăng nhập không sinh request lỗi (Q-fe-17).
// - 401 → refresh một lần → gửi lại một lần; vẫn 401, hoặc refresh 401/403 → hết phiên, không thử nữa.
import { ApiError, readApiError } from "./errors.ts";
import type { TokenOut } from "./types.ts";

/** Khớp `USERNAME_PATTERN` ở backend/app/api/auth.py — kiểm TRƯỚC khi gửi: mật khẩu gõ nhầm vào ô này sẽ bị
 *  backend ghi nguyên văn vào `security_events.username_attempted`. */
export const USERNAME_PATTERN = /^[a-z][a-z0-9._-]{0,127}$/;
export const REFRESH_LOCK = "auth-refresh";
/** Refresh treo thì giữ khoá mãi → mọi tab chờ. Quá hạn → coi như lỗi mạng (không phải hết phiên). */
export const REFRESH_TIMEOUT_MS = 10_000;
/** Có kênh giữa các tab: trước khi tự xoay token, chờ chừng này để nhận token tab khác vừa lấy (tin đang trên đường). */
export const CHANNEL_SETTLE_MS = 50;

export type Locks = { request<T>(name: string, callback: () => Promise<T>): Promise<T> };

/** Tin giữa các tab cùng origin (Q-fe-13) — CHỈ đúng các khoá này: không bao giờ có CSRF hay refresh token (refresh
 *  nằm trong cookie HttpOnly, JS không đọc được). Không ghi đĩa; tab mở sau không nhận được tin cũ. */
export type AuthMessage = { type: "token"; user_id: string; token: string; issued_at: number } | { type: "logout" };
/** Người nhận được `unknown` — client tự kiểm dạng (`parseAuthMessage`), không tin nội dung kênh. */
export type AuthChannel = { post(message: AuthMessage): void; subscribe(listener: (message: unknown) => void): void };

export type ClientDeps = {
  fetch: (input: string, init?: RequestInit) => Promise<Response>;
  readCookie: (name: string) => string | null;
  locks: Locks | null;
  channel?: AuthChannel | null;
  onSessionEnd: () => void;
};

export type RequestOptions = Omit<RequestInit, "body"> & { json?: unknown; body?: BodyInit };
export type ApiResult<T> = { data: T; status: number; headers: Headers };

export type LoginResult =
  | { ok: true }
  | { ok: false; kind: "otp_required" }
  | { ok: false; kind: "invalid_username" }
  /** Đăng nhập được nhưng không tải được `/api/auth/me`. */
  | { ok: false; kind: "profile_error" }
  /** `error` null = lỗi mạng / phản hồi hỏng (không có mã lỗi của backend). */
  | { ok: false; kind: "error"; error: ApiError | null };

export type Client = ReturnType<typeof createClient>;

/** `issued_at` lớn hơn giờ máy quá mức này → tin giả (một mốc cực lớn sẽ làm tab bỏ mọi tin thật về sau). */
export const FUTURE_TOLERANCE_MS = 60_000;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** `sub` trong payload JWT — chỉ để so danh tính giữa các lần cấp token, KHÔNG dùng để quyết quyền. */
function subjectOf(token: string): string | null {
  try {
    const payload = token.split(".")[1] ?? "";
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const sub = (JSON.parse(json) as { sub?: unknown }).sub;
    return typeof sub === "string" ? sub : null;
  } catch {
    return null;
  }
}

const JWT_SHAPE = /^[\w-]+\.[\w-]+\.[\w-]*$/;
const TOKEN_KEYS = "issued_at,token,type,user_id";

/** Kiểm dạng tin nhận từ kênh: đúng khoá, đúng kiểu, `user_id` khớp `sub` của chính token. Sai → null (bỏ tin). */
export function parseAuthMessage(raw: unknown): AuthMessage | null {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return null;
  const m = raw as Record<string, unknown>;
  const keys = Object.keys(m).sort().join(",");
  if (m.type === "logout") return keys === "type" ? { type: "logout" } : null;
  if (m.type !== "token" || keys !== TOKEN_KEYS) return null;
  const { user_id, token, issued_at } = m;
  if (typeof user_id !== "string" || user_id === "") return null;
  if (typeof token !== "string" || token.length > 4096 || !JWT_SHAPE.test(token) || subjectOf(token) !== user_id) return null;
  if (typeof issued_at !== "number" || !Number.isFinite(issued_at) || issued_at <= 0) return null;
  if (issued_at > Date.now() + FUTURE_TOLERANCE_MS) return null;
  return { type: "token", user_id, token, issued_at };
}

export function createClient(deps: ClientDeps) {
  const channel = deps.channel ?? null;
  let accessToken: string | null = null;
  let subject: string | null = null; // người dùng của phiên trong tab này
  let tokenAt = 0; // mốc của token hiện tại (theo `stamp()` của tab cấp nó)
  let refreshing: Promise<boolean> | null = null;
  // Phiên đã hết (refresh bị từ chối / đăng xuất): không refresh nữa cho tới khi đăng nhập lại.
  let ended = false;
  let endNotified = false;
  // Tăng mỗi lần đăng nhập / đăng xuất: kết quả của refresh bắt đầu TRƯỚC đó bị bỏ, không ghi đè phiên mới.
  let generation = 0;

  // Mốc cho token do tab này cấp: giờ máy (`Date.now()` giống nhau giữa các tab/process — `performance.timeOrigin`
  // thì lệch giữa process sau khi máy ngủ), không bao giờ lùi so với mốc đã thấy (đồng hồ chỉnh lùi vẫn đúng thứ tự).
  const stamp = () => Math.max(Date.now(), tokenAt + 1);

  function endSession(): void {
    accessToken = null;
    ended = true;
    if (!endNotified) {
      endNotified = true; // báo MỘT lần mỗi phiên, dù nhiều request cùng thất bại
      deps.onSessionEnd();
    }
  }

  /** Gửi token vừa cấp cho các tab khác — chỉ 4 khoá của `AuthMessage`. Token không đọc được `sub` → không gửi. */
  function share(token: string, issuedAt: number): void {
    const user_id = subjectOf(token);
    if (channel && user_id) channel.post({ type: "token", user_id, token, issued_at: issuedAt });
  }

  /** Token do CHÍNH tab này nhận từ backend (refresh). Khác người dùng của phiên → hết phiên (cookie đã bị người
   *  khác ghi đè ở tab khác) — không lẳng lặng đổi danh tính. */
  function takeRefreshed(token: string): boolean {
    const sub = subjectOf(token);
    if (subject !== null && sub !== null && sub !== subject) {
      endSession();
      return false;
    }
    accessToken = token;
    tokenAt = stamp();
    subject = sub ?? subject;
    share(token, tokenAt);
    return true;
  }

  // Nhận tin từ tab khác (Q-fe-13). Sai dạng → bỏ; khác người dùng → hết phiên; cũ hơn token đang có → bỏ.
  channel?.subscribe((raw) => {
    const message = parseAuthMessage(raw);
    if (message === null || ended) return;
    if (message.type === "logout") {
      endSession(); // tab khác đã đăng xuất → xoá token ở tab này
      return;
    }
    // Kiểm danh tính TRƯỚC kiểm cũ: tin của người khác không bao giờ bị bỏ qua lặng lẽ (fail-closed).
    if (subject !== null && message.user_id !== subject) {
      endSession(); // tab khác đăng nhập người khác
      return;
    }
    if (message.issued_at <= tokenAt) return; // tin cũ đến muộn không đè token mới hơn
    accessToken = message.token;
    tokenAt = message.issued_at;
    subject = message.user_id;
  });

  // true = có token mới; false = phiên hết (401, hoặc 403 `csrf`). Lỗi mạng / 5xx / quá hạn → ném, KHÔNG coi là hết phiên.
  async function refreshNow(): Promise<boolean> {
    const started = generation;
    const csrf = deps.readCookie("csrf"); // đọc NGAY lúc gọi — không nhớ bản cũ
    // Q-fe-17: thiếu cookie `csrf` → backend chắc chắn trả 403 (`csrf_matches` đòi cả cookie lẫn header) → khỏi gọi.
    // Cùng kết quả như 403: phiên hết. Hai cookie `csrf` và `refresh` được đặt cùng lúc, cùng hạn.
    if (!csrf) {
      accessToken = null;
      ended = true;
      return false;
    }
    const res = await deps.fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf },
      signal: AbortSignal.timeout(REFRESH_TIMEOUT_MS),
    });
    if (started !== generation) return accessToken !== null; // đã đăng nhập / đăng xuất trong lúc chờ
    if (ended) return false; // phiên hết trong lúc chờ phản hồi (tin từ tab khác) → bỏ token vừa nhận
    if (res.status === 401 || res.status === 403) {
      accessToken = null;
      ended = true;
      return false;
    }
    if (!res.ok) throw await readApiError(res);
    const token = ((await res.json()) as Partial<TokenOut>).access_token;
    if (typeof token !== "string" || !token) throw new Error("refresh: phản hồi thiếu access_token");
    return takeRefreshed(token);
  }

  /** `rejected`: token vừa bị 401 (null khi khôi phục phiên lúc tải trang). */
  function refreshOnce(rejected: string | null): Promise<boolean> {
    if (ended) return Promise.resolve(false);
    // Kiểm CHÍNH trong khoá: token hiện tại đã khác token vừa bị 401 (tab khác vừa refresh và gửi qua kênh) →
    // gửi lại bằng token hiện tại, KHÔNG xoay thêm. Chờ 50 ms tin còn trên đường chỉ là lớp phụ.
    const fresh = () => accessToken !== null && accessToken !== rejected;
    // `ended` kiểm LẠI sau mỗi chỗ chờ (khoá, 50 ms): phiên có thể hết trong lúc chờ (tab khác đăng xuất / đăng nhập
    // người khác) → không refresh nữa, kẻo xoay phiên của người đang dùng cookie hoặc lấy lại token sau khi đã báo hết.
    const run = async () => {
      if (ended) return false;
      if (fresh()) return true;
      if (channel) {
        await sleep(CHANNEL_SETTLE_MS);
        if (ended) return false;
        if (fresh()) return true;
      }
      return refreshNow();
    };
    refreshing ??= (deps.locks ? deps.locks.request(REFRESH_LOCK, run) : run()).finally(() => {
      refreshing = null;
    });
    return refreshing;
  }

  function send(path: string, options: RequestOptions, token: string | null): Promise<Response> {
    // Token chỉ đi tới API cùng origin — không bao giờ gắn cho URL tuyệt đối / `//host` lấy từ dữ liệu.
    if (!path.startsWith("/api/") || path.includes("\\")) throw new Error(`client chỉ gọi /api/… cùng origin: ${path}`);
    const { json, headers: extra, ...rest } = options;
    const headers = new Headers(extra);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    let body = options.body;
    if (json !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(json);
    }
    return deps.fetch(path, { ...rest, body, headers, credentials: "same-origin" });
  }

  async function readBody<T>(res: Response): Promise<T> {
    if (res.status === 204) return undefined as T;
    const type = res.headers.get("Content-Type") ?? "";
    return (type.includes("application/json") ? await res.json() : await res.text()) as T;
  }

  async function request<T>(path: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
    const sentWith = accessToken;
    let res = await send(path, options, sentWith);
    if (res.status === 401) {
      // Lời gọi khác (hoặc tab khác) vừa làm mới token trong lúc request này chờ → dùng luôn, khỏi refresh thêm.
      const renewed = accessToken !== null && accessToken !== sentWith ? true : await refreshOnce(sentWith);
      if (!renewed) {
        endSession();
        throw await readApiError(res);
      }
      res = await send(path, options, accessToken); // gửi lại ĐÚNG một lần
      if (res.status === 401) {
        endSession();
        throw await readApiError(res);
      }
    }
    if (!res.ok) throw await readApiError(res);
    return { data: await readBody<T>(res), status: res.status, headers: res.headers };
  }

  async function login(username: string, password: string, otp?: string): Promise<LoginResult> {
    const name = username.trim();
    if (!USERNAME_PATTERN.test(name)) return { ok: false, kind: "invalid_username" };
    let token: string;
    try {
      const res = await deps.fetch("/api/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(otp ? { username: name, password, otp } : { username: name, password }),
      });
      if (!res.ok) {
        const error = await readApiError(res);
        if (res.status === 401 && error.code === "mfa_required") return { ok: false, kind: "otp_required" };
        return { ok: false, kind: "error", error };
      }
      token = ((await res.json()) as TokenOut).access_token;
      if (typeof token !== "string" || !token) throw new Error("thiếu access_token");
    } catch {
      return { ok: false, kind: "error", error: null }; // lỗi mạng hoặc phản hồi 200 hỏng
    }
    generation += 1;
    accessToken = token;
    tokenAt = stamp();
    subject = subjectOf(token);
    ended = false;
    endNotified = false;
    share(token, tokenAt);
    return { ok: true };
  }

  /** Tải lại trang: lấy access token mới từ cookie refresh. Không gọi `onSessionEnd` (chưa đăng nhập ≠ hết phiên). */
  async function restore(): Promise<boolean> {
    if (accessToken) return true;
    try {
      return await refreshOnce(null);
    } catch {
      return false;
    }
  }

  /** true = backend đã thu hồi phiên (hoặc phiên vốn đã hết). false = CHƯA đăng xuất được (mạng/5xx) — cookie
   *  refresh HttpOnly vẫn sống, JS không xoá được → giao diện phải báo, không giả vờ đã đăng xuất. */
  async function logout(): Promise<boolean> {
    try {
      await request<void>("/api/auth/logout", { method: "POST" });
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) return false;
    }
    generation += 1;
    accessToken = null;
    tokenAt = 0;
    subject = null;
    ended = true;
    endNotified = true; // chính tab này chủ động đăng xuất — giao diện tự cập nhật
    channel?.post({ type: "logout" });
    return true;
  }

  return { request, login, restore, logout };
}
