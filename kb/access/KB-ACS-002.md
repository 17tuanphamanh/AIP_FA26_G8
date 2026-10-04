---
doc_id: KB-ACS-002
version: 1
request_type: access
doc_type: policy
owner: it_mgr01
updated_at: 2026-10-04
sensitivity: internal
enabled: true
title: "Mức độ nhạy của thư mục và ai duyệt"
distractor: false
tags: [access, thư mục, độ nhạy, phê duyệt]
---

## Các mức độ nhạy của thư mục

Các thư mục hiện tại sử dụng ba mức độ nhạy là low, medium và high.

engineering/specs có mức độ nhạy medium.

finance/Q3 và hr/salaries có mức độ nhạy high.

finance/public-reports và shared/templates có mức độ nhạy low.

Khi xử lý yêu cầu truy cập, cần sử dụng đúng mức độ nhạy đã được gán cho từng thư mục. Không tự thay đổi mức độ nhạy dựa trên tên thư mục hoặc nội dung suy đoán.

## Phòng ban sở hữu thư mục

engineering/specs thuộc Engineering.

finance/Q3 và finance/public-reports thuộc Finance.

hr/salaries thuộc HR.

shared/templates thuộc IT.

Phòng ban sở hữu và mức độ nhạy là hai thông tin riêng biệt.

Ví dụ, finance/Q3 và finance/public-reports cùng thuộc Finance nhưng có mức độ nhạy khác nhau. Vì vậy không nên xác định mức độ nhạy chỉ dựa trên phòng ban sở hữu.

## Phê duyệt quyền truy cập

Yêu cầu quyền truy cập cần được xử lý theo chính sách áp dụng cho tài nguyên tương ứng.

Yêu cầu được duyệt trong 30 phút.

Thông tin hiện có về thư mục gồm đường dẫn, mức độ nhạy và phòng ban sở hữu. Những thông tin này cần được sử dụng đúng khi tạo và kiểm tra yêu cầu truy cập.

Không tự thay đổi tài nguyên hoặc mức độ nhạy để làm thay đổi cách xử lý yêu cầu.

## Khi chưa xác định được người duyệt

Nếu người dùng chưa xác định được yêu cầu quyền cần được chuyển cho ai, cần liên hệ IT để được hướng dẫn.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Không tự chỉ định một cá nhân hoặc một vai trò làm người duyệt nếu chưa có thông tin được xác nhận.

Khi gửi yêu cầu, người dùng cần ghi đúng đường dẫn thư mục cần truy cập để IT có thể xác định tài nguyên liên quan.