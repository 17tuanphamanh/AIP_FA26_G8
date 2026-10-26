// NHÃN TẠM — thay bằng tên trong docs/bao-cao/chi-so-phuong-an.md (file định nghĩa chỉ số của Dương, hợp đồng N-PA §2).
// Tab "So sánh phương án" tra nhãn theo KHOÁ server trả (`labelOf`): khoá lạ → hiện nguyên khoá. Thứ tự dòng là thứ tự
// server — bảng này KHÔNG quyết thứ tự.
import { labelOf } from "../../lib/lookup.ts";

export const METRIC_LABEL: Record<string, string> = {
  tickets: "Số yêu cầu đã kết thúc",
  auto_rate: "Hệ thống tự xử lý",
  hitl_rate: "Qua L1 duyệt",
  l2_rate: "Chuyển L2",
  confirmed_rate: "Người dùng xác nhận đã xong",
  no_response_rate: "Tự đóng vì không phản hồi sau 48 giờ",
  unresolved_rate: "Người dùng báo chưa xong (E8)",
  l1_reject_rate: "L1 từ chối",
  quick_approve_rate: "Duyệt dưới 5 giây hoặc chưa mở phiếu",
  system_time_p50: "Thời gian hệ thống xử lý — trung vị",
  system_time_p90: "Thời gian hệ thống xử lý — p90",
  human_wait_p50: "Thời gian chờ người — trung vị",
  human_minutes_per_100: "Phút người xử lý mỗi 100 yêu cầu",
  e5_recheck_failed: "Ca bị bác ở bước kiểm lại (B17)",
  overrides: "Số lần ghi đè",
  rollbacks: "Số lần hoàn tác",
  llm_cost_per_ticket: "Chi phí LLM mỗi yêu cầu",
};

/** Loại yêu cầu (`intent_mix`) — như backend/app/domain/messages.py; khoá lạ → hiện nguyên. */
export const INTENT_LABEL: Record<string, string> = { vpn: "VPN", account: "Tài khoản", software: "Phần mềm", access: "Quyền truy cập" };

export const metricLabel = (key: string): string => labelOf(METRIC_LABEL, key);
export const intentLabel = (key: string): string => labelOf(INTENT_LABEL, key);
