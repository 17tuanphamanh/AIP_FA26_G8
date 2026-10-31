// Hàm thuần cho màn L1 (B4L1Queue, B4L1Detail, hộp ghi đè). Không gọi mạng, không đọc đồng hồ — `now` truyền vào
// (giờ MÁY CHỦ: api/serverClock.ts). Tên khoá của `action` / `risk` / `facts` KHÔNG được đọc ở đây: phiếu hiện đúng
// object đã băm, đủ mọi khoá (KH 4.2 #5), risk hiện khoá–giá trị chung (F4 P1).
import { HUONG_XU_LY, KHAC, luatIT, nhanIT } from "../../lib/nhan.ts";
import { NOTE_MAX } from "../../api/approvals.ts";
import { ApiError, errorMessage } from "../../api/errors.ts";
import type {
  MatchedRule,
  ApprovalAffected,
  ApprovalListItem,
  ApprovalRiskView,
  ApprovalStatus,
  DecisionIn,
  OverrideDecision,
  OverrideIn,
  OverrideReasonCode,
  ReasonCode,
} from "../../api/types.ts";
import { ownEntry } from "../../lib/lookup.ts";

// ---------------------------------------------------------------- hộp thư

/** Sắp theo `deadline` tăng dần (hạn gần nhất trước) — ở client, không tin thứ tự server (F4 P4). Hạn hỏng xuống cuối. */
export function sortByDeadline<T extends Pick<ApprovalListItem, "deadline" | "approval_id">>(items: readonly T[]): T[] {
  const at = (item: T) => {
    const t = Date.parse(item.deadline);
    return Number.isNaN(t) ? Number.POSITIVE_INFINITY : t;
  };
  return [...items].sort((a, b) => at(a) - at(b) || a.approval_id.localeCompare(b.approval_id));
}

/** Đỏ khi thời gian còn lại < 20% của (deadline − created_at) — KH 7 F4. Bằng đúng 20% → chưa đỏ. */
export const URGENT_RATIO = 0.2;

export function remainingMs(deadline: string, now: number): number | null {
  const d = Date.parse(deadline);
  return Number.isNaN(d) ? null : d - now;
}

/** `createdAt` null (chưa biết) hoặc tổng thời gian ≤ 0 → không tô đỏ (không đủ dữ liệu để tính ngưỡng). */
export function isUrgent(createdAt: string | null, deadline: string, now: number): boolean {
  const d = Date.parse(deadline);
  const c = createdAt === null ? Number.NaN : Date.parse(createdAt);
  if (Number.isNaN(d) || Number.isNaN(c) || d - c <= 0) return false;
  return d - now < URGENT_RATIO * (d - c);
}

/** Dòng hộp thư: "còn 4 phút" / "còn dưới 1 phút" / "đã quá hạn". */
export function remainingShort(deadline: string, now: number): string {
  const ms = remainingMs(deadline, now);
  if (ms === null) return "";
  if (ms <= 0) return "đã quá hạn";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "còn dưới 1 phút";
  if (minutes < 60) return `còn ${minutes} phút`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `còn ${hours} giờ ${minutes % 60} phút` : `còn ${Math.floor(hours / 24)} ngày`;
}

const two = (n: number) => String(n).padStart(2, "0");

/** Đồng hồ chi tiết: "Còn 03:58" (+ " / 30 phút" khi biết created_at); quá hạn → "Đã quá hạn". */
export function remainingClock(deadline: string, now: number, createdAt: string | null = null): string {
  const ms = remainingMs(deadline, now);
  if (ms === null) return "";
  if (ms <= 0) return "Đã quá hạn";
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const clock = h > 0 ? `${h}:${two(Math.floor((total % 3600) / 60))}:${two(total % 60)}` : `${two(Math.floor(total / 60))}:${two(total % 60)}`;
  const span = createdAt === null ? Number.NaN : Date.parse(deadline) - Date.parse(createdAt);
  return Number.isNaN(span) || span <= 0 ? `Còn ${clock}` : `Còn ${clock} / ${Math.round(span / 60_000)} phút`;
}

export type InboxTab = "pending" | "decided" | "expired";
export const INBOX_TABS: readonly { tab: InboxTab; label: string; statuses: readonly ApprovalStatus[] }[] = [
  { tab: "pending", label: "Chờ duyệt", statuses: ["pending"] },
  { tab: "decided", label: "Đã quyết", statuses: ["approved", "rejected"] },
  { tab: "expired", label: "Hết hạn", statuses: ["timeout"] },
];

