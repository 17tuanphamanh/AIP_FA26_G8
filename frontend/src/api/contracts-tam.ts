// Kiểu VIẾT TAY (KH mục 3.2): route chưa có ở backend, route trả `dict` nên openapi không sinh được kiểu, hoặc route mới
// có mà kiểu sinh chưa thành nguồn (M9 A3 — soi hai chiều ở schema.check.ts).
// Mỗi kiểu 2 dòng: `Nguồn:` (file code hoặc mục spec) và `Xoá khi:`. Route CHƯA CÓ = phỏng đoán theo spec,
// chấp nhận sửa khi backend ra. Component KHÔNG import file này — chỉ import `./types.ts`.

// ---------------------------------------------------------------- Route đã có, trả dict (Nợ API #3)

// Nguồn: backend/app/api/auth.py me() — trả dict, openapi không có schema.
// Xoá khi: route có response_model (KH Nợ API #3) → dùng kiểu của schema.gen.ts.
export type Me = { user_id: string; role: "employee" | "l1" | "manager" | "l2"; permissions: string[] };

// Nguồn: backend/app/api/auth.py _token_body() — body của login và refresh, trả dict.
// Xoá khi: route có response_model (KH Nợ API #3).
export type TokenOut = { access_token: string; token_type: "bearer"; expires_in: number; csrf_token: string };

// Nguồn: backend/app/api/tickets.py Accepted — 202 của POST tickets / messages / confirm (JSONResponse, không vào openapi).
// Xoá khi: route khai response_model cho 202.
export type Accepted = { ticket_id: string; status: string; notices: string[] };

// Nguồn: backend/app/domain/messages.py source_of() — đúng 3 khoá, không đoạn trích (P9).
// Xoá khi: TicketView khai kiểu cho conversation (KH Nợ API #3).
export type Source = { chunk_id: string; title: string; heading_path: string };

// Nguồn: domain/messages.py (answer, question, result), graph/nodes/b20_audit.py (escalation); 4c thêm rejection.
// `kind` lạ → hiện `text` như tin thường, không lỗi (12b Q-fe-2); `digest` (tin tổng hợp nhiều ý) — Đề xuất F6, kiểu
// `DigestConversationItem` ở khối route CHƯA CÓ. Xoá khi: TicketView khai kiểu conversation.
export type ConversationItem =
  | { role: "user"; text: string }
  | DigestConversationItem
  | {
      role: "assistant";
      kind: "answer" | "question" | "result" | "escalation" | "rejection" | (string & {});
      text: string;
      ref?: string | null;
      needs?: string;
      sources?: Source[];
    };

// Nguồn: backend/app/api/tickets.py TicketView (response_model) — `conversation` là list[dict] nên phần tử để `unknown`,
// component tự kiểm dạng (components/Conversation.tsx). Xoá khi: `npm run gen:api` chạy được (12b Q-fe-1) → dùng
// kiểu của schema.gen.ts (conversation vẫn phải kiểm dạng).
// `children_progress`: CHƯA CÓ ở backend — Đề xuất F6 cho T20 (kiểu `ChildProgress` dưới); thiếu/null = ticket thường.
// Giao diện vẫn kiểm dạng từng phần tử (routes/employee/multi.ts `normalizeProgress`).
export type TicketView = {
  ticket_id: string;
  status: string;
  waiting_for: "clarify" | "approval" | "confirm" | "reply" | null;
  conversation: unknown[];
  exit_code: string | null;
  close_reason: string | null;
  final_state: string | null;
  created_at: string;
  closed_at: string | null;
  children_progress?: ChildProgress[] | null;
};

// Nguồn: backend/app/api/tickets.py ConfirmIn (extra="forbid", note ≤ 1000). Xoá khi: route khai body trong openapi.
export type ConfirmIn = { confirmed: boolean; note?: string };

