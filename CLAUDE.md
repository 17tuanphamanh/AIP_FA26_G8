# AIP_FA26_G8

Cài  : .venv/bin/python -m pip install -r requirements.txt
Test : .venv/bin/python -m pytest -q
Chạy : .venv/bin/python main.py

## Cách làm việc

- **Làm trọn việc rồi mới báo cáo.** Sửa xong thì chạy test, đọc kết quả, rồi mới
  quay lại. Đừng dừng hỏi sau từng bước nhỏ — trừ khi có hai hướng khác hẳn nhau
  mà chọn sai thì phải làm lại từ đầu.
- **Việc dài thì lên kế hoạch trước** (Plan Mode, Shift+Tab). Rẻ hơn nhiều so với
  đi sai hướng rồi sửa.
- **Báo cáo trung thực.** Test đỏ thì nói đỏ kèm output. Bỏ qua bước nào thì nói rõ.
  Đừng viết "đã xong" cho phần chưa chạy thử.
- **Không commit, không push trừ khi được bảo.**

## Ranh giới

- Đổi phụ thuộc thì sửa `requirements.txt`, đừng cài ngầm vào máy.
- Bí mật nằm ở `.env` (đã gitignore) — không đọc, không ghi, không in ra.
  `.env.example` là file mẫu công khai, sửa thoải mái.
- Thư mục dữ liệu thô: chỉ đọc, không ghi đè.
- File sinh tự động (build, cache, lockfile) thì sửa nguồn, đừng sửa file sinh ra.

## Ghi chú riêng của repo

<!-- Thêm vào đây: kiến trúc, quy ước đặt tên, chỗ hay sai, người phụ trách phần nào -->
