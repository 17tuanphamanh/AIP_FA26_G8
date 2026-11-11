/** Có ít nhất một ký tự nhìn thấy: bỏ khoảng trắng VÀ ký tự định dạng vô hình (`\p{Cf}`: zero-width, soft hyphen, word
 *  joiner, BOM…). JS `trim()` không xoá U+200B, nên chuỗi chỉ gồm ký tự vô hình từng gửi được rồi ra E9 (kiểm thử 12/11;
 *  server nay trả 422 — đây là lớp chặn sớm ở máy khách, cùng định nghĩa "rỗng" với guard L0 của backend). */
export const hasVisibleText = (value: string): boolean => value.replace(/\p{Cf}/gu, "").trim().length > 0;
