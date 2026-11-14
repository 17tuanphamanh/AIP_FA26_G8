// Giả lập giờ hành chính cho demo (D-97, TA chốt 14/11) — route thật backend/app/api/hours_mode.py:
// - `GET /api/hours-mode` (mọi vai trò đã đăng nhập) → `HoursModeView` — dải báo "đang giả lập" ở mọi màn.
// - `PUT /api/admin/hours-mode` thân `{mode}` (Trưởng BP, đăng nhập gần đây) → 200 thân như GET. Lỗi: 403 `reauth_required`
//   (useReauthRetry), 403 `forbidden`, 422 `fields:["mode"]`, 409 `same_as_current`.
// Chỉ đổi fact "trong giờ hành chính" của luật (R18 VPN ngoài giờ cần duyệt) — KHÔNG đổi đồng hồ.
// Đọc chặt: thân sai hình dạng → ApiError 502 (không dựng màn từ dữ liệu không rõ).
import { queryOptions } from "@tanstack/react-query";
import type { Client } from "./client.ts";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";

export type HoursMode = "real" | "outside" | "inside";
export const HOURS_MODES: readonly HoursMode[] = ["real", "outside", "inside"];

export type HoursModeView = {
  mode: HoursMode;
  modes: HoursMode[];
  changed_by: string | null;
  changed_at: string | null;
  eval_mode: boolean;
};

/** Hỏi lại mỗi 30 giây: Trưởng BP bật ở máy khác thì dải báo ở mọi màn tự hiện. */
export const HOURS_MODE_REFRESH_MS = 30_000;

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const isMode = (v: unknown): v is HoursMode => typeof v === "string" && (HOURS_MODES as readonly string[]).includes(v);
const isNullableString = (v: unknown) => v === null || typeof v === "string";

export function parseHoursModeView(body: unknown): HoursModeView {
  const ok =
    isRecord(body) &&
    isMode(body.mode) &&
    Array.isArray(body.modes) &&
    body.modes.every(isMode) &&
    isNullableString(body.changed_by) &&
    isNullableString(body.changed_at) &&
    typeof body.eval_mode === "boolean";
  if (!ok) throw new ApiError(502, "invalid_hours_mode_body");
  return body as HoursModeView;
}

export async function getHoursMode(client: Client = api): Promise<HoursModeView> {
  return parseHoursModeView((await client.request<unknown>("/api/hours-mode")).data);
}

/** Đổi chế độ. CHỈ 200 là đã đổi; 2xx khác → 502 (không báo thành công giả). */
export async function putHoursMode(mode: HoursMode, client: Client = api): Promise<HoursModeView> {
  const res = await client.request<unknown>("/api/admin/hours-mode", { method: "PUT", json: { mode } });
  if (res.status !== 200) throw new ApiError(502, "unexpected_hours_mode_status");
  return parseHoursModeView(res.data);
}

export const hoursModeQuery = (client: Client = api) =>
  queryOptions({
    queryKey: ["hours-mode"] as const,
    queryFn: () => getHoursMode(client),
    retry: false,
    refetchInterval: HOURS_MODE_REFRESH_MS,
  });

export const HOURS_MODE_LABEL: Record<HoursMode, string> = {
  real: "Theo giờ thật",
  outside: "Giả lập NGOÀI giờ hành chính",
  inside: "Giả lập TRONG giờ hành chính",
};

export const HOURS_MODE_HINT: Record<HoursMode, string> = {
  real: "Luật dùng giờ hiện tại (thứ Hai – thứ Sáu, 08:00–18:00).",
  outside: "Mọi yêu cầu được xét như gửi ngoài giờ: gia hạn / cấp lại VPN cần L1 duyệt (luật R18).",
  inside: "Mọi yêu cầu được xét như gửi trong giờ: VPN của chính mình được tự xử lý (luật R20).",
};
