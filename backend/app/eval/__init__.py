"""M8 — khung đánh giá (P8). Chỉ import được khi `EVAL_MODE=true` (P8 §8; Q-T29-2 chốt 13/10 ở #32).

Đọc thẳng `os.environ`, không dựng `Settings()` (cần DSN, `.env`). Chỉ nhận đúng chữ `true` (không phân biệt hoa thường, bỏ khoảng
trắng hai đầu) — chặt hơn bool của `Settings` (`1`, `yes`… bị từ chối ở đây): lệch về phía không import.
"""

import os

if os.environ.get("EVAL_MODE", "").strip().lower() != "true":
    raise ImportError("app.eval chỉ import được khi EVAL_MODE=true (P8 §8) — M8 không chạy trong vận hành")
