// NHÃN TẠM — thay bằng tên trong docs/bao-cao/chi-so-phuong-an.md (file định nghĩa chỉ số của Dương, hợp đồng N-PA §2).
// Tab "So sánh phương án" tra nhãn theo KHOÁ server trả (`labelOf`): khoá lạ → hiện nguyên khoá. Thứ tự dòng là thứ tự
// server — bảng này KHÔNG quyết thứ tự.
import { labelOf } from "../../lib/lookup.ts";

export const METRIC_LABEL: Record<string, string> = {
  tickets: "Số yêu cầu đã kết thúc",
  auto_rate: "Hệ thống tự xử lý",
  hitl_rate: "Qua L1 duyệt",
  l2_rate: "Chuyển L2 ở bước đánh giá rủi ro", // B2 (12/11): khác "Chuyển L2" tab Nghiệp vụ — xem METRIC_HINT
  confirmed_rate: "Người dùng xác nhận đã xong",
  no_response_rate: "Tự đóng vì không phản hồi sau 48 giờ",
  unresolved_rate: "Người dùng báo chưa giải quyết",
  l1_reject_rate: "L1 từ chối",
  quick_approve_rate: "Duyệt dưới 5 giây hoặc chưa mở phiếu",
  system_time_p50: "Thời gian hệ thống xử lý — trung vị",
  system_time_p90: "Thời gian hệ thống xử lý — p90",
  human_wait_p50: "Thời gian chờ người — trung vị",
  human_minutes_per_100: "Phút người xử lý mỗi 100 yêu cầu",
  // Ba chỉ số đếm — nhãn theo ĐƠN VỊ ĐẾM của backend/app/monitor/queries/strategies.py: `e5_recheck_failed`, `rollbacks` đếm SỐ LÁ
  // (mỗi yêu cầu tính một lần); `overrides` cộng SỐ DÒNG audit OVERRIDE/override_recorded (một yêu cầu có thể bị ghi đè nhiều lần).
  e5_recheck_failed: "Số yêu cầu kiểm tra lại trước khi thực hiện không đạt",
  overrides: "Số lần ghi đè",
  rollbacks: "Số yêu cầu đã thử hoàn tác", // gồm cả `partial`, `undo_failed` (ROLLBACK_DONE ở strategies.py)
  llm_cost_per_ticket: "Chi phí LLM mỗi yêu cầu",
};

/** Loại yêu cầu (`intent_mix`) — như backend/app/domain/messages.py; khoá lạ → hiện nguyên. */
export const INTENT_LABEL: Record<string, string> = {
  vpn: "VPN",
  account: "Tài khoản",
  software: "Phần mềm",
  access: "Quyền truy cập",
  it_help: "Hỏi đáp IT", // gọn 13/11 (TA): trước hiện khoá thô
  none: "Chưa phân loại (bị chặn / ngoài phạm vi)",
};

/** Một dòng chú thích dưới nhãn — chỉ cho chỉ số dễ hiểu nhầm (B2, soát 12/11 agent 20 L3). Không đổi số. */
export const METRIC_HINT: Record<string, string> = {
  l2_rate: "Chỉ đếm ca bước đánh giá rủi ro (M5) quyết định chuyển L2 — khác “Chuyển L2” ở tab Nghiệp vụ (mọi ca kết thúc bằng mã E).",
};

export const metricLabel = (key: string): string => labelOf(METRIC_LABEL, key);
export const metricHint = (key: string): string | null => (Object.hasOwn(METRIC_HINT, key) ? METRIC_HINT[key]! : null);
export const intentLabel = (key: string): string => labelOf(INTENT_LABEL, key);
