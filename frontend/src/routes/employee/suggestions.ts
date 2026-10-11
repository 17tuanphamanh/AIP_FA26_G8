// Nút gợi ý nhanh trên trang chủ nhân viên (B4EmpHome; P10 §3.1 "Nên có"). Nhãn = chữ Bản 4; bấm → ĐIỀN câu mẫu vào ô nhập
// để người dùng sửa rồi tự gửi (KHÔNG tự gửi). Câu mẫu chung chung, không chứa dữ liệu cá nhân (tên, mã máy, mật khẩu).
export const SUGGESTIONS: readonly { label: string; text: string }[] = [
  { label: "Quên mật khẩu", text: "Tôi quên mật khẩu, cần đặt lại." },
  { label: "Lỗi VPN", text: "Tôi không kết nối được VPN công ty." },
  { label: "Cài phần mềm", text: "Tôi cần cài phần mềm lên máy làm việc." },
  { label: "Xin quyền truy cập", text: "Tôi cần xin quyền truy cập thư mục dùng chung." },
];
