// Trạng thái ticket cho NHÂN VIÊN (KH mục 5, 4.2): nhãn thường, KHÔNG BAO GIỜ hiện mã `S_*`; E0 (`S_BLOCKED`) chỉ câu
// trung tính, không chữ nào gợi ý đã phát hiện tấn công [Chốt 7.1]. 14 trạng thái: backend/app/domain/states.py. 4 trạng thái
// kết thúc đổi theo bảng từ ngữ ĐP 26/10 23:10 (NGU-1: "Đã giải quyết", "Đã chuyển kỹ thuật viên", "Chờ IT duyệt", "Bị từ chối").
import type { HandlingView, TicketView } from "../../api/types.ts";
import { ownEntry } from "../../lib/lookup.ts";

export const STATUS_LABEL: Readonly<Record<string, string>> = {
  S_NEW: "Đang tiếp nhận yêu cầu",
  S_SCREENING: "Đang tiếp nhận yêu cầu",
  S_CLASSIFYING: "Đang tiếp nhận yêu cầu",
  S_DIAGNOSING: "Đang kiểm tra hệ thống",
  S_RETRIEVING: "Đang tra cứu hướng dẫn",
  S_ASSESSING: "Đang đánh giá yêu cầu",
  S_EXECUTING: "Đang thực hiện",
  S_CLARIFYING: "Cần bạn bổ sung thông tin",
  S_PENDING_APPROVAL: "Chờ IT duyệt",
  S_CONFIRMING: "Chờ bạn xác nhận kết quả",
  S_ESCALATED: "Đã chuyển kỹ thuật viên",
  S_RESOLVED: "Đã giải quyết",
  S_REJECTED: "Bị từ chối",
  S_BLOCKED: "Yêu cầu này không thể xử lý tự động",
};

/** Trạng thái lạ (backend thêm sau) → câu chung, không lộ mã. */
export const UNKNOWN_STATUS_LABEL = "Đang xử lý yêu cầu";

export function statusLabel(status: string | null | undefined): string {
  return (status && ownEntry(STATUS_LABEL, status, "")) || UNKNOWN_STATUS_LABEL;
}

/** Câu dưới hội thoại khi ticket đã kết thúc (B4EmpStates). Nhãn nào không có ở đây → dùng `statusLabel`. */
export const FINAL_NOTE: Readonly<Record<string, string>> = {
  S_RESOLVED: "Yêu cầu đã hoàn tất. Cần thêm gì, bạn tạo yêu cầu mới nhé.",
  S_ESCALATED: "Kỹ thuật viên sẽ liên hệ bạn để hỗ trợ tiếp.",
  S_REJECTED: "Yêu cầu không được duyệt. Lý do (nếu có) nằm trong cuộc trò chuyện ở trên.",
  S_BLOCKED: "Yêu cầu này không thể xử lý tự động. Vui lòng liên hệ bộ phận IT nếu bạn vẫn cần hỗ trợ.",
};

/** Kiểm thử 12/11: ca đã chuyển kỹ thuật viên mà L2 ĐÃ đóng (`close_reason` của B20 4.3) — câu cũ "Kỹ thuật viên sẽ liên hệ bạn…" không
 *  còn đúng, cuộc trò chuyện cũng không có tin nào (thông báo đóng ca chỉ ở chuông). Câu trung tính, đúng cho cả 3 kết quả đóng và ca
 *  nghi tấn công (như `NEUTRAL_TEXT` của backend/app/api/notifications.py) — không đoán kết quả cụ thể. */
export const L2_CLOSED_NOTE = "Bộ phận IT đã xem xét xong yêu cầu này. Kết quả có trong thông báo (biểu tượng chuông).";
const L2_CLOSE_REASONS: ReadonlySet<string> = new Set(["resolved_after_escalation", "resolved_after_deny_review"]);

