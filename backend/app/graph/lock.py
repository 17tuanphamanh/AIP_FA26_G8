"""Khoá theo ticket (P1 mục 7, D-19): `pg_advisory_lock` CẤP SESSION trên lock pool riêng.

Không giữ transaction mở suốt lượt: câu lấy khoá commit ngay, kết nối chỉ giữ khoá. `lock_timeout`
(đặt ở `db/session.py`) → `TicketBusy`. Nhả trong `finally`; nhả lỗi thì huỷ hẳn kết nối — Postgres tự
nhả khoá cấp session khi kết nối đóng, không để kết nối còn giữ khoá quay về pool.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.graph.ports import TicketBusy

LOCK_NOT_AVAILABLE = "55P03"  # SQLSTATE lock_not_available (hết lock_timeout)


class PgTicketLock:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def hold(self, ticket_id: str) -> AsyncIterator[None]:
        async with self._engine.connect() as conn:
            try:
                await conn.execute(text("SELECT pg_advisory_lock(hashtext(:t))"), {"t": ticket_id})
                await conn.commit()
            except DBAPIError as exc:
                await conn.rollback()
                if getattr(exc.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE:
                    raise TicketBusy(ticket_id) from exc
                raise
            try:
                yield
            finally:
                try:
                    await conn.execute(
                        text("SELECT pg_advisory_unlock(hashtext(:t))"), {"t": ticket_id}
                    )
                    await conn.commit()
                except Exception:
                    await conn.invalidate()
                    raise
