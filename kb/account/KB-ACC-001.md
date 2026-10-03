---
doc_id: KB-ACC-001
version: 1
request_type: account
doc_type: howto
owner: it_mgr01
updated_at: 2026-10-03
sensitivity: internal
enabled: true
title: Tự đặt lại mật khẩu tài khoản cá nhân
distractor: false
tags: [account, mật khẩu, đặt lại mật khẩu, tài khoản cá nhân]
---

## Khi nào nên dùng quy trình đặt lại mật khẩu cá nhân

Quy trình này dành cho người dùng cần xử lý mật khẩu của chính tài khoản cá nhân đang được mình sử dụng. Ví dụ, nv001 là Kế toán viên thuộc phòng Finance và đang có trạng thái active. nv002 là Kỹ sư phần mềm thuộc phòng Engineering và cũng đang có trạng thái active.

Khi một người dùng như nv001 hoặc nv002 gặp vấn đề với mật khẩu của chính tài khoản mình, cần sử dụng quy trình dành cho tài khoản cá nhân. Không nên sử dụng quy trình này để yêu cầu đặt lại mật khẩu cho đồng nghiệp, tài khoản dịch vụ hoặc tài khoản có quyền đặc biệt.

Trước khi gửi yêu cầu, người dùng cần xác định đúng tài khoản đang gặp vấn đề và đúng hệ thống mình không thể đăng nhập.

## Cách gửi yêu cầu đặt lại mật khẩu

Người dùng gửi yêu cầu qua hệ thống hỗ trợ IT và mô tả rõ tài khoản cá nhân nào đang gặp vấn đề. Không gửi mật khẩu hiện tại, mật khẩu cũ hoặc thông tin bí mật trong nội dung yêu cầu.

Nếu hệ thống yêu cầu xác minh danh tính hoặc bổ sung thông tin, người dùng cần cung cấp đúng thông tin của chính tài khoản mình. Không sử dụng user_id của người khác để yêu cầu đặt lại mật khẩu.

Ví dụ, nv001 chỉ nên yêu cầu xử lý tài khoản của nv001. Tương tự, nv002 chỉ nên sử dụng quy trình này cho tài khoản của chính mình.

Nếu không xác định được nguyên nhân lỗi đăng nhập, người dùng nên ghi lại thông báo lỗi để IT kiểm tra thay vì tự thử nhiều quy trình khác nhau.

## Sau khi mật khẩu được đặt lại

Sau khi quá trình đặt lại mật khẩu hoàn tất, người dùng đăng nhập lại bằng thông tin mới theo hướng dẫn của hệ thống.

Nếu tài khoản vẫn không thể đăng nhập, cần kiểm tra lại trạng thái tài khoản. Trong hệ thống hiện có các trạng thái active, probation, disabled và terminated. Không nên coi mọi trường hợp đăng nhập thất bại đều là lỗi mật khẩu.

Ví dụ, nv003 có trạng thái probation và nv004 có trạng thái disabled. Những trường hợp này có thể cần IT kiểm tra thêm thay vì chỉ thực hiện lại quy trình đặt lại mật khẩu.

Không chia sẻ mật khẩu mới trong ticket, nhóm chat hoặc cho người dùng khác.

## Khi nào cần liên hệ IT

Người dùng cần liên hệ IT khi không thể hoàn tất quy trình đặt lại mật khẩu, không xác định được trạng thái tài khoản hoặc vẫn không đăng nhập được sau khi thực hiện đúng hướng dẫn.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Trong yêu cầu hỗ trợ, người dùng nên cung cấp user_id, hệ thống đang gặp vấn đề và nội dung thông báo lỗi nếu có. Không gửi mật khẩu hoặc thông tin bí mật cho IT.