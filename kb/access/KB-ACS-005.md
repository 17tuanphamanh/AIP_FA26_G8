---
doc_id: KB-ACS-005
version: 1
request_type: access
doc_type: howto
owner: it_mgr01
updated_at: 2026-10-06
sensitivity: internal
enabled: true
title: "Xem quyền truy cập hiện có của mình"
distractor: false
tags: [access, quyền truy cập, thư mục, xem quyền]
---

## Khi nào sử dụng hướng dẫn này

Hướng dẫn này dùng khi nhân viên muốn biết mình hiện có quyền truy cập vào thư mục nào và quyền đó đang được ghi nhận ra sao.

Đây là yêu cầu tra cứu thông tin hiện có, không phải yêu cầu cấp thêm quyền, gia hạn quyền hoặc thay đổi quyền truy cập.

Người dùng cần hỏi về quyền của chính mình. Nếu muốn xin thêm quyền vào một thư mục hoặc thay đổi quyền đang có, cần sử dụng quy trình yêu cầu quyền truy cập phù hợp.

## Thông tin hệ thống có thể trả về

Khi tra cứu quyền truy cập hiện có, hệ thống kiểm tra các bản ghi quyền gắn với người dùng và các thư mục tương ứng.

Kết quả có thể cho biết người dùng đang có bản ghi quyền trên thư mục nào và thông tin quyền được lưu cho tài nguyên đó.

Các thư mục hiện có trong hệ thống gồm engineering/specs, finance/Q3, finance/public-reports, hr/salaries và shared/templates.

Người dùng không cần tự đoán tên thư mục hoặc tự chỉ định quyền mình đang có. Hệ thống trả về thông tin dựa trên dữ liệu quyền hiện tại.

## Yêu cầu này có cần phê duyệt không

Việc xem quyền truy cập hiện có của chính mình là thao tác tra cứu thông tin.

Yêu cầu này không làm thay đổi quyền truy cập và không cấp thêm quyền cho người dùng, vì vậy không cần bước phê duyệt.

Nếu sau khi xem kết quả người dùng muốn xin thêm quyền, đổi quyền hoặc gia hạn quyền, yêu cầu đó được xử lý theo quy trình tương ứng.

Không sử dụng chức năng xem quyền hiện có để thay thế cho yêu cầu cấp quyền mới.

## Khi kết quả chưa rõ

Nếu người dùng không thấy thư mục mình mong đợi hoặc không hiểu thông tin quyền được trả về, cần liên hệ IT để được kiểm tra.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Người dùng nên cung cấp đúng tên thư mục cần kiểm tra. Không gửi mật khẩu hoặc thông tin bí mật trong nội dung yêu cầu.