// Hàm thuần cho màn L1 (B4L1Queue, B4L1Detail, hộp ghi đè). Không gọi mạng, không đọc đồng hồ — `now` truyền vào
// (giờ MÁY CHỦ: api/serverClock.ts). Tên khoá của `action` / `risk` / `facts` KHÔNG được đọc ở đây: phiếu hiện đúng
// object đã băm, đủ mọi khoá (KH 4.2 #5), risk hiện khoá–giá trị chung (F4 P1).
import { NOTE_MAX } from "../../api/approvals.ts";
import { ApiError, errorMessage, routeMissing } from "../../api/errors.ts";
import type {
  ApprovalListItem,
  ApprovalStatus,
  DecisionIn,
  OverrideDecision,
  OverrideIn,
  OverrideReasonCode,
  ReasonCode,
} from "../../api/types.ts";

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

/** Phase 4 chỉ có intent VPN (KH 4.6). Loại lạ → hiện nguyên mã, không đoán nghĩa. */
export const ACTION_LABEL: Record<string, string> = {
  renew_vpn_cert: "Cấp lại chứng chỉ VPN",
  reissue_vpn_access: "Cấp lại truy cập VPN",
};
export const actionLabel = (type: string): string => ACTION_LABEL[type] ?? type;

export const INBOX_MISSING_TITLE = "Hộp thư duyệt có từ Phase 4 (4c)";
export const PLAN_CHANGED_TEXT = "Hành động đã thay đổi sau khi tạo phiếu — không thể duyệt";
export const VIEW_NOT_FOUND_TEXT = "Không tìm thấy phiếu hoặc phiếu không giao cho bạn";
export const BACKUP_TEXT = "Bạn duyệt với vai trò dự phòng";
export const DECISION_SENT = "Đã gửi quyết định";
export const NOTICES_TEXT = "Ghi chú đã được ẩn bớt thông tin nhạy cảm";
/** Màn xem ticket để ghi đè: GET ticket lỗi (vd 404) → câu trung tính, không mã lỗi (Q-fe-24). */
export const TICKET_UNAVAILABLE = "Chưa tải được chi tiết yêu cầu.";

// ---------------------------------------------------------------- Bảng của object đã băm

export type FlatEntry = { key: string; value: string };

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

export function overrideErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return errorMessage(null);
  if (routeMissing(error)) return "Ghi đè có từ Phase 4 (4d) — máy chủ chưa có chức năng này.";
  if (error.status === 404) return "Không tìm thấy ticket hoặc bạn không được xem ticket này.";
  return errorMessage(error);
}

/** Mã ticket nhập tay: ký tự của mã ticket thật (uuid) và mã fixture; ≤ 64 (cột `tickets.ticket_id`). */
export const TICKET_ID_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
