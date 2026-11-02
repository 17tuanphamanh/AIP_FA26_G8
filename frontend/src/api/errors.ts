import { ownEntry } from "../lib/lookup.ts";

// Lỗi HTTP → thông báo tiếng Việt (KH mục 5; 12b Q-fe-3). Backend trả HAI dạng thân lỗi:
//   {detail: "<mã hoặc câu>"}                  — HTTPException, AuthError, 409 sự kiện muộn, 413
//   {error: "<mã>", fields?: ["body.text", …]}  — 422 kiểm dữ liệu (`invalid_request`), 503 privacy guard
// (backend/app/api/errors.py). Thân lỗi không bao giờ chứa giá trị người dùng gửi (chống rò qua 422).
// F7 (route thật `POST /api/policy/validate`, backend/app/api/policy.py): 422 `invalid_policy` kèm `errors: [{loc, msg}]`
// (dạng lỗi Pydantic, `loc` tính từ gốc nội dung chính sách) → `issues`.

export class ApiError extends Error {
  readonly status: number;
  /** `detail` hoặc `error` của thân lỗi; null khi thân rỗng / không phải JSON. */
  readonly code: string | null;
  /** 422 `invalid_request`: vị trí trường đã bỏ tiền tố `body.` (vd `text`). */
  readonly fields: string[];
  /** Giây, từ header `Retry-After` (503 `ticket_busy`). */
  readonly retryAfter: number | null;
  /** 422 `invalid_policy`: lỗi theo vị trí trong nội dung (chỉ phần tử đúng dạng `{loc, msg}`). */
  readonly issues: Issue[];

