---
doc_id: KB-VPN-001
version: 1
request_type: vpn
doc_type: faq
owner: it_mgr01
updated_at: 2026-09-27
sensitivity: public
enabled: true
title: Tổng quan dịch vụ VPN của Công ty ABC
distractor: false
tags: [vpn, cổng, giao thức, ABC Connect]
---

## VPN công ty dùng để làm gì

VPN (mạng riêng ảo) giúp máy tính của bạn kết nối an toàn vào mạng nội bộ Công ty ABC khi làm việc ở nhà, đi công tác hoặc dùng mạng bên ngoài. Khi đã kết nối VPN, bạn truy cập được thư mục dùng chung, hệ thống nội bộ và máy in văn phòng giống như đang ngồi tại công ty.

Mỗi nhân viên được dùng VPN trên tối đa 2 thiết bị đã đăng ký với bộ phận IT. Thiết bị chưa đăng ký không kết nối được VPN, kể cả khi bạn nhập đúng tài khoản.

## Địa chỉ máy chủ và cổng kết nối

Máy chủ VPN của công ty có địa chỉ vpn.congty-abc.vn. Công ty dùng hai giao thức:

- Giao thức chính là IKEv2, dùng cổng UDP 500 và 4500. Đây là giao thức ứng dụng ABC Connect chọn mặc định vì nhanh và ổn định.
- Giao thức dự phòng là SSTP, dùng cổng TCP 443. Dùng SSTP khi mạng bạn đang ở (khách sạn, quán cà phê, mạng khách của đối tác) chặn các cổng UDP của IKEv2.

Bạn không cần tự cấu hình địa chỉ hay cổng: ứng dụng ABC Connect đã cài sẵn các thông số này. Chỉ đổi giao thức khi được hướng dẫn xử lý lỗi.

## Ứng dụng kết nối ABC Connect

Công ty chỉ hỗ trợ kết nối VPN qua ứng dụng ABC Connect phiên bản 3.2 trở lên. Không dùng trình VPN có sẵn của Windows hay macOS để kết nối vào vpn.congty-abc.vn, vì các trình này không có chứng chỉ của công ty.

Kiểm tra phiên bản: mở ABC Connect, chọn "Giới thiệu". Nếu phiên bản thấp hơn 3.2, hãy cập nhật qua Trung tâm phần mềm của công ty trước khi kết nối.

## Chứng chỉ VPN

Mỗi thiết bị đã đăng ký có một chứng chỉ VPN riêng. Chứng chỉ có hiệu lực 365 ngày kể từ ngày cấp. Bạn có thể yêu cầu gia hạn từ trước 30 ngày khi chứng chỉ hết hạn; chứng chỉ đã hết hạn thì cần cấp lại. Khi chứng chỉ hết hạn, ABC Connect báo "Chứng chỉ không hợp lệ" và không kết nối được.

Yêu cầu gia hạn hoặc cấp lại chứng chỉ gửi qua trợ lý IT trong cổng hỗ trợ. Yêu cầu cho thiết bị đã đăng ký của chính bạn trong giờ hành chính (08:00–18:00, thứ Hai đến thứ Sáu) thường được xử lý tự động.

## Khi nào liên hệ bộ phận IT

Liên hệ bộ phận IT (máy lẻ 1234) khi bạn đã làm theo hướng dẫn xử lý lỗi mà vẫn không kết nối được, khi cần đăng ký thêm thiết bị, hoặc khi nghi ngờ tài khoản bị người khác dùng. Không gửi mật khẩu qua chat hay email cho bất kỳ ai, kể cả nhân viên IT.
