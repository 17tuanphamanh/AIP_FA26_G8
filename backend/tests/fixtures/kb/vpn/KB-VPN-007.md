---
doc_id: KB-VPN-007
version: 1
request_type: vpn
doc_type: howto
owner: it_mgr01
updated_at: 2026-09-27
sensitivity: restricted
enabled: true
title: Cấu hình máy chủ VPN cho bộ phận IT
distractor: false
tags: [vpn, máy chủ, cấu hình, tường lửa, IKEv2, IKEEXT, lỗi 809]
---

## Giao thức và cổng trên máy chủ VPN

Máy chủ vpn.congty-abc.vn phục vụ hai giao thức. IKEv2 nhận kết nối qua cổng UDP 500 và 4500; SSTP nhận kết nối qua cổng TCP 443. Trên tường lửa biên của công ty, chỉ mở chiều vào cho đúng ba cổng này tới máy chủ VPN, không mở thêm cổng quản trị nào ra Internet. Cấu hình giao thức nằm trong bảng điều khiển của máy chủ VPN, mục "Giao thức", chỉ tài khoản quản trị của bộ phận IT mới đăng nhập được.

## Chẩn đoán lỗi 809 phía máy chủ

Khi nhiều người dùng cùng báo lỗi 809 trong một khoảng thời gian ngắn, kiểm tra phía máy chủ trước khi hướng dẫn từng người. Xem dịch vụ IKEEXT trên máy chủ có đang chạy không, nhật ký IKEv2 có ghi nhận gói tin tới cổng UDP 500 và 4500 không, và tường lửa biên có vừa bị thay đổi luật không. Nếu nhật ký không thấy gói tin nào, lỗi nằm ở tường lửa biên hoặc nhà mạng; nếu có gói tin mà phiên không lập được, kiểm tra chứng chỉ của máy chủ.

## Quy trình thay đổi cấu hình máy chủ

Mọi thay đổi cấu hình máy chủ VPN phải có phiếu thay đổi được trưởng bộ phận IT phê duyệt trước khi làm. Thực hiện thay đổi ngoài giờ hành chính để ít ảnh hưởng tới người dùng, sao lưu cấu hình cũ trước khi sửa, và ghi lại các bước đã làm vào phiếu. Sau khi thay đổi, tự kết nối thử bằng cả IKEv2 lẫn SSTP từ một mạng bên ngoài công ty rồi mới đóng phiếu.
