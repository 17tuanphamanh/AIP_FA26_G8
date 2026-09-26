"""Cổng lưu trữ của runtime (P1) — bản SQL ở `app/db/runtime.py`, `app/audit/writer.py`; bản
in-memory cùng hợp đồng ở `backend/tests/fakes/graph.py` để test graph không cần Postgres.
"""

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.db.runtime import DueWait, OpenTurn, WaitKind

__all__ = ["DueWait", "OpenTurn", "WaitKind"]  # bản ghi dữ liệu dùng chung với store SQL


class AuditSink(Protocol):
    async def record(self, row: Mapping[str, Any]) -> bool:
        """INSERT `audit_logs`; `idempotency_key` trùng → bỏ qua (ON CONFLICT DO NOTHING).

        Trả True nếu SAU lệnh ghi có dòng mang khoá đó (vừa ghi hoặc đã có) — kiểm trong CÙNG
        transaction với INSERT (cấm 4, P1 mục 5.1.1). Dòng không khoá: luôn ghi, trả True."""
        ...


class EffectStore(Protocol):
    async def run_once(
        self,
        *,
        key: str,
        ticket_id: str,
        kind: str,
        step: str,
        turn_id: str,
        call: Callable[[], Awaitable[Any]],
    ) -> str | None:
        """Khoá chưa có → ghi `side_effects`, gọi `call()` đúng một lần, lưu `result_ref`, cùng
        một transaction. Khoá đã có → trả `result_ref` cũ, KHÔNG gọi `call` (D-18)."""
        ...


@dataclass
class SpanRecord:
    span_id: str
    trace_id: str
    turn_id: str
    span_type: str  # node | llm | tool | rag
    name: str
    started_at: datetime
    parent_span_id: str | None = None
    duration_ms: int | None = None
    status: str = "ok"  # ok | error | interrupted
    attributes: dict[str, Any] = field(default_factory=dict)


class SpanSink(Protocol):
    async def write(self, span: SpanRecord) -> None: ...


class TurnStore(Protocol):
    async def start(
        self, *, turn_id: str, ticket_id: str, session_id: str | None, event_type: str, at: datetime
    ) -> None: ...

    async def end(self, turn_id: str, at: datetime) -> None: ...

    async def is_open(self, turn_id: str) -> bool: ...

    async def stale(self, before: datetime, limit: int) -> list[OpenTurn]:
        """Lượt chưa kết thúc (`ended_at IS NULL`) bắt đầu trước `before` (P1 mục 7)."""
        ...


class DeadlineStore(Protocol):
    async def set(self, ticket_id: str, kind: str, deadline: datetime, created_turn: str) -> str:
        """Đặt hạn chờ `clarify`/`confirm` (`wait_deadlines`). Hạn cũ chưa bắn của cùng ticket +
        kind bị đánh dấu đã bắn (bị thay) — để hạn vòng hỏi trước không cắt ngang vòng sau."""
        ...

    async def due(self, now: datetime, limit: int) -> list[DueWait]:
        """Hạn đã qua, chưa bắn: `wait_deadlines` + `approvals` đang `pending` (hạn duyệt nằm ở
        `approvals.deadline` [Chốt], P7 2.5). Worker không đọc checkpoint."""
        ...

    async def mark_fired(self, due: DueWait, at: datetime) -> None: ...


class TicketLock(Protocol):
    def hold(self, ticket_id: str) -> AbstractAsyncContextManager[None]:
        """Khoá theo ticket suốt một lượt (D-19). Hết `lock_timeout` → `TicketBusy`."""
        ...


class TicketBusy(Exception):
    """Ticket đang bị lượt khác giữ khoá quá `lock_timeout` — lỗi tạm, thử lại chu kỳ sau."""
