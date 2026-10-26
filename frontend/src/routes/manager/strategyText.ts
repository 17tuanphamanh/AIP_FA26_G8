// Chữ của khối "Cách xử lý của hệ thống" (D-60) và tên chiến lược dùng chung cho tab "So sánh phương án". Hàm thuần.
// Tên 3 lựa chọn ĐÚNG D-60 mục 2. Mô tả TRUNG TÍNH (không khen/chê phương án nào — D-60: các lựa chọn chỉ khác nhau ở
// khối lượng việc của người), đối chiếu backend/app/risk/strategy.py.
import { REASON_MAX, REASON_MIN, reasonLength } from "../../api/strategy.ts";
import type { RuntimeStrategy } from "../../api/types.ts";
import { labelOf } from "../../lib/lookup.ts";

export const STRATEGY_HEADING = "Cách xử lý của hệ thống";

export const STRATEGY_OPTIONS: readonly { key: RuntimeStrategy; title: string; desc: string }[] = [
  { key: "rule_only", title: "Chỉ dùng luật", desc: "Bảng luật quyết định; yêu cầu không khớp luật nào được chuyển người duyệt." },
  { key: "hybrid", title: "Kết hợp luật và LLM (mặc định)", desc: "Có luật khớp thì luật quyết định; không khớp luật nào thì LLM ước lượng." },
  {
    key: "hybrid_guarded",
    title: "LLM xét mọi yêu cầu, luật làm lớp chặn cuối",
    desc: "Luật cần duyệt hoặc cấm được giữ nguyên; các yêu cầu còn lại LLM xét thêm và chỉ có thể nâng mức cần người.",
  },
];

const STRATEGY_NAME: Record<string, string> = Object.fromEntries(STRATEGY_OPTIONS.map((o) => [o.key, o.title]));
/** Tên hiển thị theo khoá chiến lược; khoá lạ → hiện nguyên khoá. */
export const strategyName = (key: string): string => labelOf(STRATEGY_NAME, key);

/** Lựa chọn dùng lớp LLM — có nhãn "chưa hiệu chỉnh" khi `llm_calibrated` không phải `true`. */
export const USES_LLM: ReadonlySet<string> = new Set(["hybrid", "hybrid_guarded"]);
export const UNCALIBRATED_TEXT = "Lớp AI chưa hiệu chỉnh: không tự xử lý";
/** Thiếu khoá `llm_calibrated` → coi như CHƯA hiệu chỉnh (hợp đồng N-PA §1). */
export const showUncalibrated = (key: string, calibrated: boolean | undefined): boolean => USES_LLM.has(key) && calibrated !== true;

export const NOT_SELECTABLE_TEXT = "Máy chủ không cho chọn phương án này khi vận hành.";
export const EVAL_MODE_TEXT =
  "Hệ thống đang ở chế độ đánh giá. Lựa chọn ở đây chưa được áp dụng cho tới khi tắt chế độ đánh giá.";
export const READONLY_TEXT = "Bạn chỉ có quyền xem cách xử lý.";
export const STRATEGY_MISSING_TEXT = "Máy chủ chưa có chức năng chọn cách xử lý.";
export const REASON_LABEL = `Lý do đổi (bắt buộc, ${REASON_MIN}–${REASON_MAX} ký tự)`;
export const SAME_AS_CURRENT_TEXT = "Phương án này đang được áp dụng";
/** PUT trả 2xx khác 200 hoặc 200 thân sai hình: server có thể đã ghi → không báo thành công, tải lại. */
export const UNCONFIRMED_TEXT = "Chưa xác nhận được kết quả — đang tải lại trạng thái hiện tại.";
export const HISTORY_HEADING = "Lịch sử đổi cách xử lý";
export const HISTORY_EMPTY_TEXT = "Chưa có lần đổi nào.";
export const HISTORY_TRUNCATED_TEXT = "Chỉ hiện 50 lần đổi gần nhất.";
export const appliedText = (key: string): string => `Đã áp dụng: ${strategyName(key)}.`;

/** Lỗi của ô lý do TRƯỚC khi gửi (null = gửi được). Không nhắc lại nội dung người dùng gõ. */
export function reasonProblem(reason: string): string | null {
  const n = reasonLength(reason);
  if (n < REASON_MIN) return `Lý do cần ít nhất ${REASON_MIN} ký tự (hiện có ${n}).`;
  if (n > REASON_MAX) return `Lý do tối đa ${REASON_MAX} ký tự (hiện có ${n}).`;
  return null;
}
