import { http } from "msw";
import { createEscalationStore } from "../fixtures/escalations.ts";
import { invalid, reply, requireAny } from "./shared.ts";

// Hàng đợi L2 dạng MỚI `{items, next_cursor}` (hợp đồng N-PA §4) — backend hiện còn trả mảng trần (be-tuan8 chưa merge) nên ở
// dev:mock handler này giữ TRỌN `GET /api/escalations/queue` bằng dữ liệu minh hoạ (Q-fe-N8 — ngoại lệ có ghi lại: route
// đã có nhưng hình dạng mới chưa có). Xoá file này khi be-tuan8 merge. Quyền hỏi backend THẬT (requireAny).
// `after` là chuỗi mờ `cur-<vị trí>`; sai dạng / vượt cuối → 422 `fields:["query.after"]`.

export const escalationStore = createEscalationStore(Date.now());
type Store = typeof escalationStore;

const CURSOR = /^cur-(\d{1,6})$/;

export function queuePage(store: Store, url: URL) {
  const q = url.searchParams;
  const status = q.get("status") ?? "open";
  const limitRaw = q.get("limit");
  const limit = limitRaw === null ? 50 : Number(limitRaw);
  const fields: string[] = [];
  if (status !== "open" && status !== "closed") fields.push("query.status");
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) fields.push("query.limit");
  const after = q.get("after");
  let offset = 0;
  if (after !== null) {
    const m = CURSOR.exec(after);
    if (!m) fields.push("query.after");
    else offset = Number(m[1]);
  }
  if (fields.length > 0) return { fields };
  const list = store.list(status as "open" | "closed");
  if (offset > list.length) return { fields: ["query.after"] };
  const items = list.slice(offset, offset + limit);
  const end = offset + items.length;
  return { body: { items, next_cursor: end < list.length ? `cur-${end}` : null } };
}

export const escalationQueueHandlers = [
  http.get("/api/escalations/queue", async ({ request }) => {
    const who = await requireAny(request, ["escalation:handle"]);
    if ("response" in who) return who.response;
    const page = queuePage(escalationStore, new URL(request.url));
    return "fields" in page ? invalid(page.fields!) : reply(page.body!);
  }),
];
