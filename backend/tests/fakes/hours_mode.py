"""Giả lập giờ hành chính giả (D-97) — cùng ngữ nghĩa `db/hours_mode.SqlHoursModeStore`: chưa đổi → `real`, trùng chế độ hiện hành →
`SameHoursMode`, mỗi lần đổi ghi một `policy_saved {kind: hours_mode, from, to}` vào `events`."""

from datetime import datetime
from typing import Any

from app.db.hours_mode import DEFAULT_MODE, HoursMode, HoursModeState, SameHoursMode


class MemoryHoursModeStore:
    def __init__(self) -> None:
        self.state = HoursModeState(mode=DEFAULT_MODE, changed_by=None, changed_at=None)
        self.events: list[dict[str, Any]] = []

    async def current(self) -> HoursModeState:
        return self.state

    async def mode(self) -> HoursMode:
        return self.state.mode

    async def set_mode(self, mode: HoursMode, *, changed_by: str, at: datetime) -> HoursModeState:
        previous = self.state.mode
        if mode == previous:
            raise SameHoursMode(mode)
        self.state = HoursModeState(mode=mode, changed_by=changed_by, changed_at=at)
        self.events.append({"event_type": "policy_saved", "user_id": changed_by,
                            "detail": {"kind": "hours_mode", "from": previous, "to": mode}})  # fmt: skip
        return self.state
