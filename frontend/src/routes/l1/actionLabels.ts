// B2 (đợt 2 tên gọi, ĐP 01/11 12:25 — duyệt có điều kiện; bảng nhãn: Project claude/bang-nhan-b2-01-11.md).
// Nhãn dễ đọc ĐI KÈM khoá/giá trị GỐC ở bảng "Hệ thống sẽ thực hiện chính xác" — KHÔNG thay. Nguồn tập giá trị: backend
// domain/action.py (Scope, PrivilegeLevel, Reversibility, Sensitivity, PARAMS_BY_ACTION), config/action_metadata.yaml,
// config/slots.yaml (account_type), domain/facts.py (FACT_TYPES, FACT_VALUE_SETS). Cặp khoá/giá trị ngoài bảng → null (chỉ
// hiện gốc, không đoán). Mọi tra cứu bằng Object.hasOwn — giá trị như "__proto__", "constructor" không bao giờ ra nhãn.

type Labels = Readonly<Record<string, string>>;

// Tập giá trị đóng — chép từ backend; `Record<Kiểu, string>` → thiếu nhãn cho một giá trị là tsc đỏ. Đồng bộ với backend kiểm
// ở actionLabels.sync.test.ts (đọc thẳng domain/action.py, domain/facts.py, config/*.yaml — backend đổi mà FE chưa theo → đỏ).
// OpenAPI không có các enum này (`action` là dict tự do) nên không lấy được kiểu từ schema.gen.ts.
export type ActionType =
  | "renew_vpn_cert" | "reissue_vpn_access" | "check_vpn_status" | "reset_password" | "unlock_account"
  | "install_software" | "view_permissions" | "grant_permission" | "extend_permission";
export type Scope = "single_account" | "single_device" | "multiple" | "org_wide";
export type PrivilegeLevel = "standard_user" | "elevated" | "admin";
export type Reversibility = "full" | "partial" | "none";
export type Sensitivity = "low" | "medium" | "high";
export type PermissionLevel = "read" | "write" | "full";
export type AccountType = "ad" | "email" | "erp";
export type CertStatus = "valid" | "expired" | "revoked" | "none";
export type UserStatus = "active" | "probation" | "disabled" | "terminated";
export type DisableReason = "security" | "other";
export type LockReason = "bad_password" | "admin" | "inactivity" | "other";

const has = (table: Labels, key: string): string | null => (Object.hasOwn(table, key) ? table[key]! : null);

/** Tên hành động — dùng chung cho tiêu đề phiếu, hộp thư (inbox.ts ACTION_LABEL) và nhãn giá trị `type`. */
export const ACTION_TYPE_LABEL: Readonly<Record<ActionType, string>> = {
  renew_vpn_cert: "Cấp lại chứng chỉ VPN",
  reissue_vpn_access: "Cấp lại truy cập VPN",
  check_vpn_status: "Kiểm tra trạng thái VPN",
  reset_password: "Đặt lại mật khẩu",
  unlock_account: "Mở khoá tài khoản",
  install_software: "Cài phần mềm",
  view_permissions: "Xem quyền truy cập",
  grant_permission: "Cấp quyền truy cập",
  extend_permission: "Gia hạn quyền truy cập",
};

const BOOL: Labels = { true: "Có", false: "Không" };
export const SCOPE_LABEL: Readonly<Record<Scope, string>> = {
  single_account: "Một tài khoản",
  single_device: "Một máy",
  multiple: "Nhiều đối tượng",
  org_wide: "Toàn công ty",
};
export const LEVEL: Readonly<Record<Sensitivity, string>> = { low: "Thấp", medium: "Trung bình", high: "Cao" };
export const PRIVILEGE: Readonly<Record<PrivilegeLevel, string>> = { standard_user: "Người dùng thường", elevated: "Quyền nâng cao", admin: "Quản trị" };
export const PERMISSION: Readonly<Record<PermissionLevel, string>> = { read: "Chỉ đọc", write: "Đọc và ghi", full: "Toàn quyền" };
export const REVERSIBILITY: Readonly<Record<Reversibility, string>> = { full: "Hoàn tác toàn bộ", partial: "Hoàn tác một phần", none: "Không hoàn tác được" };
export const ACCOUNT_TYPE: Readonly<Record<AccountType, string>> = { ad: "Tài khoản đăng nhập (AD)", email: "Email", erp: "ERP" };
export const CERT_STATUS: Readonly<Record<CertStatus, string>> = { valid: "Còn hạn", expired: "Đã hết hạn", revoked: "Đã thu hồi", none: "Chưa có chứng chỉ" };
export const USER_STATUS: Readonly<Record<UserStatus, string>> = { active: "Đang làm việc", probation: "Đang thử việc", disabled: "Đã vô hiệu hoá", terminated: "Đã nghỉ việc" };
export const DISABLE_REASON: Readonly<Record<DisableReason, string>> = { security: "Lý do bảo mật", other: "Khác" };
export const LOCK_REASON: Readonly<Record<LockReason, string>> = { bad_password: "Nhập sai mật khẩu", admin: "Quản trị viên khoá", inactivity: "Lâu không dùng", other: "Khác" };

