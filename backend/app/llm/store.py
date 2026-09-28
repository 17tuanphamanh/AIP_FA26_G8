"""Store SQL của gateway: `llm_cache` (P7 2.4), `spans` + `llm_calls` (HD17.1, P2 mục 11), tổng chi tiêu (P2 mục 5).

`record` ghi span rồi `llm_calls` trong MỘT transaction ngắn (`llm_calls.span_id` FK → `spans`). Không có lượt graph
(`turn_id` None) → `RuntimeError`: `spans.turn_id` NOT NULL FK → `turns` (PLAN-3d Q-3d-2) — gateway kiểm trước khi gọi
provider nên nhánh này chỉ là lớp bảo vệ thứ hai.
"""

from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import Table, func, insert, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import LlmCache, LlmCall, Span
from app.llm.ports import CacheMode, LlmCallRow, LlmSpan

_CACHE: Table = LlmCache.__table__  # type: ignore[assignment]
_CALLS: Table = LlmCall.__table__  # type: ignore[assignment]
_SPANS: Table = Span.__table__  # type: ignore[assignment]


class SqlLlmStore:
    requires_trace = True

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def cache_get(self, key: str, *, mode: CacheMode, now: datetime) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = await conn.execute(
                select(_CACHE.c.response_json).where(
                    _CACHE.c.cache_key == key,
                    _CACHE.c.mode == mode,
                    or_(_CACHE.c.expires_at.is_(None), _CACHE.c.expires_at > now),
                )
            )
            value = row.scalar_one_or_none()
            return dict(value) if value is not None else None

    async def cache_put(
        self,
        key: str,
        *,
        mode: CacheMode,
        prompt_id: str,
        prompt_version: str,
        model: str,
        response: dict[str, Any],
        now: datetime,
        expires_at: datetime | None,
    ) -> None:
        values = {"prompt_id": prompt_id, "prompt_version": prompt_version, "model": model, "response_json": response,
                  "created_at": now, "expires_at": expires_at, "mode": mode}  # fmt: skip
        stmt = pg_insert(_CACHE).values(cache_key=key, **values)
        async with self._engine.begin() as conn:
            await conn.execute(stmt.on_conflict_do_update(index_elements=["cache_key"], set_=values))

    async def record(self, span: LlmSpan, call: LlmCallRow) -> None:
        if span.turn_id is None:
            raise RuntimeError("span LLM không có turn_id — spans.turn_id NOT NULL FK (Q-3d-2)")
        async with self._engine.begin() as conn:
            await conn.execute(insert(_SPANS).values(**asdict(span)))
            await conn.execute(insert(_CALLS).values(**asdict(call)))

    async def spend_total(self) -> float:
        async with self._engine.connect() as conn:
            row = await conn.execute(select(func.coalesce(func.sum(_CALLS.c.cost_usd), 0.0)))
            return float(row.scalar_one())
