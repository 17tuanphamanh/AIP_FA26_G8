"""Đồng hồ tiêm được: code nghiệp vụ gọi clock.now(), test dùng FakeClock để tua thời gian
(hạn chờ 24h/30 phút/48h) mà không cần sleep."""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Thời điểm hiện tại, luôn có múi giờ UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = _require_aware(start or datetime(2026, 1, 1, tzinfo=UTC))

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def set(self, at: datetime) -> None:
        self._now = _require_aware(at)


def _require_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("FakeClock cần datetime có múi giờ")
    return dt.astimezone(UTC)
