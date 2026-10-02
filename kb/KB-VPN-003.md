---
doc_id: KB-VPN-003
version: 1
request_type: vpn
doc_type: troubleshooting
owner: it_mgr01
updated_at: 2026-09-27
sensitivity: internal
enabled: true
title: Xử lý lỗi VPN 809 trên Windows
distractor: false
tags: [vpn, lỗi 809, windows, không kết nối được vpn, IKEv2, SSTP]
---

## Lỗi 809 là gì

Lỗi 809 xuất hiện khi ABC Connect trên Windows không kết nối được tới máy chủ VPN vpn.congty-abc.vn. Thông báo thường gặp: "Lỗi 809: Không thể thiết lập kết nối mạng giữa máy tính của bạn và máy chủ VPN vì máy chủ từ xa không phản hồi".

Lỗi này gần như luôn do **đường mạng** giữa máy bạn và máy chủ bị chặn, không phải do sai tài khoản hay mật khẩu (mk). Vì vậy đừng đổi mật khẩu khi gặp lỗi 809. Nguyên nhân thường gặp nhất là mạng bạn đang dùng chặn cổng UDP 500 và 4500 của giao thức IKEv2, ví dụ mạng khách sạn, quán cà phê hoặc mạng khách của công ty đối tác. Nguyên nhân ít gặp hơn: tường lửa trên máy chặn ABC Connect, dịch vụ IPsec của Windows bị tắt, hoặc chứng chỉ VPN của thiết bị đã hết hạn.

## Cách khắc phục: kiểm tra mạng và đổi giao thức

Làm lần lượt các bước sau. Sau mỗi bước, thử kết nối lại ABC Connect; kết nối được thì dừng.

1. Kiểm tra máy có vào được Internet: mở trình duyệt, vào một trang web bất kỳ. Không vào được thì sửa kết nối Internet trước, lỗi 809 sẽ tự hết.
2. Thử một mạng khác: phát Wi-Fi từ điện thoại (hotspot) rồi kết nối lại ABC Connect. Nếu dùng hotspot kết nối được, mạng cũ đang chặn IKEv2.
3. Chuyển ABC Connect sang giao thức dự phòng SSTP: mở ABC Connect, chọn "Cài đặt", mục "Giao thức", chọn "SSTP (TCP 443)", bấm "Lưu" rồi kết nối lại. SSTP đi qua cổng TCP 443 nên hầu hết mạng công cộng không chặn.

Nếu bước 3 kết nối được, bạn có thể tiếp tục dùng SSTP ở mạng đó. Khi về mạng gia đình hoặc văn phòng, chuyển lại "IKEv2 (tự động)" để có tốc độ tốt hơn.

## Cách khắc phục: kiểm tra trên máy tính

Nếu đã đổi mạng và đổi sang SSTP mà vẫn gặp lỗi 809, làm tiếp các bước sau trên máy Windows:

4. Kiểm tra tường lửa: mở "Windows Security", chọn "Firewall & network protection", chọn "Allow an app through firewall". Đảm bảo ABC Connect được đánh dấu cho cả mạng "Private" và "Public". Máy công ty bị khóa mục này thì bỏ qua bước 4.
5. Kiểm tra chứng chỉ VPN của thiết bị: mở ABC Connect, chọn "Chứng chỉ". Nếu dòng "Trạng thái" ghi "Hết hạn", hãy yêu cầu gia hạn hoặc cấp lại chứng chỉ qua trợ lý IT; không cần làm tiếp bước 6.
6. Khởi động lại dịch vụ IPsec: bấm Windows + R, gõ services.msc, tìm dịch vụ "IKE and AuthIP IPsec Keying Modules" (tên ngắn IKEEXT). Nếu trạng thái là "Stopped", bấm chuột phải chọn "Start". Sau đó khởi động lại máy và kết nối lại ABC Connect.

## Khi nào cần chuyển bộ phận IT

Liên hệ bộ phận IT (máy lẻ 1234) hoặc tạo yêu cầu trên trợ lý IT khi đã làm đủ 6 bước mà vẫn gặp lỗi 809, hoặc khi lỗi xuất hiện trên nhiều máy trong cùng văn phòng (có thể máy chủ đang gặp sự cố). Khi liên hệ, ghi rõ: mã lỗi 809, mạng bạn đang dùng (nhà, văn phòng, mạng công cộng), giao thức đã thử (IKEv2, SSTP) và các bước đã làm. Thông tin này giúp IT xử lý nhanh mà không phải hỏi lại.

Các mã lỗi VPN khác như 789, 812 hoặc 691 có cách xử lý khác, xem tài liệu riêng về các mã lỗi đó.
