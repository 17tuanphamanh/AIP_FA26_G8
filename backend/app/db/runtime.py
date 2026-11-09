"""Store SQL cho runtime graph (P1, P7 2.5, 2.8; HD17.1): `side_effects`, `turns`, `spans`,
`wait_deadlines` (+ đọc hạn `approvals`). Khớp các Protocol ở `app/graph/ports.py` theo cấu trúc.

Nhắc duyệt 50 %/80 % (Phase 4 4c P3, Q-4c-2 = A): `due_reminders` + `mark_reminder_once` nằm ở `SqlDeadlineStore` (cùng chỗ `due`/
`mark_fired` vốn đã đọc/ghi `approvals`) vì `worker.py` chỉ truyền runner/deadlines/turns cho `WorkerJobs`. `mark_reminder_once` = ĐÚNG
câu SQL P3 (`… reminder_n_at IS NULL AND deadline > :now RETURNING …`): hai worker cùng quét chỉ một bên nhận dòng → một thông báo.

Mọi transaction ở đây ngắn (D-19): không store nào giữ transaction trong lúc graph chạy node.
"""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Table, TextClause, and_, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import Approval, SideEffect, Span, Ticket, Turn, WaitDeadline
from app.domain.approval import REMINDER_FRACTIONS, ReminderN

_EFFECTS: Table = SideEffect.__table__  # type: ignore[assignment]
_TURNS: Table = Turn.__table__  # type: ignore[assignment]
_SPANS: Table = Span.__table__  # type: ignore[assignment]
_WAITS: Table = WaitDeadline.__table__  # type: ignore[assignment]
_APPROVALS: Table = Approval.__table__  # type: ignore[assignment]
_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]

RESULT_REF_MAX = 128  # side_effects.result_ref VARCHAR(128)
CHILD_SKIP = "child:skip"  # Phase 5 T20b P5: `deadlines.set` của ticket con không ghi gì — hạn do cha giữ (`result_ref` của `deadline_set`)

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


@dataclass(frozen=True)
class OrphanChild:
    """Phase 5 T20b P12 (b): con đang chờ người dùng mà cha đã kết thúc — worker giao `timeout` (`needs` → trạng thái chờ)."""

    ticket_id: str
    needs: Literal["answer", "confirm"]


@dataclass(frozen=True)
class DueReminder:
    """Phiếu `pending`, chưa tới hạn, đã qua mốc 1 mà còn ít nhất một cột nhắc NULL — worker tính nhắc nào bằng
    `domain.approval.next_reminder`."""

    approval_id: str
    ticket_id: str
    created_at: datetime
    deadline: datetime
    reminder_1_at: datetime | None
    reminder_2_at: datetime | None


@dataclass(frozen=True)
class ReminderTarget:
    """`RETURNING approver_id, backup_approver_id` của `mark_reminder_once` — có dòng = bên này thắng, được gửi."""

    approver_id: str
    backup_approver_id: str | None


# 4c P3: lọc THÔ (đã qua mốc 1, còn cột NULL, chưa tới hạn) — nhắc nào do `domain.approval.next_reminder` quyết.
_DUE_REMINDERS = text(
    "SELECT approval_id, ticket_id, created_at, deadline, reminder_1_at, reminder_2_at FROM approvals "
    "WHERE status = 'pending' AND deadline > :now AND (reminder_1_at IS NULL OR reminder_2_at IS NULL) "
    "AND created_at + (deadline - created_at) * :f1 <= :now ORDER BY deadline LIMIT :limit"
)
# 4c P3 — câu SQL NGUYÊN VĂN của spec (chốt Q-4c-2): có dòng trả về = bên này thắng, chỉ bên đó gửi.
_MARK_REMINDER: dict[ReminderN, TextClause] = {
    n: text(
        f"UPDATE approvals SET reminder_{n}_at = :now WHERE approval_id = :id AND status = 'pending' "
        f"AND reminder_{n}_at IS NULL AND deadline > :now RETURNING approver_id, backup_approver_id"
    )
    for n in (1, 2)
}

