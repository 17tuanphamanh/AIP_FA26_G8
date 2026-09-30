import { http, passthrough } from "msw";
import { NOTE_MAX } from "../../api/approvals.ts";
import type { ApprovalStatus } from "../../api/types.ts";
import { APPROVAL_DEMO_PREFIX, type ApprovalFixture, buildApprovalFixtures } from "../fixtures/approvals.ts";
import { invalid, readJson, reply, requireAny } from "./shared.ts";

// Hộp thư `GET /api/approvals?mine=1&status=…` (4c P5) và xem phiếu `GET /api/approvals/{id}` (4c P6) — route CHƯA CÓ.
// `POST /api/approvals/{id}/decision` ĐÃ CÓ THẬT: handler này chỉ chặn id tiền tố `apv-demo-` (id fixture, không bao giờ có
// ở backend); id khác → `passthrough()` tới backend thật — ngoại lệ duy nhất của checklist KH 8 #5 (12b Q-fe-5).
// Xoá file này khi 4c merge (gen:api) — decision khi đó đi thẳng backend cho mọi id.

const STATUSES: readonly ApprovalStatus[] = ["pending", "approved", "rejected", "timeout"];
const REASONS = ["missing_info", "not_authorized", "policy_violation", "duplicate", "wrong_device", "security_concern", "other"];
const DECISION_KEYS = new Set(["decision", "note", "reason_code", "view_started_at"]);
const LATE = "Yêu cầu đã chuyển sang bước khác"; // đúng câu 409 của backend/app/api/approvals.py

// Mốc giờ của fixture = lúc nạp trang (handler chạy trong trang) → ổn định trong một phiên trang.
const fixtures: ApprovalFixture[] = buildApprovalFixtures(Date.now());
// Quyết định 202 → phiếu đổi trạng thái (thay cho B16 chạy nền của backend) — chỉ trong bộ nhớ, mất khi tải lại trang.
const decided = new Map<string, ApprovalStatus>();

const find = (id: string) => fixtures.find((f) => f.item.approval_id === id);
const statusOf = (f: ApprovalFixture) => decided.get(f.item.approval_id) ?? f.item.status;

/** Kiểm thân như `DecisionIn` (extra="forbid"). Trả danh sách trường sai kiểu `body.<khoá>`. */
export function decisionFields(body: unknown): string[] {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return ["body"];
  const b = body as Record<string, unknown>;
  const fields = Object.keys(b).filter((k) => !DECISION_KEYS.has(k)).map((k) => `body.${k}`);
  if (b.decision !== "approved" && b.decision !== "rejected") fields.push("body.decision");
  if (b.note != null && (typeof b.note !== "string" || b.note.length > NOTE_MAX)) fields.push("body.note");
  if (b.reason_code != null && !REASONS.includes(b.reason_code as string)) fields.push("body.reason_code");
  if (b.view_started_at != null && (typeof b.view_started_at !== "string" || Number.isNaN(Date.parse(b.view_started_at)))) {
    fields.push("body.view_started_at");
  }
  return fields;
}

export const approvalHandlers = [
  http.get("/api/approvals", async ({ request }) => {
    const who = await requireAny(request, ["approval:decide"]);
    if ("response" in who) return who.response;
    const query = new URL(request.url).searchParams;
    if (query.get("mine") !== "1") return invalid(["query.mine"]); // 4c P5: mine bắt buộc = 1
    const status = query.get("status");
    if (status !== null && !STATUSES.includes(status as ApprovalStatus)) return invalid(["query.status"]);
    // Cố ý trả theo created_at GIẢM dần (mới nhất trước) — khác thứ tự hạn: giao diện phải tự sắp theo deadline (F4 P4).
    const items = fixtures
      .map((f) => ({ ...f.item, status: statusOf(f) }))
      .filter((item) => status === null || item.status === status)
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
      .slice(0, 50);
    return reply(items);
  }),

  http.get("/api/approvals/:id", async ({ request, params }) => {
    const who = await requireAny(request, ["approval:decide", "audit:read:all"]);
    if ("response" in who) return who.response;
    const fixture = find(String(params.id));
    if (!fixture) return reply({ detail: "not_found" }, 404); // không có / không giao cho tôi → CÙNG 404 (4c P6)
    if (fixture.view === "plan_changed") return reply({ detail: "plan_changed" }, 409); // không trả bản nào (G4-13)
    return reply({ ...fixture.view, status: statusOf(fixture) });
  }),

  http.post("/api/approvals/:id/decision", async ({ request, params }) => {
    const id = String(params.id);
    if (!id.startsWith(APPROVAL_DEMO_PREFIX)) return passthrough(); // route THẬT — không che (Q-fe-5)
    // Thứ tự như backend/app/api/approvals.py: quyền → 404 → hết bước (409) → thân (422) → 202.
    const who = await requireAny(request, ["approval:decide"]);
    if ("response" in who) return who.response;
    const fixture = find(id);
    if (!fixture) return reply({ detail: "not_found" }, 404);
    if (statusOf(fixture) !== "pending" || Date.now() >= Date.parse(fixture.item.deadline)) return reply({ detail: LATE }, 409);
    const body = await readJson(request);
    const fields = decisionFields(body);
    if (fields.length > 0) return invalid(fields);
    const b = body as { decision: "approved" | "rejected"; note?: string | null };
    if (b.decision === "rejected" && !b.note?.trim()) return reply({ detail: "rejected_requires_note" }, 422);
    decided.set(id, b.decision);
    return reply({ approval_id: id, ticket_id: fixture.item.ticket_id, status: "accepted", notices: [] }, 202);
  }),
];
