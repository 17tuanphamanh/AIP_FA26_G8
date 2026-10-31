import { http } from "msw";
import { CLOSE_NOTE_MAX, CLOSE_RESULTS } from "../../api/escalations.ts";
import type { EscalationCloseIn, EscalationCloseResult } from "../../api/types.ts";
import type { CloseOutcome, EscalationStore } from "../fixtures/escalations.ts";
import { escalationStore } from "./escalation-queue.ts";
import { readJson, reply, requireAny } from "./shared.ts";

// `POST /api/escalations/:id/close` — route CHƯA CÓ (be-tuan8; B20 §4.3, hợp đồng N-PA §4). Xoá file này khi be-tuan8 merge
// (và đổi `CLOSE_AVAILABLE` ở api/escalations.ts thành `true`). Đóng ca trên kho minh hoạ của escalation-queue.ts: 200 → ca
// rời danh sách mở; 409 `already_closed`; 404; 422 ca E5/E6 + `completed`; 422 thân sai.

/** Kiểm thân như backend (`extra="forbid"`): đúng 2 khoá; lỗi → danh sách trường kiểu `body.<khoá>`. */
export function parseCloseIn(body: unknown): { value: EscalationCloseIn } | { fields: string[] } {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return { fields: ["body"] };
  const b = body as Record<string, unknown>;
  const fields = Object.keys(b)
    .filter((k) => k !== "close_result" && k !== "note")
    .map((k) => `body.${k}`);
  if (!CLOSE_RESULTS.includes(b.close_result as EscalationCloseResult)) fields.push("body.close_result");
  const note = typeof b.note === "string" ? b.note.trim() : "";
  if (!note || note.length > CLOSE_NOTE_MAX) fields.push("body.note");
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
