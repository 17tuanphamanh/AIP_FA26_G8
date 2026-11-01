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
// `kind` lạ → hiện `text` như tin thường, không lỗi (12b Q-fe-2); `digest` (tin tổng hợp nhiều ý) — kiểu
// `DigestConversationItem` ở khối "Route ĐÃ CÓ — T20b". Xoá khi: TicketView khai kiểu conversation.
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

// Nguồn: backend/app/api/tickets.py TicketView (response_model) — PHẦN VIẾT TAY: `conversation` là list[dict] nên phần tử
// để `unknown`, component tự kiểm dạng (components/Conversation.tsx); `children_progress` (T20b, kiểu `ChildProgress` dưới)
// viết tay chặt hơn openapi (list[dict]) — hình dạng kiểm lúc chạy ở api/tickets.ts `parseTicketView`. `deadline` +
// `server_now` LẤY TỪ schema.gen.ts (N-TB nối API thật, be-thong-bao 56ea4d9) — ghép ở types.ts `TicketView`; tập khoá +
// từng khoá soát hai chiều ở schema.check.ts `TicketViewOk`.
export type TicketViewBase = {
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

// Nguồn: B20-audit-escalate-L2.md §4.3 (`close_result`) + hợp đồng N-PA §4 — `POST /api/escalations/{id}/close` (route thật,
// backend/app/api/escalations.py). Thân đúng 2 khoá; ghi chú bắt buộc 1–1000 ký tự. Thành công 200; 404 `not_found`; 409
// `already_closed`; 422 fields ["close_result"] (ca deny/E5/E6 + `completed`) / ["note"]. Xoá khi: gen:api có kiểu này.
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

// F6 (#76): `affected` = người BỊ TÁC ĐỘNG (`Action.requested_for`), có thể khác người gửi; `risk_view` = RiskDecision + 2 cờ
// suy ra (`calibrated`, `auto_allowed`), null ⇔ `risk` null. Nguồn: backend/app/api/approvals.py (AffectedView, ManagerRef,
// RiskView) — soi hai chiều với openapi ở schema.check.ts. Xoá khi: ApprovalViewP4 lấy thẳng từ schema.gen.ts (cần `status`
// của openapi là enum; hiện là `string`).
export type ApprovalManagerRef = { status: "known" | "unknown"; user_id: string | null; full_name: string | null };
export type ApprovalAffected = {
  user_id: string;
  is_requester: boolean;
  department: string | null;
  manager: ApprovalManagerRef;
};
export type ApprovalRiskView = {
  decided_by: "rule" | "llm";
  policy_decision: "allow" | "approval_required" | "deny" | null;
  matched_rule_id: string | null;
  raw_prob: number | null;
  calibrated_prob: number | null;
  p_method: "self_report" | "sampling_k5" | null;
  risk_level: "low" | "medium" | "high";
  route: "AUTO" | "HITL" | "ESCALATE_L2";
  reason: string;
  thresholds: [number, number] | null;
  calibrated: boolean;
  auto_allowed: boolean;
};
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
  affected: ApprovalAffected;
  risk_view: ApprovalRiskView | null;
  /** N-PA §3 (route CHƯA CÓ ở be-tuan8): thiếu khoá = chưa có dữ liệu luật khớp. */
  matched_rules?: MatchedRule[];
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

// Nguồn: backend/app/api/policy.py `ValidateIn` (extra="forbid", `content: dict`) — `POST /api/policy/validate` tự đọc thân
// (`_read_body`) nên openapi không có requestBody. Kiểu PHẢN HỒI lấy từ schema.gen.ts (types.ts). Xoá khi: route khai body.
export type PolicyValidateIn = { content: Record<string, unknown> };

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

// ---------------------------------------------------------------- Route ĐÃ CÓ — T20b (nhiều ý, D-31; viết tay tới khi gen:api)

// ĐÃ CHỐT theo T20b 5df24c7: backend/app/api/tickets.py (`TicketView.children_progress`, `ReplyIn`, `_reply_body`,
// `_items_match`, route `reply`), domain/children.py (`children_progress`, `child_index`, `SUMMARY`), domain/messages.py
// (`compose_digest`, `child_title`, `reply_text`). openapi khai `children_progress: list[dict] | None` và `conversation:
// list[dict]` → schema.check KHÔNG bắt được lệch: hình dạng kiểm LÚC CHẠY ở api/tickets.ts (`parseTicketView` — sai → 502
// `invalid_ticket_body`, không vẽ một phần). Giá trị lạ của progress/outcome/kind/needs KHÔNG phải lỗi hình dạng (nhãn dự
// phòng ở routes/employee/multi.ts, components/messages.ts). MSW chỉ còn minh hoạ ca lỗi khó tạo trên stack (id
// `tkt-demo-multi-`, mocks/handlers/employee-multi.ts). Xoá khi: gen:api thành nguồn kiểu cho TicketView (vẫn phải kiểm dạng).

// `children_progress` (P11, 5.2.6): theo `index`; `child_id` = "<cha>-<index>"; `title` = `child_title(seed)` — CÓ THỂ "";
// `outcome` chỉ khác null khi `closed` (con không bao giờ S_BLOCKED — P1). `null` = ticket thường / ticket con.
export type ChildProgressState = "processing" | "pending_approval" | "ready" | "needs_user" | "closed";
export type ChildOutcome = "resolved" | "escalated" | "rejected";
export type ChildProgress = {
  child_id: string;
  index: number;
  title: string;
  progress: ChildProgressState | (string & {});
  outcome: ChildOutcome | (string & {}) | null;
};

// Tin tổng hợp `compose_digest` (P9): `items[]` mỗi notice chưa gửi một khối (một con có thể có >1 khối, nhưng chỉ MỘT khối
// `needs ≠ none`); notice B10 `answer` hiện là `result` (server đổi). KHÔNG có `options`, `sources`. `text` = các dòng
// "Ý {index} – {title}: {text}" nối "\n" (+ câu tổng kết ở dòng cuối khi MỌI con đã kết thúc; vòng cuối không còn notice →
// `items: []`, `text` = chỉ câu tổng kết). `DigestItem` là dạng ĐÃ chuẩn hoá (components/messages.ts — kind/needs lạ đã đổi).
export type DigestItemKind = "result" | "question" | "rejection" | "escalation";
export type DigestNeeds = "confirm" | "answer" | "none";
export type DigestItem = { child_id: string; index: number; title: string; kind: DigestItemKind; text: string; needs: DigestNeeds };
export type DigestConversationItem = { role: "assistant"; kind: "digest"; round: number; text: string; items: DigestItem[] };

// `ReplyIn` (extra="forbid" mọi tầng, `items` ≥ 1): khoá = child_id "<cha>-<số>" (khác dạng → 422 `["body.items"]`, vị trí
// CHUNG), ĐÚNG tập `awaiting` và đúng loại theo `needs` (lệch → 422 `["body.items.<child_id>", …]` sắp theo id); lỗi hình
// dạng Pydantic → `items.<child_id>.ReplyAnswer.answer` … (KHÔNG tiền tố `body.`). `note` rỗng → không gửi khoá. Không ở
// `parent_reply_wait` → 409 sự kiện muộn. 202 = `Accepted`.
export type ParentReplyItem = { answer: string } | { confirmed: boolean; note?: string };
export type ParentReplyIn = { items: Record<string, ParentReplyItem> };

// ---------------------------------------------------------------- Route ĐÃ CÓ — I1 (viết tay tới khi gen:api)

// backend/app/api/llm_status.py (`LlmStatus`, model `extra="forbid"`): GET /api/admin/llm-status, quyền `llm_status:read`.
// `api_key_configured` CHỈ là boolean — backend không bao giờ trả khoá, độ dài, tiền tố hay mã băm.
// `spend.percent` là số thô (25 = 25 %, có thể > 100); `warn_percent` lấy từ `spend.warn_ratio` của cấu hình.
// `avg_cost_per_ticket_usd` = SUM(cost_usd) ÷ số ticket có ≥ 1 lời gọi, toàn bộ lịch sử (chưa có ticket → null).
// Xoá khi: gen:api thành nguồn kiểu cho route này.
export type LlmBackend = "scripted" | "real";
export type LlmSpendStatus = "ok" | "warn" | "over";
export type LlmKbStatus = "ready" | "missing" | "unknown";
export type LlmStatus = {
  as_of: string;
  backend: LlmBackend | null;
  models: { fast: string | null; strong: string | null };
  api_key_configured: boolean;
  spend: { total_usd: number; cap_usd: number; percent: number; warn_percent: number; status: LlmSpendStatus };
  usage: { calls_total: number; calls_24h: number; tickets_with_calls: number; avg_cost_per_ticket_usd: number | null };
  kb: { alias: string; collection: string | null; status: LlmKbStatus };
};

// ---------------------------------------------------------------- Route CHƯA CÓ — N-PA, hợp đồng chốt ĐP 26/10 17:30
// Nguồn: hợp đồng API be-tuan8 / fe-phuong-an (bản chốt ĐP 26/10 17:30) + D-67. Backend (nhánh be-tuan8) chưa có code →
// dev:mock dựng bằng MSW (mocks/handlers/strategy.ts, strategy-compare.ts, escalation-queue.ts, escalation-close.ts).
// Hình dạng kiểm LÚC CHẠY (api/strategy.ts, dashboard.ts, approvals.ts, trace.ts, escalations.ts) — thân sai → 502.
// Xoá khi: be-tuan8 merge, mọi route có response_model → `gen:api` thành nguồn kiểu (vẫn giữ kiểm lúc chạy).

/** D-67: tập chọn được khi vận hành (`RUNTIME_SELECTABLE`). */
export type RuntimeStrategy = "rule_only" | "hybrid" | "hybrid_guarded";
/** `GET /api/admin/strategy` (cũng là thân 200 của PUT). `llm_calibrated` thiếu khoá → FE coi là CHƯA hiệu chỉnh. */
export type StrategyView = {
  strategy: RuntimeStrategy;
  selectable: RuntimeStrategy[];
  llm_calibrated?: boolean;
  eval_mode: boolean;
  changed_by: string | null;
  changed_at: string | null;
  reason: string | null;
};
/** `PUT /api/admin/strategy`: `reason` 10–500 ký tự sau khi cắt khoảng trắng. */
export type StrategyIn = { strategy: RuntimeStrategy; reason: string };
/** Một dòng `m5_strategy_changes`; `strategy_from` của dòng đầu tiên là "hybrid". */
export type StrategyChange = {
  changed_at: string;
  changed_by: string;
  strategy_from: RuntimeStrategy;
  strategy_to: RuntimeStrategy;
  reason: string;
};
/** `GET /api/admin/strategy/history?limit=` — mới nhất lên trước. */
export type StrategyHistory = { items: StrategyChange[]; truncated: boolean };

/** `GET /api/dashboard/strategies?from=&to=&source=` — không có giá trị `all`. */
export type StrategySource = "real" | "sim";
export type StrategyRatio = { num: number; den: number };
export type StrategyValue = { value: number | null; n?: number };
export type StrategyMetric = {
  key: string;
  kind: "ratio" | "value";
  unit?: string;
  values: Record<string, StrategyRatio | StrategyValue | null>;
};
export type StrategiesDashboard = {
  source: StrategySource;
  from: string;
  to: string;
  strategies: string[];
  intent_mix: Record<string, Record<string, number>>;
  metrics: StrategyMetric[];
  unavailable: string[];
};

/** Các luật khớp (ApprovalView gốc + TicketTrace bước B13/B14 `policy`), thứ tự như `all_matched`. Hợp đồng sửa 21:15/21:30:
 *  tối đa MỘT phần tử `applied` (0 = quyết định cuối không do luật, vd hybrid_guarded + AI lỗi → E5 llm_layer_disabled);
 *  `decision` null = luật đã bị xoá khỏi chính sách. Thiếu khoá = chưa có dữ liệu (≠ mảng rỗng = không luật nào khớp). */
export type MatchedRule = {
  rule_id: string;
  description: string | null;
  decision: "allow" | "approval_required" | "deny" | null;
  applied: boolean;
};

/** `GET /api/escalations/queue?status=open|closed&limit=&after=` → `{items, next_cursor}`. */
export type EscalationQueueStatus = "open" | "closed";
/** Ca đã đóng mang thêm 3 trường bắt buộc (+ `close_note` tuỳ chọn — FE đề nghị BE thêm); ca mở: vắng hoặc null. */
export type EscalationClosedInfo = {
  closed_at?: string | null;
  close_result?: EscalationCloseResult | null;
  closed_by?: string | null;
  close_note?: string | null;
};
export type EscalationQueuePage = { items: (EscalationQueueItem & EscalationClosedInfo)[]; next_cursor: string | null };
