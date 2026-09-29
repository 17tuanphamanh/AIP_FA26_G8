"""Sàng lọc tin trả lời (phase3 mục 8.6, 3-Q3 phương án A): L0 + L2, thuần, không gọi mạng.

Dùng trong `clarify_wait` (câu trả lời) và `confirm_wait` (`note`) ngay sau `interrupt()`: khớp → `S_ESCALATED`, E0,
`injection_in_reply` (không `S_BLOCKED` — bảng 2.1 không có chuyển đó). Chỉ L0 + L2: rẻ, tất định; lớp bảo vệ bắt buộc
vẫn là bất biến 1 + 3-Q1. L4 cho mỗi câu trả lời là việc tối ưu sau (Phase 5).
"""

from app.guard import injection
from app.guard.injection import ScreenHit


def screen_reply(text: str) -> ScreenHit | None:
    return injection.match(text)
