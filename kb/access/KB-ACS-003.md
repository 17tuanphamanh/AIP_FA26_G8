---
doc_id: KB-ACS-003
version: 2
request_type: access
doc_type: policy
owner: it_mgr01
updated_at: 2026-10-18
sensitivity: internal
enabled: true
title: "Quyền truy cập có thời hạn và gia hạn quyền"
distractor: false
tags: [access, quyền có thời hạn, gia hạn quyền, thư mục]
---

## Quyền truy cập có thời hạn

Mỗi yêu cầu quyền truy cập phải ghi rõ số ngày cần sử dụng quyền. Quyền có thời hạn tự hết hiệu lực vào ngày hết hạn.

Một số quyền cũ không ghi thời hạn; nghĩa là "Không thời hạn", không phải thiếu dữ liệu, chưa thiết lập hoặc quyền đã hết hạn.

Khi gửi yêu cầu, người dùng cần xác định đúng tài nguyên, nhu cầu sử dụng quyền và số ngày cần dùng.

Trong trường hợp cần thêm hướng dẫn, người dùng cần liên hệ IT.

## Xác định đúng tài nguyên

Các tài nguyên hiện có gồm engineering/specs, finance/Q3, finance/public-reports, hr/salaries và shared/templates.

Khi yêu cầu quyền có thời hạn hoặc gia hạn quyền, người dùng cần ghi đúng tài nguyên liên quan.

Mức độ nhạy và phòng ban sở hữu của thư mục quyết định yêu cầu gia hạn quyền được tự xử lý hay cần người duyệt; điều kiện cụ thể nằm ở mục "Khi nào quyền được gia hạn tự động và khi nào cần người duyệt" bên dưới. Xem quyền hiện có của chính mình không cần phê duyệt. Cấp quyền mới không được hệ thống tự thực hiện: yêu cầu được chuyển cho người duyệt hoặc IT xem xét, trong đó quyền mới vào thư mục có mức độ nhạy high, quyền toàn quyền hoặc quyền mới vào thư mục thuộc phòng ban khác luôn cần phê duyệt.

Nếu tài nguyên cần sử dụng không xác định được, người dùng cần liên hệ IT trước khi tiếp tục yêu cầu.

## Gia hạn quyền truy cập

Người dùng nên gửi yêu cầu gia hạn cho đúng tài nguyên trước ngày hết hạn để không bị gián đoạn công việc. Nếu quyền đã hết hạn, người dùng vẫn có thể gửi yêu cầu gia hạn cho thư mục mà trước đây mình đã có quyền.

Yêu cầu gia hạn cần nêu rõ nhu cầu tiếp tục sử dụng và số ngày cần gia hạn.

Người dùng cần mô tả nhu cầu tiếp tục truy cập để yêu cầu được xem xét.

Nếu chưa xác định được thời hạn áp dụng hoặc cách gia hạn phù hợp, cần liên hệ IT để được hướng dẫn.

## Khi nào quyền được gia hạn tự động và khi nào cần người duyệt

Yêu cầu gia hạn quyền được hệ thống tự xử lý, không cần người duyệt, khi đồng thời thỏa tất cả các điều kiện sau:

- Người dùng gia hạn quyền của chính mình, không gia hạn thay cho người khác.
- Người dùng đã từng có quyền trên đúng thư mục đó (còn hạn hoặc đã hết hạn) và mức quyền hiện có là read hoặc write. Quyền toàn quyền không được tự gia hạn.
- Thư mục thuộc phòng ban của chính người dùng.
- Thư mục có mức độ nhạy low hoặc medium. Thư mục có mức độ nhạy high không được tự gia hạn.
- Tài khoản của người dùng đang hoạt động hoặc đang thử việc.
- Thời hạn gia hạn không quá 90 ngày.

Gia hạn quyền vào thư mục thuộc phòng ban khác luôn cần người duyệt. Tài khoản bị vô hiệu hóa vì lý do bảo mật không được gia hạn quyền. Trường hợp không đủ các điều kiện tự động ở trên, yêu cầu gia hạn được chuyển cho người duyệt hoặc IT xem xét, không tự thực hiện.

## Phê duyệt và hỗ trợ

Người duyệt có 30 phút để phản hồi; quá hạn, yêu cầu được chuyển cho kỹ thuật viên IT xử lý tiếp, không tự thực hiện.

Người dùng không nên gửi nhiều yêu cầu gia hạn giống nhau trong khi yêu cầu trước đang được xử lý.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Khi gửi yêu cầu, cần ghi đúng tài nguyên liên quan và mô tả nhu cầu truy cập. Không cung cấp thông tin bí mật trong nội dung yêu cầu.