export const STATUS_LABEL: Record<ApprovalStatus, string> = {
  pending: "Chờ duyệt",
  approved: "Đã đồng ý",
  rejected: "Đã từ chối",
  timeout: "Hết hạn — đã chuyển L2",
};

/** Dải chỉ đọc của phiếu đã rời bước duyệt: câu viết riêng từng trạng thái — KHÔNG hạ chữ của nhãn ("L2" giữ hoa). */
const READONLY_STATE: Partial<Record<ApprovalStatus, string>> = {
  approved: "đã đồng ý",
  rejected: "đã từ chối",
  timeout: "hết hạn, đã chuyển L2",
};
export const readonlyText = (status: ApprovalStatus): string =>
  `Phiếu ${ownEntry<string | undefined>(READONLY_STATE, status, undefined) ?? "không còn chờ duyệt"} — chỉ xem, không quyết định được nữa.`;

/** Phase 4 chỉ có intent VPN (KH 4.6). Loại lạ → hiện nguyên mã, không đoán nghĩa. */
export const ACTION_LABEL: Record<string, string> = {
  renew_vpn_cert: "Cấp lại chứng chỉ VPN",
  reissue_vpn_access: "Cấp lại truy cập VPN",
};
/** Hộp thư không biết hành động (`action_type` null — dòng audit B15 không có): dòng VẪN hiện, mở phiếu để xem object. */
export const ACTION_UNKNOWN = "Chưa rõ hành động — mở phiếu để xem";
/** Loại hành động lạ → "Khác · <mã>" (không hiện mã trần một mình — bảng ĐP 23:10). */
export const actionLabel = (type: string | null): string =>
  type === null ? ACTION_UNKNOWN : Object.hasOwn(ACTION_LABEL, type) ? ACTION_LABEL[type]! : `${KHAC} · ${type}`;

/** Nhãn cạnh khoá đã biết của object hành động đã băm (G4-13: khoá + giá trị giữ NGUYÊN; chỉ thêm nhãn). */
export const ACTION_KEY_LABEL: Record<string, string> = {
  type: "Loại hành động",
  target: "Đối tượng",
  requested_for: "Thực hiện cho",
  scope: "Phạm vi",
  privilege_level: "Mức quyền",
  reversible: "Hoàn tác được",
  reversibility: "Mức hoàn tác",
  data_sensitivity: "Độ nhạy dữ liệu",
  params: "Tham số",
  facts: "Dữ kiện",
};
/** Nhãn cho một khoá phẳng (`params.device_id` → nhãn của `params`); khoá lạ → null (chỉ hiện khoá). */
export function actionKeyLabel(key: string): string | null {
  const head = key.split(".")[0] ?? key;
  return Object.hasOwn(ACTION_KEY_LABEL, head) ? ACTION_KEY_LABEL[head]! : null;
}

/** Hộp thư đã có dữ liệu nhưng lần tải lại gần nhất lỗi (Q-fe-38): giữ danh sách cũ, báo có thể đã cũ + câu lỗi. */
export const INBOX_STALE_TEXT = "Chưa cập nhật được hộp thư — danh sách dưới đây có thể đã cũ.";
/** Đang ở tab khác "Chờ duyệt" mà truy vấn `pending` (nuôi số đếm trên tab — tín hiệu duy nhất về phiếu mới) tải lại lỗi. */
export const INBOX_COUNT_STALE_TEXT = "Chưa cập nhật được số phiếu chờ duyệt — con số trên tab có thể đã cũ.";

/** Ô thông tin không có giá trị (phòng ban null, vai trò rỗng). */
export const MISSING_VALUE = "—";

export const PLAN_CHANGED_TEXT = "Hành động đã thay đổi sau khi tạo phiếu — không thể duyệt";
export const VIEW_NOT_FOUND_TEXT = "Không tìm thấy phiếu hoặc phiếu không giao cho bạn";
export const BACKUP_TEXT = "Bạn duyệt với vai trò dự phòng";
export const VIEWER_TEXT = "Bạn đang xem phiếu này với quyền giám sát — không thể quyết định.";
export const RISK_MISSING_TEXT = "Chưa có đánh giá rủi ro cho phiếu này.";

/**
 * Vai trò của tôi với phiếu (`role_as` của xem phiếu). Chỉ `primary` / `backup` được quyết; `viewer` và MỌI giá trị lạ
 * → `viewer` (fail-closed: không hiện đường quyết định khi không chắc). Server vẫn là nơi quyết quyền (403).
 */
export function decisionRole(roleAs: unknown): "primary" | "backup" | "viewer" {
  return roleAs === "primary" || roleAs === "backup" ? roleAs : "viewer";
}
// ---------------------------------------------------------------- người bị ảnh hưởng, mức rủi ro, hạn (F6 #76, R3 #76)

