/**
 * Lối vào HỆ THỐNG GIẢ LẬP (mock: AD, VPN, điện thoại nhân viên, cổng đăng nhập — chỉ nghe 127.0.0.1:8100, cần
 * MOCK_CONSOLE_ENABLED=1). TA 14/11: "khó mở" → app có nút mở thẳng sang.
 *
 * Chỉ hiện ở bản demo: `npm run dev`, hoặc bản build có VITE_DEMO_TOOLS=1 (gói nộp "bấm là chạy" build như vậy). Bản build
 * thường không hiện — hệ thống thật không có trang giả lập.
 */
export const DEMO_TOOLS: boolean = import.meta.env.DEV || import.meta.env.VITE_DEMO_TOOLS === "1";

export const MOCK_CONSOLE_URL = "http://127.0.0.1:8100/console";
/** D-97 (cách 1): quản trị nhân viên nằm ở AD của công ty (ở đây: AD giả lập), app chỉ mở sang. */
export const AD_ADMIN_URL = `${MOCK_CONSOLE_URL}/nhan-vien`;
/** "Điện thoại của tôi": SMS mật khẩu tạm gửi tới số của người đang đăng nhập. */
export const phoneUrl = (userId: string): string => `${MOCK_CONSOLE_URL}/phone/${encodeURIComponent(userId)}`;
