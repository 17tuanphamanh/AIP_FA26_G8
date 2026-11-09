import { http, passthrough } from "msw";
import { NOTE_MAX, TEXT_MAX } from "../../api/tickets.ts";
import type { ParentReplyIn } from "../../api/types.ts";
import {
  applyReply,
  awaitingOf,
  childId,
  createMulti,
  MULTI_DEMO_IDS,
  MULTI_DEMO_PREFIX,
  type MultiTicket,
  type Need,
  readMulti,
} from "../fixtures/multi.ts";
import { invalid, readJson, realMe, reply, requireAny } from "./shared.ts";

// Yêu cầu nhiều ý (D-31): `GET /api/tickets/{id}` + `POST …/reply` là route THẬT (T20b 5df24c7). Handler này CHỈ chặn id
// tiền tố `tkt-demo-multi-` (id fixture, không bao giờ có ở backend — như 12b Q-fe-5) để minh hoạ ca lỗi khó tạo trên stack
// (422 tại một ý, 409 trả muộn); id khác → `passthrough()` tới backend thật. Thứ tự kiểm + dạng 422 bám
// backend/app/api/tickets.py (`_reply_body`, `ReplyIn`, `_items_match`) và api/errors.py (`error_fields`).

const LATE = "Yêu cầu đã chuyển sang bước khác"; // câu 409 sự kiện muộn của backend (LateEvent.message)
const EXTRA = "<extra>"; // backend/app/api/errors.py: tên khoá thừa có thể là bí mật → thay bằng `<extra>`
const CHILD_INDEX = /^[0-9]{1,2}$/; // `_CHILD_INDEX` của tickets.py

const tickets = new Map<string, MultiTicket>();

function ticketOf(id: string): MultiTicket | null {
  if (!MULTI_DEMO_IDS.includes(id)) return null;
  let ticket = tickets.get(id);
  if (!ticket) {
    ticket = createMulti(id, Date.now());
    tickets.set(id, ticket);
  }
  return ticket;
}

/** Cho test: về trạng thái đầu (GET đầu = đang xử lý). */
export function resetMultiTickets() {
  tickets.clear();
}

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);

/** Khoá THỪA của một object (không thuộc `allowed`). */
const extras = (value: Record<string, unknown>, allowed: readonly string[]) => Object.keys(value).some((k) => !allowed.includes(k));

/** Lỗi hình dạng của MỘT ý như union `ReplyAnswer | ReplyConfirm` của Pydantic: ý hợp với một trong hai → []; không →
 *  lỗi của CẢ hai nhánh, vị trí `items.<cid>.<Nhánh>.<trường>` (không tiền tố `body.` — `error_fields`). */
function itemFields(at: string, value: unknown): string[] {
  if (!isRecord(value)) return [`${at}.ReplyAnswer`, `${at}.ReplyConfirm`];
  const answer: string[] = [];
  if (typeof value.answer !== "string" || value.answer.length < 1 || value.answer.length > TEXT_MAX) answer.push(`${at}.ReplyAnswer.answer`);
  if (extras(value, ["answer"])) answer.push(`${at}.ReplyAnswer.${EXTRA}`);
  const confirm: string[] = [];
  if (typeof value.confirmed !== "boolean") confirm.push(`${at}.ReplyConfirm.confirmed`);
  if (value.note != null && (typeof value.note !== "string" || value.note.length > NOTE_MAX)) confirm.push(`${at}.ReplyConfirm.note`);
  if (extras(value, ["confirmed", "note"])) confirm.push(`${at}.ReplyConfirm.${EXTRA}`);
  return answer.length === 0 || confirm.length === 0 ? [] : [...answer, ...confirm];
}

/** Bước 422 HÌNH DẠNG (trước privacy guard, trước khoá ticket): khoá `items` không có dạng "<cha>-<số>" → `["body.items"]`
 *  (vị trí CHUNG, không dội khoá người gửi); rồi như `ReplyIn` (extra="forbid" mọi tầng, `items` ≥ 1). [] = qua. */
export function shapeFields(parentId: string, body: unknown): string[] {
  const items = isRecord(body) ? body.items : undefined;
  const prefix = `${parentId}-`;
  if (isRecord(items) && Object.keys(items).some((k) => !(k.startsWith(prefix) && CHILD_INDEX.test(k.slice(prefix.length))))) {
    return ["body.items"];
  }
  if (!isRecord(body)) return [""];
  const fields: string[] = [];
  if (extras(body, ["items"])) fields.push(EXTRA);
  if (!isRecord(items) || Object.keys(items).length === 0) fields.push("items");
  else for (const [cid, value] of Object.entries(items)) fields.push(...itemFields(`items.${cid}`, value));
  return [...new Set(fields)];
}

/** Bước 422 dưới khoá (`_items_match`): `items` ≡ ĐÚNG tập `awaiting`, đúng loại theo `needs` — lệch → `body.items.<cid>`
 *  sắp theo id. */
export function awaitingFields(items: Readonly<Record<string, object>>, awaiting: Readonly<Record<string, Need>>): string[] {
  const keys = new Set([...Object.keys(items), ...Object.keys(awaiting)]);
  const bad = [...keys].filter((cid) => {
    if (!Object.hasOwn(items, cid) || !Object.hasOwn(awaiting, cid)) return true;
    return "answer" in items[cid]! !== (awaiting[cid] === "answer");
  });
  return bad.sort().map((cid) => `body.items.${cid}`);
}

export const multiHandlers = [
  http.get("/api/tickets/:id", async ({ request, params }) => {
    const id = String(params.id);
    if (!id.startsWith(MULTI_DEMO_PREFIX)) return passthrough(); // route THẬT — không che
    const who = await realMe(request); // chưa đăng nhập / token hết hạn → đúng mã của backend
    if ("response" in who) return who.response;
    const ticket = ticketOf(id);
    if (!ticket) return reply({ detail: "not_found" }, 404);
    return reply(readMulti(ticket));
  }),

  http.post("/api/tickets/:id/reply", async ({ request, params }) => {
    const id = String(params.id);
    if (!id.startsWith(MULTI_DEMO_PREFIX)) return passthrough();
    // Thứ tự như route thật: quyền → 404 → thân sai hình dạng (422) → [guard] → không ở parent_reply_wait (409) → items
    // lệch `awaiting` (422) → 202.
    const who = await requireAny(request, ["ticket:message"]);
    if ("response" in who) return who.response;
    const ticket = ticketOf(id);
    if (!ticket) return reply({ detail: "not_found" }, 404);
    const body = await readJson(request);
    if (body === undefined) return invalid([]); // JSON hỏng
    const shape = shapeFields(id, body);
    if (shape.length > 0) return invalid(shape);
    const awaiting = awaitingOf(ticket);
    if (id === `${MULTI_DEMO_PREFIX}409` || awaiting === null) return reply({ detail: LATE }, 409);
    const items = (body as ParentReplyIn).items;
    const fields = awaitingFields(items, awaiting);
    if (fields.length > 0) return invalid(fields);
    if (id === `${MULTI_DEMO_PREFIX}422`) return invalid([`body.items.${childId(id, 2)}`]); // minh hoạ: server thấy ý 2 lệch
    applyReply(ticket, items, Date.now());
    return reply({ ticket_id: id, status: "S_CONFIRMING", notices: [] }, 202);
  }),
];