/** Quản lý chưa biết (`manager.status = "unknown"`): backend gộp "không có sếp" và "không biết" làm một → KHÔNG BAO GIỜ viết
 *  "không có quản lý". */
export const MANAGER_UNKNOWN_TEXT = "Chưa rõ quản lý";
/** Sếp có trong `manager_id` nhưng chưa từng đăng nhập nên chưa có tên. */
export const MANAGER_NO_NAME_TEXT = "(chưa có tên)";
export const AFFECTED_OTHER_TEXT = "Khác người gửi yêu cầu";
export const AFFECTED_SELF_TEXT = "Chính người gửi yêu cầu";

export const RISK_LEVEL_LABEL: Record<ApprovalRiskView["risk_level"], string> = { low: "Thấp", medium: "Trung bình", high: "Cao" };
/** Hướng xử lý, bên quyết định: nhãn từ src/lib/nhan.ts (bảng ĐP 26/10 23:10) — màn hiện "Nhãn · mã" (MaNhan). */
export const RISK_ROUTE_LABEL = HUONG_XU_LY;
/** Điểm LLM chưa qua hiệu chỉnh: xác suất không dùng để tự xử lý — chữ của FE (backend chỉ trả cờ). */
export const UNCALIBRATED_TEXT = "Chưa hiệu chỉnh, không tự xử lý";

type Pair = { nhan: string; ma: string; goiY?: string };
export type RiskSummary = { level: string; route: Pair; reason: string; rule: Pair | null; source: Pair; note: string | null };

/**
 * Tóm tắt `risk_view` cho người duyệt. Hướng xử lý / bên quyết định: "Nhãn · mã" (mã lạ → "Khác · mã"). Luật khớp: "Mô tả ·
 * R18" — mô tả lấy từ `matched_rules` của phiếu (luật cùng id), không có → "Luật chưa có mô tả · R18".
 */
export function riskSummary(view: ApprovalRiskView, rules: readonly MatchedRule[] = []): RiskSummary {
  const ruleId = view.matched_rule_id;
  return {
    level: ownEntry<string>(RISK_LEVEL_LABEL, view.risk_level, view.risk_level),
    route: nhanIT("huong_xu_ly", view.route),
    reason: view.reason,
    rule: ruleId === null ? null : luatIT(ruleId, rules.find((r) => r.rule_id === ruleId)?.description),
    source: nhanIT("ben_quyet_dinh", view.decided_by),
    note: view.decided_by === "llm" && !view.calibrated ? UNCALIBRATED_TEXT : null,
  };
}

/** Quản lý của người bị ảnh hưởng thành một dòng chữ. */
export function managerText(manager: ApprovalAffected["manager"]): string {
  if (manager.status !== "known") return MANAGER_UNKNOWN_TEXT;
  const id = manager.user_id ?? MISSING_VALUE;
  return manager.full_name ? `${manager.full_name} (${id})` : `${id} ${MANAGER_NO_NAME_TEXT}`;
}

const VN_TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Ho_Chi_Minh",
  hour: "2-digit",
  minute: "2-digit",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hourCycle: "h23",
});

/** Mốc hạn tuyệt đối theo giờ Việt Nam ("21:30 30/09/2026"); null / chuỗi không phải thời điểm → null (không hiện). Ghép từ
 *  từng phần của Intl nên không phụ thuộc dấu phân cách của từng bản ICU. */
export function deadlineText(deadline: unknown): string | null {
  if (typeof deadline !== "string") return null;
  const ms = Date.parse(deadline);
  if (Number.isNaN(ms)) return null;
  const p = Object.fromEntries(VN_TIME.formatToParts(new Date(ms)).map((part) => [part.type, part.value]));
  return `${p.hour}:${p.minute} ${p.day}/${p.month}/${p.year}`;
}

export const DECISION_SENT = "Đã gửi quyết định";
export const NOTICES_TEXT = "Ghi chú đã được ẩn bớt thông tin nhạy cảm";
/** Màn xem ticket để ghi đè: GET ticket lỗi (vd 404) → câu trung tính, không mã lỗi (Q-fe-24). */
export const TICKET_UNAVAILABLE = "Chưa tải được chi tiết yêu cầu.";

// ---------------------------------------------------------------- Bảng của object đã băm

export type FlatEntry = { key: string; value: string };

/** Giá trị ngắn (≤ ngần này ký tự HIỂN THỊ, gồm ngoặc kép của chuỗi JSON) không ngắt giữa chừng: không vừa cạnh khoá thì
 *  CẢ giá trị xuống dòng dưới (lỗi F4: dấu `"` cuối của `"approval_required"` rơi riêng một dòng ở cột 360 px). */
