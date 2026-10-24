// Chữ của màn "Nhật ký quyết định" (TicketTrace.tsx) — hàm thuần, test riêng. Mọi bảng nhãn tra bằng `labelOf` (khoá
// riêng của object — mã "constructor" từ server không đụng prototype); mã lạ hiện NGUYÊN mã, không đoán nghĩa. Số xác suất
// đã làm tròn 2 số ở backend; ở đây chỉ in theo kiểu Việt Nam (dấu phẩy thập phân).
import { ApiError, errorMessage } from "../../api/errors.ts";
import type {
  ApprovalInfo,
  ClassifyInfo,
  ExecutionInfo,
  OutcomeInfo,
  PolicyInfo,
  ScreenInfo,
  TraceStep,
} from "../../api/trace.ts";
import { labelOf } from "../../lib/lookup.ts";

export const TRACE_TITLE = "Nhật ký quyết định";
export const TRACE_FORBIDDEN_TEXT = "Bạn không có quyền xem nhật ký quyết định. Trang này dành cho L1, L2 và Trưởng bộ phận IT.";
export const TRACE_NOT_FOUND_TEXT = "Không tìm thấy ticket này, hoặc bạn không được xem nhật ký của nó.";
export const TRACE_INVALID_TEXT = "Máy chủ trả nhật ký không đúng dạng — không hiển thị để tránh hiểu sai.";
export const TRACE_BAD_ID_TEXT = "Mã ticket không hợp lệ.";
export const TRACE_EMPTY_TEXT = "Ticket này chưa có bước nào được ghi nhật ký.";

const STEP_NAME: Record<string, string> = {
  B1: "Xác thực người gửi",
  B2: "Kiểm tra tấn công",
  B3: "Phân loại",
  B4: "Phân loại",
  B5: "Tách nhiều ý",
  B6: "Chẩn đoán",
  B7: "Chẩn đoán",
  B8: "Tra cứu KB",
  B9: "Kiểm tra căn cứ",
  B10: "Định tuyến",
  B11: "Dựng hành động",
  "B13/B14": "Chính sách",
  B15: "Gửi duyệt",
  B16: "Duyệt",
  B17: "Thực thi",
  B18: "Thực thi",
  B20: "Kết cục",
  OVERRIDE: "Ghi đè",
};
export const stepName = (step: string): string => labelOf(STEP_NAME, step);

const EVENT: Record<string, string> = {
  identity_established: "đã xác thực",
  diagnosed: "đã chẩn đoán",
  diagnosis_skipped: "bỏ qua chẩn đoán",
  retrieved: "đã tra cứu",
  needs_action: "cần thực hiện hành động",
  deflected_info_only: "trả lời hướng dẫn",
  no_evidence: "không đủ căn cứ trong KB",
  action_built: "đã dựng hành động",
  asked: "hỏi thêm người dùng",
  risk_decided: "đã quyết định",
  queued: "đã gửi phiếu duyệt",
  approved: "đã đồng ý",
  rejected: "đã từ chối",
  approval_timeout: "hết hạn duyệt",
  executed_ok: "thành công",
  exec_failed: "thất bại",
  ticket_closed: "đã đóng",
};
export const eventText = (event: string): string => labelOf(EVENT, event);

/** 0,03 — luôn 2 chữ số thập phân. */
export const formatProb = (p: number): string =>
  p.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const TIME = new Intl.DateTimeFormat("vi-VN", {
  timeZone: "Asia/Ho_Chi_Minh",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});
/** Giờ Việt Nam, vd "08:09:00 26/09/2099". */
export const formatAt = (iso: string): string => TIME.format(new Date(iso));

const LAYER: Record<string, string> = { regex: "mẫu regex", model: "model", llm: "LLM" };
const SCREEN: Record<string, string> = {
  safe: "an toàn",
  attack: "phát hiện tấn công — đã chặn",
  suspected: "nghi ngờ — chuyển L2",
  unavailable: "chưa kiểm tra được — chuyển L2",
};

export function screenLine(s: ScreenInfo): string {
  const verdict = s.decision === null ? "chưa rõ kết quả" : labelOf(SCREEN, s.decision);
  const p = s.p_injection === null ? "" : ` (model ${formatProb(s.p_injection)})`;
  return `Kiểm tra tấn công: ${verdict}${p}`;
}
export const screenLayer = (s: ScreenInfo): string | null => (s.layer === null ? null : `Lớp quyết định: ${labelOf(LAYER, s.layer)}`);

export function classifyLine(c: ClassifyInfo): string {
  const parts: string[] = [];
  if (c.confidence !== null) parts.push(`LLM ${formatProb(c.confidence)}`);
  const model = c.intent !== null && c.model_probs !== null ? ownProb(c.model_probs, c.intent) : null;
  if (model !== null) parts.push(`model ${formatProb(model)}`);
  const head = `Phân loại: ${c.intent ?? "chưa rõ"}`;
  const multi = c.is_multi ? " · nhiều ý" : "";
  return `${head}${parts.length ? ` — ${parts.join(", ")}` : ""}${multi}`;
}

const ownProb = (probs: Record<string, number>, key: string): number | null => (Object.hasOwn(probs, key) ? probs[key]! : null);

