---
doc_id: KB-ACS-001
version: 1
request_type: access
doc_type: policy
owner: it_mgr01
updated_at: 2026-10-04
sensitivity: internal
enabled: true
title: "Quy trình xin quyền thư mục dùng chung"
distractor: false
tags: [access, thư mục dùng chung, quyền truy cập, phê duyệt]
---

## Các thư mục dùng chung hiện có

Hệ thống hiện có năm thư mục được ghi nhận trong danh sách tài nguyên: engineering/specs, finance/Q3, finance/public-reports, hr/salaries và shared/templates.

Mỗi thư mục có mức độ nhạy và phòng ban sở hữu riêng. engineering/specs có mức medium và thuộc Engineering. finance/Q3 có mức high và thuộc Finance. finance/public-reports có mức low và thuộc Finance. hr/salaries có mức high và thuộc HR. shared/templates có mức low và thuộc IT.

Khi gửi yêu cầu quyền truy cập, người dùng cần xác định đúng đường dẫn thư mục. Không tự tạo một tên thư mục khác hoặc thay thế bằng thư mục có tên gần giống.

## Thông tin cần xác định khi xin quyền

Yêu cầu cần chỉ rõ tài nguyên mà người dùng muốn truy cập. Thông tin về mức độ nhạy và phòng ban sở hữu phải được lấy đúng theo danh sách tài nguyên hiện tại.

Ví dụ, finance/Q3 và finance/public-reports đều thuộc Finance nhưng không có cùng mức độ nhạy. finance/Q3 có mức high, còn finance/public-reports có mức low.

Do đó không nên suy luận mức độ nhạy chỉ dựa vào phòng ban sở hữu. Cần dùng đúng giá trị đã có trong hệ thống.

Nguồn hiện tại chưa cung cấp các loại quyền cụ thể như đọc, ghi hoặc chỉnh sửa, nên tài liệu này không tự bổ sung các loại quyền đó.

## Gửi yêu cầu quyền truy cập

Khi cần truy cập một thư mục dùng chung, người dùng gửi yêu cầu với đúng đường dẫn thư mục cần sử dụng.

Không tự thay đổi owner_department hoặc sensitivity trong nội dung yêu cầu. Nếu thư mục không có trong danh sách tài nguyên hiện tại, dữ liệu nguồn chưa đủ để xác định quy trình xử lý.

Đối với yêu cầu thuộc quy trình cần duyệt, yêu cầu được duyệt trong 30 phút.

Nguồn hiện tại chưa xác định người duyệt cụ thể cho từng thư mục hoặc từng mức độ nhạy.

## Khi cần hỗ trợ thêm

Nếu người dùng không xác định được đúng thư mục hoặc tài nguyên cần truy cập không có trong danh sách hiện tại, cần liên hệ IT để được kiểm tra.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Không tự tạo tên tài nguyên, không tự thay đổi mức độ nhạy và không tự chỉ định người duyệt nếu thông tin đó chưa có trong nguồn dữ liệu.