export const SHORT_VALUE_MAX = 24;
export const isShortValue = (value: string): boolean => [...value].length <= SHORT_VALUE_MAX;

/**
 * Trải phẳng ĐỦ mọi khoá (đệ quy): object lồng → "cha.con", mảng → "cha[0]"; object/mảng rỗng giữ một dòng "{}" / "[]"
 * (không lược bớt). Tên khoá giữ nguyên. Giá trị lá viết như JSON (chuỗi có ngoặc kép) — cùng nghĩa với tab JSON.
 */
export function flattenEntries(value: unknown, prefix = ""): FlatEntry[] {
  if (Array.isArray(value)) {
    if (value.length === 0) return [{ key: prefix, value: "[]" }];
    return value.flatMap((v, i) => flattenEntries(v, `${prefix}[${i}]`));
  }
  if (value !== null && typeof value === "object") {
    const keys = Object.keys(value);
    if (keys.length === 0) return [{ key: prefix, value: "{}" }];
    return keys.flatMap((k) => flattenEntries((value as Record<string, unknown>)[k], prefix ? `${prefix}.${k}` : k));
  }
  return [{ key: prefix, value: value === undefined ? "undefined" : JSON.stringify(value) }];
}

// ---------------------------------------------------------------- quyết định

/** Nhãn theo Bản 4 (B4L1Detail); thứ tự = `ReasonCode` ở backend/app/api/approvals.py. */
export const REJECT_REASONS: readonly { value: ReasonCode; label: string }[] = [
  { value: "missing_info", label: "Thiếu thông tin" },
  { value: "not_authorized", label: "Không có thẩm quyền" },
  { value: "policy_violation", label: "Trái chính sách" },
  { value: "duplicate", label: "Yêu cầu trùng" },
  { value: "wrong_device", label: "Sai thiết bị" },
  { value: "security_concern", label: "Lo ngại bảo mật" },
  { value: "other", label: "Khác" },
];

/** Từ chối: bắt buộc chọn lý do VÀ có ghi chú (backend 422 `rejected_requires_note`). Trả câu lỗi, null = gửi được. */
export function rejectProblem(reason: ReasonCode | null, note: string): string | null {
  if (reason === null) return "Chọn lý do từ chối.";
  const text = note.trim();
  if (!text) return "Nhập lý do gửi người dùng (bắt buộc).";
  if (text.length > NOTE_MAX) return `Lý do tối đa ${NOTE_MAX} ký tự.`;
  return null;
}

// ---------------------------------------------------------------- chống duyệt theo phản xạ (P10 §3.2 "Nên có", F6 P3)

/** Xem phiếu chưa tới ngần này giây mà bấm "Đồng ý thực hiện" → hỏi xác nhận lại. Hằng DUY NHẤT của ngưỡng. */
export const REFLEX_MIN_SECONDS = 5;

/** Số giây đã xem, đo bằng `performance.now()` (đồng hồ đơn điệu — chỉnh giờ máy giữa chừng không làm sai). Chưa có
 *  mốc bắt đầu → 0 (coi như chưa xem: hỏi lại). Chỉ để giao diện hỏi lại; body quyết định KHÔNG đổi — server tự tính
 *  thời gian xem từ `first_viewed_at` (graph/nodes/approval_wait.py), `view_started_at` chỉ để log. */
export const viewedSeconds = (startedAt: number | null, now: number): number =>
  startedAt === null ? 0 : Math.max(0, (now - startedAt) / 1000);

export const isReflex = (seconds: number): boolean => seconds < REFLEX_MIN_SECONDS;

export const reflexText = (seconds: number): string =>
  `Bạn mới xem phiếu này ${Math.max(1, Math.floor(seconds))} giây. Đã kiểm tra hành động, đối tượng và mã băm chưa?`;

export const approveBody = (viewStartedAt: string | null): DecisionIn =>
  viewStartedAt ? { decision: "approved", view_started_at: viewStartedAt } : { decision: "approved" };

export function rejectBody(reason: ReasonCode, note: string, viewStartedAt: string | null): DecisionIn {
  const body: DecisionIn = { decision: "rejected", reason_code: reason, note: note.trim() };
  return viewStartedAt ? { ...body, view_started_at: viewStartedAt } : body;
}

// ---------------------------------------------------------------- ghi đè (4d)

