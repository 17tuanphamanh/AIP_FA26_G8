# Bản 4 — bản thiết kế chốt (tham chiếu cho agent code frontend)

Bản sao chỉ-đọc các artboard Bản 4 từ canvas Claude Design (29–30/09/2026). Mỗi file `B4*.dc.html` là một màn 1440×900
(nhân viên 720 px cột giữa). Đọc **style inline** để lấy số đo, màu, cỡ chữ; đọc khối `renderVals()` để lấy dữ liệu mẫu.

- Không chạy được trực tiếp (thiếu `support.js` của canvas) — chỉ để đọc.
- `<dc-import name="B4Sidebar" role=… active=…>` = chèn thanh bên ở `B4Sidebar.dc.html` với vai trò tương ứng.
- Token và quy tắc: `../ke-hoach-frontend-khung.md` mục 4.5; tinh chỉnh bắt buộc theo hợp đồng Phase 4: mục 4.6
  (vd ẩn chuông, ẩn tab "Hệ thống đã tự xử lý", fixture L1 chỉ VPN) — **mục 4.6 thắng bản vẽ**.
- Dữ liệu trong bản vẽ là minh hoạ; khi lệch hợp đồng API (mục 1, 3.2) → theo hợp đồng.

| File | Màn |
|---|---|
| B4Login | Đăng nhập (+ OTP cho Trưởng BP IT) |
| B4EmpHome, B4EmpChat, B4EmpStates, B4EmpDigest | Nhân viên: trang đầu, hội thoại, các trạng thái, tin tổng hợp nhiều ý |
| B4L1Queue, B4L1Detail | L1: hộp thư duyệt, chi tiết phiếu (Bảng/JSON, sheet từ chối) |
| B4L2Queue, B4L2Detail | L2: hàng đợi escalate, bàn giao + đóng |
| B4MgrDashboard, B4MgrPolicy | Trưởng BP IT: tổng quan (trường API M9), chính sách |
| B4Sidebar | Thanh bên 4 vai trò |
| B4Main | Trang tổng các màn (bỏ qua khi code) |
