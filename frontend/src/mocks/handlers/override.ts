import { http } from "msw";
import { NOTE_MAX } from "../../api/approvals.ts";
import { DEMO_TICKETS, TICKET_DEMO_PREFIX } from "../fixtures/approvals.ts";
import { invalid, readJson, realFetch, reply, requireAny } from "./shared.ts";

// `POST /api/tickets/{id}/override` (4d P1–P4) — route CHƯA CÓ. Ghi đè không đổi ticket, chỉ ghi nhật ký → ở đây chỉ nhớ
// "ai đã ghi đè ticket nào" trong bộ nhớ trang (lần 2 → 409 already_overridden). Thứ tự như 4d P1: quyền → reauth → 404
// → 409 ticket_open → 422 thân → 422 same_as_original → 409 already_overridden → 201.
// - `tkt-demo-*`: kết quả cố định theo mã (fixtures/approvals.ts DEMO_TICKETS).
// - Mã khác: đọc ticket THẬT (`GET /api/tickets/{id}` qua bypass, cùng token) → 404 / 409 ticket_open / 201.
// Xoá file này khi 4d merge (gen:api).

const DECISIONS = ["AUTO", "HITL", "L2", "ANSWER"];
const REASONS = ["too_risky_for_auto", "approval_unnecessary", "should_not_escalate", "wrong_answer", "policy_gap", "other"];
const KEYS = new Set(["override_decision", "reason_code", "note"]);

/** Kiểm thân như `OverrideIn` (extra="forbid"; note ≤ 1000, bắt buộc khi reason_code="other"). */
export function overrideFields(body: unknown): string[] {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return ["body"];
  const b = body as Record<string, unknown>;
  const fields = Object.keys(b).filter((k) => !KEYS.has(k)).map((k) => `body.${k}`);
  if (!DECISIONS.includes(b.override_decision as string)) fields.push("body.override_decision");
  if (!REASONS.includes(b.reason_code as string)) fields.push("body.reason_code");
  const note = b.note;
  if (note != null && (typeof note !== "string" || note.length > NOTE_MAX)) fields.push("body.note");
  else if (b.reason_code === "other" && !(typeof note === "string" && note.trim())) fields.push("body.note");
  return fields;
}

let reauthAsked = false; // `tkt-demo-reauth`: chỉ lần gọi ĐẦU mỗi phiên trang bị đòi đăng nhập lại
const recorded = new Set<string>(); // `${user_id}:${ticket_id}` đã ghi đè (idempotency 4d P4)

export const overrideHandlers = [
  http.post("/api/tickets/:id/override", async ({ request, params }) => {
    const ticketId = String(params.id);
    const who = await requireAny(request, ["decision:override"]);
    if ("response" in who) return who.response;
    const demo = DEMO_TICKETS[ticketId];
    if (demo?.reauthFirst && !reauthAsked) {
      reauthAsked = true;
      return reply({ detail: "reauth_required" }, 403);
    }
    let original: string | null = null;
    if (ticketId.startsWith(TICKET_DEMO_PREFIX)) {
      if (!demo) return reply({ detail: "not_found" }, 404);
      if (demo.kind === "open") return reply({ detail: "ticket_open" }, 409);
      original = demo.original;
    } else {
      const res = await realFetch(request, `/api/tickets/${encodeURIComponent(ticketId)}`);
      if (!res.ok) return reply(await res.json().catch(() => null), res.status); // 404 thật; 401 → client refresh
      const view = (await res.json()) as { final_state?: string | null };
      if (!view.final_state) return reply({ detail: "ticket_open" }, 409);
    }
    const body = await readJson(request);
    const fields = overrideFields(body);
    if (fields.length > 0) return invalid(fields);
    const choice = (body as { override_decision: string }).override_decision;
    if (demo?.kind === "same" || choice === original) return reply({ detail: "same_as_original" }, 422);
    const key = `${who.me.user_id}:${ticketId}`;
    if (recorded.has(key)) return reply({ detail: "already_overridden" }, 409);
    recorded.add(key);
    return reply({ ticket_id: ticketId, override_decision: choice, status: "recorded" }, 201);
  }),
];
