// Tổng quan Trưởng BP IT (F5): `GET /api/dashboard/business`, `GET /api/dashboard/ai` (P9 §7, ke-hoach-m9-monitor.md
// §4.5, §5.1–5.2) — route CHƯA CÓ (M9 A3). MSW bật → handler giả (mocks/handlers/dashboard.ts); MSW tắt → backend: chưa
// có route → 404 "Not Found" của Starlette (`routeMissing`) → màn "có từ M9 (chặng A3)". 503 `monitor_unavailable`
// (fail-closed của M9) → "Số liệu tạm thời không có" — KHÔNG hiện số cũ (KH mục 5): không `placeholderData`, màn bỏ
// `data` khi có lỗi. `from`/`to` bắt buộc có múi giờ (§4.5) — dựng ở routes/manager/range.ts.
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type { AiDashboard, BusinessDashboard } from "./types.ts";

export type DashboardWindow = { from: string; to: string };
export type DashboardKind = "business" | "ai";

const query = (w: DashboardWindow) => `from=${encodeURIComponent(w.from)}&to=${encodeURIComponent(w.to)}`;

/** Thân phải là object có mảng `unavailable` (§4.3) — thiếu thì không dựng màn từ dữ liệu không rõ (fail-closed). */
function checked<T>(data: unknown): T {
  if (data === null || typeof data !== "object" || !Array.isArray((data as { unavailable?: unknown }).unavailable)) {
    throw new ApiError(502, "invalid_dashboard_body");
  }
  return data as T;
}

export async function getBusinessDashboard(w: DashboardWindow): Promise<BusinessDashboard> {
  return checked<BusinessDashboard>((await api.request<unknown>(`/api/dashboard/business?${query(w)}`)).data);
}

export async function getAiDashboard(w: DashboardWindow): Promise<AiDashboard> {
  return checked<AiDashboard>((await api.request<unknown>(`/api/dashboard/ai?${query(w)}`)).data);
}
