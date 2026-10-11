import { bypass, http } from "msw";
import { CLOSE_NOTE_MAX, QUEUE_LIMIT } from "../../api/escalations.ts";
import type { EscalationCloseIn, EscalationCloseResult, EscalationQueueItem } from "../../api/types.ts";
import { reply } from "./shared.ts";

// `POST /api/escalations/:id/close` — route CHƯA CÓ (Phase 7, T31; B20 §4.3, P10 §3.4). Xoá file này khi T31 merge.
// KHÔNG giả `GET /api/escalations/{id}` (12b Q-fe-6) và KHÔNG sửa hàng đợi thật: 202 ở đây không xoá ca nào.
// Ca có còn mở không / có phải ca deny không: đọc từ hàng đợi THẬT (`bypass`, cùng token của người đang đăng nhập) —
// không có bảng id giả nào.

const RESULTS: readonly EscalationCloseResult[] = ["completed", "confirmed_denial", "reopened_as_new"];

type Outcome = { status: number; body: unknown };

/** Kiểm thân như backend (`extra="forbid"`): đúng 2 khoá; lỗi → danh sách trường kiểu `body.<khoá>`. */
export function parseCloseIn(body: unknown): { value: EscalationCloseIn } | { fields: string[] } {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return { fields: ["body"] };
  const b = body as Record<string, unknown>;
  const fields = Object.keys(b)
    .filter((k) => k !== "close_result" && k !== "note")
    .map((k) => `body.${k}`);
  if (!RESULTS.includes(b.close_result as EscalationCloseResult)) fields.push("body.close_result");
  const note = typeof b.note === "string" ? b.note.trim() : "";
  if (!note || note.length > CLOSE_NOTE_MAX) fields.push("body.note");
  return fields.length ? { fields } : { value: { close_result: b.close_result as EscalationCloseResult, note } };
}

/** Kết quả giả của `/close` cho ca `item` (undefined = không còn trong hàng đợi mở). */
export function closeOutcome(body: unknown, item: EscalationQueueItem | undefined): Outcome {
  const parsed = parseCloseIn(body);
  if ("fields" in parsed) return { status: 422, body: { error: "invalid_request", fields: parsed.fields } };
  if (!item) return { status: 404, body: { detail: "escalation_not_found" } };
  if (parsed.value.close_result === "completed" && item.is_deny_case) {
    return { status: 422, body: { detail: "deny_case_cannot_complete" } };
  }
  return { status: 202, body: { escalation_id: item.escalation_id, close_result: parsed.value.close_result, status: "accepted" } };
}

export const escalationCloseHandlers = [
  http.post("/api/escalations/:id/close", async ({ request, params }) => {
    let body: unknown = null;
    try {
      body = await request.clone().json();
    } catch {
      // thân không phải JSON → 422 ở closeOutcome
    }
    const headers = new Headers();
    const authorization = request.headers.get("Authorization");
    if (authorization) headers.set("Authorization", authorization);
    const queueUrl = new URL(`/api/escalations/queue?limit=${QUEUE_LIMIT}`, request.url);
    const queue = await fetch(bypass(new Request(queueUrl, { headers })));
    if (!queue.ok) {
      // 401 (token hết hạn) → client tự refresh rồi gửi lại; 403 → không có quyền escalation:handle.
      return reply(await queue.json().catch(() => null), queue.status);
    }
    const items = (await queue.json()) as EscalationQueueItem[];
    const id = Number(params.id);
    const outcome = closeOutcome(body, items.find((i) => i.escalation_id === id));
    return reply(outcome.body as Record<string, unknown>, outcome.status);
  }),
];
