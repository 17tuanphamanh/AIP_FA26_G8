"""Đồng hồ tiêm được: code nghiệp vụ gọi clock.now() / await clock.sleep(), test dùng FakeClock để
tua thời gian (hạn chờ 24h/30 phút/48h, backoff 1s/2s của call_with_retry) mà không phải chờ thật."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Thời điểm hiện tại, luôn có múi giờ UTC."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Chờ `seconds` giây (FakeClock: tua đồng hồ ngay, không chờ thật)."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = _require_aware(start or datetime(2026, 1, 1, tzinfo=UTC))
        self.sleeps: list[float] = []  # các lần sleep đã gọi — test kiểm backoff 1s, 2s

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def set(self, at: datetime) -> None:
        self._now = _require_aware(at)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += timedelta(seconds=seconds)


def _require_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("FakeClock cần datetime có múi giờ")
    return dt.astimezone(UTC)
