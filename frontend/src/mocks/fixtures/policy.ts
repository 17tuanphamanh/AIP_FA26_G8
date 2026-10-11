// Dữ liệu GIẢ cho Chính sách (F5 P8) — chỉ nạp khi dev:mock. Hình dạng [Đề xuất F5 — Q-fe-26]: bám cột
// `policy_versions` (`version` chuỗi, `updated_by`, `updated_at`, `is_current`) + `restored_from` khi bản được tạo bằng
// quay lui (append-only). Nội dung bản đang áp dụng = CHÉP NGUYÊN config/policy.json (3 khoá gốc: constants,
// business_hours, rules R16–R20) tại 75a88fb; các bản cũ đổi vài hằng số để lịch sử có khác biệt. 4 phiên bản, 1 đang
// áp dụng; bản "3" là bản khôi phục từ bản "1".
// Xoá khi: Phase 7 có route /api/policy* (gen:api) — xoá cùng mocks/handlers/policy.ts.

export type PolicyVersionRecord = {
  version_id: number;
  version: string;
  content: Record<string, unknown>;
  updated_by: string | null;
  updated_at: string;
  is_current: boolean;
  restored_from: string | null;
};

/** config/policy.json (chép nguyên văn giá trị). */
export const POLICY_JSON = {
  constants: {
    MAX_LOOPS: 5,
    MAX_CLARIFICATION_TURNS: 3,
    TOOL_RETRY: 2,
    BACKOFF_BASE_SECONDS: 1,
    MAX_AUTH_FAILURES: 5,
    AUTH_FAILURE_WINDOW_MINUTES: 10,
    SLA_MINUTES: 30,
    THRESHOLD_LOW: 0.25,
    THRESHOLD_HIGH: 0.75,
    RETRIEVAL_THRESHOLD: 0.6,
    TAU_INTENT: 0.6,
    CLARIFY_TIMEOUT_HOURS: 24,
    CONFIRM_TIMEOUT_HOURS: 48,
  },
  business_hours: { tz: "Asia/Ho_Chi_Minh", weekdays: [1, 2, 3, 4, 5], start: "08:00", end: "18:00" },
  rules: [
    {
      id: "R16",
      type: "allow",
      intent: "vpn",
      action: "check_vpn_status",
      conditions: { all: [{ fact: "ctx.target_is_other", op: "is_false" }] },
      description: "Kiểm tra trạng thái VPN của chính mình",
    },
    {
      id: "R17",
      type: "approval_required",
      intent: "vpn",
      action: ["renew_vpn_cert", "reissue_vpn_access"],
      conditions: { all: [{ fact: "action.facts.device_registered", op: "is_false" }] },
      description: "Thiết bị chưa đăng ký",
    },
    {
      id: "R18",
      type: "approval_required",
      intent: "vpn",
      action: ["renew_vpn_cert", "reissue_vpn_access"],
      conditions: { all: [{ fact: "time.within_business_hours", op: "is_false" }] },
      description: "Ngoài giờ hành chính",
    },
    {
      id: "R19",
      type: "approval_required",
      intent: "vpn",
      action: ["renew_vpn_cert", "reissue_vpn_access"],
      conditions: { all: [{ fact: "requester.employment_status", op: "eq", value: "probation" }] },
      description: "Nhân viên chưa qua thử việc",
    },
    {
      id: "R20",
      type: "allow",
      intent: "vpn",
      action: ["renew_vpn_cert", "reissue_vpn_access"],
      conditions: {
        all: [
          { fact: "action.facts.device_registered", op: "is_true" },
          { fact: "action.facts.device_owner_is_requester", op: "is_true" },
          { fact: "ctx.target_is_other", op: "is_false" },
        ],
      },
      description: "Cấp lại cho thiết bị đã đăng ký của chính người gửi",
    },
  ],
};

const DAY = 86_400_000;
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

function withConstants(changes: Record<string, number>): Record<string, unknown> {
  const content = clone(POLICY_JSON);
  Object.assign(content.constants, changes);
  return content;
}

export function buildPolicyVersions(now: number): PolicyVersionRecord[] {
  const at = (daysAgo: number) => new Date(now - daysAgo * DAY).toISOString();
  const v1 = withConstants({ SLA_MINUTES: 45, THRESHOLD_LOW: 0.3 });
  return [
    { version_id: 11, version: "1", content: v1, updated_by: null, updated_at: at(6), is_current: false, restored_from: null },
    { version_id: 12, version: "2", content: withConstants({ SLA_MINUTES: 20 }), updated_by: "it_mgr01", updated_at: at(4), is_current: false, restored_from: null },
    { version_id: 13, version: "3", content: clone(v1), updated_by: "it_mgr01", updated_at: at(3), is_current: false, restored_from: "1" },
    { version_id: 14, version: "4", content: clone(POLICY_JSON), updated_by: "it_mgr01", updated_at: at(1), is_current: true, restored_from: null },
  ];
}
