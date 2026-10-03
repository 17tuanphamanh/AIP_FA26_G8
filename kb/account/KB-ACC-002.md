---
doc_id: KB-ACC-002
version: 1
request_type: account
doc_type: troubleshooting
owner: it_mgr01
updated_at: 2026-10-03
sensitivity: internal
enabled: true
title: "Tài khoản bị khóa: nguyên nhân và cách mở"
distractor: false
tags: [account, tài khoản bị khóa, tài khoản bị vô hiệu hóa, đăng nhập]
---

## Cách xác định tình trạng tài khoản

Khi người dùng không thể đăng nhập, trước tiên cần kiểm tra trạng thái thực tế của tài khoản thay vì tự kết luận tài khoản đã bị khóa vì nhập sai mật khẩu.

Dữ liệu hệ thống hiện có các trạng thái active, probation, disabled và terminated. Ví dụ, nv001 và nv002 đang có trạng thái active. nv003 có trạng thái probation. nv004 có trạng thái disabled, còn nv006 có trạng thái terminated.

Mỗi trạng thái có ý nghĩa khác nhau và cần được xử lý phù hợp. Việc không đăng nhập được không đủ để xác định nguyên nhân nếu chưa kiểm tra trạng thái tài khoản.

## Tài khoản bị vô hiệu hóa

Tài khoản nv004 hiện có trạng thái disabled. Danh sách giá trị hợp lệ chỉ xác nhận tài khoản này bị vô hiệu hóa và chưa ghi lý do cụ thể.

Vì vậy, không nên viết hoặc kết luận rằng nv004 bị khóa do nhập sai mật khẩu hay do một nguyên nhân cụ thể nào khác nếu chưa có dữ liệu xác nhận.

Khi gặp tài khoản ở trạng thái disabled, người dùng cần gửi yêu cầu cho IT để kiểm tra nguyên nhân và xác định bước xử lý tiếp theo. Không nên áp dụng tự động quy trình đặt lại mật khẩu và coi đó là cách mở lại tài khoản.

## Tài khoản đã nghỉ việc

Tài khoản nv006 có trạng thái terminated, nghĩa là người dùng đã nghỉ việc.

Trường hợp này không nên được xử lý giống tài khoản active đang gặp lỗi đăng nhập. Không sử dụng quy trình mở khóa hoặc đặt lại mật khẩu cá nhân để tự kích hoạt lại tài khoản đã có trạng thái terminated.

Nếu có yêu cầu liên quan đến tài khoản đã nghỉ việc, cần chuyển cho IT kiểm tra theo đúng quy trình quản lý tài khoản.

## Khi nào cần chuyển cho IT

Cần chuyển cho IT khi tài khoản ở trạng thái disabled, terminated hoặc khi người dùng không xác định được nguyên nhân đăng nhập thất bại.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Người dùng nên cung cấp user_id và nội dung thông báo lỗi. Không tự thay đổi trạng thái tài khoản và không sử dụng tài khoản của người khác để tiếp tục công việc.