// Trạng thái ticket cho NHÂN VIÊN (KH mục 5, 4.2): nhãn thường, KHÔNG BAO GIỜ hiện mã `S_*`; E0 (`S_BLOCKED`) chỉ câu
// trung tính, không chữ nào gợi ý đã phát hiện tấn công [Chốt 7.1]. 14 trạng thái: backend/app/domain/states.py.
import type { TicketView } from "../../api/types.ts";
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
  S_PENDING_APPROVAL: "Đang chờ IT duyệt",
  S_CONFIRMING: "Chờ bạn xác nhận kết quả",
  S_ESCALATED: "Đã chuyển kỹ thuật viên hỗ trợ",
  S_RESOLVED: "Đã hoàn tất",
  S_REJECTED: "Yêu cầu không được duyệt",
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
export function pollDelay(view: Pick<TicketView, "final_state" | "waiting_for"> | undefined): number | false {
  if (view?.final_state) return false;
  return view?.waiting_for ? POLL_WAITING_MS : POLL_PROCESSING_MS;
}
