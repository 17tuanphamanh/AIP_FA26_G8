// Hàm thuần cho màn L2 (B4L2Queue, B4L2Detail). Thứ tự hàng đợi: backend ĐÃ sắp theo `priority`, `created_at`,
// `escalation_id` với `priority` lấy từ bảng seed `exit_code_priority` — nguồn duy nhất (B20 §5.1). Frontend KHÔNG sắp
// lại và KHÔNG giữ bảng ưu tiên/nhãn/màu theo mã E nào của riêng mình: chỉ gom các dòng LIÊN TIẾP cùng `priority`.
import { CLOSE_NOTE_MAX } from "../../api/escalations.ts";
import type { EscalationCloseResult, EscalationQueueItem, HandoffNote } from "../../api/types.ts";
import { labelOf } from "../../lib/lookup.ts";

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
/** Chi tiết ca đã đóng (`?status=closed`) không có trong các trang đã tải và không còn trang nào. */
export const CLOSED_GONE_TEXT = "Không tìm thấy ca đã đóng này";
/** Chi tiết: không thấy ca trong các trang ĐÃ tải mà server còn trang (`next_cursor`) → KHÔNG khẳng định là đã đóng. */
export const notLoadedText = (n: number): string => `Không tìm thấy ca trong ${n} ca đã tải`;
export const NOT_LOADED_NOTE = "Ca có thể nằm ở phần chưa tải — bấm “Tải thêm” để tải tiếp danh sách.";

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
const CLOSE_TITLE: Record<string, string> = Object.fromEntries(CLOSE_OPTIONS.map((o) => [o.value, o.title]));
/** Nhãn kết quả đóng theo khoá (đã kiểm enum ở api/escalations.ts; khoá lạ → hiện nguyên). */
export const closeResultLabel = (value: string): string => labelOf(CLOSE_TITLE, value);

export const CLOSED_TEXT = "Đã đóng ca — ca đã rời danh sách Mở.";
export const ALREADY_CLOSED_TEXT = "Ca đã được đóng";
export const CLOSE_UNAVAILABLE_TEXT = "Chức năng đóng ca chưa bật ở máy chủ này.";

export const STATUS_TABS: readonly { key: "open" | "closed"; label: string }[] = [
  { key: "open", label: "Mở" },
  { key: "closed", label: "Đã đóng" },
];

/**
 * Lý do KHOÁ "Đã hoàn tất" (null = mở):
 * - `is_deny_case` (mọi E5 — backend/app/audit/handoff.py): B20 [Chốt] nguyên tắc 5, server trả 422.
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

// ---- Tìm nhanh + phân trang trong nhóm (phía trình duyệt, CHỈ trên các ca đã tải; không sắp lại thứ tự server) ----

/** Cỡ trang trong MỘT nhóm của hàng đợi. */
export const GROUP_PAGE_SIZE = 10;
/** Ô tìm tối đa 100 ký tự. Chữ tìm chỉ dùng để so chuỗi — không thành RegExp, không dựng HTML. */
export const SEARCH_MAX = 100;
/** Đang tìm mà server còn trang chưa tải (`next_cursor`) → nói rõ phạm vi tìm. */
export const searchScopeNote = (loaded: number): string => ` · chỉ tìm trong ${loaded} ca đã tải`;
export const NO_MATCH_TEXT = "Không có ca nào khớp ô tìm";
/** 0 ca khớp khi còn trang chưa tải: KHÔNG khẳng định ca không tồn tại. */
export const noMatchPartialText = (loaded: number): string =>
  `Không có ca nào khớp trong ${loaded} ca đã tải — ca cần tìm có thể nằm ngoài danh sách.`;

/** Chữ thường, bỏ dấu tiếng Việt, đ → d: gõ "an ninh" khớp "An ninh", "tu choi" khớp "từ chối". */
export function foldText(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[đĐ]/g, "d")
    .toLowerCase()
    .trim();
}

/** Các từ của ô tìm (đã `foldText`). Rỗng = không tìm. Dùng chung cho "đang tìm" và bộ lọc. */
export function searchWords(query: string): string[] {
  return foldText(query).split(/\s+/).filter(Boolean);
}

/** Chuỗi để tìm của một ca: mã E, nhãn nhóm, lý do (1 dòng), mã ticket, số ca, người đang xử lý. */
export function searchText(item: EscalationQueueItem): string {
  return foldText(
    [item.exit_code, item.label, reasonLine(item), item.ticket_id, `#${item.escalation_id}`, item.assigned_to ?? ""].join(" "),
  );
}

/** Lọc theo ô tìm: MỌI từ (cách nhau bằng khoảng trắng) phải có trong `searchText`. Ô trống → giữ nguyên. Giữ thứ tự server. */
export function filterQueue(items: readonly EscalationQueueItem[], query: string): EscalationQueueItem[] {
  const words = searchWords(query);
  if (words.length === 0) return [...items];
  return items.filter((item) => {
    const hay = searchText(item);
    return words.every((w) => hay.includes(w));
  });
}

