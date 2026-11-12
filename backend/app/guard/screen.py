"""Sàng lọc tin trả lời (phase3 mục 8.6, 3-Q3 phương án A): L0 + L2, thuần, không gọi mạng.

Dùng trong `clarify_wait` (câu trả lời) và `confirm_wait` (`note`) ngay sau `interrupt()`: khớp → `S_ESCALATED`, E0,
`injection_in_reply` (không `S_BLOCKED` — bảng 2.1 không có chuyển đó). Chỉ L0 + L2: rẻ, tất định; lớp bảo vệ bắt buộc
vẫn là bất biến 1 + 3-Q1. L4 cho mỗi câu trả lời là việc tối ưu sau (Phase 5).
"""

import re
from collections.abc import Mapping
from typing import Any

from app.guard import injection
from app.guard.injection import ScreenHit
from app.guard.patterns import INJECTION_GROUPS

# E1 soát 12/11 (agent 15 L4, D-92): API che TRƯỚC (D-07) → luật mật khẩu có thể nuốt từ khoá tấn công ("mk: Ignore previous
# instructions…" → "mk: [BÍ_MẬT_ĐÃ_ẨN] previous instructions…"). API so mẫu trên bản GỐC (chưa che) và chỉ chuyển MÃ mẫu + nhóm (không
# chữ) xuống graph: `raw_screen_hit` ở state đầu (B2) / `screen_hit` trong sự kiện trả lời (B11, B19). Bản gốc vẫn không được lưu.
_PATTERN_ID = re.compile(r"[A-Z]{2,5}-\d{2}")


def screen_reply(text: str) -> ScreenHit | None:
    return injection.match(text)


def hit_payload(hit: ScreenHit | None) -> dict[str, str] | None:
    return None if hit is None else {"id": hit.id, "group": hit.group}


def hit_from_payload(payload: object) -> ScreenHit | None:
    """Mã mẫu do API chuyển xuống — chỉ nhận đúng dáng (id `ABC-01`, nhóm thuộc tập đóng); sai dáng → None (không tin chữ tự do)."""
    if not isinstance(payload, Mapping):
        return None
    pid, group = payload.get("id"), payload.get("group")
    if isinstance(pid, str) and isinstance(group, str) and group in INJECTION_GROUPS and _PATTERN_ID.fullmatch(pid):
        return ScreenHit(pid, group)
    return None


def screen_event(text: str, ev: Mapping[str, Any]) -> ScreenHit | None:
    """Câu trả lời / ghi chú: khớp trên bản đã che, hoặc API đã thấy khớp trên bản gốc (`ev["screen_hit"]`)."""
    return screen_reply(text) or hit_from_payload(ev.get("screen_hit"))