/** Đủ 4 lựa chọn — client không biết quyết định gốc (server tự suy, 4d P3); trùng → 422 `same_as_original` (Q-fe-10). */
export const OVERRIDE_OPTIONS: readonly { value: OverrideDecision; title: string; desc: string }[] = [
  { value: "AUTO", title: "Tự xử lý", desc: "Hệ thống được làm luôn, không cần người duyệt" },
  { value: "HITL", title: "Cần người duyệt", desc: "Phải có IT duyệt trước khi làm" },
  { value: "L2", title: "Chuyển L2", desc: "Kỹ thuật viên L2 xử lý tay" },
  { value: "ANSWER", title: "Chỉ trả lời", desc: "Hướng dẫn, không thực hiện hành động" },
];

export const OVERRIDE_REASONS: readonly { value: OverrideReasonCode; label: string }[] = [
  { value: "too_risky_for_auto", label: "Quá rủi ro để tự xử lý" },
  { value: "approval_unnecessary", label: "Không cần duyệt" },
  { value: "should_not_escalate", label: "Không nên chuyển L2" },
  { value: "wrong_answer", label: "Trả lời sai" },
  { value: "policy_gap", label: "Chính sách còn thiếu" },
  { value: "other", label: "Khác" },
];

/** Ghi chú bắt buộc khi lý do "Khác" (4d P2), luôn ≤ 1000. Trả câu lỗi, null = gửi được. */
export function overrideProblem(decision: OverrideDecision | null, reason: OverrideReasonCode | null, note: string): string | null {
  if (decision === null) return "Chọn quyết định đúng cho ticket này.";
  if (reason === null) return "Chọn lý do ghi đè.";
  const text = note.trim();
  if (reason === "other" && !text) return "Lý do “Khác” cần ghi chú.";
  if (text.length > NOTE_MAX) return `Ghi chú tối đa ${NOTE_MAX} ký tự.`;
  return null;
}

/** Body đúng khoá của `OverrideIn` (backend `extra="forbid"`); ghi chú rỗng → bỏ hẳn khoá `note`. */
export function overrideBody(decision: OverrideDecision, reason: OverrideReasonCode, note: string): OverrideIn {
  const text = note.trim();
  return text ? { override_decision: decision, reason_code: reason, note: text } : { override_decision: decision, reason_code: reason };
}

export const OVERRIDE_DONE = "Đã ghi nhận ghi đè.";
export const OVERRIDE_ORIGINAL_PREFIX = "Quyết định ban đầu của hệ thống: ";
export const OVERRIDE_NOTE_INVALID = "Ghi chú không hợp lệ hoặc trống sau khi ẩn thông tin nhạy cảm — hãy viết lại ghi chú.";
/** 403 `forbidden`: không có quyền HOẶC người gửi tự ghi đè — cùng một mã, client không phân biệt được (4d). */
export const OVERRIDE_FORBIDDEN = "Bạn không được ghi đè ticket này (không có quyền, hoặc đây là ticket do chính bạn gửi).";
export const OVERRIDE_NOT_FOUND = "Không tìm thấy ticket hoặc bạn không được xem ticket này.";

/** Nhãn của một quyết định ghi đè (như hộp chọn); giá trị lạ / thiếu → null — không đoán. */
export const overrideDecisionLabel = (value: unknown): string | null =>
  OVERRIDE_OPTIONS.find((option) => option.value === value)?.title ?? null;

/** 422 `invalid_request` vì ghi chú (thiếu khi "Khác", quá dài, hoặc rỗng sau khi che). Backend trả `note`; `errors.ts` đã
 *  bỏ tiền tố `body.` — nhận cả hai cho chắc. */
const NOTE_FIELDS: ReadonlySet<string> = new Set(["note", "body.note"]);
export const noteRejected = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 422 && error.code === "invalid_request" && error.fields.some((f) => NOTE_FIELDS.has(f));

export function overrideErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return errorMessage(null);
  if (noteRejected(error)) return OVERRIDE_NOTE_INVALID;
  if (error.status === 403 && error.code === "forbidden") return OVERRIDE_FORBIDDEN;
  if (error.status === 404) return OVERRIDE_NOT_FOUND; // kể cả "Not Found" (không có route) — không còn trang "có từ…"
  return errorMessage(error);
}

/** Lỗi của hộp ghi đè: câu + chỗ gắn (`note` → ngay dưới ô ghi chú; null → dòng lỗi chung). */
export const overrideFailure = (error: unknown): { text: string; field: "note" | null } => ({
  text: overrideErrorMessage(error),
  field: noteRejected(error) ? "note" : null,
});

/** Mã ticket nhập tay: ký tự của mã ticket thật (uuid) và mã fixture; ≤ 64 (cột `tickets.ticket_id`). */
export const TICKET_ID_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