const DECISION: Record<string, string> = {
  allow: "tự xử lý",
  approval_required: "cần duyệt",
  deny: "không được phép — chuyển L2",
};
const RISK: Record<string, string> = { low: "rủi ro thấp", medium: "rủi ro trung bình", high: "rủi ro cao" };

export function policyLine(p: PolicyInfo): string {
  if (p.decided_by === "rule" || (p.decided_by === null && p.policy_decision !== null)) {
    const decision = p.policy_decision === null ? "chưa rõ" : labelOf(DECISION, p.policy_decision);
    const rule = p.rule_id === null ? "" : ` — luật ${p.rule_id}${p.rule_description ? ` (${p.rule_description})` : ""}`;
    return `Chính sách: ${decision}${rule}`;
  }
  const risk = p.risk_level === null ? "chưa rõ rủi ro" : labelOf(RISK, p.risk_level);
  return `Chính sách: ${risk} — ${p.decided_by === "llm" ? "mô hình ước lượng (không luật nào khớp)" : "chưa rõ ai quyết"}`;
}

export function policyProbs(p: PolicyInfo): string | null {
  const parts: string[] = [];
  if (p.raw_prob !== null) parts.push(`p rủi ro thô ${formatProb(p.raw_prob)}`);
  if (p.calibrated_prob !== null) parts.push(`đã hiệu chỉnh ${formatProb(p.calibrated_prob)}`);
  return parts.length ? parts.join(" · ") : null;
}

const APPROVAL: Record<string, string> = {
  pending: "chờ duyệt",
  approved: "đã đồng ý",
  rejected: "đã từ chối",
  timeout: "hết hạn — chuyển L2",
};

export function approvalLine(a: ApprovalInfo, step: string): string {
  const who = a.approver_name ?? a.approver_id ?? "chưa rõ người duyệt";
  const result = a.result === null ? "chưa rõ kết quả" : labelOf(APPROVAL, a.result);
  const head = step === "B15" ? "Gửi duyệt" : "Duyệt";
  return `${head}: ${result} — ${who}${a.approver_name && a.approver_id ? ` (${a.approver_id})` : ""}`;
}

const ACTION: Record<string, string> = {
  renew_vpn_cert: "gia hạn chứng chỉ",
  reissue_vpn_access: "cấp lại truy cập VPN",
  check_vpn_status: "kiểm tra trạng thái VPN",
  reset_password: "đặt lại mật khẩu",
  unlock_account: "mở khoá tài khoản",
  install_software: "cài phần mềm",
  view_permissions: "xem quyền truy cập",
  grant_permission: "cấp quyền truy cập",
  extend_permission: "gia hạn quyền truy cập",
};
const ROLLBACK: Record<string, string> = {
  undone: "đã hoàn tác",
  partial: "hoàn tác một phần",
  undo_failed: "hoàn tác thất bại",
  not_attempted: "chưa hoàn tác",
  none_needed: "không cần hoàn tác",
};

export function executionLine(e: ExecutionInfo): string {
  const action = e.action === null ? "chưa rõ hành động" : labelOf(ACTION, e.action);
  const result = e.success === null ? "chưa rõ kết quả" : e.success ? "thành công" : "thất bại";
  return `Thực thi: ${action} — ${result}`;
}
export const rollbackText = (e: ExecutionInfo): string | null =>
  e.rollback_status === null ? null : `Hoàn tác: ${labelOf(ROLLBACK, e.rollback_status)}`;

const ROUTE: Record<string, string> = {
  auto: "tự động xử lý",
  approved: "xử lý sau khi duyệt",
  rejected: "bị từ chối",
  escalated: "chuyển L2",
  deflected: "trả lời hướng dẫn",
};

export function outcomeLine(o: OutcomeInfo): string {
  const route = o.route === null ? "chưa rõ" : labelOf(ROUTE, o.route);
  return `Kết cục: ${route}${o.exit_code ? ` — mã ${o.exit_code}` : ""}`;
}

/** Dòng tiêu đề của một thẻ. Bước không có trường chi tiết → "<tên bước>: <sự kiện>". */
export function stepTitle(s: TraceStep): string {
  if (s.screen) return screenLine(s.screen);
  if (s.classify) return classifyLine(s.classify);
  if (s.policy) return policyLine(s.policy);
  if (s.approval) return approvalLine(s.approval, s.step);
  if (s.execution) return executionLine(s.execution);
  if (s.outcome) return outcomeLine(s.outcome);
  if (s.diagnose) return `Chẩn đoán: dùng ${s.diagnose.fact_keys.length} dữ kiện`;
  return `${stepName(s.step)}: ${eventText(s.event)}`;
}

/** Câu lỗi tải: 403 và 404 có câu riêng; thân sai hình dạng (502 `invalid_trace_body`) có câu riêng; còn lại theo mã. */
export function traceErrorText(error: unknown): string {
  const api = error instanceof ApiError ? error : null;
  if (api?.status === 403) return TRACE_FORBIDDEN_TEXT;
  if (api?.status === 404) return TRACE_NOT_FOUND_TEXT;
  if (api?.status === 502 && api.code === "invalid_trace_body") return TRACE_INVALID_TEXT;
  return errorMessage(api);
}
