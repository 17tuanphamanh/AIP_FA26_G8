// Dữ liệu GIẢ cho hộp thư duyệt / xem phiếu / ghi đè (F4 P2, N4c P6d) — chỉ nạp khi dev:mock. Hình dạng ĐÚNG route thật
// (backend/app/api/approvals.py @b457e6e: InboxItem 10 khoá, ApprovalView 12 khoá). Chỉ intent VPN (KH 4.6):
// `renew_vpn_cert`, `reissue_vpn_access`. Người, máy, chứng chỉ theo mock_services/seed.json; luật theo config/policy.json
// (R17 máy chưa đăng ký, R18 ngoài giờ, R19 thử việc); `action` đúng khoá của `Action` (backend/app/domain/action.py
// build_action) với thuộc tính của config/action_metadata.yaml; `risk` theo RiskDecision (domain/ticket_state.py);
// căn cứ quy trình theo KB fixture (backend/tests/fixtures/kb/vpn). Mã băm là chuỗi minh hoạ, KHÔNG phải băm thật.
// Mốc giờ tính từ `base` (giờ nạp trang) → mỗi lần tải trang dữ liệu mới, ổn định trong một phiên trang.
// Hộp thư ở dev:mock = phiếu THẬT của backend + các phiếu này (mocks/handlers/approvals.ts). Xoá khi: 4c + 4d có
// response_model (gen:api) và không còn cần minh hoạ (cùng mocks/handlers/approvals.ts, override.ts).
import type {
  ApprovalAffected,
  ApprovalListItem,
  ApprovalRiskView,
  ApprovalRoleAs,
  ApprovalStatus,
  ApprovalViewP4,
  MatchedRule,
  OverrideDecision,
} from "../../api/types.ts";

export const APPROVAL_DEMO_PREFIX = "apv-demo-";
export const TICKET_DEMO_PREFIX = "tkt-demo-";

const MIN = 60_000;
const SLA_MIN = 30;

export type ApprovalFixture = {
  approval_id: string;
  ticket_id: string;
  status: ApprovalStatus;
  deadline: string;
  /** Vai trò của người đang xem với phiếu — `decided_as` của 202; `viewer` → quyết định 403 (như `approval_role` None). */
  role_as: ApprovalRoleAs;
  /** Dòng hộp thư; null = phiếu KHÔNG nằm trong hộp thư (chỉ mở bằng URL — phiếu giám sát). */
  item: ApprovalListItem | null;
  /** "plan_changed": `hash_action(action) != action_plan_hash` → xem phiếu 409, không trả bản nào (4c P6). */
  view: ApprovalViewP4 | "plan_changed";
};

type Requester = { user_id: string; department: string | null };
type Rule = { id: string; reason: string };

type Spec = {
  n: string;
  status: ApprovalStatus;
  role_as: ApprovalRoleAs;
  /** Phút so với lúc nạp trang (âm = trước). Hạn = tạo + 30 phút (APPROVAL_SLA). */
  created: number;
  action_type: "renew_vpn_cert" | "reissue_vpn_access";
  /** null → hành động nhắm tài khoản (`user:…`), không phải máy → hộp thư `device_id` null. */
  device_id: string | null;
  requester: Requester;
  request: string;
  /** null → phiếu chưa có đánh giá rủi ro (`risk` null). */
  rule: Rule | null;
  facts: Record<string, string | number | boolean>;
  procedure: ApprovalViewP4["procedure"];
  hash: string;
  planChanged?: boolean;
  /** Dòng audit B15 `queued` không có (B15 giả) → hộp thư `action_type` null. */
  auditMissing?: boolean;
  /** false → không nằm trong hộp thư. */
  listed?: boolean;
  /** Người BỊ TÁC ĐỘNG (F6 #76); mặc định = người gửi, quản lý chưa rõ. Khác người gửi → `is_requester` false. */
  affected?: { user_id: string; department: string | null; manager: ApprovalAffected["manager"] };
  /** true → đánh giá do LLM, chưa hiệu chỉnh (`risk_view.calibrated` false): màn hiện "chưa hiệu chỉnh, không tự xử lý". */
  llmRisk?: boolean;
  /** N-PA §3: các luật khớp (khoá gốc `matched_rules`); vắng → phiếu không có khoá (màn hiện "Chưa có dữ liệu luật khớp"). */
  matched?: MatchedRule[];
};

