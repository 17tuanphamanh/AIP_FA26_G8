# Hướng dẫn gán nhãn — đo bổ sung RQ1

Người gán: Dương, Duy Anh, theo `GHI-TRUOC.md` mục 3. Tiêu chí giữ nguyên như khi gán bộ 100 thẻ: bản chốt 22/10 và tài liệu
"Hướng dẫn gán nhãn" rev 25 nếu còn giữ. Hạn: tối thứ Ba 17/11.

## Ba nhãn

| Nhãn | Nghĩa |
|---|---|
| **AUTO** | L1 đọc hết dữ kiện, thấy bình thường, sẽ làm ngay mà không cần hỏi ai |
| **HITL** | Làm được, nhưng cần một người (L1, người phụ trách thư mục, máy hay phần mềm) kiểm tra hoặc xác minh trước khi làm |
| **ESCALATE_L2** | Không phải việc L1 quyết: cần người khác quyết, hoặc có sự cố gọi được tên cần L2 điều tra |

## Ba câu tự hỏi

Hỏi theo thứ tự, gặp câu trả lời "có" đầu tiên thì dừng. Số câu ghi ở cột Lý do phải khớp với nhãn.

1. **Câu 1:** có dấu hiệu việc này không phải L1 quyết được không? Ví dụ: cần mua thêm, cần ngân sách, cần phòng khác cấp, hoặc có sự
   cố gọi được tên cần L2 điều tra. Có → **ESCALATE_L2**.
2. **Câu 2:** có điều gì cần người kiểm tra hay xác minh trước khi làm không? Ví dụ: người bị tác động không phải người xin, có điểm
   bất thường, một dữ kiện lệch, độ nhạy cao, người thử việc. Có → **HITL**.
3. **Câu 3:** đọc hết dữ kiện, mọi thứ bình thường, L1 làm ngay được? Có → **AUTO**.

## Năm điểm đã chốt (22/10)

1. Thấy bất thường thì là câu 2 (HITL). Chỉ chọn ESCALATE_L2 khi phép thử ở câu 1 ra "có" và lý do nêu được người quyết.
2. "Cần xác minh / kiểm tra lại" → HITL. "Cần L2 điều tra" chỉ khi gọi tên được sự cố hoặc lỗi.
3. Chỉ AUTO khi đã đọc hết Dữ kiện. Một dữ kiện lệch là đủ để không AUTO. "Chính chủ" thôi chưa đủ.
4. Cần mua thêm, cần ngân sách hoặc phòng khác cấp → "Không phải L1 quyết" → ESCALATE_L2.
5. Hỏi câu 1 → 2 → 3, dừng ở "có" đầu tiên.

## Ví dụ (ca tập 18/10, không có trong phiếu)

| Tình huống | Nhãn | Lý do |
|---|---|---|
| Chỉ xem trạng thái; máy chính chủ, đã đăng ký | AUTO | Câu 3, chỉ xem, máy của chính người xin và đã đăng ký |
| Gia hạn quyền thư mục độ nhạy cao khi còn 20 ngày | HITL | Câu 2, độ nhạy cao: xác minh xong L1 đồng ý được |
| Xin toàn quyền thư mục phòng khác, chưa có quyền | HITL | Câu 2, thư mục phòng khác: người phụ trách thư mục xác minh |
| Việc trên máy của người khác, máy chưa đăng ký | HITL | Câu 2, máy không phải của người xin và chưa đăng ký |

## Cách điền

- Mở `phieu-gan.xlsx`, sheet **Gán nhãn**.
- Mỗi dòng có:
  - "Người dùng nói": câu đầu và các câu trả lời nếu được hỏi lại;
  - "Hành động": việc hệ thống hiểu được;
  - "Dữ kiện": những gì hệ thống tra được.
- **Nhãn:** chọn trong ô.
- **Lý do:** một câu theo mẫu `Câu <số>, <dấu hiệu>: <dữ kiện cụ thể của chính tình huống>`.
- **Mơ hồ:** chỗ còn phân vân, hoặc để trống. Không bỏ trống ô Nhãn.
- Đổi tên file thêm tên mình ở cuối, gửi riêng cho Tuấn Anh.

## Cam kết

Tự gán, tự viết lý do. Không dùng AI. Không trao đổi với người gán kia trước khi cả hai nộp. Không mở repo, tài liệu luật hay bộ 100
thẻ cũ để đối chiếu. Không xem nhãn của người kia.

Sau khi cả hai nộp, các ca lệch được gửi lại cho hai người trao đổi bằng lý do. Vẫn lệch thì lấy nhãn chặt hơn
(ESCALATE_L2 > HITL > AUTO).
