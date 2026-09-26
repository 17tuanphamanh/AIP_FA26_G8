"""Kết quả cuối của ticket (B20 mục 2 bước 3; điểm log 8) — kiểu thuần, dùng chung cho `audit/final.py`
(tính) và `db/tickets.py` (ghi một lần, đọc lại)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FinalSummary:
    """Các cột `tickets` ghi một lần ở B20 — cũng là nội dung điểm log 8."""

    final_state: str
    exit_code: str | None
    block_reason: str | None
    close_reason: str | None
    resolution_path: str | None
    aggregate_status: str | None
    auto_closed: bool
    intent: str | None
    slots: dict[str, Any] | None
    total_turns: int
    total_duration_seconds: int
    closed_at: datetime
