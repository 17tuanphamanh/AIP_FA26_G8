---
doc_id: KB-ACC-003
version: 1
request_type: account
doc_type: policy
owner: it_mgr01
updated_at: 2026-10-03
sensitivity: internal
enabled: true
title: Quy trình đặt lại mật khẩu tài khoản quản trị
distractor: false
tags: [account, tài khoản quản trị, tài khoản đặc quyền, mật khẩu, phê duyệt]
---

## Tài khoản đặc quyền là gì

Một số tài khoản trong hệ thống có quyền đặc biệt và không nên được xử lý giống tài khoản cá nhân thông thường.

Trong danh sách giá trị hợp lệ, svc_backup là Service account thuộc bộ phận IT và được đánh dấu is_privileged_account là true. Đây là ví dụ về tài khoản cần được xử lý cẩn thận hơn khi có yêu cầu liên quan đến mật khẩu.

Không sử dụng quy trình tự đặt lại mật khẩu tài khoản cá nhân cho svc_backup hoặc tài khoản có quyền đặc biệt tương tự.

## Vì sao yêu cầu cần được phê duyệt

Yêu cầu đặt lại mật khẩu cho tài khoản có quyền đặc biệt cần được đưa qua bước phê duyệt trước khi thực hiện.

Việc phê duyệt giúp tránh thay đổi thông tin xác thực của tài khoản quan trọng mà chưa được kiểm tra. Người dùng không nên tìm cách bỏ qua bước này bằng cách gửi yêu cầu dưới dạng tài khoản cá nhân thông thường.

Tài liệu hiện tại không xác định cụ thể người nào là người duyệt, vì vậy không nên tự ghi tên người duyệt vào bài KB.

## Quy trình gửi yêu cầu

Người gửi yêu cầu cần cung cấp đúng user_id của tài khoản đặc quyền cần xử lý và mô tả lý do cần đặt lại mật khẩu.

Ví dụ, nếu yêu cầu liên quan đến svc_backup, cần nêu rõ tài khoản svc_backup thay vì mô tả chung chung là một tài khoản IT.

Không cung cấp mật khẩu hiện tại, mật khẩu cũ hoặc bí mật khác trong ticket.

Sau khi yêu cầu được tiếp nhận, yêu cầu được chuyển vào quy trình phê duyệt. Yêu cầu được duyệt trong 30 phút.

## Sau khi yêu cầu được xử lý

Sau khi yêu cầu được phê duyệt và xử lý xong, người có quyền sử dụng tài khoản thực hiện đăng nhập theo hướng dẫn được cung cấp.

Không chia sẻ thông tin xác thực của tài khoản đặc quyền qua ticket hoặc nhóm chat. Nếu tài khoản vẫn gặp lỗi sau khi xử lý, cần liên hệ IT để kiểm tra tiếp.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.