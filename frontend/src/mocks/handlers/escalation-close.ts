import { http } from "msw";
import { CLOSE_NOTE_MAX, CLOSE_RESULTS } from "../../api/escalations.ts";
import type { EscalationCloseIn, EscalationCloseResult } from "../../api/types.ts";
import type { CloseOutcome, EscalationStore } from "../fixtures/escalations.ts";
import { escalationStore } from "./escalation-queue.ts";
import { readJson, reply, requireAny } from "./shared.ts";

// `POST /api/escalations/:id/close` — route THẬT đã có (be-tuan8, backend/app/api/escalations.py). File này CHỈ để dev:mock
// đóng được ca MINH HOẠ của escalation-queue.ts, cùng hình dạng route thật: 200 (thân EscalationCloseOut) → ca rời danh sách
// mở; 404 `not_found`; 409 `already_closed`; 422 `fields: ["close_result"]` (completed cho ca deny / E6); 422 thân sai với
// `fields` KHÔNG tiền tố (`parse_body` của backend): `["close_result"]`, `["note"]`, hoặc tên khoá thừa.

/** Kiểm thân như backend (`extra="forbid"`): đúng 2 khoá; lỗi → danh sách trường không tiền tố như `parse_body`. */
export function parseCloseIn(body: unknown): { value: EscalationCloseIn } | { fields: string[] } {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return { fields: ["body"] };
  const b = body as Record<string, unknown>;
  const fields = Object.keys(b)
    .filter((k) => k !== "close_result" && k !== "note");
  if (!CLOSE_RESULTS.includes(b.close_result as EscalationCloseResult)) fields.push("close_result");
  const note = typeof b.note === "string" ? b.note.trim() : "";
  if (!note || note.length > CLOSE_NOTE_MAX) fields.push("note");
  return fields.length ? { fields } : { value: { close_result: b.close_result as EscalationCloseResult, note } };
}

/** Kết quả giả của `/close` cho ca `id` trên kho `store`. */
export function closeOutcome(store: EscalationStore, id: number, body: unknown, by: string, now = Date.now()): CloseOutcome {
  const parsed = parseCloseIn(body);
  if ("fields" in parsed) return { status: 422, body: { error: "invalid_request", fields: parsed.fields } };
  return store.close(id, parsed.value.close_result, parsed.value.note, by, now);
}

export const escalationCloseHandlers = [
  http.post("/api/escalations/:id/close", async ({ request, params }) => {
    const who = await requireAny(request, ["escalation:handle"]);
    if ("response" in who) return who.response;
    const id = Number(params.id);
    if (!Number.isSafeInteger(id)) return reply({ detail: "not_found" }, 404);
    const outcome = closeOutcome(escalationStore, id, await readJson(request), who.me.user_id);
    return reply(outcome.body, outcome.status);
  }),
];
