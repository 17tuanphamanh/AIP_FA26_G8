import { http, passthrough } from "msw";
import { NOTE_MAX } from "../../api/approvals.ts";
import { DEMO_TICKETS, TICKET_DEMO_PREFIX } from "../fixtures/approvals.ts";
import { invalid, readJson, reply, requireAny } from "./shared.ts";

// `POST /api/tickets/{id}/override` — route THẬT (4d `e510a6e`, backend/app/api/tickets.py). Handler CHỈ chặn id có tiền
// tố ticket minh hoạ (fixtures/approvals.ts DEMO_TICKETS); id khác → `passthrough()` NGAY, không gọi gì (kể cả `/me`) — mock
// không che route thật, không bao giờ báo "đã ghi" cho ticket thật (N4d P7). Ghi đè không đổi ticket, chỉ ghi nhật ký → ở
// đây chỉ nhớ "ai đã ghi đè ticket nào" trong bộ nhớ trang. Thứ tự kiểm theo CODE `e510a6e` (PLAN-fe mục 7 #36): quyền 403
// → reauth 403 → 404 → 409 ticket_open → 422 thân → 422 `other` thiếu ghi chú → 422 same_as_original → [guard] 422 `other`
// mà ghi chú rỗng sau khi che → 409 already_overridden → 201. Không giả: 403 người gửi tự ghi đè, 503 guard.
// Xoá file này khi không còn cần minh hoạ.

const DECISIONS = ["AUTO", "HITL", "L2", "ANSWER"];
const REASONS = ["too_risky_for_auto", "approval_unnecessary", "should_not_escalate", "wrong_answer", "policy_gap", "other"];
const KEYS = new Set(["override_decision", "reason_code", "note"]);
const EXTRA_KEY = "<extra>"; // backend/app/api/errors.py: tên khoá thừa có thể là bí mật → không trả lại

/**
 * Kiểm thân như `parse_body(OverrideIn)` (extra="forbid", note ≤ 1000). Vị trí trường KHÔNG có tiền tố `body.` (route
 * gọi `model_validate` trên dict); khoá thừa → `<extra>`; JSON hỏng → `[]`; thân không phải object → `[""]`.
 * null = thân hợp lệ.
 */
export function overrideFields(body: unknown): string[] | null {
  if (body === undefined) return [];
  if (body === null || typeof body !== "object" || Array.isArray(body)) return [""];
  const b = body as Record<string, unknown>;
  const fields: string[] = [];
  if (!DECISIONS.includes(b.override_decision as string)) fields.push("override_decision");
  if (!REASONS.includes(b.reason_code as string)) fields.push("reason_code");
  if (b.note != null && (typeof b.note !== "string" || b.note.length > NOTE_MAX)) fields.push("note");
  if (Object.keys(b).some((k) => !KEYS.has(k))) fields.push(EXTRA_KEY);
  return fields.length > 0 ? fields : null;
}

/** Như privacy guard (backend/app/guard/normalize.py): xoá ký tự loại `Cf` (zero-width, soft hyphen, word joiner…). */
const visible = (text: string) => text.replace(/\p{Cf}/gu, "").trim();

let reauthAsked = false; // `tkt-demo-reauth`: chỉ lần gọi ĐẦU mỗi phiên trang bị đòi đăng nhập lại
const recorded = new Set<string>(); // `${user_id}:${ticket_id}` đã ghi đè (mỗi người một lần / ticket)

export const overrideHandlers = [
  http.post("/api/tickets/:id/override", async ({ request, params }) => {
    const ticketId = String(params.id);
    if (!ticketId.startsWith(TICKET_DEMO_PREFIX)) return passthrough(); // ticket thật — route thật quyết (N4d P7)
    const who = await requireAny(request, ["decision:override"]);
    if ("response" in who) return who.response;
    const demo = DEMO_TICKETS[ticketId];
    if (demo?.reauthFirst && !reauthAsked) {
      reauthAsked = true;
      return reply({ detail: "reauth_required" }, 403);
    }
    if (!demo) return reply({ detail: "not_found" }, 404);
    if (demo.kind === "open") return reply({ detail: "ticket_open" }, 409);
    const body = await readJson(request);
    const fields = overrideFields(body);
    if (fields !== null) return invalid(fields);
    const { override_decision: choice, reason_code: reason, note } = body as { override_decision: string; reason_code: string; note?: string | null };
    const text = note ?? "";
    if (reason === "other" && !text.trim()) return invalid(["note"]);
    if (demo.kind === "same" || choice === demo.original) return reply({ detail: "same_as_original" }, 422);
    if (reason === "other" && !visible(text)) return invalid(["note"]); // che xong rỗng
    const key = `${who.me.user_id}:${ticketId}`;
    if (recorded.has(key)) return reply({ detail: "already_overridden" }, 409);
    recorded.add(key);
    return reply(
      { ticket_id: ticketId, original_decision: demo.original, override_decision: choice, reason_code: reason, notices: demo.notices },
      201,
    );
  }),
];