export function pageCount(total: number, size = GROUP_PAGE_SIZE): number {
  return Number.isFinite(total) && total > 0 ? Math.ceil(total / size) : 1;
}

/** Trang hợp lệ gần nhất (số ca đổi sau khi lọc / tự tải lại → trang đang đứng có thể vượt trang cuối). Không phải số hữu
 *  hạn → 1; số lẻ → cắt phần lẻ. */
export function clampPage(page: number, total: number, size = GROUP_PAGE_SIZE): number {
  if (!Number.isFinite(page)) return 1;
  return Math.min(Math.max(1, Math.trunc(page)), pageCount(total, size));
}

/** Trạng thái xem hàng đợi — CHỈ trong bộ nhớ, khoá theo `priority`: nhóm thu gọn, trang đang đứng (vắng = trang 1), thẻ
 *  nhóm đang chọn (null = "Tất cả"). */
export type QueueView = {
  collapsed: ReadonlySet<number>;
  pages: Readonly<Record<number, number>>;
  active: number | null;
};
/** Mặc định: mọi nhóm mở, trang 1, thẻ "Tất cả". */
export const EMPTY_VIEW: QueueView = { collapsed: new Set<number>(), pages: {}, active: null };

/**
 * Dọn trạng thái xem theo danh sách `list` vừa tải: nhóm không còn → bỏ khỏi `collapsed` và `pages` (hết ca rồi có ca mới
 * thì nhóm sinh ra MỞ, trang 1); trang vượt trang cuối → LƯU trang hợp lệ gần nhất (nhóm lớn lại không tự nhảy về trang
 * cũ); thẻ đang chọn không còn → "Tất cả". Không có gì đổi → trả CHÍNH `view` (màn so tham chiếu, không setState lặp).
 */
export function pruneQueueView(view: QueueView, list: readonly EscalationQueueItem[]): QueueView {
  const sizes = new Map<number, number>();
  for (const group of groupQueue(list)) sizes.set(group.priority, Math.max(sizes.get(group.priority) ?? 0, group.items.length));
  const collapsed = [...view.collapsed].filter((priority) => sizes.has(priority));
  const pages: Record<number, number> = {};
  for (const [key, page] of Object.entries(view.pages)) {
    const size = sizes.get(Number(key));
    if (size !== undefined) pages[Number(key)] = clampPage(page, size);
  }
  const active = view.active !== null && sizes.has(view.active) ? view.active : null;
  const samePages =
    Object.keys(pages).length === Object.keys(view.pages).length &&
    Object.entries(pages).every(([key, page]) => view.pages[Number(key)] === page);
  if (collapsed.length === view.collapsed.size && samePages && active === view.active) return view;
  return { collapsed: new Set(collapsed), pages, active };
}

// ---- Ca mới ở nhóm đang khuất (Q-fe-43): thẻ nhóm + thu gọn có thể che ca mới đến lúc tự tải lại → con số là tín hiệu duy
// nhất, nên báo thành một dòng riêng. Chỉ theo trạng thái ĐÃ LƯU; "nằm ở trang sau" KHÔNG tính (ca mới vốn ở cuối nhóm, đã có
// "· N ca" + thanh trang). Không dùng bảng hạng ưu tiên nào ở frontend.

/** Nhóm `priority` có bị che theo trạng thái đã lưu: đang thu gọn, hoặc đang chọn thẻ của nhóm khác. */
export function isHidden(priority: number, view: QueueView): boolean {
  return view.collapsed.has(priority) || (view.active !== null && view.active !== priority);
}

export const NO_IDS: ReadonlySet<number> = new Set<number>();

/**
 * Tập `escalation_id` của ca mới còn phải báo. `before` = danh sách chưa lọc lần trước (null = lần tải đầu → không ca nào là
 * mới), `after` = danh sách chưa lọc hiện tại, `view` = trạng thái đã lưu. Ca mới = có trong `after`, không có trong `before`
 * (so theo id) và đang khuất → thêm (cộng dồn). Ca đã báo mà nay hiện ra (tự mở nhóm / đổi thẻ) hoặc rời hàng đợi → bỏ HẲN (ẩn
 * lại sau đó không báo lại). Không đổi → trả đúng `missed` (màn so tham chiếu, không setState lặp).
 */
export function trackMissed(
  missed: ReadonlySet<number>,
  before: readonly EscalationQueueItem[] | null,
  after: readonly EscalationQueueItem[],
  view: QueueView,
): ReadonlySet<number> {
  const old = before === null ? null : new Set(before.map((item) => item.escalation_id));
  const next = new Set<number>();
  for (const item of after) {
    if (!isHidden(item.priority, view)) continue;
    const id = item.escalation_id;
    if (missed.has(id) || (old !== null && !old.has(id))) next.add(id);
  }
  if (next.size === missed.size && [...next].every((id) => missed.has(id))) return missed;
  return next;
}
