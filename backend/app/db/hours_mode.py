"""Giả lập giờ hành chính cho demo (D-97, TA chốt 14/11) — KHÔNG thêm bảng: trạng thái hiện hành là dòng `security_events` loại
`policy_saved` mới nhất có `detail.kind = "hours_mode"` (bảng chỉ ghi thêm → đủ lịch sử ai đổi, lúc nào; khuôn `detail` giống đổi
chiến lược M5: `{kind, from, to}`). Chưa có dòng nào → `real` (theo giờ thật).

- `real`: `time.within_business_hours` tính từ đồng hồ thật như cũ.
- `outside`: coi MỌI thời điểm là ngoài giờ hành chính (R18 khớp với VPN như lúc 20:00).
- `inside`: coi MỌI thời điểm là trong giờ hành chính.

Chỉ đổi đúng một fact của luật (`time.within_business_hours`), KHÔNG đổi đồng hồ (OTP, hạn token, hạn duyệt vẫn theo giờ thật).
B12/B17 đọc chế độ lúc đánh giá (`NodeDeps.hours_mode`); điểm log 4 ghi `detail.hours_mode` khi khác `real`.
`set_mode`: MỘT transaction — khoá tư vấn (hai PUT đồng thời không cùng thấy "khác hiện tại"), so chế độ hiện hành (trùng →
`SameHoursMode`), INSERT `security_events`. Giá trị lạ trong DB (không được xảy ra: chỉ route PUT ghi) → `real` + log cảnh báo.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.security_events import insert_event

log = logging.getLogger(__name__)

HoursMode = Literal["real", "outside", "inside"]
HOURS_MODES: tuple[HoursMode, ...] = ("real", "outside", "inside")
DEFAULT_MODE: HoursMode = "real"
KIND = "hours_mode"
POLICY_SAVED = "policy_saved"
ROUTE = "/api/admin/hours-mode"
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended('hours_mode', 0))")
_CURRENT = text(
    "SELECT user_id, occurred_at, detail->>'to' AS mode FROM security_events "
    "WHERE event_type = 'policy_saved' AND detail->>'kind' = 'hours_mode' ORDER BY event_id DESC LIMIT 1"
)


class HoursModeReader(Protocol):
    async def mode(self) -> "HoursMode": ...


class SameHoursMode(Exception):
    """Chế độ mới trùng chế độ hiện hành (409 `same_as_current`)."""


@dataclass(frozen=True)
class HoursModeState:
    mode: HoursMode
    changed_by: str | None
    changed_at: datetime | None


def as_mode(raw: object) -> HoursMode:
    if raw in HOURS_MODES:
        return cast(HoursMode, raw)
    log.warning("hours_mode: giá trị %r ngoài %s — dùng %s", raw, HOURS_MODES, DEFAULT_MODE)
    return DEFAULT_MODE


def _state(row: Any) -> HoursModeState:
    if row is None:
        return HoursModeState(mode=DEFAULT_MODE, changed_by=None, changed_at=None)
    at = row.occurred_at.astimezone(UTC) if row.occurred_at is not None else None
    return HoursModeState(mode=as_mode(row.mode), changed_by=row.user_id, changed_at=at)


async def _current(conn: AsyncConnection) -> HoursModeState:
    return _state((await conn.execute(_CURRENT)).first())


class SqlHoursModeStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def current(self) -> HoursModeState:
        async with self._engine.connect() as conn:
            return await _current(conn)

    async def mode(self) -> HoursMode:
        return (await self.current()).mode

    async def set_mode(self, mode: HoursMode, *, changed_by: str, at: datetime) -> HoursModeState:
        async with self._engine.begin() as conn:
            await conn.execute(_LOCK)
            previous = (await _current(conn)).mode
            if mode == previous:
                raise SameHoursMode(mode)
            await insert_event(
                conn, POLICY_SAVED, occurred_at=at, user_id=changed_by, route=ROUTE,
                detail={"kind": KIND, "from": previous, "to": mode},
            )  # fmt: skip
        return HoursModeState(mode=mode, changed_by=changed_by, changed_at=at)


class StaticHoursMode:
    """Bản cố định (mặc định của `NodeDeps` trong test, và khi không có DB): luôn trả đúng một chế độ."""

    def __init__(self, mode: HoursMode = DEFAULT_MODE) -> None:
        self._mode = mode

    async def mode(self) -> HoursMode:
        return self._mode
