// Kiểu VIẾT TAY (KH mục 3.2): route chưa có ở backend, hoặc route trả `dict` nên openapi không sinh được kiểu.
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
// `kind` lạ → hiện `text` như tin thường, không lỗi (12b Q-fe-2). Xoá khi: TicketView khai kiểu conversation.
export type ConversationItem =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      kind: "answer" | "question" | "result" | "escalation" | "rejection" | (string & {});
      text: string;
      ref?: string | null;
      needs?: string;
      sources?: Source[];
    };

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

// Nguồn: backend/app/api/approvals.py decide() — JSONResponse 202.
// Xoá khi: route khai response_model.
export type DecisionAccepted = { approval_id: string; ticket_id: string; status: "accepted"; notices: string[] };

// Nguồn: backend/app/api/health.py health() — JSONResponse; 200 "ok" / 503 "degraded"; `runtime` chỉ để báo.
// Xoá khi: route có response_model.
export type Health = {
  status: "ok" | "degraded";
  checks: Record<string, string>;
  failed: string[];
  runtime: "up" | "down";
  kb: { alias: string; collection: string | null; status: "ready" | "missing" | "unknown" };
};

// ---------------------------------------------------------------- Route CHƯA CÓ (MSW)

// Nguồn: phase4-thiet-ke-chi-tiet.md §6.1 P5 (4c).
// Xoá khi: 4c merge → gen:api (xoá cùng mocks/handlers/approvals.ts).
export type ApprovalStatus = "pending" | "approved" | "rejected" | "timeout";

// Nguồn: phase4-thiet-ke-chi-tiet.md §6.1 P5 (4c) — `GET /api/approvals?mine=1&status=…`, tối đa 50.
// Xoá khi: 4c merge → gen:api.
export type ApprovalListItem = {
  approval_id: string;
  ticket_id: string;
  status: ApprovalStatus;
  created_at: string;
  deadline: string;
  reminder_1_at: string | null;
  reminder_2_at: string | null;
  role_as: "primary" | "backup";
  action_type: string;
  device_id: string | null;
};

// Nguồn: phase4-thiet-ke-chi-tiet.md §6.1 P6 (4c) — thay ApprovalView phỏng đoán ở KH 3.2. Không có
// server_now → giờ máy chủ từ header `Date` (KH 1.3 #5). 409 `plan_changed`, 404, 403. Xoá khi: 4c merge → gen:api.
export type ApprovalView = {
  approval_id: string;
  ticket_id: string;
  status: ApprovalStatus;
  deadline: string;
  requester: { role: string; department: string | null };
  request_summary: string;
  action: Record<string, unknown>;
  action_plan_hash: string;
  risk: Record<string, unknown>;
  facts: Record<string, unknown>;
  role_as: "primary" | "backup";
};

// Nguồn: phase4-thiet-ke-chi-tiet.md §7.1 P2 (4d).
// Xoá khi: 4d merge → gen:api (xoá cùng mocks/handlers/override.ts).
export type OverrideDecision = "AUTO" | "HITL" | "L2" | "ANSWER";

// Nguồn: phase4-thiet-ke-chi-tiet.md §7.1 P2 (4d).
// Xoá khi: 4d merge → gen:api.
export type OverrideReasonCode =
  | "too_risky_for_auto"
  | "approval_unnecessary"
  | "should_not_escalate"
  | "wrong_answer"
  | "policy_gap"
  | "other";

// Nguồn: phase4-thiet-ke-chi-tiet.md §7.1 P1–P4 (4d) — 201; 409 ticket_open / already_overridden;
// 422 same_as_original; 403 reauth_required (P6 §4, 12b Q-fe-4). `note` bắt buộc khi reason_code="other". Xoá khi: 4d merge.
export type OverrideIn = { override_decision: OverrideDecision; reason_code: OverrideReasonCode; note?: string };

// Nguồn: KH 3.2 ← ke-hoach-m9-monitor.md §5.1 — tên trường giữ nguyên, không tự đặt. Soát lại §5.1 khi vào F5.
// Xoá khi: M9 A3 merge (gen:api) — xoá cùng mocks/handlers/dashboard.ts.
export type BusinessDashboard = {
  automation_rate: number | null;
  escalation_rate_raw: number | null;
  escalation_rate_weighted: number | null;
  deflection_rate: number | null;
  approval_expired_count: number;
  decided_by_distribution: Record<string, number>;
  top_matched_rules: { rule_id: string; count: number }[];
  e1_split?: Record<string, number>;
  e3_cases?: { ticket_id: string; intent: string; created_at: string; kb_version: string; request_excerpt: string }[];
  unavailable: string[];
};