const NV001: Requester = { user_id: "nv001", department: "Finance" }; // an.nv — LAP-0342, chứng chỉ hết hạn 3 ngày
const NV002: Requester = { user_id: "nv002", department: "Engineering" }; // binh.tt — LAP-0417, PC-0977 chưa đăng ký
const NV003: Requester = { user_id: "nv003", department: "Finance" }; // chau.hm (thử việc) — LAP-0501
const NV004_NO_DEPT: Requester = { user_id: "nv004", department: null }; // dung.dv — ngữ cảnh người gửi thiếu phòng ban
const NV005: Requester = { user_id: "nv005", department: "Sales" }; // hoa.bt — LAP-0610, chứng chỉ bị thu hồi

const R17: Rule = { id: "R17", reason: "Thiết bị chưa đăng ký" };
const R18: Rule = { id: "R18", reason: "Ngoài giờ hành chính" };
const R19: Rule = { id: "R19", reason: "Nhân viên chưa qua thử việc" };

/** apv-demo-01 (N-PA P4, Q-fe-N3): 3 luật, đúng 1 applied (R18) — R20 (allow) là luật thua có quyết định KHÁC, R19
 *  (approval_required) là luật thua CÙNG quyết định; R20 không có mô tả (null → "—"). */
const MATCHED_01: MatchedRule[] = [
  { rule_id: "R18", description: "Yêu cầu gửi ngoài giờ hành chính cần người duyệt", decision: "approval_required", applied: true },
  { rule_id: "R19", description: "Nhân viên chưa qua thử việc cần người duyệt", decision: "approval_required", applied: false },
  { rule_id: "R20", description: null, decision: "allow", applied: false },
];

const KB_CERT = { doc_id: "KB-VPN-004", title: "Gia hạn và cấp lại chứng chỉ VPN" };
const KB_DEVICE = { doc_id: "KB-VPN-005", title: "Đăng ký thiết bị mới để dùng VPN" };

const UNKNOWN_MANAGER: ApprovalAffected["manager"] = { status: "unknown", user_id: null, full_name: null };
type RiskBody = Omit<ApprovalRiskView, "calibrated" | "auto_allowed">;
const RULE_RISK: RiskBody = {
  decided_by: "rule",
  policy_decision: "approval_required",
  matched_rule_id: null,
  raw_prob: null,
  calibrated_prob: null,
  p_method: null,
  risk_level: "medium",
  route: "HITL",
  reason: "",
  thresholds: null,
};
/** Đánh giá của LLM, chưa có calibrated_prob → `calibrated` false (điểm tự khai, không dùng để tự xử lý). */
const LLM_RISK: RiskBody = {
  decided_by: "llm",
  policy_decision: null,
  matched_rule_id: null,
  raw_prob: 0.62,
  calibrated_prob: null,
  p_method: "self_report",
  risk_level: "high",
  route: "HITL",
  reason: "Mô hình thấy chứng chỉ bị thu hồi bất thường, không có luật khớp",
  thresholds: null,
};