// Nguồn: backend/app/audit/handoff.py HandoffNote (ghi chú bàn giao 4 phần, B20 mục 4.2).
// Xoá khi: escalations/queue có response_model.
export type HandoffNote = { request: string; done_so_far: string; why_escalated: string; next_for_l2: string };

// Nguồn: backend/app/db/escalations.py QueueItem + api/escalations.py (asdict, created_at ISO) — trả list[dict].
// Xoá khi: route có response_model (KH Nợ API #3).
export type EscalationQueueItem = {
  escalation_id: number;
  ticket_id: string;
  exit_code: string;
  priority: number;
  label: string;
  reason_detail: string | null;
  is_deny_case: boolean;
  handoff_note: HandoffNote;
  assigned_to: string | null;
  created_at: string;
};

// Nguồn: B20-audit-escalate-L2.md §4.3 (`close_result`) + P10 §3.4 — `POST /api/escalations/{id}/close` CHƯA CÓ (Phase 7, T31).
// Body phỏng đoán: đúng 2 khoá; ghi chú bắt buộc (≤ 1000 như ghi chú confirm). Ca deny + `completed` → 422
// `deny_case_cannot_complete`. Xoá khi: T31 merge → gen:api (xoá cùng mocks/handlers/escalation-close.ts).
export type EscalationCloseResult = "completed" | "confirmed_denial" | "reopened_as_new";
export type EscalationCloseIn = { close_result: EscalationCloseResult; note: string };

// Nguồn: backend/app/api/approvals.py ReasonCode — danh sách cố định (PLAN-3e Q-3e-13).
// Xoá khi: route khai body trong openapi.
export type ReasonCode =
  | "missing_info"
  | "not_authorized"
  | "policy_violation"
  | "duplicate"
  | "wrong_device"
  | "security_concern"
  | "other";

// Nguồn: backend/app/api/approvals.py DecisionIn — body tự kiểm (parse_body) nên không vào openapi; `rejected` bắt buộc note.
// Xoá khi: route khai body trong openapi.
export type DecisionIn = {
  decision: "approved" | "rejected";
  note?: string;
  reason_code?: ReasonCode;
  view_started_at?: string;
};

// Nguồn: backend/app/api/approvals.py @b457e6e decide() dòng 222–223 — JSONResponse 202; `decided_as` (4c P4) chỉ để log,
// giao diện không hiện; khai tuỳ chọn để backend cũ (thiếu khoá) vẫn đúng kiểu. Xoá khi: route khai response_model (nợ API #3).
export type DecisionAccepted = {
  approval_id: string;
  ticket_id: string;
  status: "accepted";
  notices: string[];
  decided_as?: "primary" | "backup";
};

// Nguồn: backend/app/api/approvals.py @b457e6e (InboxItem dòng 85–97, ApprovalView 110–124).
// Xoá khi: route có response_model (nợ API #3).
// Hộp thư `GET /api/approvals?mine=1[&status=…]` → `{items: [...]}` (KHÔNG phải mảng trần), ≤ 50 mục, server sắp
// created_at giảm dần. `status` là cột `approvals.status`; `action_type` / `device_id` null khi dòng audit B15 không có
// (B15 giả) hoặc đích không phải "device:…".
export type ApprovalStatus = "pending" | "approved" | "rejected" | "timeout";
export type ApprovalListItem = {
  approval_id: string;
  ticket_id: string;
  status: ApprovalStatus;
  created_at: string;
  deadline: string;
  reminder_1_at: string | null;
  reminder_2_at: string | null;
  role_as: "primary" | "backup";
  action_type: string | null;
  device_id: string | null;
};
export type InboxResponse = { items: ApprovalListItem[] };

