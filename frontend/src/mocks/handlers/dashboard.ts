import { http } from "msw";
import { buildAi, buildBusiness } from "../fixtures/dashboard.ts";
import { invalid, reply, requireAny } from "./shared.ts";

// `GET /api/dashboard/business`, `GET /api/dashboard/ai` (P9 §7; ke-hoach-m9-monitor.md §4.5, §5.1–5.2) — route CHƯA
// CÓ (M9 A3). Quyền: hỏi backend thật (`/api/auth/me`) — chỉ mô phỏng `dashboard:read:all` (phần `:own` của L1 là
// Nên có, chưa có màn). Kiểm `from`/`to` như §4.5: có múi giờ, `from < to`, ≤ 90 ngày → sai thì 422.
// 503 `monitor_unavailable` (fail-closed của M9) bật bằng cookie `mock_monitor=unavailable` (Q-fe-28) — CHỈ handler giả
// đọc khoá này, ứng dụng không biết; verify F5-4 đặt cookie qua trình duyệt.
// Xoá khi: M9 A3 merge (gen:api) — xoá cùng mocks/fixtures/dashboard.ts.

export const MONITOR_COOKIE = "mock_monitor";
const TZ = /(?:Z|[+-]\d{2}:\d{2})$/;
const MAX_SPAN_MS = 90 * 86_400_000;

export const monitorDown = (cookies: Record<string, string>): boolean => cookies[MONITOR_COOKIE] === "unavailable";

/** Cửa sổ của request; thiếu cả hai → mặc định 7 ngày gần nhất (§4.5). Sai → danh sách trường lỗi. */
export function parseWindow(url: string): { from: string; to: string } | { fields: string[] } {
  const q = new URL(url).searchParams;
  const from = q.get("from");
  const to = q.get("to");
  if (from === null && to === null) {
    const now = Date.now();
    return { from: new Date(now - 7 * 86_400_000).toISOString(), to: new Date(now).toISOString() };
  }
  const fields: string[] = [];
  if (from === null || !TZ.test(from) || Number.isNaN(Date.parse(from))) fields.push("query.from");
  if (to === null || !TZ.test(to) || Number.isNaN(Date.parse(to))) fields.push("query.to");
  if (fields.length > 0) return { fields };
  const span = Date.parse(to!) - Date.parse(from!);
  if (span <= 0 || span > MAX_SPAN_MS) return { fields: ["query.from", "query.to"] };
  return { from: from!, to: to! };
}

export const dashboardHandlers = [
  http.get("/api/dashboard/business", async ({ request, cookies }) => {
    const who = await requireAny(request, ["dashboard:read:all"]);
    if ("response" in who) return who.response;
    if (monitorDown(cookies)) return reply({ detail: "monitor_unavailable" }, 503);
    const w = parseWindow(request.url);
    if ("fields" in w) return invalid(w.fields);
    return reply(buildBusiness(w.from, w.to));
  }),

  http.get("/api/dashboard/ai", async ({ request, cookies }) => {
    const who = await requireAny(request, ["dashboard:read:all"]);
    if ("response" in who) return who.response;
    if (monitorDown(cookies)) return reply({ detail: "monitor_unavailable" }, 503);
    const w = parseWindow(request.url);
    if ("fields" in w) return invalid(w.fields);
    return reply(buildAi(w.from, w.to));
  }),
];
