"""`child_notices` — hộp thư của ticket con (P7 2.9; Phase 5 T20b P5). Ghi trong transaction của `effects.once` (`current_tx()`) nên
dòng notice và dòng `side_effects` cùng commit; không có transaction đó thì tự mở transaction ngắn. `effect_key` UNIQUE: lần ghi thứ
hai (chạy lại node con) không thêm dòng, trả `notice_id` cũ."""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import ChildNotice, Ticket
from app.db.runtime import current_tx

_NOTICES: Table = ChildNotice.__table__  # type: ignore[assignment]
_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]


class SqlNoticeStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def _in_tx[T](self, fn: Callable[[AsyncConnection], Awaitable[T]]) -> T:
        conn = current_tx()
        if conn is not None:
            return await fn(conn)
        async with self._engine.begin() as own:
            return await fn(own)

    async def parent_of(self, ticket_id: str) -> str | None:
        async def run(conn: AsyncConnection) -> str | None:
            row = await conn.execute(select(_TICKETS.c.parent_ticket_id).where(_TICKETS.c.ticket_id == ticket_id))
            value: Any = row.scalar_one_or_none()
            return None if value is None else str(value)

        return await self._in_tx(run)

    async def insert(
        self, *, parent_id: str, child_id: str, source_step: str, kind: str, needs: str, body: str, effect_key: str
    ) -> int:
        async def run(conn: AsyncConnection) -> int:
            done = await conn.execute(
                pg_insert(_NOTICES)
                .values(parent_ticket_id=parent_id, child_ticket_id=child_id, source_step=source_step, kind=kind,
                        needs=needs, body=body, effect_key=effect_key)
                .on_conflict_do_nothing(index_elements=["effect_key"])
                .returning(_NOTICES.c.notice_id)
            )  # fmt: skip
            new = done.scalar_one_or_none()
            if new is not None:
                return int(new)
            old = await conn.execute(select(_NOTICES.c.notice_id).where(_NOTICES.c.effect_key == effect_key))
            return int(old.scalar_one())

        return await self._in_tx(run)