const SPECS: readonly Spec[] = [
  {
    // Còn 4/30 phút (13%) → ĐỎ; đã qua cả 2 mốc nhắc.
    n: "01", status: "pending", role_as: "primary", created: -26, action_type: "renew_vpn_cert", device_id: "LAP-0342",
    requester: NV001, rule: R18, matched: MATCHED_01,
    affected: { user_id: "nv001", department: "Finance", manager: { status: "known", user_id: "mgr01", full_name: "Lê Thị Hạnh" } },
    request: "VPN báo chứng chỉ hết hạn trên máy LAP-0342, tối nay em cần vào hệ thống kế toán để chốt sổ ạ.",
    facts: { device_registered: true, device_owner_is_requester: true, cert_status: "expired", cert_days_to_expiry: -3, last_connection_ok: false },
    procedure: KB_CERT, hash: "9f2c7e5d1b8a4c3e6f0d2a9b7c5e1f3a8d6b4c2e0f9a7b5c3d1e8f6a4b2c0e41",
  },
  {
    // Dự phòng: chỉ duyệt được sau nhắc 2 (4c P4, Q-4-O) → luôn có reminder_2_at. Còn 5/30 phút (17%) → ĐỎ.
    n: "02", status: "pending", role_as: "backup", created: -25, action_type: "reissue_vpn_access", device_id: "LAP-0610",
    requester: NV005, rule: R18, llmRisk: true,
    affected: { user_id: "nv005", department: "Sales", manager: { status: "known", user_id: "mgr02", full_name: null } }, // sếp chưa từng đăng nhập
    request: "Máy LAP-0610 không vào được VPN, báo chứng chỉ bị thu hồi. Nhờ IT cấp lại giúp em.",
    facts: { device_registered: true, device_owner_is_requester: true, cert_status: "revoked", cert_days_to_expiry: 65, last_connection_ok: false },
    procedure: { doc_id: "KB-VPN-004", title: null }, // không tìm thấy tiêu đề ở bản KB hiện hành → chỉ doc_id (4c P6)
    hash: "3b8e1c0a7f5d2e9c4a6b8d0f1e3c5a7b9d2f4e6a8c0b1d3f5e7a9c2b4d6f8e10",
  },
  {
    // Còn 26/30 phút → KHÔNG đỏ, chưa nhắc.
    n: "03", status: "pending", role_as: "primary", created: -4, action_type: "renew_vpn_cert", device_id: "LAP-0501",
    requester: NV003, rule: R19,
    // Người bị tác động KHÁC người gửi (nhờ hộ): is_requester false → màn hiện dải "Khác người gửi yêu cầu".
    affected: { user_id: "nv006", department: "Operations", manager: { status: "unknown", user_id: null, full_name: null } },
    request: "Nhờ IT gia hạn trước chứng chỉ VPN máy LAP-0501 của bạn nv006 (còn 5 ngày nữa hết hạn) để không bị gián đoạn công việc.",
    facts: { device_registered: true, device_owner_is_requester: false, cert_status: "valid", cert_days_to_expiry: 5, last_connection_ok: true },
    procedure: KB_CERT, hash: "c4d9a2e7f1b6c3d8e0a5f2b7c9d4e1a6f3b8c0d5e2a7f4b9c1d6e3a8f5b0c2d7",
  },
  {
    // Hành động bị sửa sau khi tạo phiếu → xem phiếu 409 plan_changed.
    n: "04", status: "pending", role_as: "primary", created: -12, action_type: "reissue_vpn_access", device_id: "LAP-0417",
    requester: NV002, rule: R18,
    request: "Cấp lại truy cập VPN cho máy LAP-0417 giúp mình.",
    facts: { device_registered: true, device_owner_is_requester: true, cert_status: "valid", cert_days_to_expiry: 200, last_connection_ok: true },
    procedure: KB_CERT, hash: "0e5a9c3f7b1d4e8a2c6f0b3d7e1a5c9f2b6d0e4a8c1f5b9d3e7a0c4f8b2d6e9a", planChanged: true,
  },
  {
    n: "05", status: "approved", role_as: "primary", created: -180, action_type: "renew_vpn_cert", device_id: "LAP-0342",
    requester: NV001, rule: R18,
    request: "Gia hạn chứng chỉ VPN cho LAP-0342.",
    facts: { device_registered: true, device_owner_is_requester: true, cert_status: "expired", cert_days_to_expiry: -3, last_connection_ok: false },
    procedure: KB_CERT, hash: "7a1f4c8e2b5d9a3c6e0f4b8d1a5c9e2f6b0d3a7c1e5f9b2d6a0c4e8f3b7d1a5c",
  },
  {
    n: "06", status: "rejected", role_as: "primary", created: -120, action_type: "reissue_vpn_access", device_id: "PC-0977",
    requester: NV002, rule: R17,
    request: "Em muốn dùng VPN trên máy PC-0977 ở nhà.",
    facts: { device_registered: false, device_owner_is_requester: true, cert_status: "none", last_connection_ok: true },
    procedure: KB_DEVICE, hash: "5d0b8f2a6c9e3d7f1b4a8c2e6f0d3b7a1c5e9f2d6b0a4c8e3f7b1d5a9c2e6f04",
  },
  {
    n: "07", status: "timeout", role_as: "primary", created: -300, action_type: "renew_vpn_cert", device_id: "LAP-0501",
    requester: NV003, rule: R19,
    request: "Gia hạn VPN cho máy LAP-0501.",
    facts: { device_registered: true, device_owner_is_requester: true, cert_status: "valid", cert_days_to_expiry: 5, last_connection_ok: true },
    procedure: KB_CERT, hash: "e8c2a6f0b4d8e1c5a9f3b7d0e4a8c2f6b1d5e9a3c7f0b4d8e2a6c1f5b9d3e7a0",
  },
  {
    // Dữ liệu thiếu (N4c P3): B15 giả không ghi dòng audit → hộp thư `action_type` null; đích là tài khoản → `device_id`
    // null; ngữ cảnh người gửi thiếu phòng ban; chưa có đánh giá rủi ro; hành động không có trong action_metadata →
    // `procedure` null. Còn 28/30 phút → không đỏ. Vẫn quyết được: căn cứ là object đã băm + mã băm.
    n: "08", status: "pending", role_as: "primary", created: -2, action_type: "reissue_vpn_access", device_id: null,
    requester: NV004_NO_DEPT, rule: null, auditMissing: true,
    affected: { user_id: "nv004", department: null, manager: { status: "unknown", user_id: null, full_name: null } },
    request: "Em cần cấp lại quyền VPN cho tài khoản để tuần sau làm việc từ xa ạ.",
    facts: { device_registered: false, cert_status: "none", last_connection_ok: false },
    procedure: null, hash: "a3f9c1e7b5d2a8f4c0e6b2d8a4f0c6e2b8d4a0f6c2e8b4d0a6f2c8e4b0d6a2f1",
  },
  {
    // Phiếu giám sát (`role_as: "viewer"` — backend thật chỉ trả cho người có `audit:read:all` xem phiếu không giao cho
    // mình). Ở đây trả cho MỌI người có `approval:decide` (Q-fe-36): mục đích là kiểm trạng thái giao diện; phân quyền thật
    // do backend. KHÔNG nằm trong hộp thư — chỉ mở bằng URL. Còn chờ (pending) để chứng minh không có đường quyết định.
    n: "viewer", status: "pending", role_as: "viewer", created: -8, action_type: "renew_vpn_cert", device_id: "LAP-0342",
    requester: NV001, rule: R18, listed: false,
    request: "Chứng chỉ VPN trên LAP-0342 hết hạn, nhờ IT gia hạn giúp em.",
    facts: { device_registered: true, device_owner_is_requester: true, cert_status: "expired", cert_days_to_expiry: -3, last_connection_ok: false },
    procedure: KB_CERT, hash: "6c0e4a8f2d6b0e4c8a2f6d0b4e8c2a6f0d4b8e2c6a0f4d8b2e6c0a4f8d2b6e9c",
  },
];

