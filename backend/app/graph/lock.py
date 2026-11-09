"""Khoá theo ticket (P1 mục 7, D-19): `pg_advisory_lock(hashtextextended(ticket_id, 0))` CẤP SESSION trên lock pool riêng.

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
# G1: khoá bigint từ `hashtextextended(text, 0)` (64 bit) — `hashtext` chỉ 32 bit nên hai ticket khác nhau dễ trùng khoá và chặn nhau.
# Lock và unlock dùng CÙNG biểu thức: unlock lệch khoá là no-op và khoá cấp session ở lại trên kết nối đã trả pool.
# Đổi hàm băm = đổi khoá: khởi động lại backend VÀ worker cùng lúc (xem tài liệu vận hành), không để hai bản chạy song song.
KEY_EXPR = "hashtextextended(:t, 0)"
LOCK_SQL = f"SELECT pg_advisory_lock({KEY_EXPR})"
UNLOCK_SQL = f"SELECT pg_advisory_unlock({KEY_EXPR})"


class PgTicketLock:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def hold(self, ticket_id: str) -> AsyncIterator[None]:
        async with self._engine.connect() as conn:
            try:
                await conn.execute(text(LOCK_SQL), {"t": ticket_id})
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
                    await conn.execute(text(UNLOCK_SQL), {"t": ticket_id})
                    await conn.commit()
                except Exception:
                    await conn.invalidate()
                    raise
