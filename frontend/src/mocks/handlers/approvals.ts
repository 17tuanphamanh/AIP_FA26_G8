import { HttpResponse, http, passthrough } from "msw";
import { NOTE_MAX } from "../../api/approvals.ts";
import type { ApprovalListItem, ApprovalStatus } from "../../api/types.ts";
import { APPROVAL_DEMO_PREFIX, type ApprovalFixture, buildApprovalFixtures } from "../fixtures/approvals.ts";
import { invalid, readJson, realFetch, reply, requireAny } from "./shared.ts";

// Route duyệt ĐỀU ĐÃ CÓ THẬT (backend/app/api/approvals.py, 4c `b457e6e`). Nguyên tắc: mock KHÔNG được che API thật.
// - Hộp thư `GET /api/approvals`: LUÔN gọi backend thật trước (nguyên URL + query, cùng token — `realFetch`), handler không
//   tự kiểm query hay quyền. Thật không 2xx (401, 403, 422 `query.mine`/`query.status`, 5xx…) → trả NGUYÊN response thật;
//   thật 2xx mà thân không phải `{items: mảng}` → trả nguyên thân (client tự báo lỗi). Chỉ khi thật hợp lệ mới gộp phiếu
//   minh hoạ (lọc theo `status` của query; không có → mọi trạng thái); header `Date` LẤY TỪ response thật (đồng hồ đếm hạn
//   dùng giờ máy chủ). Lỗi mạng (fetch ném) → 503 `backend_unreachable` — không bao giờ trả riêng dữ liệu minh hoạ.
// - Xem phiếu `GET /api/approvals/{id}` và `POST …/decision`: CHỈ chặn id tiền tố `apv-demo-` (không bao giờ có ở backend);
//   id khác → `passthrough()` tới backend thật (12b Q-fe-5, N4c P6b).
// Xoá file này khi không còn cần phiếu minh hoạ (route có response_model → gen:api).

const REASONS = ["missing_info", "not_authorized", "policy_violation", "duplicate", "wrong_device", "security_concern", "other"];
const DECISION_KEYS = new Set(["decision", "note", "reason_code", "view_started_at"]);
const LATE = "Yêu cầu đã chuyển sang bước khác"; // đúng câu 409 của backend/app/api/approvals.py
// Header không chép sang response trả lại: thân đã được đọc thành chữ (đã giải nén, độ dài có thể khác).
const DROPPED_HEADERS = ["content-encoding", "content-length", "transfer-encoding"];

// Mốc giờ của fixture = lúc nạp trang (handler chạy trong trang) → ổn định trong một phiên trang.
const fixtures: ApprovalFixture[] = buildApprovalFixtures(Date.now());
// Quyết định 202 → phiếu đổi trạng thái (thay cho B16 chạy nền của backend) — chỉ trong bộ nhớ, mất khi tải lại trang.
const decided = new Map<string, ApprovalStatus>();

const find = (id: string) => fixtures.find((f) => f.approval_id === id);
const statusOf = (f: ApprovalFixture) => decided.get(f.approval_id) ?? f.status;

/** Phiếu minh hoạ của hộp thư (chỉ phiếu có dòng hộp thư), lọc theo trạng thái; created_at giảm dần như server. */
function demoInbox(status: string | null): ApprovalListItem[] {
  return fixtures
    .flatMap((f) => (f.item ? [{ ...f.item, status: statusOf(f) }] : []))
    .filter((item) => status === null || item.status === status)
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}

/** Trả lại NGUYÊN response thật (mã, thân, header) — sau khi đã đọc thân thành chữ. */
function asReal(res: Response, text: string): HttpResponse<string> {
  const headers = new Headers(res.headers);
  for (const name of DROPPED_HEADERS) headers.delete(name);
  return new HttpResponse(text === "" ? null : text, { status: res.status, statusText: res.statusText, headers });
}

const isInboxBody = (body: unknown): body is { items: unknown[] } =>
  body !== null && typeof body === "object" && !Array.isArray(body) && Array.isArray((body as { items?: unknown }).items);

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
    const url = new URL(request.url);
    let res: Response;
    let text: string;
    try {
      res = await realFetch(request, `${url.pathname}${url.search}`);
      text = await res.text();
    } catch {
      return reply({ detail: "backend_unreachable" }, 503); // backend tắt: KHÔNG trả riêng minh hoạ
    }
    if (!res.ok) return asReal(res, text); // 401 / 403 / 422 / 5xx của thật — nguyên vẹn
    let body: unknown;
    try {
      body = JSON.parse(text);
    } catch {
      return asReal(res, text);
    }
    if (!isInboxBody(body)) return asReal(res, text); // thân sai dạng → để client báo lỗi (api/approvals.ts parseInbox)
    const headers = new Headers({ "Content-Type": "application/json" });
    const date = res.headers.get("Date");
    if (date) headers.set("Date", date);
    return HttpResponse.json({ items: [...body.items, ...demoInbox(url.searchParams.get("status"))] }, { status: res.status, headers });
  }),

  http.get("/api/approvals/:id", async ({ request, params }) => {
    const id = String(params.id);
    if (!id.startsWith(APPROVAL_DEMO_PREFIX)) return passthrough(); // phiếu thật — không che (N4c P6b)
    const who = await requireAny(request, ["approval:decide"]); // như `require("approval:decide")` của route xem phiếu
    if ("response" in who) return who.response;
    const fixture = find(id);
    if (!fixture) return reply({ detail: "not_found" }, 404); // không có / không giao cho tôi → CÙNG 404 (4c P6)
    if (fixture.view === "plan_changed") return reply({ detail: "plan_changed" }, 409); // không trả bản nào (G4-13)
    return reply({ ...fixture.view, status: statusOf(fixture) });
  }),

  http.post("/api/approvals/:id/decision", async ({ request, params }) => {
    const id = String(params.id);
    if (!id.startsWith(APPROVAL_DEMO_PREFIX)) return passthrough(); // route THẬT — không che (Q-fe-5)
    // Thứ tự như backend/app/api/approvals.py: quyền → 404 → vai trò (403) → hết bước (409) → thân (422) → 202.
    const who = await requireAny(request, ["approval:decide"]);
    if ("response" in who) return who.response;
    const fixture = find(id);
    if (!fixture) return reply({ detail: "not_found" }, 404);
    if (fixture.role_as === "viewer") return reply({ detail: "forbidden" }, 403); // `approval_role` None → 403
    if (statusOf(fixture) !== "pending" || Date.now() >= Date.parse(fixture.deadline)) return reply({ detail: LATE }, 409);
    const body = await readJson(request);
    const fields = decisionFields(body);
    if (fields.length > 0) return invalid(fields);
    const b = body as { decision: "approved" | "rejected"; note?: string | null };
    if (b.decision === "rejected" && !b.note?.trim()) return reply({ detail: "rejected_requires_note" }, 422);
    decided.set(id, b.decision);
    return reply(
      { approval_id: id, ticket_id: fixture.ticket_id, status: "accepted", notices: [], decided_as: fixture.role_as },
      202,
    );
  }),
];