const iso = (ms: number) => new Date(ms).toISOString();
const ticketOf = (n: string) => `0f4e2a6c-9b1d-4c7e-8a3f-5d2b6e9c10${/^\d\d$/.test(n) ? n : "99"}`;

function build(spec: Spec, base: number): ApprovalFixture {
  const created = base + spec.created * MIN;
  const deadline = created + SLA_MIN * MIN;
  // Mốc nhắc 4c P3: 50% và 80% thời hạn — chỉ ghi khi mốc đã qua.
  const mark = (ratio: number) => {
    const at = created + ratio * SLA_MIN * MIN;
    return at <= base ? iso(at) : null;
  };
  const approval_id = `${APPROVAL_DEMO_PREFIX}${spec.n}`;
  const ticket_id = ticketOf(spec.n);
  const item: ApprovalListItem | null =
    spec.listed === false || spec.role_as === "viewer"
      ? null
      : {
          approval_id,
          ticket_id,
          status: spec.status,
          created_at: iso(created),
          deadline: iso(deadline),
          reminder_1_at: mark(0.5),
          reminder_2_at: mark(0.8),
          role_as: spec.role_as,
          action_type: spec.auditMissing ? null : spec.action_type,
          device_id: spec.device_id,
        };
  const meta = { approval_id, ticket_id, status: spec.status, deadline: iso(deadline), role_as: spec.role_as, item };
  if (spec.planChanged) return { ...meta, view: "plan_changed" };
  const affected: ApprovalAffected = {
    ...(spec.affected ?? { user_id: spec.requester.user_id, department: spec.requester.department, manager: UNKNOWN_MANAGER }),
    is_requester: (spec.affected?.user_id ?? spec.requester.user_id) === spec.requester.user_id,
  };
  const risk = spec.rule && (spec.llmRisk ? LLM_RISK : { ...RULE_RISK, matched_rule_id: spec.rule.id, reason: spec.rule.reason });
  const action = {
    type: spec.action_type,
    target: spec.device_id ? `device:${spec.device_id}` : `user:${spec.requester.user_id}`,
    requested_for: affected.user_id,
    scope: "single_device",
    privilege_level: "standard_user",
    reversible: true,
    reversibility: "full",
    data_sensitivity: "low",
    params: spec.device_id ? { device_id: spec.device_id } : {},
    facts: spec.facts,
  };
  const view: ApprovalViewP4 = {
    approval_id,
    ticket_id,
    status: spec.status,
    deadline: meta.deadline,
    requester: { role: "employee", department: spec.requester.department },
    request_summary: spec.request,
    action,
    action_plan_hash: spec.hash,
    risk,
    risk_view: risk && { ...risk, calibrated: risk.calibrated_prob !== null, auto_allowed: risk.route === "AUTO" },
    facts: spec.facts,
    role_as: spec.role_as,
    procedure: spec.procedure,
    affected,
    ...(spec.matched ? { matched_rules: spec.matched } : {}),
  };
  return { ...meta, view };
}