// Xem phiếu `GET /api/approvals/{id}`: 404 `not_found` (không có / không giao cho tôi — cùng một 404), 409 `plan_changed`
// (không trả object nào). Không có created_at → lấy từ hộp thư; giờ máy chủ từ header `Date` (KH 1.3 #5). `risk`
// (RiskDecision) hiện khoá–giá trị chung, KHÔNG đọc tên trường. `procedure` null khi action_type không có trong
// action_metadata; `title` null khi không tìm thấy tài liệu ở bản KB hiện hành. `viewer` = người có `audit:read:all` xem
// phiếu không giao cho mình (không quyết được, không ghi lần xem đầu).
export type ApprovalRoleAs = "primary" | "backup" | "viewer";
export type ApprovalViewP4 = {
  approval_id: string;
  ticket_id: string;
  status: ApprovalStatus;
  deadline: string;
  requester: { role: string; department: string | null };
  request_summary: string;
  action: Record<string, unknown>;
  action_plan_hash: string;
  risk: Record<string, unknown> | null;
  facts: Record<string, unknown>;
  role_as: ApprovalRoleAs;
  procedure: { doc_id: string; title: string | null } | null;
};

// Nguồn: backend/app/api/health.py health() — JSONResponse; 200 "ok" / 503 "degraded"; `runtime` chỉ để báo.
// Xoá khi: route có response_model.
export type Health = {
  status: "ok" | "degraded";
  checks: Record<string, string>;
  failed: string[];
  runtime: "up" | "down";
  kb: { alias: string; collection: string | null; status: "ready" | "missing" | "unknown" };
};

// Ghi đè `POST /api/tickets/{id}/override` (4d) — ghi một dòng audit OVERRIDE, KHÔNG đổi ticket. Thứ tự lỗi (code): 403
// `forbidden` (không quyền) → 403 `reauth_required` (đăng nhập > 10 phút) → 404 `not_found` → 403 `forbidden` (người gửi tự
// ghi đè — cùng mã, không phân biệt được) → 409 `ticket_open` → 422 `{error:"invalid_request", fields}` (tên trường KHÔNG có
// tiền tố `body.`) → 422 `same_as_original` → 503 `privacy_guard_unavailable` → 422 `fields:["note"]` (`other` mà ghi chú
// rỗng sau khi che) → 409 `already_overridden` (mỗi người một lần / ticket).

// Nguồn: backend/app/api/tickets.py @e510a6e (`Decision` ở domain/override.py). Xoá khi: route có response_model (nợ API #3).
export type OverrideDecision = "AUTO" | "HITL" | "L2" | "ANSWER";

// Nguồn: backend/app/api/tickets.py @e510a6e (`OverrideReason` ở domain/override.py). Xoá khi: route có response_model (nợ API #3).
export type OverrideReasonCode =
  | "too_risky_for_auto"
  | "approval_unnecessary"
  | "should_not_escalate"
  | "wrong_answer"
  | "policy_gap"
  | "other";

// Nguồn: backend/app/api/tickets.py @e510a6e `OverrideIn` (extra="forbid"; `note` ≤ 1000, bắt buộc khi reason_code="other").
// Xoá khi: route có response_model (nợ API #3).
export type OverrideIn = { override_decision: OverrideDecision; reason_code: OverrideReasonCode; note?: string };

// Nguồn: backend/app/api/tickets.py @e510a6e override() — JSONResponse 201; `original_decision` do SERVER suy từ audit;
// `notices` = thông báo của privacy guard khi ghi chú có bí mật bị che (giao diện chỉ hiện câu chung).
// Xoá khi: route có response_model (nợ API #3).
export type OverrideRecorded = {
  ticket_id: string;
  original_decision: OverrideDecision;
  override_decision: OverrideDecision;
  reason_code: OverrideReasonCode;
  notices: string[];
};

// ---------------------------------------------------------------- Route ĐÃ CÓ — M9 A3 (viết tay tới khi gen:api)

