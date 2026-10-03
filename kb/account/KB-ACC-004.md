---
doc_id: KB-ACC-004
version: 1
request_type: account
doc_type: faq
owner: it_mgr01
updated_at: 2026-10-03
sensitivity: internal
enabled: true
title: Đổi mật khẩu email khác đổi mật khẩu Windows
distractor: true
tags: [account, email, windows, mật khẩu, đăng nhập]
---

## Cần xác định đúng hệ thống đang gặp lỗi

Khi người dùng báo vấn đề về mật khẩu, cần xác định rõ hệ thống nào đang không đăng nhập được trước khi áp dụng một hướng dẫn.

Người dùng nên nêu rõ mình đang gặp lỗi ở email, Windows hay một hệ thống khác. Chỉ nói rằng “mật khẩu không dùng được” là chưa đủ để xác định quy trình phù hợp.

Danh sách giá trị hiện tại không mô tả cơ chế xác thực giữa email và Windows. Vì vậy không nên tự kết luận rằng hai hệ thống luôn sử dụng cùng một mật khẩu hoặc luôn sử dụng hai mật khẩu khác nhau.

## Không áp dụng nhầm hướng dẫn

Hướng dẫn dành cho một hệ thống không nên được áp dụng cho hệ thống khác khi chưa xác định chúng sử dụng cùng cơ chế xác thực.

Ví dụ, người dùng không nên thực hiện quy trình dành cho email chỉ vì không đăng nhập được Windows. Tương tự, không nên tự đặt lại mật khẩu tài khoản cá nhân nếu lỗi thực tế liên quan đến một tài khoản đặc quyền hoặc tài khoản đã bị vô hiệu hóa.

Việc xác định đúng loại tài khoản và hệ thống giúp IT chọn đúng quy trình xử lý.

## Thông tin nên cung cấp khi yêu cầu hỗ trợ

Khi gửi yêu cầu, người dùng nên cung cấp user_id, tên hệ thống không đăng nhập được và nội dung thông báo lỗi nếu có.

Có thể sử dụng các user_id hợp lệ như nv001, nv002 hoặc nv003 khi xây dựng tình huống kiểm thử, nhưng trong vận hành thực tế người dùng cần cung cấp đúng user_id của chính mình.

Không cung cấp mật khẩu hiện tại hoặc mật khẩu cũ trong nội dung yêu cầu.

## Khi nào cần liên hệ IT

Nếu người dùng không xác định được mình đang gặp lỗi ở email, Windows hay một hệ thống khác, nên liên hệ IT để được hướng dẫn.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

IT cần thông tin về tài khoản và hệ thống gặp lỗi để xác định cách xử lý. Không cần và không nên gửi mật khẩu cho IT.