export const buildApprovalFixtures = (base: number): ApprovalFixture[] => SPECS.map((spec) => build(spec, base));

// ---------------------------------------------------------------- ghi đè (4d — route THẬT `e510a6e`)

/** Nguyên văn `NOTICE_SECRET` của privacy guard (backend/app/guard/privacy.py) — giao diện KHÔNG hiện, chỉ đếm. */
const NOTICE_SECRET = "Vui lòng không gửi mật khẩu hoặc mã bí mật qua chat. Phần đó đã được ẩn và không được lưu.";

export type DemoTicket = {
  kind: "open" | "same" | "closed";
  /** Quyết định gốc server suy từ audit — trả trong 201, chọn trùng → 422 same_as_original. */
  original: OverrideDecision;
  /** `notices` của 201 (ghi chú có bí mật bị che). */
  notices: string[];
  reauthFirst?: boolean;
};

/** Ticket minh hoạ cho hộp ghi đè — không có ở backend (GET thật → 404). Kết quả cố định theo mã (F4 P2, N4d P7):
 *  `open` → 409 ticket_open · `same` → 422 same_as_original · `reauth` → lần gọi ĐẦU mỗi phiên trang 403
 *  reauth_required, các lần sau như ticket đã kết thúc (gốc AUTO) → 201 · `notice` → đã kết thúc (gốc L2) → 201 có
 *  `notices` một phần tử. */
export const DEMO_TICKETS: Record<string, DemoTicket> = {
  [`${TICKET_DEMO_PREFIX}open`]: { kind: "open", original: "AUTO", notices: [] },
  [`${TICKET_DEMO_PREFIX}same`]: { kind: "same", original: "AUTO", notices: [] },
  [`${TICKET_DEMO_PREFIX}reauth`]: { kind: "closed", original: "AUTO", notices: [], reauthFirst: true },
  [`${TICKET_DEMO_PREFIX}notice`]: { kind: "closed", original: "L2", notices: [NOTICE_SECRET] },
};
