// Cảnh báo (F5): `GET /api/alerts?status=open` (P9 §7), "Tất cả" = không tham số `status` (Q-fe-27), và
// `POST /api/alerts/{id}/ack` → 200 (cảnh báo đã ack) | 403 | 404 | 409 đã ack (ke-hoach-m9-monitor.md §4.5) — route
// CHƯA CÓ (M9 A3). MSW bật → mocks/handlers/alerts.ts; tắt → backend 404 "Not Found" → "có từ M9 (chặng A3)".
import { queryOptions } from "@tanstack/react-query";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type { AlertItem } from "./types.ts";

export type AlertFilter = "open" | "all";

export async function listAlerts(filter: AlertFilter): Promise<AlertItem[]> {
  const res = await api.request<unknown>(filter === "open" ? "/api/alerts?status=open" : "/api/alerts");
  if (!Array.isArray(res.data)) throw new ApiError(502, "invalid_alerts_body");
  return res.data as AlertItem[];
}

export async function ackAlert(id: number): Promise<AlertItem> {
  return (await api.request<AlertItem>(`/api/alerts/${encodeURIComponent(String(id))}/ack`, { method: "POST" })).data;
}

export const alertsQuery = (filter: AlertFilter) =>
  queryOptions({
    queryKey: ["alerts", filter] as const,
    queryFn: () => listAlerts(filter),
    retry: false,
  });
