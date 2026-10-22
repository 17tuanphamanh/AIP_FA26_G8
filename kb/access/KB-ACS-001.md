---
doc_id: KB-ACS-001
version: 2
request_type: access
doc_type: policy
owner: it_mgr01
updated_at: 2026-10-18
sensitivity: internal
enabled: true
title: "Quy trình xin quyền thư mục dùng chung"
distractor: false
tags: [access, thư mục dùng chung, quyền truy cập, phê duyệt]
---

## Các thư mục dùng chung hiện có

Hệ thống hiện có các thư mục engineering/specs, finance/Q3, finance/public-reports, hr/salaries và shared/templates.

Mỗi thư mục có mức độ nhạy và phòng ban sở hữu riêng.

engineering/specs có mức medium và thuộc Engineering. finance/Q3 có mức high và thuộc Finance. finance/public-reports có mức low và thuộc Finance. hr/salaries có mức high và thuộc HR. shared/templates có mức low và thuộc IT.

Người dùng cần xác định đúng thư mục cần truy cập trước khi gửi yêu cầu.

## Xác định đúng tài nguyên cần truy cập

Khi yêu cầu quyền truy cập, người dùng cần ghi đúng đường dẫn thư mục cần sử dụng.

Ví dụ, finance/Q3 và finance/public-reports đều thuộc Finance nhưng là hai tài nguyên khác nhau và có mức độ nhạy khác nhau.

Không sử dụng một thư mục khác để thay thế cho tài nguyên thực tế cần truy cập.

Nếu không xác định được đúng tên thư mục, người dùng cần liên hệ IT để được kiểm tra trước khi gửi yêu cầu.

## Gửi yêu cầu quyền truy cập

Khi gửi yêu cầu, người dùng cần mô tả rõ thư mục cần truy cập và nhu cầu sử dụng.

Ghi đường dẫn thư mục, phòng ban sở hữu và mức độ nhạy theo thông tin hiện có; nếu không xác định được, liên hệ IT để kiểm tra trước khi gửi yêu cầu.

Xem quyền hiện có của chính mình không cần phê duyệt. Cấp quyền mới không được hệ thống tự thực hiện: yêu cầu được chuyển cho người duyệt hoặc IT xem xét, trong đó quyền mới vào thư mục có mức độ nhạy high, quyền toàn quyền hoặc quyền mới vào thư mục thuộc phòng ban khác luôn cần phê duyệt. Gia hạn quyền chỉ được tự xử lý khi đủ điều kiện nêu trong bài về quyền truy cập có thời hạn và gia hạn quyền; gia hạn quyền vào thư mục thuộc phòng ban khác luôn cần phê duyệt. Tài khoản bị vô hiệu hóa vì lý do bảo mật không được cấp mới hoặc gia hạn quyền.

Người duyệt có 30 phút để phản hồi; quá hạn, yêu cầu được chuyển cho kỹ thuật viên IT xử lý tiếp, không tự thực hiện.

Nếu chưa xác định được cách xử lý phù hợp, người dùng cần chờ hướng dẫn thay vì gửi nhiều yêu cầu giống nhau.

## Khi cần hỗ trợ

Nếu không xác định được thư mục cần truy cập hoặc yêu cầu không thể tiếp tục xử lý, người dùng cần liên hệ IT.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Người dùng nên cung cấp đúng tên thư mục và mô tả nhu cầu truy cập để IT kiểm tra.

Nếu chưa có thông tin tài nguyên, hãy cung cấp nhu cầu sử dụng để IT kiểm tra tên thư mục và thông tin liên quan.
