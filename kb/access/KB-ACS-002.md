---
doc_id: KB-ACS-002
version: 2
request_type: access
doc_type: policy
owner: it_mgr01
updated_at: 2026-10-18
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

Khi xử lý yêu cầu truy cập, dùng đúng mức độ nhạy đã được gán cho từng thư mục. Nếu mức độ nhạy chưa rõ, IT kiểm tra bản ghi tài nguyên trước khi phân loại yêu cầu.

## Phòng ban sở hữu thư mục

engineering/specs thuộc Engineering.

finance/Q3 và finance/public-reports thuộc Finance.

hr/salaries thuộc HR.

shared/templates thuộc IT.

Phòng ban sở hữu và mức độ nhạy là hai thông tin riêng biệt.

Ví dụ, finance/Q3 và finance/public-reports cùng thuộc Finance nhưng có mức độ nhạy khác nhau. Vì vậy không nên xác định mức độ nhạy chỉ dựa trên phòng ban sở hữu.

## Phê duyệt quyền truy cập

Người duyệt là nhân viên IT Helpdesk đang trực; có nhân viên dự phòng khi cần. Trưởng phòng sở hữu thư mục và chủ dữ liệu không đóng vai trò người duyệt.

Yêu cầu được chuyển cho Trưởng bộ phận IT xử lý khi người duyệt đồng thời là người gửi yêu cầu, khi người gửi là cấp trên của người duyệt, hoặc khi người duyệt là người được cấp quyền trong yêu cầu. Người gửi không cần tự chọn người duyệt.

Mức độ nhạy và phòng ban liên quan chỉ xác định yêu cầu có cần phê duyệt hay không, không quyết định ai phê duyệt. Xem quyền hiện có của chính mình không cần phê duyệt. Cấp quyền mới không được hệ thống tự thực hiện: yêu cầu được chuyển cho người duyệt hoặc IT xem xét, trong đó quyền mới vào thư mục có mức độ nhạy high, quyền toàn quyền hoặc quyền mới vào thư mục thuộc phòng ban khác luôn cần phê duyệt. Gia hạn quyền chỉ được tự xử lý khi đủ điều kiện nêu trong bài về quyền truy cập có thời hạn và gia hạn quyền; gia hạn quyền vào thư mục thuộc phòng ban khác luôn cần phê duyệt.

Người duyệt có 30 phút để phản hồi; quá hạn, yêu cầu được chuyển cho kỹ thuật viên IT xử lý tiếp, không tự thực hiện.

## Khi chưa xác định được người duyệt

Yêu cầu được chuyển vào hàng đợi IT Helpdesk để nhân viên đang trực xử lý; nhân viên dự phòng thay thế khi cần.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Nếu phát hiện xung đột lợi ích trong quá trình phân công, yêu cầu được chuyển cho Trưởng bộ phận IT.

Khi gửi yêu cầu, người dùng cần ghi đúng đường dẫn thư mục cần truy cập để IT có thể xác định tài nguyên liên quan.
