// Dữ liệu GIẢ cho hộp thư duyệt / xem phiếu / ghi đè (F4 P2) — chỉ nạp khi dev:mock. Chỉ intent VPN (KH 4.6):
// `renew_vpn_cert`, `reissue_vpn_access`. Người, máy, chứng chỉ theo mock_services/seed.json; luật theo config/policy.json
// (R17 máy chưa đăng ký, R18 ngoài giờ, R19 thử việc); `action` đúng khoá của `Action` (backend/app/domain/action.py
// build_action) với thuộc tính của config/action_metadata.yaml; `risk` theo RiskDecision (domain/ticket_state.py);
// căn cứ quy trình theo KB fixture (backend/tests/fixtures/kb/vpn). Mã băm là chuỗi minh hoạ, KHÔNG phải băm thật.
// Mốc giờ tính từ `base` (giờ nạp trang) → mỗi lần tải trang dữ liệu mới, ổn định trong một phiên trang.
// Xoá khi: 4c + 4d merge (cùng mocks/handlers/approvals.ts, override.ts).
import type { ApprovalListItem, ApprovalStatus, ApprovalViewP4, OverrideDecision } from "../../api/types.ts";

export const APPROVAL_DEMO_PREFIX = "apv-demo-";
export const TICKET_DEMO_PREFIX = "tkt-demo-";

const MIN = 60_000;
const SLA_MIN = 30;

export type ApprovalFixture = {
  item: ApprovalListItem;
  /** "plan_changed": `hash_action(action) != action_plan_hash` → xem phiếu 409, không trả bản nào (4c P6). */
  view: ApprovalViewP4 | "plan_changed";
};

type Requester = { user_id: string; department: string };
type Rule = { id: string; reason: string };

type Spec = {
  n: string;
  status: ApprovalStatus;
  role_as: "primary" | "backup";
  /** Phút so với lúc nạp trang (âm = trước). Hạn = tạo + 30 phút (APPROVAL_SLA). */
  created: number;
  action_type: "renew_vpn_cert" | "reissue_vpn_access";
  device_id: string;
  requester: Requester;
  request: string;
  rule: Rule;
  facts: Record<string, string | number | boolean>;
  procedure: ApprovalViewP4["procedure"];
  hash: string;
  planChanged?: boolean;
};

const NV001: Requester = { user_id: "nv001", department: "Finance" }; // an.nv — LAP-0342, chứng chỉ hết hạn 3 ngày
const NV002: Requester = { user_id: "nv002", department: "Engineering" }; // binh.tt — LAP-0417, PC-0977 chưa đăng ký
const NV003: Requester = { user_id: "nv003", department: "Finance" }; // chau.hm (thử việc) — LAP-0501
const NV005: Requester = { user_id: "nv005", department: "Sales" }; // hoa.bt — LAP-0610, chứng chỉ bị thu hồi

const R17: Rule = { id: "R17", reason: "Thiết bị chưa đăng ký" };
const R18: Rule = { id: "R18", reason: "Ngoài giờ hành chính" };
const R19: Rule = { id: "R19", reason: "Nhân viên chưa qua thử việc" };

const KB_CERT = { doc_id: "KB-VPN-004", title: "Gia hạn và cấp lại chứng chỉ VPN" };
const KB_DEVICE = { doc_id: "KB-VPN-005", title: "Đăng ký thiết bị mới để dùng VPN" };

