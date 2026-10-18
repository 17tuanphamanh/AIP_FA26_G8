"""Cổng đếm 429 giả (gói 2b, D-54 a) cho test HTTP không có DB — cùng hợp đồng `api.ratelimit.RateGate` với `db.rate_limits.SqlRateGate`.

Dùng CHÍNH các hàm thuần của `db/rate_limits.py` (biên cửa sổ, so ngưỡng, `Retry-After`, `detail` của sự kiện), chỉ thay chỗ lưu:
- bộ A (`tickets`): đếm dòng `MemoryTickets.rows` của người gửi có `parent_ticket_id is None` (ticket con chép `requester_id` của cha);
- bộ B (`messages`): `hits[user_id]` = giờ các request đã được cho qua; dọn dòng cũ của người đang gửi; request bị 429 không ghi;
- `rate_limited` ghi vào `RecordingSink` (đồng hồ của sink = Clock của app), mỗi đợt (người, bộ đếm, cửa sổ) một dòng.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any

from app.db.rate_limits import (
    RATE_LIMITED,
    Counter,
    RateLimits,
    Window,
    event_detail,
    over_limit,
    retry_after,
    since,
)
from tests.fakes.auth import RecordingSink

type TicketRows = Callable[[], Iterable[Mapping[str, Any]]]


class MemoryRateGate:
    def __init__(self, limits: RateLimits, *, tickets: TicketRows, sink: RecordingSink) -> None:
        self.limits = limits
        self._tickets = tickets
        self._sink = sink
        self.hits: dict[str, list[datetime]] = {}
        self.calls: list[tuple[Counter, str, str]] = []  # (bộ đếm, user_id, route) — test kiểm "chưa xác thực không hao lượt"

    async def tickets(self, user_id: str, now: datetime, route: str) -> int | None:
        self.calls.append(("tickets", user_id, route))
        times = sorted(
            r["created_at"] for r in self._tickets()
            if r["requester_id"] == user_id and r["parent_ticket_id"] is None
        )  # fmt: skip
        overs = [o for w in self.limits.ticket_windows() if (o := _over(times, w, now)) is not None]
        return await self._limited("tickets", user_id, now, route, overs)

    async def messages(self, user_id: str, now: datetime, route: str) -> int | None:
        self.calls.append(("messages", user_id, route))
        w = self.limits.message_window()
        times = self.hits.setdefault(user_id, [])
        times[:] = sorted(t for t in times if t > since(w, now))  # dọn dòng cũ của chính người gửi
        over = _over(times, w, now)
        if over is None:
            times.append(now)
            return None
        return await self._limited("messages", user_id, now, route, [over])

    async def _limited(
        self, counter: Counter, user_id: str, now: datetime, route: str, overs: list[tuple[Window, datetime]]
    ) -> int | None:
        if not overs:
            return None
        for w, _ in overs:
            seen = any(
                e.user_id == user_id and e.detail.get("counter") == counter and e.detail.get("window") == w.name
                and e.occurred_at > since(w, now)
                for e in self._sink.of(RATE_LIMITED)
            )  # fmt: skip
            if not seen:
                await self._sink.record(RATE_LIMITED, user_id=user_id, route=route, detail=event_detail(counter, w))
        return retry_after(overs, now)


def _over(times: list[datetime], w: Window, now: datetime) -> tuple[Window, datetime] | None:
    """Cửa sổ đang vượt → (cửa sổ, giờ của request thứ `count − limit + 1` tính từ cũ nhất); không vượt → None."""
    inside = [t for t in times if t > since(w, now)]
    if not over_limit(len(inside), w):
        return None
    return w, inside[len(inside) - w.limit]
