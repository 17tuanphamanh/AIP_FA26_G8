// Hàm thuần cho màn L2 (B4L2Queue, B4L2Detail). Thứ tự hàng đợi: backend ĐÃ sắp theo `priority`, `created_at`,
// `escalation_id` với `priority` lấy từ bảng seed `exit_code_priority` — nguồn duy nhất (B20 §5.1). Frontend KHÔNG sắp
// lại và KHÔNG giữ bảng ưu tiên/nhãn/màu theo mã E nào của riêng mình: chỉ gom các dòng LIÊN TIẾP cùng `priority`.
import { CLOSE_NOTE_MAX, QUEUE_LIMIT } from "../../api/escalations.ts";
import type { EscalationCloseResult, EscalationQueueItem, HandoffNote } from "../../api/types.ts";

/** Nhãn seed có thể kèm phần phụ sau dấu phẩy ("Thường, cần bổ sung KB") → tên nhóm "Thường" + huy hiệu trên dòng. */
export function splitLabel(label: string): { base: string; extra: string | null } {
  const comma = label.indexOf(",");
  if (comma < 0) return { base: label.trim(), extra: null };
  const extra = label.slice(comma + 1).trim();
  return {
    base: label.slice(0, comma).trim(),
    extra: extra ? extra.charAt(0).toLocaleUpperCase("vi") + extra.slice(1) : null,
  };
}

export type QueueGroup = { priority: number; name: string; items: EscalationQueueItem[] };

/** Gom dòng LIÊN TIẾP cùng `priority`, giữ nguyên thứ tự server. Cùng hạng mà khác nhãn (seed: E2 "Hạ tầng", E9 "Lỗi hệ
 *  thống" cùng hạng 4) → tên nhóm nối các nhãn gốc khác nhau theo thứ tự xuất hiện. */
export function groupQueue(items: readonly EscalationQueueItem[]): QueueGroup[] {
  const groups: QueueGroup[] = [];
  for (const item of items) {
    const last = groups.at(-1);
    if (last && last.priority === item.priority) last.items.push(item);
    else groups.push({ priority: item.priority, name: "", items: [item] });
  }
  for (const group of groups) {
    group.name = [...new Set(group.items.map((i) => splitLabel(i.label).base))].join(" / ");
  }
  return groups;
}

/** "chờ N phút" tính từ `created_at` (giờ máy chủ) tới `now` (lần tải hàng đợi gần nhất). Lệch đồng hồ âm → "vừa xong". */
export function waitingText(createdAt: string, now: number): string {
  const created = Date.parse(createdAt);
  if (Number.isNaN(created)) return "";
  const minutes = Math.floor((now - created) / 60_000);
  if (minutes < 1) return "chờ dưới 1 phút";
  if (minutes < 60) return `chờ ${minutes} phút`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `chờ ${hours} giờ`;
  return `chờ ${Math.floor(hours / 24)} ngày`;
}

export const EMPTY_NOTE = "(không có)";
/** Chi tiết: ca không còn trong hàng đợi (đã đóng, hoặc id sai) — P2. */
export const GONE_TEXT = "Ca đã đóng hoặc không còn trong hàng đợi";
/** Chi tiết: không thấy ca mà hàng đợi đã đủ `QUEUE_LIMIT` ca → có thể ca nằm ngoài giới hạn, KHÔNG khẳng định là đã đóng
 *  (server sắp ca cũ trước; escalation chưa đóng được tới Phase 7 nên hàng đợi dev dài dần). */
export const OVERFLOW_TEXT = `Không tìm thấy ca trong ${QUEUE_LIMIT} ca đầu của hàng đợi`;
export const OVERFLOW_NOTE =
  `Hàng đợi đang quá ${QUEUE_LIMIT} ca (màn chỉ tải tối đa ${QUEUE_LIMIT}) — ca này có thể nằm ngoài giới hạn hoặc đã đóng. ` +
  "Xem riêng một ca có ở Phase 7.";

export const HANDOFF_FIELDS: readonly { key: keyof HandoffNote; label: string }[] = [
  { key: "request", label: "Yêu cầu (đã che)" },
  { key: "done_so_far", label: "Agent đã làm" },
  { key: "why_escalated", label: "Lý do chuyển" },
  { key: "next_for_l2", label: "Việc cần làm" },
];

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);

/** Một phần của ghi chú bàn giao dưới dạng CHỮ THÔ (không Markdown, không HTML). Thiếu / rỗng / không phải chuỗi → null. */
export function noteText(note: unknown, key: keyof HandoffNote): string | null {
  const value = isRecord(note) ? note[key] : undefined;
  return typeof value === "string" && value.trim() ? value : null;
}

/** 4 khối ghi chú bàn giao đúng thứ tự B20 §4.2; `text = null` → hiện "(không có)". */
export function handoffRows(note: unknown): { key: keyof HandoffNote; label: string; text: string | null }[] {
  return HANDOFF_FIELDS.map((f) => ({ ...f, text: noteText(note, f.key) }));
}

/** Tóm tắt 1 dòng cho hàng đợi: `why_escalated` gộp khoảng trắng (CSS cắt phần thừa). */
export function reasonLine(item: EscalationQueueItem): string {
  const text = noteText(item.handoff_note, "why_escalated") ?? item.reason_detail ?? EMPTY_NOTE;
  return text.replace(/\s+/g, " ").trim();
}

export const DENY_BADGE = "E5 — không thực hiện lại";
export const DENY_BANNER = {
  strong: "Ca E5 — không thực hiện lại hành động.",
  rest: "Chỉ xác nhận từ chối hoặc mở ticket mới.",
};

export const CLOSE_OPTIONS: readonly { value: EscalationCloseResult; title: string; desc: string }[] = [
  { value: "completed", title: "Đã hoàn tất", desc: "L2 đã làm xong việc agent định làm" },
  { value: "confirmed_denial", title: "Xác nhận từ chối", desc: "Giữ nguyên quyết định không thực hiện" },
  { value: "reopened_as_new", title: "Mở ticket mới", desc: "Chạy lại từ đầu, liên kết ticket này" },
];

/**
 * Lý do KHOÁ "Đã hoàn tất" (null = mở):
 * - `is_deny_case` (mọi E5 — backend/app/audit/handoff.py): B20 [Chốt] nguyên tắc 5, 422 ở Phase 7.
 * - E6 (hết hạn duyệt): B20 §4.3 + decisions.md mục 2 Q2 [Chốt] — L2 không hoàn tất tay (12b Q-fe-21).
 */
export function completedLock(item: Pick<EscalationQueueItem, "is_deny_case" | "exit_code">): string | null {
  if (item.is_deny_case) return "Không dùng với ca E5 — không thực hiện lại hành động";
  if (item.exit_code === "E6") return "Không dùng với ca hết hạn duyệt (E6) — L2 không hoàn tất tay";
  return null;
}

/** Kiểm form đóng TRƯỚC khi gửi. Trả câu lỗi, hoặc null khi gửi được. */
export function closeProblem(result: EscalationCloseResult | null, note: string, lock: string | null): string | null {
  if (result === null) return "Chọn một kết quả đóng.";
  if (result === "completed" && lock !== null) return `“Đã hoàn tất” bị khoá: ${lock}.`;
  const text = note.trim();
  if (!text) return "Nhập ghi chú đóng (bắt buộc).";
  if (text.length > CLOSE_NOTE_MAX) return `Ghi chú đóng tối đa ${CLOSE_NOTE_MAX} ký tự.`;
  return null;
}
