"""Checkpoint LangGraph trên Postgres (P1 mục 3, P7 mục 3).

Bảng checkpoint do migration 0003 tạo (`PostgresSaver.setup()` chạy dưới `app_migrate`); app chạy
bằng `app_rw` chỉ có CRUD → KHÔNG gọi `setup()` ở đây.

Serde: kiểu Pydantic của domain được khai báo tường minh — LangGraph 1.x cảnh báo (và bản sau sẽ
chặn) khi đọc lại kiểu chưa đăng ký từ checkpoint.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef, ExecutionResult, RiskDecision

CHECKPOINT_TABLES = ("checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes")
STATE_TYPES: tuple[type, ...] = (RequesterContext, Action, ChunkRef, RiskDecision, ExecutionResult)


def make_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


def conninfo(database_url: str) -> str:
    """URL SQLAlchemy (`postgresql+psycopg://…`) → conninfo psycopg."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


@asynccontextmanager
async def open_postgres_saver(database_url: str, *, max_size: int) -> AsyncIterator[AsyncPostgresSaver]:
    kwargs: dict[str, Any] = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
    async with AsyncConnectionPool(
        conninfo(database_url), min_size=1, max_size=max_size, kwargs=kwargs, open=False
    ) as pool:
        yield AsyncPostgresSaver(pool, serde=make_serde())  # type: ignore[arg-type]