// ĐÃ CHỐT theo M9 A3 3f15afb: backend/app/api/alerts.py (`AlertView` đúng 12 khoá, `AlertList`), api/dashboard.py
// (`BusinessAll` + `BusinessAllMetrics`, `AiDashboard` + `AiMetrics`: model `extra="forbid"`, mọi khoá luôn có mặt, giá trị
// `T | None`), monitor/queries/{business,ai}.py (WeightedRate, RuleCount, E1Split, E3Case, E3Cases, DayCost). Thời gian là
// chuỗi ISO 8601 có múi giờ (`from`/`to` trả ở UTC). Kiểu viết tay ở đây được soi hai chiều với openapi ở
// src/api/schema.check.ts (N-A3 PHẦN 2). Nhánh `scope: "own"` (L1) chưa dùng — để chặng màn L1.
// Xoá khi: gen:api thành nguồn kiểu cho 4 route này (dùng thẳng `components["schemas"]`).
export type AlertAudience = "manager" | "dev" | "ops";
export type AlertItem = {
  alert_id: number;
  rule_id: string;
  subject: string;
  severity: string;
  value: number | null;
  window_start: string;
  status: "open" | "acked";
  detail: Record<string, unknown>;
  audience: AlertAudience[];
  acked_by: string | null;
  acked_at: string | null;
  created_at: string;
};
/** `truncated`: còn cảnh báo ngoài `limit` (mặc định 200) — không phân trang, giao diện hiện băng. */
export type AlertList = { items: AlertItem[]; truncated: boolean };

/** `by_group` khoá "routine" | "approval" | "sensitive" (nhóm 0 lá → null); `sensitivity` khoá "60/30/10", "80/15/5". */
export type WeightedRate = {
  raw: number | null;
  weighted: number | null;
  by_group: Record<string, number | null>;
  sensitivity: Record<string, number | null>;
};
export type RuleCount = { rule_id: string; count: number };
/** `counts`: 4 lý do E1 + "other"; `shares` = count / total (total 0 → null). */
export type E1Split = { total: number; counts: Record<string, number>; shares: Record<string, number | null> };
export type E3Case = { ticket_id: string; intent: string | null; created_at: string; kb_version: string | null; request_excerpt: string };
/** `truncated`: còn ca ngoài trần 100 ca mới nhất. */
export type E3Cases = { items: E3Case[]; truncated: boolean };
export type BusinessMetrics = {
  automation_rate: number | null;
  escalation_rate_raw: number | null;
  escalation_rate_weighted: WeightedRate | null;
  deflection_rate: number | null;
  approval_expired_count: number | null;
  decided_by_distribution: Record<string, number> | null;
  top_matched_rules: RuleCount[] | null;
  override_count: number | null;
  e1_split: E1Split | null;
  e3_cases: E3Cases | null;
};
export type BusinessDashboard = { from: string; to: string; unavailable: string[]; scope: "all"; metrics: BusinessMetrics };

/** `day_start` = 00:00 giờ VN của ngày, viết ở UTC (vd "2026-09-29T17:00:00Z" là ngày 30/09). */
export type DayCost = { day_start: string; cost_usd: number };
export type AiMetrics = {
  tokens_per_ticket: number | null;
  cost_per_day: DayCost[] | null;
  latency_p95_by_step: Record<string, number> | null;
  cache_hit_rate: number | null;
  json_invalid_first_try_rate: number | null;
  fallback_rate: number | null;
  e2_llm_count: number | null;
  e9_count: number | null;
  b2_llm_rate: number | null;
  intent_filter_fallback_rate: number | null;
  b3_llm_rate: number | null;
  intent_model_version: string | null;
  multi_intent_first_stop_to_reply_s: number | null;
  multi_intent_messages_per_turn: number | null;
};
export type AiDashboard = { from: string; to: string; unavailable: string[]; metrics: AiMetrics };

// ---------------------------------------------------------------- Route CHƯA CÓ (MSW)

