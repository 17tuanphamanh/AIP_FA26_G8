"""Giới hạn tần suất theo tài khoản (Phase 5 gói 2b, D-54 a; đặc tả `claude/dac-ta-bat-2-model.md` 4.8).

Hai bộ đếm, cùng Clock của app (route truyền `now = desk.clock.now()`):
- **A — `POST /api/tickets`:** đếm `tickets` của người gửi có `parent_ticket_id IS NULL` (ticket con chép `requester_id` của cha) trong
  10 phút và trong 1 giờ — chỉ đọc, index `ix_tickets_requester_created_at` (migration 0010).
- **B — `/messages`, `/reply`, `/confirm` chung một bộ:** bảng `rate_hits`. MỘT transaction mỗi lần kiểm: xoá dòng cũ của CHÍNH người này →
  đếm → dưới ngưỡng thì INSERT một dòng và cho qua; đủ ngưỡng thì 429, KHÔNG INSERT (nên công thức `Retry-After` đúng). Request sau đó bị
  404/403/409/422 vẫn đã được đếm. Mỗi tài khoản giữ tối đa khoảng ngưỡng dòng → không cần job dọn.

Vượt → `security_events(rate_limited)` CÙNG transaction, mỗi đợt một dòng: đợt = (người, bộ đếm, cửa sổ) — đã có sự kiện cùng ba khoá với
`occurred_at > now − độ dài cửa sổ` thì không ghi (Q-2B1-4). `ticket_id` luôn NULL (id trên đường dẫn là chữ người gửi tự đặt), `route` là
mẫu đường dẫn, `detail = {counter, window, limit}` — không có chữ người dùng. Hai request song song có thể lọt quá ngưỡng 1–2 lần hoặc ghi 2
dòng cho một đợt: chấp nhận, không dùng khoá (4.8).

Biên cửa sổ chặt: dòng thuộc cửa sổ khi `created_at > now − cửa sổ`. `Retry-After` (4.8): với mỗi cửa sổ đang vượt, giờ của request thứ
`count − limit + 1` tính từ cũ nhất + độ dài cửa sổ − `now`; lấy lớn nhất, làm tròn lên theo giây, tối thiểu 1. Các hàm thuần dưới đây dùng
chung cho bản giả của test (`tests/fakes/rate.py`).
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Table, delete, exists, func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import RateHit, SecurityEvent, Ticket
from app.db.security_events import insert_event
from app.settings import DEV_FAKE_ENVS, Settings

RATE_LIMITED = "rate_limited"
RATE_SETTINGS = ("ticket_rate_10min", "ticket_rate_hour", "message_rate_10min")
LOOSE_RATES_WARNING = "ngưỡng 429 lớn hơn mặc định ngoài dev/test (APP_ENV không phải dev|test): %s — chống spam đang bị nới"
type Counter = Literal["tickets", "messages"]
type WindowName = Literal["10m", "1h"]

_HITS: Table = RateHit.__table__  # type: ignore[assignment]
_EVENTS: Table = SecurityEvent.__table__  # type: ignore[assignment]
_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]


@dataclass(frozen=True)
class Window:
    name: WindowName
    seconds: int
    limit: int


@dataclass(frozen=True)
class RateLimits:
    ticket_10min: int
    ticket_hour: int
    message_10min: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "RateLimits":
        return cls(settings.ticket_rate_10min, settings.ticket_rate_hour, settings.message_rate_10min)

    def ticket_windows(self) -> tuple[Window, Window]:
        return Window("10m", 600, self.ticket_10min), Window("1h", 3600, self.ticket_hour)

    def message_window(self) -> Window:
        return Window("10m", 600, self.message_10min)


def loose_rate_vars(settings: Settings) -> list[str]:
    """Tên biến môi trường (KHÔNG giá trị) của ngưỡng 429 đặt lớn hơn mặc định khi APP_ENV không phải dev/test — `create_app` log
    WARNING, không chặn khởi động (Q-2B1-8: số lớn chỉ dành cho cổng/đo/demo; `.env` thật hay `RATE=loose` sót lại thì phải thấy)."""
    if settings.app_env in DEV_FAKE_ENVS:
        return []
    return [name.upper() for name in RATE_SETTINGS if getattr(settings, name) > Settings.model_fields[name].default]


def since(w: Window, now: datetime) -> datetime:
    return now - timedelta(seconds=w.seconds)


def over_limit(count: int, w: Window) -> bool:
    return count >= w.limit


def retry_after(overs: Iterable[tuple[Window, datetime]], now: datetime) -> int:
    """`overs` = (cửa sổ đang vượt, giờ của request thứ `count − limit + 1` tính từ cũ nhất)."""
    wait = max((at + timedelta(seconds=w.seconds) - now).total_seconds() for w, at in overs)
    return max(1, math.ceil(wait))


def event_detail(counter: Counter, w: Window) -> dict[str, Any]:
    return {"counter": counter, "window": w.name, "limit": w.limit}


class SqlRateGate:
    def __init__(self, engine: AsyncEngine, limits: RateLimits) -> None:
        self._engine = engine
        self._limits = limits

    async def tickets(self, user_id: str, now: datetime, route: str) -> int | None:
        own = (_TICKETS.c.requester_id == user_id) & _TICKETS.c.parent_ticket_id.is_(None)
        async with self._engine.begin() as conn:
            overs: list[tuple[Window, datetime]] = []
            for w in self._limits.ticket_windows():
                where = own & (_TICKETS.c.created_at > since(w, now))
                count = (await conn.execute(select(func.count()).select_from(_TICKETS).where(where))).scalar_one()
                if over_limit(count, w):
                    nth = select(_TICKETS.c.created_at).where(where).order_by(_TICKETS.c.created_at, _TICKETS.c.ticket_id)
                    overs.append((w, (await conn.execute(nth.offset(count - w.limit).limit(1))).scalar_one()))
            return await _limited(conn, "tickets", user_id, now, route, overs)

    async def messages(self, user_id: str, now: datetime, route: str) -> int | None:
        w = self._limits.message_window()
        mine = _HITS.c.user_id == user_id
        async with self._engine.begin() as conn:
            await conn.execute(delete(_HITS).where(mine & (_HITS.c.created_at <= since(w, now))))
            where = mine & (_HITS.c.created_at > since(w, now))
            count = (await conn.execute(select(func.count()).select_from(_HITS).where(where))).scalar_one()
            if not over_limit(count, w):
                await conn.execute(insert(_HITS).values(user_id=user_id, created_at=now))
                return None
            nth = select(_HITS.c.created_at).where(where).order_by(_HITS.c.created_at, _HITS.c.hit_id)
            at: datetime = (await conn.execute(nth.offset(count - w.limit).limit(1))).scalar_one()
            return await _limited(conn, "messages", user_id, now, route, [(w, at)])


async def _limited(
    conn: AsyncConnection, counter: Counter, user_id: str, now: datetime, route: str, overs: list[tuple[Window, datetime]]
) -> int | None:
    if not overs:
        return None
    for w, _ in overs:
        seen = exists().where(
            (_EVENTS.c.event_type == RATE_LIMITED) & (_EVENTS.c.user_id == user_id)
            & (_EVENTS.c.detail["counter"].astext == counter) & (_EVENTS.c.detail["window"].astext == w.name)
            & (_EVENTS.c.occurred_at > since(w, now))
        )  # fmt: skip
        if not (await conn.execute(select(seen))).scalar_one():
            await insert_event(conn, RATE_LIMITED, occurred_at=now, user_id=user_id, route=route, detail=event_detail(counter, w))
    return retry_after(overs, now)
