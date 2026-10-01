import { http } from "msw";
import type { AlertItem } from "../../api/types.ts";
import { ALERT_ACKED_ELSEWHERE_ID, ALERT_GONE_ID, buildAlerts } from "../fixtures/alerts.ts";
import { monitorDown } from "./dashboard.ts";
import { invalid, reply, requireAny } from "./shared.ts";

// `GET /api/alerts[?status=open|acked]`, `POST /api/alerts/{id}/ack` (P9 §7; ke-hoach-m9-monitor.md §4.5) — route CHƯA
// CÓ (M9 A3). Quyền `alert:read` (cả ack) — hỏi backend thật. Thứ tự ack như §4.5: quyền → 404 → 409 (không đổi
// `acked_by` cũ) → 200 trả cảnh báo đã ack. Trạng thái chỉ trong bộ nhớ trang (tải lại trang → dữ liệu mới).
// 503 `monitor_unavailable` bật bằng cookie `mock_monitor=unavailable` (Q-fe-28), như dashboard.
// Xoá khi: M9 A3 merge (gen:api) — xoá cùng mocks/fixtures/alerts.ts.

let store: AlertItem[] | null = null;
const alerts = () => (store ??= buildAlerts(Date.now()));

/** Chỉ cho test: dựng lại dữ liệu. */
export const resetAlerts = (now: number = Date.now()) => {
  store = buildAlerts(now);
};

export const alertHandlers = [
  http.get("/api/alerts", async ({ request, cookies }) => {
    const who = await requireAny(request, ["alert:read"]);
    if ("response" in who) return who.response;
    if (monitorDown(cookies)) return reply({ detail: "monitor_unavailable" }, 503);
    const status = new URL(request.url).searchParams.get("status");
    if (status !== null && status !== "open" && status !== "acked") return invalid(["query.status"]);
    // Cố ý trả theo `alert_id` tăng dần (không theo mức nghiêm trọng) — giao diện tự sắp (Q-fe-27).
    const items = alerts()
      .filter((a) => status === null || a.status === status)
      .sort((a, b) => a.alert_id - b.alert_id);
    return reply(items);
  }),

  http.post("/api/alerts/:id/ack", async ({ request, params, cookies }) => {
    const who = await requireAny(request, ["alert:read"]);
    if ("response" in who) return who.response;
    if (monitorDown(cookies)) return reply({ detail: "monitor_unavailable" }, 503);
    const id = Number(params.id);
    if (!Number.isSafeInteger(id)) return invalid(["path.id"]);
    const list = alerts();
    const alert = list.find((a) => a.alert_id === id);
    if (!alert) return reply({ detail: "not_found" }, 404);
    if (id === ALERT_GONE_ID) {
      store = list.filter((a) => a.alert_id !== id); // đã bị xoá / gộp ở server
      return reply({ detail: "not_found" }, 404);
    }
    if (id === ALERT_ACKED_ELSEWHERE_ID && alert.status === "open") {
      // Người khác (hoặc tab khác) đã xác nhận ngay trước đó.
      Object.assign(alert, { status: "acked", acked_by: "it_mgr01", acked_at: new Date(Date.now() - 30_000).toISOString() });
    }
    if (alert.status === "acked") return reply({ detail: "already_acked" }, 409);
    Object.assign(alert, { status: "acked", acked_by: who.me.user_id, acked_at: new Date().toISOString() });
    return reply(alert);
  }),
];
