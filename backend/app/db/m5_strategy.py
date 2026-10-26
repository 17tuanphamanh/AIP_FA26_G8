"""Chiến lược M5 lúc vận hành (D-67) — bảng `m5_strategy_changes` (chỉ ghi thêm, migration 0013).

- `current()`: dòng có `id` lớn nhất; chưa có dòng nào → None (nơi gọi coi là `hybrid`).
- `history(limit)`: mới nhất trước; `strategy_from` = chiến lược của dòng liền trước theo `id` (dòng đầu tiên → `hybrid`, mặc định
  trước D-67). Đọc `limit + 1` dòng để biết còn dòng cũ hơn (`truncated`).
- `append(...)`: MỘT transaction — khoá tư vấn (hai PUT đồng thời không cùng thấy "khác hiện tại"), kiểm khác chiến lược hiện hành
  (trùng → `SameStrategy`), INSERT dòng đổi và `security_events` loại `policy_saved` có sẵn (`detail.kind = "m5_strategy"` để không
  lẫn với lưu chính sách). `at` lấy từ Clock của app. Lý do đã qua privacy guard ở route; bảng không đọc lại chữ người dùng.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Table, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import M5StrategyChange
from app.db.security_events import insert_event

_CHANGES: Table = M5StrategyChange.__table__  # type: ignore[assignment]
DEFAULT_STRATEGY = "hybrid"  # trước D-67 chỉ có `hybrid` chạy lúc vận hành; chưa có dòng nào → `hybrid`
POLICY_SAVED = "policy_saved"
ROUTE = "/api/admin/strategy"
_LOCK = text("SELECT pg_advisory_xact_lock(hashtext('m5_strategy_changes'))")
_HISTORY = text(
    "SELECT id, strategy, LAG(strategy, 1, :default) OVER (ORDER BY id) AS strategy_from, changed_by, reason, changed_at "
    "FROM m5_strategy_changes ORDER BY id DESC LIMIT :limit"
)


class SameStrategy(Exception):
    """Chiến lược mới trùng chiến lược hiện hành (409 `same_as_current`)."""


@dataclass(frozen=True)
class StrategyChange:
    id: int
    strategy: str
    strategy_from: str
    changed_by: str
    reason: str
    changed_at: datetime


def _change(row: Any, strategy_from: str) -> StrategyChange:
    return StrategyChange(
        id=int(row.id), strategy=str(row.strategy), strategy_from=strategy_from, changed_by=str(row.changed_by),
        reason=str(row.reason), changed_at=row.changed_at.astimezone(UTC),
    )  # fmt: skip


class SqlStrategyStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def current(self) -> StrategyChange | None:
        async with self._engine.connect() as conn:
            rows = (await conn.execute(_HISTORY, {"default": DEFAULT_STRATEGY, "limit": 1})).all()
        return _change(rows[0], str(rows[0].strategy_from)) if rows else None

    async def history(self, limit: int) -> tuple[list[StrategyChange], bool]:
        async with self._engine.connect() as conn:
            rows = (await conn.execute(_HISTORY, {"default": DEFAULT_STRATEGY, "limit": limit + 1})).all()
        items = [_change(r, str(r.strategy_from)) for r in rows[:limit]]
        return items, len(rows) > limit

    async def append(self, strategy: str, *, changed_by: str, reason: str, at: datetime) -> StrategyChange:
        async with self._engine.begin() as conn:
            await conn.execute(_LOCK)
            last = (
                await conn.execute(select(_CHANGES.c.strategy).order_by(_CHANGES.c.id.desc()).limit(1))
            ).scalar()
            previous = DEFAULT_STRATEGY if last is None else str(last)
            if strategy == previous:
                raise SameStrategy(strategy)
            row = (
                await conn.execute(
                    insert(_CHANGES)
                    .values(strategy=strategy, changed_by=changed_by, reason=reason, changed_at=at)
                    .returning(*_CHANGES.c)
                )
            ).one()
            await insert_event(
                conn, POLICY_SAVED, occurred_at=at, user_id=changed_by, route=ROUTE,
                detail={"kind": "m5_strategy", "from": previous, "to": strategy},
            )  # fmt: skip
        return _change(row, previous)
