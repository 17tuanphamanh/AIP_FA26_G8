import { http } from "msw";
import { createDuyet, createNotifications, DUYET_IDS, DUYET_PREFIX, type DuyetTicket, duyetView, pageOf } from "../fixtures/notifications.ts";
import { invalid, realMe, reply } from "./shared.ts";

// N-TB (ĐP 26/10; hợp đồng thông báo §1, §2 — be-thong-bao CHƯA merge):
// - `GET /api/me/notifications?limit=&after=` — route CHƯA CÓ ở backend → giả toàn bộ (mọi người đã đăng nhập, danh sách
//   minh hoạ chung). `limit` 1–50 (mặc định 20), `after` lạ → 422 như hợp đồng. Backend ra route → xoá handler này.
// - `GET /api/tickets/:id` (route THẬT) CHỈ cho id tiền tố `tkt-demo-duyet-`: ticket chờ duyệt có `deadline` + `server_now`
//   (backend chưa trả 2 khoá này). Id khác → để handler sau / backend thật (trả `undefined`, không che route thật).

let feed: ReturnType<typeof createNotifications> | null = null;
const duyet = new Map<string, DuyetTicket>();

/** Cho test: về trạng thái đầu. */
export function resetNotificationMocks() {
  feed = null;
  duyet.clear();
}

export const notificationHandlers = [
  http.get("/api/me/notifications", async ({ request }) => {
    const who = await realMe(request);
    if ("response" in who) return who.response;
    const url = new URL(request.url);
    const rawLimit = url.searchParams.get("limit");
    const limit = rawLimit === null ? 20 : /^[0-9]{1,2}$/.test(rawLimit) ? Number(rawLimit) : Number.NaN;
    if (!(limit >= 1 && limit <= 50)) return invalid(["limit"]);
    // Mốc tròn giờ: tải lại trang (service worker chạy lại module → `feed` mới) vẫn ra CÙNG `created_at` trong giờ đó —
    // không thì dòng mới nhất "mới hơn" mốc đã xem sau mỗi lần tải lại (chấm chưa đọc giả).
    feed ??= createNotifications(Math.floor(Date.now() / 3_600_000) * 3_600_000);
    const page = pageOf(feed, limit, url.searchParams.get("after"));
    return page === null ? invalid(["after"]) : reply(page);
  }),

  http.get("/api/tickets/:id", async ({ request, params }) => {
    const id = String(params.id);
    if (!id.startsWith(DUYET_PREFIX)) return undefined; // không phải id minh hoạ này → handler sau (multi) / backend thật
    const who = await realMe(request);
    if ("response" in who) return who.response;
    if (!DUYET_IDS.includes(id)) return reply({ detail: "not_found" }, 404);
    let ticket = duyet.get(id);
    if (!ticket) {
      ticket = createDuyet(id, Date.now());
      duyet.set(id, ticket);
    }
    return reply(duyetView(ticket, Date.now()));
  }),
];
