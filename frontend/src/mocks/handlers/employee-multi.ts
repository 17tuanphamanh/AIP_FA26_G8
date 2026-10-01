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

// Yêu cầu nhiều ý (F6, D-31): `POST /api/tickets/{cha}/reply` + `children_progress` CHƯA CÓ (Phase 5, T20).
// `GET /api/tickets/{id}` là route THẬT: handler này CHỈ chặn id tiền tố `tkt-demo-multi-` (id fixture, không bao giờ có ở
// backend — như 12b Q-fe-5); id khác → `passthrough()` tới backend thật (ticket thường F2 không đổi gì).
// Xoá file này khi T20 merge (gen:api) — cùng mocks/fixtures/multi.ts.

const LATE = "Yêu cầu đã chuyển sang bước khác"; // câu 409 sự kiện muộn của backend (LateEvent.message)
const EXTRA = "<extra>"; // backend/app/api/errors.py: tên khoá thừa có thể là bí mật → thay bằng `<extra>`

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

/** Kiểm thân như `ParentReplyIn` đề xuất (extra="forbid" mọi tầng; PLAN-fe mục 8): đủ MỌI ý trong `awaiting`, không ý
 *  nào ngoài `awaiting`, đúng hình theo loại chờ. Trả các trường sai dạng `body.items.<child_id>…`. */
export function replyFields(body: unknown, awaiting: Readonly<Record<string, Need>>): string[] {
  if (!isRecord(body)) return ["body"];
  const fields: string[] = [];
  if (Object.keys(body).some((k) => k !== "items")) fields.push(`body.${EXTRA}`);
  const items = body.items;
  if (!isRecord(items)) return [...fields, "body.items"];
  if (Object.keys(items).some((k) => !Object.hasOwn(awaiting, k))) fields.push(`body.items.${EXTRA}`);
  for (const [cid, need] of Object.entries(awaiting)) {
    const at = `body.items.${cid}`;
    const value = items[cid];
    if (!isRecord(value)) {
      fields.push(at);
      continue;
    }
    const allowed = need === "answer" ? ["answer"] : ["confirmed", "note"];
    if (Object.keys(value).some((k) => !allowed.includes(k))) fields.push(`${at}.${EXTRA}`);
    if (need === "answer") {
      const answer = value.answer;
      if (typeof answer !== "string" || !answer.trim() || answer.length > TEXT_MAX) fields.push(`${at}.answer`);
    } else {
      if (typeof value.confirmed !== "boolean") fields.push(`${at}.confirmed`);
      if (value.note != null && (typeof value.note !== "string" || value.note.length > NOTE_MAX)) fields.push(`${at}.note`);
    }
  }
  return fields;
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
    // Thứ tự như các route sự kiện của backend: quyền → 404 → hết bước (409) → thân (422) → 202.
    const who = await requireAny(request, ["ticket:message"]);
    if ("response" in who) return who.response;
    const ticket = ticketOf(id);
    if (!ticket) return reply({ detail: "not_found" }, 404);
    const awaiting = awaitingOf(ticket);
    if (id === `${MULTI_DEMO_PREFIX}409` || awaiting === null) return reply({ detail: LATE }, 409);
    const body = await readJson(request);
    const fields = replyFields(body, awaiting);
    if (fields.length > 0) return invalid(fields);
    if (id === `${MULTI_DEMO_PREFIX}422`) return invalid([`body.items.${childId(id, 2)}.answer`]);
    applyReply(ticket, (body as ParentReplyIn).items, Date.now());
    return reply({ ticket_id: id, status: "S_CONFIRMING", notices: [] }, 202);
  }),
];
