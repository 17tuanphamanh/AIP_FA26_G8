"""Repository `tickets` (P7; B20 mục 3, 5; `tickets` ghi một lần ở B20 [Chốt DB vòng 3]).

`finalize_once`: `UPDATE … WHERE final_state IS NULL`, rồi ĐỌC LẠI dòng đang có trong cùng
transaction và trả nó — lần đầu là kết quả vừa ghi, lần chạy lại là kết quả đã ghi trước đó. B20 ghi
điểm log 8 từ chính giá trị này (quyết định Q-C 2b-2), nên audit và `tickets` không bao giờ lệch nhau
dù B20 chạy lại sau vài phút. "Ghi một lần" hiểu theo từng cột (2b-Q5): `close_reason` của ticket
escalate còn NULL tới khi L2 đóng (Phase 7).

`create` (tạo ticket từ API) làm ở 2b-3; `create_child`/`mark_parent_once` ở Phase 5.
"""

from datetime import UTC, datetime

from sqlalchemy import Table, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import Ticket, Turn
from app.domain.final import FinalSummary

_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]
_TURNS: Table = Turn.__table__  # type: ignore[assignment]
_FINAL_COLUMNS = (
    "final_state", "exit_code", "block_reason", "close_reason", "resolution_path",
    "aggregate_status", "auto_closed", "intent", "slots", "total_turns", "total_duration_seconds",
    "closed_at",
)  # fmt: skip


class TicketMissing(LookupError):
    """Không có dòng `tickets` — lỗi lập trình (ticket phải được tạo trước khi submit graph)."""


class SqlTicketStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def created_at(self, ticket_id: str) -> datetime:
        async with self._engine.connect() as conn:
            value = (
                await conn.execute(
                    select(_TICKETS.c.created_at).where(_TICKETS.c.ticket_id == ticket_id)
                )
            ).scalar()
        if value is None:
            raise TicketMissing(ticket_id)
        return value.astimezone(UTC)  # type: ignore[no-any-return]

    async def count_turns(self, ticket_id: str) -> int:
        async with self._engine.connect() as conn:
            count = await conn.execute(
                select(func.count()).select_from(_TURNS).where(_TURNS.c.ticket_id == ticket_id)
            )
            return int(count.scalar_one())

    async def finalize_once(self, ticket_id: str, summary: FinalSummary) -> FinalSummary:
        values = {c: getattr(summary, c) for c in _FINAL_COLUMNS}
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_TICKETS)
                .where(_TICKETS.c.ticket_id == ticket_id, _TICKETS.c.final_state.is_(None))
                .values(**values)
            )
            row = (
                await conn.execute(
                    select(*(_TICKETS.c[c] for c in _FINAL_COLUMNS)).where(
                        _TICKETS.c.ticket_id == ticket_id
                    )
                )
            ).first()
        if row is None:
            raise TicketMissing(ticket_id)
        stored = dict(row._mapping)
        stored["closed_at"] = stored["closed_at"].astimezone(UTC)
        return FinalSummary(**stored)
