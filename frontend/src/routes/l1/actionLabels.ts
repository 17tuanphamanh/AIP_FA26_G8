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
  "facts.software_prohibited": "Phần mềm bị cấm theo quy định",
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
  "facts.software_prohibited": BOOL,
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
  if (key === "target") {
    const parts = targetParts(raw);
    return parts ? `${parts.prefix} ${parts.rest}` : null;
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

// ---- Chế độ TẮT chỉ còn chữ người đọc được (ĐP 01/11 15:35, bảng nhãn mục 0c) -------------------------------------------

export const EMPTY_TEXT = "(trống)";
export const NULL_TEXT = "(không có)";
export const RAW_FORMAT_NOTE = "định dạng gốc";

/** (d) Trường danh tính — luôn hiện nội dung, font đơn cách. Phần sau ":" của `target` xử lý riêng (targetParts). */
export const IDENTITY_KEYS: ReadonlySet<string> = new Set(["requested_for", "params.device_id", "params.resource_path", "params.software_name"]);

// Khoảng trắng đầu/cuối · ký tự điều khiển (C0, DEL, C1) · ký tự vô hình (zero-width, điều hướng chữ, word joiner…, soft
// hyphen, BOM, Mongolian vowel separator) · chuỗi trông như số / true / false / null / NaN / Infinity.
const EDGE_SPACE = /^\s|\s$/u;
// eslint-disable-next-line no-control-regex -- cố ý: phát hiện ký tự điều khiển để hiện dạng JSON có escape
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/u;
const INVISIBLE = /[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/u;
const LOOKS_LITERAL = /^(?:[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|true|false|null|nan|[+-]?infinity)$/iu;

// ---- Hiển thị JSON an toàn (ĐP 01/11 16:00, mục 0d) — DÙNG CHUNG cho chế độ TẮT ca (c), chế độ BẬT và tab JSON ------------------
// JSON.stringify KHÔNG escape DEL, C1 (U+007F–U+009F) và ký tự vô hình / điều khiển hướng chữ → thay từng đơn vị UTF-16 bằng
// \uXXXX. Các ký tự này chỉ có thể nằm TRONG chuỗi JSON (khoá hoặc giá trị) → kết quả vẫn là JSON hợp lệ, JSON.parse ra ĐÚNG giá
// trị/object gốc, chỉ là nhìn thấy được. Không có ký tự nào như vậy → kết quả === JSON.stringify như cũ.
const HIDDEN_UNIT = /[\u007f-\u009f\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
/** (h) Trường danh tính bắt buộc ASCII: mọi đơn vị ngoài U+0020–U+007E (JSON.stringify đã escape U+0000–U+001F). */
const NON_ASCII_UNIT = /[^\u0020-\u007e]/g;
const unitEscape = (c: string): string => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`;

/** Chữ JSON (đã JSON.stringify) → escape ký tự vô hình. `asciiOnly` (h): escape mọi ký tự ngoài ASCII. */
export const safeJsonText = (jsonText: string, asciiOnly = false): string =>
  jsonText.replace(asciiOnly ? NON_ASCII_UNIT : HIDDEN_UNIT, unitEscape);

/** Chuỗi → JSON hiển thị an toàn (ca (c), (h)). */
export const visibleJson = (value: string, asciiOnly = false): string => safeJsonText(JSON.stringify(value), asciiOnly);

/** (h) Danh tính phải là ASCII in được: requested_for, params.device_id, phần sau ":" của target. resource_path, software_name
 *  được có tiếng Việt — không áp. */
export const ASCII_IDENTITY_KEYS: ReadonlySet<string> = new Set(["requested_for", "params.device_id", "target"]);
export const hasNonAscii = (s: string): boolean => new RegExp(NON_ASCII_UNIT.source).test(s);

/** (c) Chuỗi phải hiện dạng JSON.stringify (có ngoặc kép, có escape) kể cả khi TẮT. */
export const needsRawFormat = (s: string): boolean => EDGE_SPACE.test(s) || CONTROL.test(s) || INVISIBLE.test(s) || LOOKS_LITERAL.test(s);

/** `target` = "<tiền tố>:<phần sau>" với tiền tố trong bảng → nhãn tiền tố + phần sau GIỮ NGUYÊN. Phần sau rỗng hoặc cần
 *  định dạng gốc (c) → null (dòng hiện như chuỗi không nhãn). */
export function targetParts(raw: string): { prefix: string; rest: string } | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "string") return null;
  const at = value.indexOf(":");
  if (at <= 0) return null;
  const prefix = has(TARGET_PREFIX, value.slice(0, at));
  const rest = value.slice(at + 1);
  return prefix && rest && !needsRawFormat(rest) && !hasNonAscii(rest) ? { prefix, rest } : null;
}