# Phase 5 T20b P12 (a) — hai vế (spec gốc + Q-T20b-7 thay vế 1, duyệt DỪNG 2): cha chưa kết thúc mà (1) số con ĐÃ khởi động (dòng
# `child_submit` của cha — `result_ref` = `started:<con>`, đếm khác nhau) < số con (con chưa khởi động / khởi động lỗi trước checkpoint đầu:
# có `turns` mà thread rỗng — FAIL-2), HOẶC (2) ĐÚNG điều kiện `domain.children.round_ready` trên `SqlTicketStore.children_view` (D-77):
# mọi con đã dừng (`final_state` hoặc phiếu duyệt `pending`, VÀ không còn lượt `turns` mở; hoặc có notice chưa gửi `needs ≠ none`) VÀ (có
# notice chưa gửi HOẶC mọi con đã kết thúc) — vế sau để cha chỉ còn con chờ duyệt (đã báo) không bị đánh thức mỗi chu kỳ (con cạn phục hồi
# ở B20 / tín hiệu đánh thức bị mất — NGHI-2). Đánh thức thừa (cha không ở `parent_wait`) là no-op.
_PARENTS_TO_WAKE = text(
    "SELECT p.ticket_id FROM tickets p "
    "WHERE p.is_parent AND p.final_state IS NULL "
    "AND EXISTS (SELECT 1 FROM tickets c WHERE c.parent_ticket_id = p.ticket_id) "
    "AND ((SELECT count(DISTINCT s.result_ref) FROM side_effects s WHERE s.ticket_id = p.ticket_id AND s.kind = 'child_submit') "
    "      < (SELECT count(*) FROM tickets c WHERE c.parent_ticket_id = p.ticket_id) "
    "  OR (NOT EXISTS (SELECT 1 FROM tickets c WHERE c.parent_ticket_id = p.ticket_id AND NOT ("
    "      ((c.final_state IS NOT NULL "
    "        OR EXISTS (SELECT 1 FROM approvals a WHERE a.ticket_id = c.ticket_id AND a.status = 'pending')) "
    "       AND NOT EXISTS (SELECT 1 FROM turns t WHERE t.ticket_id = c.ticket_id AND t.ended_at IS NULL)) "
    "      OR EXISTS (SELECT 1 FROM child_notices n WHERE n.child_ticket_id = c.ticket_id AND n.parent_ticket_id = p.ticket_id "
    "                 AND n.delivered_at IS NULL AND n.needs <> 'none'))) "
    "    AND (EXISTS (SELECT 1 FROM child_notices n WHERE n.parent_ticket_id = p.ticket_id AND n.delivered_at IS NULL) "
    "         OR NOT EXISTS (SELECT 1 FROM tickets c WHERE c.parent_ticket_id = p.ticket_id AND (c.final_state IS NULL "
    "             OR EXISTS (SELECT 1 FROM turns t WHERE t.ticket_id = c.ticket_id AND t.ended_at IS NULL)))))) "
    "ORDER BY p.created_at LIMIT :limit"
)
# P12 (b) mở rộng (Q-T20b-5 (iii)): con chưa kết thúc, cha ĐÃ kết thúc, có notice `needs ≠ none` (đã gửi hay chưa) — `needs` của notice đó
# mới nhất; con đang có phiếu duyệt `pending` → bỏ (chờ L1, không chờ người dùng). Q-T20b-9 (ii): chỉ khi đã quá hạn thường (24 h hỏi lại /
# 48 h xác nhận) tính từ `delivered_at` của notice đó (chưa gửi → `created_at`).
_ORPHAN_CHILDREN = text(
    "SELECT c.ticket_id, n.needs FROM tickets c JOIN tickets p ON p.ticket_id = c.parent_ticket_id "
    "JOIN LATERAL (SELECT x.needs, coalesce(x.delivered_at, x.created_at) AS since FROM child_notices x "
    "              WHERE x.child_ticket_id = c.ticket_id AND x.needs <> 'none' "
    "              ORDER BY x.created_at DESC, x.notice_id DESC LIMIT 1) n ON true "
    "WHERE c.final_state IS NULL AND p.final_state IS NOT NULL "
    "AND NOT EXISTS (SELECT 1 FROM approvals a WHERE a.ticket_id = c.ticket_id AND a.status = 'pending') "
    "AND n.since <= CAST(:now AS timestamptz) "
    "    - make_interval(hours => CASE n.needs WHEN 'answer' THEN CAST(:clarify_h AS integer) ELSE CAST(:confirm_h AS integer) END) "
    "ORDER BY c.created_at LIMIT :limit"
)

_TX: ContextVar[AsyncConnection | None] = ContextVar("effect_tx", default=None)


def current_tx() -> AsyncConnection | None:
    """Kết nối đang mở transaction của `effects.once` — hàm side effect ghi DB cùng transaction với
    dòng `side_effects` (P1 mục 5.3: thông báo trong app nằm cùng transaction)."""
    return _TX.get()


@dataclass(frozen=True)
class EffectCall:
    """Side effect đang chạy trong `effects.once` (Phase 5 T20b P5): `ChildAwareNotifier` ghi `child_notices.source_step` +
    `effect_key` từ đây (không truyền qua chữ ký `notify_user`)."""

    step: str
    key: str


