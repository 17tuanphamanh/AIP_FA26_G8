"""Store SQL cho runtime graph (P1, P7 2.5, 2.8; HD17.1): `side_effects`, `turns`, `spans`,
`wait_deadlines` (+ đọc hạn `approvals`). Khớp các Protocol ở `app/graph/ports.py` theo cấu trúc.

Mọi transaction ở đây ngắn (D-19): không store nào giữ transaction trong lúc graph chạy node.
"""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Table, and_, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import Approval, SideEffect, Span, Ticket, Turn, WaitDeadline

_EFFECTS: Table = SideEffect.__table__  # type: ignore[assignment]
_TURNS: Table = Turn.__table__  # type: ignore[assignment]
_SPANS: Table = Span.__table__  # type: ignore[assignment]
_WAITS: Table = WaitDeadline.__table__  # type: ignore[assignment]
_APPROVALS: Table = Approval.__table__  # type: ignore[assignment]
_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]

RESULT_REF_MAX = 128  # side_effects.result_ref VARCHAR(128)

type WaitKind = Literal["clarify", "confirm", "approval"]


@dataclass(frozen=True)
class OpenTurn:
    ticket_id: str
    turn_id: str
    started_at: datetime


@dataclass(frozen=True)
class DueWait:
    ticket_id: str
    kind: WaitKind
    ref: str  # created_turn (clarify/confirm) hoặc approval_id (approval)
    is_parent: bool = False


_TX: ContextVar[AsyncConnection | None] = ContextVar("effect_tx", default=None)


def current_tx() -> AsyncConnection | None:
    """Kết nối đang mở transaction của `effects.once` — hàm side effect ghi DB cùng transaction với
    dòng `side_effects` (P1 mục 5.3: thông báo trong app nằm cùng transaction)."""
    return _TX.get()


def as_ref(value: Any) -> str | None:
    return None if value is None else str(value)[:RESULT_REF_MAX]


class SqlEffectStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

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
        async with self._engine.begin() as conn:
            inserted = await conn.execute(
                pg_insert(_EFFECTS)
                .values(effect_key=key, ticket_id=ticket_id, kind=kind, step=step, turn_id=turn_id)
                .on_conflict_do_nothing(index_elements=["effect_key"])
                .returning(_EFFECTS.c.effect_key)
            )
            if inserted.first() is None:  # đã làm ở lần chạy trước
                old = await conn.execute(
                    select(_EFFECTS.c.result_ref).where(_EFFECTS.c.effect_key == key)
                )
                return old.scalar_one_or_none()
            token = _TX.set(conn)
            try:
                ref = as_ref(await call())
            finally:
                _TX.reset(token)
            await conn.execute(
                update(_EFFECTS).where(_EFFECTS.c.effect_key == key).values(result_ref=ref)
            )
            return ref

    async def peek(self, key: str) -> str | None:
        """Phase 4 4b P9: chỉ SELECT `side_effects.result_ref` — không ghi. Dòng của `run_once` đang dở (chưa commit) không thấy
        được — process chết giữa chừng thì dòng đó cũng mất, chạy lại làm như chưa làm (D-18)."""
        async with self._engine.connect() as conn:
            row = await conn.execute(select(_EFFECTS.c.result_ref).where(_EFFECTS.c.effect_key == key))
            return row.scalar_one_or_none()


class SqlTurnStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def start(
        self, *, turn_id: str, ticket_id: str, session_id: str | None, event_type: str, at: datetime
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(_TURNS).values(
                    turn_id=turn_id, ticket_id=ticket_id, session_id=session_id,
                    event_type=event_type, started_at=at,
                )
            )

    async def end(self, turn_id: str, at: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_TURNS)
                .where(_TURNS.c.turn_id == turn_id, _TURNS.c.ended_at.is_(None))
                .values(ended_at=at)
            )

    async def is_open(self, turn_id: str) -> bool:
        async with self._engine.connect() as conn:
            row = await conn.execute(
                select(_TURNS.c.turn_id).where(
                    _TURNS.c.turn_id == turn_id, _TURNS.c.ended_at.is_(None)
                )
            )
            return row.first() is not None

    async def bump_recover_attempts(self, turn_id: str) -> int | None:
        """Tăng bộ đếm TRƯỚC khi chạy lại (migration 0005): process chết giữa lượt vẫn bị tính.
        None = lượt đã đóng."""
        async with self._engine.begin() as conn:
            row = await conn.execute(
                update(_TURNS)
                .where(_TURNS.c.turn_id == turn_id, _TURNS.c.ended_at.is_(None))
                .values(recover_attempts=_TURNS.c.recover_attempts + 1)
                .returning(_TURNS.c.recover_attempts)
            )
            value = row.scalar()
            return None if value is None else int(value)

    async def stale(self, before: datetime, limit: int) -> list[OpenTurn]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                select(_TURNS.c.ticket_id, _TURNS.c.turn_id, _TURNS.c.started_at)
                .where(_TURNS.c.ended_at.is_(None), _TURNS.c.started_at < before)
                .order_by(_TURNS.c.started_at)
                .limit(limit)
            )
            return [OpenTurn(r.ticket_id, r.turn_id, r.started_at) for r in rows]


class SqlSpanSink:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def write(self, span: Any) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(insert(_SPANS).values(**asdict(span)))


class SqlDeadlineStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def set(self, ticket_id: str, kind: str, deadline: datetime, created_turn: str) -> str:
        conn = current_tx()
        if conn is not None:
            await self._set(conn, ticket_id, kind, deadline, created_turn)
        else:
            async with self._engine.begin() as own:
                await self._set(own, ticket_id, kind, deadline, created_turn)
        return created_turn

    @staticmethod
    async def _set(
        conn: AsyncConnection, ticket_id: str, kind: str, deadline: datetime, created_turn: str
    ) -> None:
        # Hạn cũ chưa bắn của cùng ticket + kind bị thay: không để hạn vòng trước cắt ngang vòng sau.
        await conn.execute(
            update(_WAITS)
            .where(_WAITS.c.ticket_id == ticket_id, _WAITS.c.kind == kind, _WAITS.c.fired_at.is_(None))
            .values(fired_at=func.now())
        )
        await conn.execute(
            pg_insert(_WAITS)
            .values(ticket_id=ticket_id, kind=kind, deadline=deadline, created_turn=created_turn)
            .on_conflict_do_nothing()
        )

    async def due(self, now: datetime, limit: int) -> list[DueWait]:
        async with self._engine.connect() as conn:
            waits = await conn.execute(
                select(_WAITS.c.ticket_id, _WAITS.c.kind, _WAITS.c.created_turn, _TICKETS.c.is_parent)
                .join(_TICKETS, _TICKETS.c.ticket_id == _WAITS.c.ticket_id)
                .where(_WAITS.c.fired_at.is_(None), _WAITS.c.deadline < now)
                .order_by(_WAITS.c.deadline)
                .limit(limit)
            )
            out = [DueWait(r.ticket_id, r.kind, r.created_turn, bool(r.is_parent)) for r in waits]
            approvals = await conn.execute(
                select(_APPROVALS.c.ticket_id, _APPROVALS.c.approval_id)
                .where(_APPROVALS.c.status == "pending", _APPROVALS.c.deadline < now)
                .order_by(_APPROVALS.c.deadline)
                .limit(limit)
            )
            out += [DueWait(r.ticket_id, "approval", str(r.approval_id)) for r in approvals]
            return out

    async def mark_fired(self, due: DueWait, at: datetime) -> None:
        async with self._engine.begin() as conn:
            if due.kind == "approval":
                # Node B16 đã ghi `timeout` khi giao được; ca 409 (ticket đã đi tiếp) thì đóng phiếu
                # ở đây để worker không bắn lại mỗi chu kỳ.
                await conn.execute(
                    update(_APPROVALS)
                    .where(and_(_APPROVALS.c.approval_id == int(due.ref), _APPROVALS.c.status == "pending"))
                    .values(status="timeout")
                )
                return
            await conn.execute(
                update(_WAITS)
                .where(
                    _WAITS.c.ticket_id == due.ticket_id, _WAITS.c.kind == due.kind,
                    _WAITS.c.created_turn == due.ref, _WAITS.c.fired_at.is_(None),
                )
                .values(fired_at=at)
            )
