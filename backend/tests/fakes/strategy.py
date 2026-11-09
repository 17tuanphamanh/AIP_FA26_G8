"""`m5_strategy_changes` giả (D-67) — cùng ngữ nghĩa `db/m5_strategy.SqlStrategyStore`: chỉ ghi thêm, hiện hành = dòng cuối, trùng
chiến lược hiện hành → `SameStrategy`, `strategy_from` của dòng đầu = `hybrid`; `append` ghi thêm `policy_saved` vào `events`."""

from datetime import datetime
from typing import Any

from app.db.m5_strategy import DEFAULT_STRATEGY, SameStrategy, StrategyChange


class MemoryStrategyStore:
    def __init__(self) -> None:
        self.rows: list[StrategyChange] = []
        self.events: list[dict[str, Any]] = []
        self.fail: Exception | None = None  # tiêm lỗi vào `current` (DB lỗi)

    async def current(self) -> StrategyChange | None:
        if self.fail is not None:
            raise self.fail
        return self.rows[-1] if self.rows else None

    async def history(self, limit: int) -> tuple[list[StrategyChange], bool]:
        newest = list(reversed(self.rows))
        return newest[:limit], len(newest) > limit

    async def append(self, strategy: str, *, changed_by: str, reason: str, at: datetime) -> StrategyChange:
        previous = self.rows[-1].strategy if self.rows else DEFAULT_STRATEGY
        if strategy == previous:
            raise SameStrategy(strategy)
        change = StrategyChange(id=len(self.rows) + 1, strategy=strategy, strategy_from=previous, changed_by=changed_by,
                                reason=reason, changed_at=at)  # fmt: skip
        self.rows.append(change)
        self.events.append({"event_type": "policy_saved", "user_id": changed_by,
                            "detail": {"kind": "m5_strategy", "from": previous, "to": strategy}})  # fmt: skip
        return change