  constructor(status: number, code: string | null, fields: string[] = [], retryAfter: number | null = null, issues: Issue[] = []) {
    super(`HTTP ${status}${code ? ` ${code}` : ""}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.retryAfter = retryAfter;
    this.issues = issues;
  }
}

export type Issue = { loc: (string | number)[]; msg: string };

function parseIssues(raw: unknown): Issue[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (item === null || typeof item !== "object") return [];
    const { loc, msg } = item as Record<string, unknown>;
    if (typeof msg !== "string" || !Array.isArray(loc)) return [];
    if (!loc.every((part) => typeof part === "string" || (typeof part === "number" && Number.isInteger(part)))) return [];
    return [{ loc: loc as (string | number)[], msg }];
  });
}

export function parseErrorBody(body: unknown): { code: string | null; fields: string[]; issues: Issue[] } {
  if (body !== null && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.detail === "string") return { code: b.detail, fields: [], issues: [] };
    if (typeof b.error === "string") {
      const fields = Array.isArray(b.fields) ? b.fields.filter((f): f is string => typeof f === "string") : [];
      return { code: b.error, fields: fields.map((f) => f.replace(/^body\./, "")), issues: parseIssues(b.errors) };
    }
  }
  return { code: null, fields: [], issues: [] };
}

/** Starlette trả `{"detail":"Not Found"}` khi KHÔNG có route; route thật của repo dùng mã thường (`not_found`). */
export const routeMissing = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 404 && error.code === "Not Found";

export async function readApiError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // thân rỗng hoặc không phải JSON (vd proxy trả HTML) — chỉ còn mã HTTP
  }
  const { code, fields, issues } = parseErrorBody(body);
  const retryAfter = Number(res.headers.get("Retry-After"));
  return new ApiError(res.status, code, fields, Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null, issues);
}

// Mã máy của backend → câu cho người dùng. Mã lạ: 409 có thể là câu tiếng Việt sẵn (`LateEvent.message`).
const CODE_MESSAGES: Record<string, string> = {
  reauth_required: "Cần đăng nhập lại để xác nhận thao tác này.",
  privacy_guard_unavailable: "Chưa gửi được — hệ thống kiểm tra nội dung đang bận, vui lòng thử lại.",
  ticket_busy: "Hệ thống đang bận, sẽ tự thử lại.",
  // Tạo ticket khi chưa đọc được phương án xử lý (hợp đồng sửa lần 3, ĐP 26/10 23:51): 503, KHÔNG tự gửi lại (api/tickets.ts).
  strategy_unavailable: "Hệ thống tạm thời chưa nhận yêu cầu, vui lòng thử lại sau ít phút.",
  payload_too_large: "Nội dung quá dài.",
  // Đóng escalation (B20 §4.3; hợp đồng N-PA §4 — route be-tuan8, hiện chỉ MSW trả).
  already_closed: "Ca đã được đóng",
  invalid_queue_body: "Hàng đợi trả về không đúng dạng — không hiển thị để tránh hiểu sai. Vui lòng tải lại trang.",
  deny_case_cannot_complete:
    "Không đóng được: ca không đủ điều kiện tự xử lý không được chọn “Đã hoàn tất”. Chỉ xác nhận từ chối hoặc mở yêu cầu mới.",
  escalation_not_found: "Ca đã đóng hoặc không còn trong hàng đợi.",
  // Duyệt (backend/app/api/approvals.py) + xem phiếu (4c P6).
  rejected_requires_note: "Từ chối cần ghi chú lý do gửi người dùng.",
  plan_changed: "Hành động đã thay đổi sau khi tạo phiếu — không thể duyệt",
  // Phiếu thiếu / sai kiểu người bị ảnh hưởng hoặc mức rủi ro — api/approvals.ts `parseApprovalView` (502 do client đặt, fail-closed).
  invalid_approval_body: "Phiếu trả về thiếu hoặc sai thông tin người bị ảnh hưởng / mức rủi ro nên không hiện để duyệt. Vui lòng tải lại trang.",
  // Ghi đè (4d P1–P4; KH 4.6, 12b Q-fe-10).
  ticket_open: "Yêu cầu chưa kết thúc — chỉ ghi đè được yêu cầu đã đóng.",
  already_overridden: "Bạn đã ghi đè yêu cầu này rồi — mỗi người chỉ ghi đè một yêu cầu một lần.",
  same_as_original: "Quyết định bạn chọn trùng với quyết định ban đầu của hệ thống — hãy chọn quyết định khác.",
  // Tổng quan / cảnh báo (M9: thiếu kết nối monitor → 503, fail-closed — KH mục 5 dòng dashboard).
  monitor_unavailable: "Số liệu tạm thời không có",
  // Ticket nhiều ý (T20b): `children_progress` / tin tổng hợp sai hình dạng — api/tickets.ts `parseTicketView` (502 do client đặt).
  invalid_ticket_body: "Chưa đọc được dữ liệu của yêu cầu này. Vui lòng tải lại trang.",
  // Chính sách (F7 — chỉ có validate; `version_conflict` của Lưu bỏ cùng nút, N-POL2 thêm lại theo route thật).
  invalid_policy: "Chính sách chưa hợp lệ — xem các dòng được đánh dấu.",
  // Cách xử lý của hệ thống + So sánh phương án (D-67; hợp đồng N-PA §1–2).
  same_as_current: "Phương án này đang được áp dụng",
  invalid_strategy_body: "Máy chủ trả cách xử lý không đúng dạng — không hiển thị để tránh hiểu sai.",
  invalid_strategy_history_body: "Máy chủ trả lịch sử đổi không đúng dạng — không hiển thị để tránh hiểu sai.",
  invalid_strategies_body: "Số liệu so sánh trả về không đúng dạng — không hiển thị để tránh hiểu sai.",
  strategies_source_mismatch: "Số liệu trả về không đúng nguồn đã chọn — không hiển thị để tránh hiểu sai.",
};

export function errorMessage(error: ApiError | null): string {
  if (error === null) return "Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.";
  // Khoá riêng: mã "constructor" / "__proto__" của server là mã lạ, không phải hàm của prototype.
  const known = error.code ? ownEntry<string | null>(CODE_MESSAGES, error.code, null) : null;
  if (known) return known;
  switch (error.status) {
    case 401:
      return "Phiên đăng nhập đã hết. Vui lòng đăng nhập lại.";
    case 403:
      return "Bạn không có quyền thực hiện thao tác này.";
    case 404:
      return "Không tìm thấy.";
    case 409:
      return error.code?.includes(" ") ? error.code : "Yêu cầu đã chuyển sang bước khác.";
    case 413:
      return "Nội dung quá dài.";
    case 422:
      return "Dữ liệu chưa hợp lệ — kiểm tra lại các ô được đánh dấu.";
    case 429:
      return "Thao tác quá nhanh, thử lại sau.";
    case 503:
      return "Hệ thống đang bận, vui lòng thử lại sau.";
    default:
      return "Có lỗi xảy ra, vui lòng thử lại.";
  }
}

// Đăng nhập (P6 §4): sai tên/mật khẩu/OTP, tài khoản khoá hay ngừng hoạt động đều là MỘT câu chung — chống dò
// username. Chỉ `mfa_not_enrolled` có câu riêng (chỉ tới được sau khi mật khẩu đúng — 12b Q-fe-3).
export const GENERIC_LOGIN_ERROR = "Tên đăng nhập hoặc mật khẩu không đúng.";
/** Ô trống ở bước mật khẩu (soát 01/11 M1, M2 — ĐP 02/11): báo ngay, KHÔNG gửi request. */
export const EMPTY_USERNAME = "Nhập tên đăng nhập.";
export const EMPTY_PASSWORD = "Nhập mật khẩu.";
/** Sai mã ở bước OTP (soát 01/11 M3 — ĐP quyết 02/11). Chỉ tới được bước này khi mật khẩu đã đúng nên câu riêng không lộ
 *  thêm gì; backend vẫn trả cùng mã `invalid_login` (Q-fe-3) — chỉ FE đổi câu. */
export const OTP_WRONG = "Mã xác thực không đúng hoặc đã hết hạn.";
export const USERNAME_HINT = "Tên đăng nhập chỉ gồm chữ thường không dấu, số và các ký tự . _ - (vd an.nv).";

export function loginErrorMessage(error: ApiError | null): string {
  if (error === null) return errorMessage(null);
  if (error.status === 401) {
    return error.code === "mfa_not_enrolled"
      ? "Tài khoản này bắt buộc xác thực hai bước nhưng chưa được cài. Liên hệ bộ phận IT."
      : GENERIC_LOGIN_ERROR;
  }
  if (error.status === 422) return "Thông tin đăng nhập không hợp lệ.";
  if (error.status === 429) return "Bạn đã thử quá nhiều lần. Vui lòng đợi vài phút rồi thử lại.";
  if (error.status === 503) return "Hệ thống xác thực đang bận, vui lòng thử lại sau.";
  return errorMessage(error);
}
