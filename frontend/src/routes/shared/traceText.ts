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
import { BEN_QUYET_DINH, nhanIT } from "../../lib/nhan.ts";
import { closeResultLabel } from "../l2/queue.ts";

export const TRACE_TITLE = "Nhật ký quyết định";
export const TRACE_FORBIDDEN_TEXT = "Bạn không có quyền xem nhật ký quyết định. Trang này dành cho L1, L2 và Trưởng bộ phận IT.";
export const TRACE_NOT_FOUND_TEXT = "Không tìm thấy yêu cầu này, hoặc bạn không được xem nhật ký của nó.";
export const TRACE_INVALID_TEXT = "Máy chủ trả nhật ký không đúng dạng — không hiển thị để tránh hiểu sai.";
export const TRACE_BAD_ID_TEXT = "Mã yêu cầu không hợp lệ.";
export const TRACE_EMPTY_TEXT = "Yêu cầu này chưa có bước nào được ghi nhật ký.";

// Bước + sự kiện: nhãn từ src/lib/nhan.ts (nguồn chữ duy nhất — bảng ĐP 26/10 23:10). Màn hiện thêm mã chữ nhỏ (MaNhan).
export const stepName = (step: string): string => nhanIT("buoc", step).nhan;
export const eventText = (event: string): string => nhanIT("su_kien", event).nhan;
/** Chữ đầu viết thường khi nhãn đứng giữa câu (giữ nguyên từ viết tắt: "IT", "AI", "VPN"…). */
const giuaCau = (t: string): string => (t.length > 1 && t[1] === t[1]!.toLocaleUpperCase("vi") && /\p{L}/u.test(t[1]!) ? t : t.charAt(0).toLocaleLowerCase("vi") + t.slice(1));

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
  const head = `Phân loại: ${c.intent === null ? "chưa rõ" : nhanIT("loai_yeu_cau", c.intent).nhan}`;
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

/** Tiêu đề thẻ chính sách — KHÔNG mã luật (mã + mô tả hiện riêng ở dòng "Luật", dạng "Mô tả · R18"). */
export function policyLine(p: PolicyInfo): string {
  if (p.decided_by === "rule" || (p.decided_by === null && p.policy_decision !== null)) {
    const decision = p.policy_decision === null ? "chưa rõ" : labelOf(DECISION, p.policy_decision);
    return `Đánh giá rủi ro: ${decision} — ${giuaCau(BEN_QUYET_DINH.rule!)}`;
  }
  const risk = p.risk_level === null ? "chưa rõ rủi ro" : labelOf(RISK, p.risk_level);
  return `Đánh giá rủi ro: ${risk} — ${p.decided_by === "llm" ? `${giuaCau(BEN_QUYET_DINH.llm!)} (không luật nào khớp)` : "chưa rõ bên quyết định"}`;
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

/** Mã lạ trong câu (không dựng được component) → "Khác · mã" — không hiện mã trần một mình. */
const orKhac = (table: Record<string, string>, key: string): string => (Object.hasOwn(table, key) ? table[key]! : `Khác · ${key}`);

export function executionLine(e: ExecutionInfo): string {
  const action = e.action === null ? "chưa rõ hành động" : orKhac(ACTION, e.action);
  const result = e.success === null ? "chưa rõ kết quả" : e.success ? "thành công" : "thất bại";
  return `Thực thi: ${action} — ${result}`;
}
export const rollbackText = (e: ExecutionInfo): string | null =>
  e.rollback_status === null ? null : `Hoàn tác: ${orKhac(ROLLBACK, e.rollback_status)}`;

/** Tiêu đề thẻ kết cục — mã kết thúc hiện riêng ("Nhãn · E5", MaNhan) ở dòng dưới. */
/** Thẻ B20. Lô N (N7): dòng `escalation_closed` (route null) có `close_result` → "L2 đã đóng ca · <nhãn đóng ca của màn L2>". */
export function outcomeLine(o: OutcomeInfo): string {
  if (o.route === null && o.close_result != null) return `Kết cục: L2 đã đóng ca · ${giuaCau(closeResultLabel(o.close_result))}`;
  const route = o.route === null ? "chưa rõ" : giuaCau(nhanIT("duong_xu_ly", o.route).nhan);
  return `Kết cục: ${route}`;
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
  return `${stepName(s.step)}: ${giuaCau(eventText(s.event))}`;
}

/** Câu lỗi tải: 403 và 404 có câu riêng; thân sai hình dạng (502 `invalid_trace_body`) có câu riêng; còn lại theo mã. */
export function traceErrorText(error: unknown): string {
  const api = error instanceof ApiError ? error : null;
  if (api?.status === 403) return TRACE_FORBIDDEN_TEXT;
  if (api?.status === 404) return TRACE_NOT_FOUND_TEXT;
  if (api?.status === 502 && api.code === "invalid_trace_body") return TRACE_INVALID_TEXT;
  return errorMessage(api);
}
