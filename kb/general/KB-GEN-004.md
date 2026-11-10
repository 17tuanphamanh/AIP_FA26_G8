---
doc_id: KB-GEN-004
version: 1
request_type: general
doc_type: troubleshooting
owner: l1_lead
updated_at: 2026-11-09
sensitivity: internal
enabled: true
title: "Outlook không gửi hoặc không nhận được email"
distractor: false
tags: [general, outlook, email, không gửi được mail, không nhận được mail, hộp thư đầy, outbox]
---

## Kiểm tra Outlook có đang kết nối không

Microsoft Outlook là ứng dụng email của công ty, đi kèm bộ Microsoft Office. Khi không gửi hoặc không nhận được email (mail), trước hết kiểm tra Outlook có đang kết nối tới máy chủ thư không:

1. Nhìn thanh trạng thái ở dưới cùng cửa sổ Outlook. Nếu thấy chữ "Working Offline" hoặc "Disconnected", Outlook đang không kết nối.
2. Nếu thấy "Working Offline", mở thẻ "Send / Receive" và bấm nút "Work Offline" một lần để tắt chế độ làm việc ngoại tuyến.
3. Kiểm tra máy tính có vào được Internet không bằng cách mở một trang web bất kỳ.
4. Đóng Outlook hoàn toàn rồi mở lại. Nếu vẫn không được, khởi động lại máy tính.

Nếu bạn dùng Outlook trên trình duyệt (Outlook trên web) mà vẫn gửi nhận bình thường, lỗi nằm ở ứng dụng Outlook trên máy chứ không phải ở hộp thư.

## Thư nằm trong Hộp thư đi (Outbox) không gửi được

Khi thư bạn gửi cứ nằm trong thư mục "Outbox" (Hộp thư đi) mà không chuyển sang "Sent Items" (Thư đã gửi), thường do một trong các lý do sau:

- **Tệp đính kèm quá lớn.** Máy chủ thư từ chối thư có tệp đính kèm vượt giới hạn. Hãy xóa tệp đính kèm, lưu tệp vào thư mục dùng chung rồi gửi đường dẫn tới thư mục đó trong email.
- **Outlook đang ngoại tuyến.** Làm theo mục kiểm tra kết nối ở trên.
- **Thư bị lỗi.** Mở thư mục "Outbox", kéo thư đó sang thư mục "Drafts" (Thư nháp), mở lại thư, kiểm tra địa chỉ người nhận rồi bấm "Send" lần nữa.

Nếu nhận được thư báo lỗi gửi thư (thư trả về, "Undeliverable"), đọc phần lý do trong thư đó. Lý do thường gặp là gõ sai địa chỉ người nhận.

## Không nhận được email

Khi người khác báo đã gửi mà bạn không thấy thư, kiểm tra lần lượt:

1. Thư mục "Junk Email" (Thư rác). Nếu thư đúng là thư công việc, bấm chuột phải vào thư, chọn "Junk", chọn "Not Junk".
2. Thẻ "Other" bên cạnh thẻ "Focused" trong Hộp thư đến. Outlook có thể tự xếp thư vào thẻ "Other".
3. Quy tắc tự chuyển thư (Rules) mà bạn từng tạo: vào "File", chọn "Manage Rules & Alerts" để xem có quy tắc nào chuyển thư sang thư mục khác không.
4. Hộp thư có bị đầy không: Outlook sẽ hiện cảnh báo hộp thư gần đầy. Khi đó hãy xóa thư cũ có tệp đính kèm lớn và dọn sạch thư mục "Deleted Items".

## Khi nào cần liên hệ bộ phận IT về email

Liên hệ bộ phận IT (máy lẻ 1234) hoặc nhắn trợ lý IT để được chuyển cho kỹ thuật viên khi:

- Đã làm đủ các bước trên mà Outlook vẫn không gửi hoặc không nhận được thư.
- Cả Outlook trên máy và Outlook trên web đều không gửi nhận được.
- Nhiều người trong phòng cùng không nhận được thư.
- Hộp thư vẫn báo đầy sau khi đã dọn dẹp.

Khi báo, ghi rõ thời điểm bắt đầu lỗi, nội dung thông báo lỗi hoặc thư trả về, và bạn dùng Outlook trên máy hay trên web. Nếu bạn nhận được email lạ yêu cầu bấm vào liên kết hoặc cung cấp thông tin, xem tài liệu về email lừa đảo.
