"""Đọc DB CHỈ-ĐỌC cho bộ thu thập M8 (G10, G11). Chỉ import được khi `EVAL_MODE=true` (qua `app.eval`).

Kết nối bằng `DATABASE_URL` (role `app_rw` — `app_monitor` không có quyền đọc bảng checkpoint, migration 0003) nhưng MỌI phiên bị ép
`default_transaction_read_only=on` (cả engine SQLAlchemy lẫn pool psycopg của `AsyncPostgresSaver`): INSERT/UPDATE/DELETE bị Postgres
từ chối. Chỉ đọc biến môi trường (`Settings(_env_file=None)`), không đọc `.env`.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.graph.checkpoint import open_postgres_saver
from app.settings import Settings

READ_ONLY_OPTION = "--default_transaction_read_only=on"
POOL_SIZE = 2


@dataclass(frozen=True)
class Reader:
    engine: AsyncEngine
    saver: AsyncPostgresSaver

    async def state(self, ticket_id: str) -> Mapping[str, Any] | None:
        """Giá trị kênh của checkpoint MỚI NHẤT của ticket (`conversation`, `retrieved`, `intended_action`, `requester_context`,
        `ctx_flags`, …); None nếu ticket chưa có checkpoint."""
        found = await self.saver.aget_tuple({"configurable": {"thread_id": ticket_id}})
        return None if found is None else found.checkpoint["channel_values"]


def read_only_url(database_url: str) -> str:
    """URL SQLAlchemy + tham số libpq `options` ép phiên chỉ đọc (cho pool psycopg của `AsyncPostgresSaver`). Dạng `--name=value` KHÔNG có
    khoảng trắng: `-c name=value` bị `conninfo()` (SQLAlchemy mã hoá khoảng trắng thành "+", libpq không giải mã) làm hỏng."""
    return make_url(database_url).update_query_dict({"options": READ_ONLY_OPTION}).render_as_string(hide_password=False)


@asynccontextmanager
async def open_reader(settings: Settings | None = None) -> AsyncIterator[Reader]:
    settings = settings or Settings(_env_file=None)  # type: ignore[call-arg]
    engine = create_async_engine(settings.database_url, connect_args={"options": READ_ONLY_OPTION}, hide_parameters=True)  # F15
    try:
        async with open_postgres_saver(read_only_url(settings.database_url), max_size=POOL_SIZE) as saver:
            yield Reader(engine, saver)
    finally:
        await engine.dispose()