// D-99 (17/11): tiến độ xử lý của bộ phận IT (`TicketView.handling`) — câu theo bước, lời nhắn của IT (đã qua cổng ở server) nối sau.
export const HANDLING_TEXT = {
  waiting: "Yêu cầu đang chờ kỹ thuật viên nhận xử lý.",
  claimed2: "Kỹ thuật viên đã nhận yêu cầu và đang xử lý.",
  claimed3: "Trưởng bộ phận IT đã nhận yêu cầu và đang xử lý.",
  raised_it_manager: "Yêu cầu cần Trưởng bộ phận IT quyết định nên kỹ thuật viên đã chuyển lên cấp cao hơn. Kết quả sẽ báo bạn tại đây.",
  raised_vendor: "Yêu cầu cần bộ phận chuyên trách hoặc nhà cung cấp xử lý nên kỹ thuật viên đã chuyển tiếp. Kết quả sẽ báo bạn tại đây.",
  completed: "Bộ phận IT đã xử lý xong yêu cầu này.",
  confirmed_denial: "Bộ phận IT đã xem xét và xác nhận không thực hiện yêu cầu này.",
  reopened_new: "Kỹ thuật viên đã mở lại yêu cầu thành một yêu cầu mới, hệ thống đang xử lý lại từ đầu.",
  reopened: "Kỹ thuật viên đề nghị bạn gửi một yêu cầu mới cho việc này.",
} as const;
export const HANDLING_MESSAGE_PREFIX = "Lời nhắn từ bộ phận IT:";

export function handlingText(h: HandlingView): string {
  let base: string;
  if (h.stage === "waiting") base = HANDLING_TEXT.waiting;
  else if (h.stage === "claimed") base = h.tier === 3 ? HANDLING_TEXT.claimed3 : HANDLING_TEXT.claimed2;
  else if (h.stage === "raised") base = h.raise_target === "vendor" ? HANDLING_TEXT.raised_vendor : HANDLING_TEXT.raised_it_manager;
  else if (h.close_result === "completed") base = HANDLING_TEXT.completed;
  else if (h.close_result === "confirmed_denial") base = HANDLING_TEXT.confirmed_denial;
  else base = h.new_ticket_id ? HANDLING_TEXT.reopened_new : HANDLING_TEXT.reopened;
  const msg = h.stage === "closed" ? h.user_message?.trim() : "";
  return msg ? `${base} ${HANDLING_MESSAGE_PREFIX} ${msg}` : base;
}

/** Câu ở khối kết thúc của ticket lá (ticket cha dùng câu riêng). D-99: ticket đã chuyển IT mà có `handling` → câu theo bước xử lý. */
export function finalNoteOf(view: Pick<TicketView, "final_state" | "close_reason"> & { handling?: HandlingView[] | null }): string {
  const state = view.final_state ?? "";
  const last = state === "S_ESCALATED" ? view.handling?.at(-1) : undefined;
  if (last) return handlingText(last);
  if (state === "S_ESCALATED" && view.close_reason != null && L2_CLOSE_REASONS.has(view.close_reason)) return L2_CLOSED_NOTE;
  return ownEntry(FINAL_NOTE, state, statusLabel(state));
}

/** D-99: ticket đã kết thúc nhưng bộ phận IT còn đang xử lý (có ca chưa đóng) → hỏi lại chậm để thấy bước mới. */
export const POLL_HANDLING_MS = 30_000;
const handlingOpen = (view: { handling?: HandlingView[] | null }): boolean => !!view.handling?.some((h) => h.stage !== "closed");

/** Màu chấm (KH mục 5): cam = chờ con người, xanh lá = xong, xám = đã chuyển / không xử lý, xanh FPT = đang chạy. */
export type Tone = "processing" | "waiting" | "done" | "closed";

export function statusTone(view: Pick<TicketView, "final_state" | "waiting_for"> | undefined): Tone {
  if (view?.final_state) return view.final_state === "S_RESOLVED" ? "done" : "closed";
  if (view?.waiting_for) return "waiting";
  return "processing";
}

export const POLL_PROCESSING_MS = 2_000;
export const POLL_WAITING_MS = 10_000;

/** Nhịp polling [Chốt P10 §3.1]: 2 s khi đang xử lý, 10 s khi chờ người (`waiting_for ≠ null`), DỪNG khi có `final_state`. */
export function pollDelay(
  view: (Pick<TicketView, "final_state" | "waiting_for"> & { handling?: HandlingView[] | null }) | undefined,
): number | false {
  if (view?.final_state) return handlingOpen(view) ? POLL_HANDLING_MS : false;
  return view?.waiting_for ? POLL_WAITING_MS : POLL_PROCESSING_MS;
}
