"""Lỗi LƯỜNG TRƯỚC của executor (B17) — node bắt tường minh; mọi exception khác (bug trong PLAN…) rơi xuống E9 (B17 §5)."""


class ExecutionInterrupted(Exception):
    """Ticket đã có dòng `transaction_log` `begun` (bất kỳ lượt nào — chốt DỪNG 2, NGHI-2) — lần chạy trước chết giữa chừng
    (hoặc sau lời gọi ghi, trước checkpoint). Không biết hệ thống ngoài đang ở trạng thái nào → KHÔNG ghi lại: B17 → E7 `exec_interrupted`
    (phase3 3.3, 11.4 bước 4; B17 §5 "vì sao chạy lại B17 không ghi hai lần"). Thông điệp chỉ có định danh."""