/** Nhãn KHOÁ đầy đủ (khoá phẳng). Khoá cấp gốc giữ bảng cũ ở inbox.ts ACTION_KEY_LABEL. */
export const FLAT_KEY_LABEL: Labels = {
  "params.device_id": "Mã máy",
  "params.account_type": "Loại tài khoản",
  "params.software_name": "Tên phần mềm",
  "params.resource_path": "Đường dẫn thư mục",
  "params.permission_level": "Mức quyền xin cấp",
  "params.duration_days": "Thời hạn",
  "facts.device_count": "Số máy của người dùng",
  "facts.has_registered_device": "Có máy đã đăng ký",
  "facts.device_registered": "Máy đã đăng ký",
  "facts.device_owner_is_requester": "Người gửi là chủ máy",
  "facts.cert_status": "Trạng thái chứng chỉ",
  "facts.cert_days_to_expiry": "Số ngày tới hạn chứng chỉ (âm = đã quá hạn)",
  "facts.last_connection_ok": "Lần kết nối gần nhất thành công",
  "facts.target_account_privilege": "Mức quyền của tài khoản đích",
  "facts.target_is_service_account": "Là tài khoản dịch vụ",
  "facts.target_user_status": "Tình trạng nhân viên",
  "facts.target_disable_reason": "Lý do vô hiệu hoá",
  "facts.target_account_locked": "Tài khoản đang bị khoá",
  "facts.target_lock_reason": "Lý do khoá",
  "facts.in_catalog": "Có trong danh mục phần mềm",
  "facts.license_paid": "Phần mềm có phí",
  "facts.requires_local_admin": "Cần quyền quản trị máy",
  "facts.resource_sensitivity": "Độ nhạy của thư mục",
  "facts.same_department": "Cùng phòng ban với chủ thư mục",
  "facts.has_permission_record": "Đã có bản ghi quyền",
  "facts.existing_permission_level": "Mức quyền hiện có",
};

/** Nhãn GIÁ TRỊ chuỗi/bool theo khoá phẳng. */
export const VALUE_LABEL: Readonly<Record<string, Labels>> = {
  type: ACTION_TYPE_LABEL,
  scope: SCOPE_LABEL,
  privilege_level: PRIVILEGE,
  reversible: BOOL,
  reversibility: REVERSIBILITY,
  data_sensitivity: LEVEL,
  "params.account_type": ACCOUNT_TYPE,
  "params.permission_level": PERMISSION,
  "facts.has_registered_device": BOOL,
  "facts.device_registered": BOOL,
  "facts.device_owner_is_requester": BOOL,
  "facts.cert_status": CERT_STATUS,
  "facts.last_connection_ok": BOOL,
  "facts.target_account_privilege": PRIVILEGE,
  "facts.target_is_service_account": BOOL,
  "facts.target_user_status": USER_STATUS,
  "facts.target_disable_reason": DISABLE_REASON,
  "facts.target_account_locked": BOOL,
  "facts.target_lock_reason": LOCK_REASON,
  "facts.in_catalog": BOOL,
  "facts.license_paid": BOOL,
  "facts.requires_local_admin": BOOL,
  "facts.resource_sensitivity": LEVEL,
  "facts.same_department": BOOL,
  "facts.has_permission_record": BOOL,
  "facts.existing_permission_level": PERMISSION,
};

/** Tiền tố `target` (domain/action.py `_target_params`): phần sau dấu ":" giữ nguyên. Tiền tố khác → không nhãn. */
const TARGET_PREFIX: Labels = { device: "Máy", user: "Tài khoản", folder: "Thư mục" };

/**
 * Nhãn đi kèm giá trị của một dòng. `raw` = chuỗi giá trị gốc ĐÚNG như bảng hiện (JSON.stringify — flattenEntries).
 * Không có nhãn → null. Không bao giờ sửa `raw`.
 */
export function actionValueLabel(key: string, raw: string): string | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null; // "undefined" hoặc dạng lạ → chỉ hiện gốc
  }
  if (key === "target" && typeof value === "string") {
    const at = value.indexOf(":");
    const prefix = at > 0 ? has(TARGET_PREFIX, value.slice(0, at)) : null;
    return prefix && at < value.length - 1 ? `${prefix} ${value.slice(at + 1)}` : null;
  }
  if (key === "params.duration_days") {
    return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? `${value} ngày` : null;
  }
  if (!Object.hasOwn(VALUE_LABEL, key)) return null;
  const table = VALUE_LABEL[key]!;
  if (typeof value === "boolean") return has(table, String(value));
  return typeof value === "string" ? has(table, value) : null;
}

/** Nhãn khoá phẳng đầy đủ (params.*, facts.*) — null nếu không có (nơi gọi lùi về nhãn khoá cấp gốc). */
export const flatKeyLabel = (key: string): string | null => has(FLAT_KEY_LABEL, key);