// Yêu cầu nhiều ý (D-31) — Phase 5, T20. Toàn bộ khối này là [Đề xuất F6 — chốt ở T20]; hình dạng đầy đủ + chỗ
// [Suy luận]: PLAN-fe mục 8 "Đề xuất hợp đồng cho T20". MSW: mocks/handlers/employee-multi.ts (chỉ id ticket nhiều ý minh hoạ).

// Nguồn: P1 §8.2–8.3 (khung tiến độ từng ý, không phải tin nhắn) + P10 §3.1 (`GET /api/tickets/{cha}` trả
// `children_progress`) — Đề xuất F6. `title` = nhãn ngắn của ý do server đặt [Suy luận]; `outcome` chỉ khi `closed`.
// Xoá khi: T20 merge (gen:api) — xoá cùng mocks/handlers/employee-multi.ts, mocks/fixtures/multi.ts.
export type ChildProgressState = "processing" | "pending_approval" | "ready" | "needs_user" | "closed";
export type ChildOutcome = "resolved" | "escalated" | "rejected" | "blocked";
export type ChildProgress = {
  child_id: string;
  index: number;
  title: string;
  progress: ChildProgressState;
  outcome: ChildOutcome | null;
};

// Nguồn: P1 §8.2 `compose_digest` (một tin / lượt, mỗi ý một khối "Ý n – …") + B03-B05 §5.4.1 (`needs` của notice) —
// Đề xuất F6. `kind` theo notice của con: B10/B18 → result, B11 → question, B16 → rejection, B20 → escalation.
// `options` (gợi ý trả lời, vd mã máy) [Suy luận]. `text` của tin = bản chữ thuần (dự phòng / kênh khác).
// Xoá khi: T20 merge (gen:api).
export type DigestItemKind = "result" | "question" | "rejection" | "escalation";
export type DigestNeeds = "confirm" | "answer" | "none";
export type DigestItem = {
  child_id: string;
  index: number;
  title: string;
  kind: DigestItemKind;
  text: string;
  needs: DigestNeeds;
  options?: string[];
  sources?: Source[];
};
export type DigestConversationItem = { role: "assistant"; kind: "digest"; round: number; text: string; items: DigestItem[] };

// Nguồn: B19 §4 `ParentReplyIn` (khoá = child_ticket_id; `ConfirmIn | ClarifyAnswerIn`) + P1 §8.2 (mọi ý trong
// `awaiting` phải có mặt, thiếu → 422) — Đề xuất F6: `{answer}` cho câu hỏi, `{confirmed, note?}` cho xác nhận (không gửi
// `satisfaction` — "Có thể"). 202 = `Accepted`; 422 `fields: ["body.items.<child_id>…"]`; 409 trả muộn [Chốt 8.3].
// Xoá khi: T20 merge (gen:api).
export type ParentReplyItem = { answer: string } | { confirmed: boolean; note?: string };
export type ParentReplyIn = { items: Record<string, ParentReplyItem> };

// Nguồn: [Đề xuất F5 — chốt lại khi làm Phase 7] (Q-fe-26; PLAN-fe mục 7 #20, nợ API #11). P10 §3.3 chỉ có TÊN route;
// tên trường bám cột bảng `policy_versions` (backend/app/db/models.py `PolicyVersion`: `version` String(16),
// `policy_json` → `content`, `updated_by`, `updated_at`, `is_current`). Quay lui = TẠO phiên bản mới (append-only,
// `restored_from` = version bản gốc). Xoá khi: Phase 7 có route (gen:api) — xoá cùng mocks/handlers/policy.ts.
export type PolicyView = {
  version_id: number;
  version: string;
  content: Record<string, unknown>;
  updated_by: string | null;
  updated_at: string;
  is_current: boolean;
};
export type PolicyVersionItem = {
  version_id: number;
  version: string;
  updated_by: string | null;
  updated_at: string;
  is_current: boolean;
  restored_from?: string | null;
};
export type PolicyPutIn = { content: Record<string, unknown>; base_version_id: number };
export type PolicySaved = { version_id: number; version: string };
