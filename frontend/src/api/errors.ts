// Lỗi HTTP → thông báo tiếng Việt (KH mục 5; 12b Q-fe-3). Backend trả HAI dạng thân lỗi:
//   {detail: "<mã hoặc câu>"}                  — HTTPException, AuthError, 409 sự kiện muộn, 413
//   {error: "<mã>", fields?: ["body.text", …]}  — 422 kiểm dữ liệu (`invalid_request`), 503 privacy guard
// (backend/app/api/errors.py). Thân lỗi không bao giờ chứa giá trị người dùng gửi (chống rò qua 422).

export class ApiError extends Error {
  readonly status: number;
  /** `detail` hoặc `error` của thân lỗi; null khi thân rỗng / không phải JSON. */
  readonly code: string | null;
  /** 422 `invalid_request`: vị trí trường đã bỏ tiền tố `body.` (vd `text`). */
  readonly fields: string[];
  /** Giây, từ header `Retry-After` (503 `ticket_busy`). */
  readonly retryAfter: number | null;

  constructor(status: number, code: string | null, fields: string[] = [], retryAfter: number | null = null) {
    super(`HTTP ${status}${code ? ` ${code}` : ""}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.retryAfter = retryAfter;
  }
}

export function parseErrorBody(body: unknown): { code: string | null; fields: string[] } {
  if (body !== null && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.detail === "string") return { code: b.detail, fields: [] };
    if (typeof b.error === "string") {
      const fields = Array.isArray(b.fields) ? b.fields.filter((f): f is string => typeof f === "string") : [];
      return { code: b.error, fields: fields.map((f) => f.replace(/^body\./, "")) };
    }
  }
  return { code: null, fields: [] };
}

export async function readApiError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // thân rỗng hoặc không phải JSON (vd proxy trả HTML) — chỉ còn mã HTTP
  }
  const { code, fields } = parseErrorBody(body);
  const retryAfter = Number(res.headers.get("Retry-After"));
  return new ApiError(res.status, code, fields, Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null);
}

// Mã máy của backend → câu cho người dùng. Mã lạ: 409 có thể là câu tiếng Việt sẵn (`LateEvent.message`).
const CODE_MESSAGES: Record<string, string> = {
  reauth_required: "Cần đăng nhập lại để xác nhận thao tác này.",
  privacy_guard_unavailable: "Chưa gửi được — hệ thống kiểm tra nội dung đang bận, vui lòng thử lại.",
  ticket_busy: "Hệ thống đang bận, sẽ tự thử lại.",
  payload_too_large: "Nội dung quá dài.",
};

export function errorMessage(error: ApiError | null): string {
  if (error === null) return "Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.";
  if (error.code && CODE_MESSAGES[error.code]) return CODE_MESSAGES[error.code]!;
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
