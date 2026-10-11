// Lỗi khi gửi (tạo ticket / trả lời / xác nhận) → câu cho người dùng (KH mục 5, errors.ts). 422 và 413 báo TẠI Ô
// nhập; lỗi khác báo chung. Thân lỗi của backend không chứa giá trị người dùng gửi — ở đây cũng không in lại.
import { ApiError, errorMessage } from "../../api/errors.ts";
import { NOTE_MAX, TEXT_MAX } from "../../api/tickets.ts";

export type SendErrorView = { field: string | null; message: string | null };

export function describeSendError(error: unknown): SendErrorView {
  if (!(error instanceof ApiError)) return { field: null, message: errorMessage(null) };
  if (error.status === 413) return { field: "Nội dung quá dài.", message: null };
  if (error.status === 422) {
    if (error.fields.includes("note")) return { field: `Ghi chú tối đa ${NOTE_MAX} ký tự.`, message: null };
    return { field: `Nội dung cần từ 1 đến ${TEXT_MAX} ký tự.`, message: null };
  }
  return { field: null, message: errorMessage(error) };
}

/** `notices` truyền qua `navigate(…, { state })` — dữ liệu từ lịch sử trình duyệt, kiểm dạng trước khi dùng. */
export function readNotices(state: unknown): string[] {
  const notices = (state as { notices?: unknown } | null)?.notices;
  return Array.isArray(notices) ? notices.filter((n): n is string => typeof n === "string") : [];
}
