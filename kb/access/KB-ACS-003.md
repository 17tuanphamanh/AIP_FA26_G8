---
doc_id: KB-ACS-003
version: 1
request_type: access
doc_type: policy
owner: it_mgr01
updated_at: 2026-10-04
sensitivity: internal
enabled: true
title: "Quyền truy cập có thời hạn và gia hạn quyền"
distractor: false
tags: [access, quyền có thời hạn, gia hạn quyền, thư mục]
---

## Quyền truy cập có thời hạn

Mỗi yêu cầu quyền truy cập phải ghi rõ số ngày cần sử dụng quyền. Quyền có thời hạn tự hết hiệu lực vào ngày hết hạn.

Một số quyền cũ có thể ghi `permissions.expires_in_days = null`; giá trị này nghĩa là "Không thời hạn", không phải thiếu dữ liệu, chưa thiết lập hoặc quyền đã hết hạn.

Khi gửi yêu cầu, người dùng cần xác định đúng tài nguyên, nhu cầu sử dụng quyền và số ngày cần dùng.

Trong trường hợp cần thêm hướng dẫn, người dùng cần liên hệ IT.

## Xác định đúng tài nguyên

Các tài nguyên hiện có gồm engineering/specs, finance/Q3, finance/public-reports, hr/salaries và shared/templates.

Khi yêu cầu quyền có thời hạn hoặc gia hạn quyền, người dùng cần ghi đúng tài nguyên liên quan.

Mức độ nhạy và phòng ban liên quan được dùng để xác định yêu cầu có cần phê duyệt hay không: quyền mới vào thư mục high, quyền toàn quyền hoặc quyền mới vào thư mục thuộc phòng ban khác cần phê duyệt; xem quyền hiện có không cần phê duyệt và gia hạn được xem xét tùy trường hợp. Chưa có ngưỡng số ngày cụ thể để quyết định việc phê duyệt; quy tắc chi tiết chờ Phase 5.

Nếu tài nguyên cần sử dụng không xác định được, người dùng cần liên hệ IT trước khi tiếp tục yêu cầu.

## Gia hạn quyền truy cập

Muốn tiếp tục sử dụng sau khi quyền hết hạn, người dùng phải gửi yêu cầu gia hạn cho đúng tài nguyên trước ngày hết hạn.

Yêu cầu gia hạn cần nêu rõ nhu cầu tiếp tục sử dụng và số ngày cần gia hạn.

Người dùng cần mô tả nhu cầu tiếp tục truy cập để yêu cầu được xem xét.

Nếu chưa xác định được thời hạn áp dụng hoặc cách gia hạn phù hợp, cần liên hệ IT để được hướng dẫn.

## Phê duyệt và hỗ trợ

Người duyệt có 30 phút để phản hồi; quá hạn, yêu cầu được chuyển cho kỹ thuật viên IT xử lý tiếp, không tự thực hiện.

Người dùng không nên gửi nhiều yêu cầu gia hạn giống nhau trong khi yêu cầu trước đang được xử lý.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Khi gửi yêu cầu, cần ghi đúng tài nguyên liên quan và mô tả nhu cầu truy cập. Không cung cấp thông tin bí mật trong nội dung yêu cầu.
