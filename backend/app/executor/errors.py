"""Lỗi LƯỜNG TRƯỚC của executor (B17) — node bắt tường minh; mọi exception khác (bug trong PLAN…) rơi xuống E9 (B17 §5)."""


class ExecutionInterrupted(Exception):
    """Không biết hệ thống ngoài đang ở trạng thái nào → KHÔNG ghi (lại): B17 → E7 `exec_interrupted` (phase3 3.3, 11.4 bước 4;
    B17 §5 "vì sao chạy lại B17 không ghi hai lần"). Hai nguồn:

    - Ticket đã có dòng `transaction_log` `begun` (bất kỳ lượt nào — chốt DỪNG 2, NGHI-2): lần chạy trước chết giữa chừng. 0
      lời gọi ghi ở lần này (`write_calls=0`, `cause=None`).
    - Lỗi bất kỳ (`Exception`, không phải `BaseException`) SAU `begin` của lần này — đứt kết nối sau khi gửi, phản hồi 2xx hỏng
      hoặc sai schema… (chốt FAIL mục 7, soát DỪNG 3b): lệnh ghi có thể đã tới đích. `cause` = CHỈ tên lớp lỗi (luật 8.9 — không
      chép thông điệp/nội dung phản hồi), `write_calls` = số lời gọi ghi đã gửi (cận trên).

    Thông điệp chỉ có định danh."""

    def __init__(
        self, message: str, *, cause: str | None = None, write_calls: int = 0, steps_begun: tuple[str, ...] = ()
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.write_calls = write_calls
        # V10 (soát 12/11, agent 12 M3): tên tool (tập đóng) các bước đã `begun` ở LẦN NÀY — ghi chú L2 nêu bước đã gửi + license
        self.steps_begun = steps_begun