_EFFECT: ContextVar[EffectCall | None] = ContextVar("effect_call", default=None)


def current_effect() -> EffectCall | None:
    """Bước + khoá của side effect đang chạy; None ngoài `effects.once`. `effects.once` đặt quanh `call()` (TQ-2 — một chỗ cho cả
    store SQL lẫn store giả của test)."""
    return _EFFECT.get()


@contextmanager
def bind_effect(step: str, key: str) -> Iterator[EffectCall]:
    token = _EFFECT.set(call := EffectCall(step, key))
    try:
        yield call
    finally:
        _EFFECT.reset(token)


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
        """Phase 5 T20b: ticket CON → không ghi gì, trả `CHILD_SKIP` (P5 (b) — hạn do cha giữ, D-31); ticket CHA → thay MỌI hạn
        `wait_deadlines` chưa bắn của cha, cả `clarify` lẫn `confirm` (Q-T20b-3 = A: hạn vòng trước khác loại không được bắn vào vòng
        sau — mọi hạn của cha đều giao `timeout` với `S_CONFIRMING`); ticket thường → như cũ (cùng loại). Không đụng hạn duyệt."""
        conn = current_tx()
        if conn is not None:
            return await self._set(conn, ticket_id, kind, deadline, created_turn)
        async with self._engine.begin() as own:
            return await self._set(own, ticket_id, kind, deadline, created_turn)

    @staticmethod
    async def _set(
        conn: AsyncConnection, ticket_id: str, kind: str, deadline: datetime, created_turn: str
    ) -> str:
        who = (await conn.execute(
            select(_TICKETS.c.parent_ticket_id, _TICKETS.c.is_parent).where(_TICKETS.c.ticket_id == ticket_id)
        )).first()  # fmt: skip
        if who is not None and who.parent_ticket_id is not None:
            return CHILD_SKIP
        same = (_WAITS.c.ticket_id == ticket_id, _WAITS.c.fired_at.is_(None))
        # Hạn cũ chưa bắn bị thay: không để hạn vòng trước cắt ngang vòng sau (cha: mọi loại; còn lại: cùng loại).
        await conn.execute(
            update(_WAITS)
            .where(*same, *(() if who is not None and who.is_parent else (_WAITS.c.kind == kind,)))
            .values(fired_at=func.now())
        )
        await conn.execute(
            pg_insert(_WAITS)
            .values(ticket_id=ticket_id, kind=kind, deadline=deadline, created_turn=created_turn)
            .on_conflict_do_nothing()
        )
        return created_turn

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

    async def due_reminders(self, now: datetime, limit: int) -> list[DueReminder]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(_DUE_REMINDERS, {"now": now, "f1": REMINDER_FRACTIONS[1], "limit": limit})
            return [DueReminder(str(r.approval_id), r.ticket_id, r.created_at, r.deadline, r.reminder_1_at, r.reminder_2_at)
                    for r in rows]  # fmt: skip

    async def parents_to_wake(self, limit: int) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(_PARENTS_TO_WAKE, {"limit": limit})
            return [str(r.ticket_id) for r in rows]

    async def orphan_children(
        self, now: datetime, limit: int, *, clarify_hours: int, confirm_hours: int
    ) -> list[OrphanChild]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                _ORPHAN_CHILDREN, {"now": now, "limit": limit, "clarify_h": clarify_hours, "confirm_h": confirm_hours}
            )
            return [OrphanChild(str(r.ticket_id), r.needs) for r in rows]

    async def mark_reminder_once(self, approval_id: str, n: ReminderN, now: datetime) -> ReminderTarget | None:
        async with self._engine.begin() as conn:
            row = (await conn.execute(_MARK_REMINDER[n], {"id": int(approval_id), "now": now})).first()
        return None if row is None else ReminderTarget(row.approver_id, row.backup_approver_id)

    async def mark_fired(self, due: DueWait, at: datetime) -> None:
        async with self._engine.begin() as conn:
            if due.kind == "approval":
                # Node B16 đã ghi `timeout` khi giao được; ca 409 (ticket đã đi tiếp) thì đóng phiếu
                # ở đây để worker không bắn lại mỗi chu kỳ. `decided_at` ở MỌI nhánh đóng phiếu (4c A11 — M9 luật 7).
                await conn.execute(
                    update(_APPROVALS)
                    .where(and_(_APPROVALS.c.approval_id == int(due.ref), _APPROVALS.c.status == "pending"))
                    .values(status="timeout", decided_at=at)
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
