import { bypass, HttpResponse, type JsonBodyType } from "msw";
import type { Me } from "../../api/types.ts";

// Dùng chung cho handler giả. MỌI response giả đặt header `Date` = giờ hiện tại (đồng hồ duyệt L1 đọc độ lệch giờ máy
// chủ từ header này — api/serverClock.ts). Quyền: hỏi backend THẬT (`/api/auth/me` qua `bypass`, cùng token của người
// đang đăng nhập) — handler giả không tự quyết quyền, không có bảng người dùng giả.

export function reply(body: JsonBodyType, status = 200): HttpResponse<JsonBodyType> {
  return HttpResponse.json(body, { status, headers: { Date: new Date().toUTCString() } });
}

/** Gọi backend thật bằng đúng header `Authorization` của request đang giả (không mang header nào khác). */
export function realFetch(request: Request, path: string): Promise<Response> {
  const headers = new Headers();
  const authorization = request.headers.get("Authorization");
  if (authorization) headers.set("Authorization", authorization);
  return fetch(bypass(new Request(new URL(path, request.url), { headers })));
}

/** Người đang đăng nhập theo backend thật. Lỗi (401 token hết hạn → client tự refresh rồi gửi lại) → trả nguyên mã. */
export async function realMe(request: Request): Promise<{ me: Me } | { response: HttpResponse<JsonBodyType> }> {
  const res = await realFetch(request, "/api/auth/me");
  if (!res.ok) return { response: reply((await res.json().catch(() => null)) as JsonBodyType, res.status) };
  return { me: (await res.json()) as Me };
}

/** Như `require(...)` của backend: thiếu MỌI quyền trong `perms` → 403 `forbidden`. */
export async function requireAny(request: Request, perms: readonly string[]): Promise<{ me: Me } | { response: HttpResponse<JsonBodyType> }> {
  const who = await realMe(request);
  if ("response" in who) return who;
  return perms.some((p) => who.me.permissions.includes(p)) ? who : { response: reply({ detail: "forbidden" }, 403) };
}

/** Thân JSON của request (hỏng → undefined, để bước kiểm thân trả 422). */
export async function readJson(request: Request): Promise<unknown> {
  try {
    return await request.clone().json();
  } catch {
    return undefined;
  }
}

export const invalid = (fields: string[]) => reply({ error: "invalid_request", fields }, 422);