const SPECS: readonly Spec[] = [
  {
    // Còn 4/30 phút (13%) → ĐỎ; đã qua cả 2 mốc nhắc.
    n: "01", status: "pending", role_as: "primary", created: -26, action_type: "renew_vpn_cert", device_id: "LAP-0342",
    requester: NV001, rule: R18,
    request: "VPN báo chứng chỉ hết hạn trên máy LAP-0342, tối nay em cần vào hệ thống kế toán để chốt sổ ạ.",
    facts: { device_registered: true, device_owner_is_requester: true, cert_status: "expired", cert_days_to_expiry: -3, last_connection_ok: false },
    procedure: KB_CERT, hash: "9f2c7e5d1b8a4c3e6f0d2a9b7c5e1f3a8d6b4c2e0f9a7b5c3d1e8f6a4b2c0e41",
  },
  {
    // Dự phòng: chỉ duyệt được sau nhắc 2 (4c P4, Q-4-O) → luôn có reminder_2_at. Còn 5/30 phút (17%) → ĐỎ.
    n: "02", status: "pending", role_as: "backup", created: -25, action_type: "reissue_vpn_access", device_id: "LAP-0610",
    requester: NV005, rule: R18,
    request: "Máy LAP-0610 không vào được VPN, báo chứng chỉ bị thu hồi. Nhờ IT cấp lại giúp em.",
    facts: { device_registered: true, device_owner_is_requester: true, cert_status: "revoked", cert_days_to_expiry: 65, last_connection_ok: false },
    procedure: { doc_id: "KB-VPN-004" }, // không tìm thấy tiêu đề → chỉ doc_id (4c P6)
    hash: "3b8e1c0a7f5d2e9c4a6b8d0f1e3c5a7b9d2f4e6a8c0b1d3f5e7a9c2b4d6f8e10",
  },
  {
    // Còn 26/30 phút → KHÔNG đỏ, chưa nhắc.
    n: "03", status: "pending", role_as: "primary", created: -4, action_type: "renew_vpn_cert", device_id: "LAP-0501",
    requester: NV003, rule: R19,
    request: "Chứng chỉ VPN máy LAP-0501 còn 5 ngày nữa hết hạn, em xin gia hạn trước để không bị gián đoạn.",
    facts: { device_registered: true, device_owner_is_requester: true, cert_status: "valid", cert_days_to_expiry: 5, last_connection_ok: true },
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
];

const iso = (ms: number) => new Date(ms).toISOString();

function build(spec: Spec, base: number): ApprovalFixture {
  const created = base + spec.created * MIN;
  const deadline = created + SLA_MIN * MIN;
  // Mốc nhắc 4c P3: 50% và 80% thời hạn — chỉ ghi khi mốc đã qua.
  const mark = (ratio: number) => {
    const at = created + ratio * SLA_MIN * MIN;
    return at <= base ? iso(at) : null;
  };
  const item: ApprovalListItem = {
    approval_id: `${APPROVAL_DEMO_PREFIX}${spec.n}`,
    ticket_id: `0f4e2a6c-9b1d-4c7e-8a3f-5d2b6e9c10${spec.n}`,
    status: spec.status,
    created_at: iso(created),
    deadline: iso(deadline),
    reminder_1_at: mark(0.5),
    reminder_2_at: mark(0.8),
    role_as: spec.role_as,
    action_type: spec.action_type,
    device_id: spec.device_id,
  };
  if (spec.planChanged) return { item, view: "plan_changed" };
  const action = {
    type: spec.action_type,
    target: `device:${spec.device_id}`,
    requested_for: spec.requester.user_id,
    scope: "single_device",
    privilege_level: "standard_user",
    reversible: true,
    reversibility: "full",
    data_sensitivity: "low",
    params: { device_id: spec.device_id },
    facts: spec.facts,
  };
  const view: ApprovalViewP4 = {
    approval_id: item.approval_id,
    ticket_id: item.ticket_id,
    status: item.status,
    deadline: item.deadline,
    requester: { role: "employee", department: spec.requester.department },
    request_summary: spec.request,
    action,
    action_plan_hash: spec.hash,
    risk: {
      decided_by: "rule",
      policy_decision: "approval_required",
      matched_rule_id: spec.rule.id,
      raw_prob: null,
      calibrated_prob: null,
      p_method: null,
      risk_level: "medium",
      route: "HITL",
      reason: spec.rule.reason,
      thresholds: null,
    },
    facts: spec.facts,
    role_as: item.role_as,
    procedure: spec.procedure,
  };
  return { item, view };
}

export const buildApprovalFixtures = (base: number): ApprovalFixture[] => SPECS.map((spec) => build(spec, base));

// ---------------------------------------------------------------- ghi đè (4d)

/** Ticket minh hoạ cho hộp ghi đè — không có ở backend (GET thật → 404). Kết quả cố định theo mã (F4 P2):
 *  `open` → 409 ticket_open · `same` → 422 same_as_original · `reauth` → lần gọi ĐẦU mỗi phiên trang 403
 *  reauth_required, các lần sau như ticket đã kết thúc (quyết định gốc AUTO) → 201. */
export const DEMO_TICKETS: Record<string, { kind: "open" | "same" | "closed"; original: OverrideDecision; reauthFirst?: boolean }> = {
  [`${TICKET_DEMO_PREFIX}open`]: { kind: "open", original: "AUTO" },
  [`${TICKET_DEMO_PREFIX}same`]: { kind: "same", original: "AUTO" },
  [`${TICKET_DEMO_PREFIX}reauth`]: { kind: "closed", original: "AUTO", reauthFirst: true },
};
