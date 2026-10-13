"""Repository `tickets` (P7; B20 mục 3, 5; `tickets` ghi một lần ở B20 [Chốt DB vòng 3]).

`finalize_once`: `UPDATE … WHERE final_state IS NULL`, rồi ĐỌC LẠI dòng đang có trong cùng
transaction và trả nó — lần đầu là kết quả vừa ghi, lần chạy lại là kết quả đã ghi trước đó. B20 ghi
điểm log 8 từ chính giá trị này (quyết định Q-C 2b-2), nên audit và `tickets` không bao giờ lệch nhau
dù B20 chạy lại sau vài phút. "Ghi một lần" hiểu theo từng cột (2b-Q5): `close_reason` của ticket
escalate còn NULL tới khi L2 đóng (Phase 7).

`create` (API, 2b-3): dòng `tickets` + dòng `turns` (lượt `submit` đầu tiên) trong MỘT transaction —
không có khe nào để lại ticket không có lượt (worker chỉ phục hồi được lượt đã có dòng `turns`).
`created_at` lấy từ Clock của app, không `now()` của Postgres (2b-QD): thời lượng B20 tính cùng đồng hồ.
Sự kiện `security_events` của lúc tạo (3e: `privacy_secret_redacted {count}`) INSERT CÙNG khối đó (phase3 mục 8.3) — lỗi
bất kỳ INSERT nào thì không còn ticket, lượt hay sự kiện nào.
Phase 5 T20b (P3, P7): `create_child` (INSERT … SELECT từ dòng cha), `mark_parent_once`, `children_view` (đối soát từ DB — D-17),
`deliver_round` (đánh dấu notice đã gửi cùng transaction với tin tổng hợp — `current_tx()`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Table, func, insert, literal, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import ChildNotice, Ticket, Turn
from app.db.runtime import current_tx
from app.db.security_events import check_event, insert_event
from app.domain.children import ChildProgressRow, ChildView, Notice, child_index
from app.domain.final import FinalSummary

_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]
_TURNS: Table = Turn.__table__  # type: ignore[assignment]
_NOTICES: Table = ChildNotice.__table__  # type: ignore[assignment]
_FINAL_COLUMNS = (
    "final_state", "exit_code", "block_reason", "close_reason", "resolution_path",
    "aggregate_status", "auto_closed", "intent", "slots", "total_turns", "total_duration_seconds",
    "closed_at",
)  # fmt: skip


@dataclass(frozen=True)
class NewTicket:
    ticket_id: str
    requester_id: str
    requester_role: str
    requester_dept: str | None
    session_id: str | None
    redacted_request: str  # ĐÃ qua privacy guard (D-07)
    created_at: datetime


@dataclass(frozen=True)
class TicketRow:
    """Phần dòng `tickets` mà API (quyền, GET) và runner (dựng state đầu) cần."""

    ticket_id: str
    requester_id: str
    session_id: str | None
    redacted_request: str
    parent_ticket_id: str | None
    is_parent: bool
    final_state: str | None
    exit_code: str | None
    close_reason: str | None
    created_at: datetime
    closed_at: datetime | None


_ROW_COLUMNS = tuple(TicketRow.__dataclass_fields__)
CREATE_ROUTE = "/api/tickets"  # `security_events.route` của sự kiện ghi lúc tạo ticket

type NewEvents = Sequence[tuple[str, Mapping[str, Any]]]  # (event_type, detail) — không chứa văn bản người dùng


class TicketMissing(LookupError):
    """Không có dòng `tickets` — lỗi lập trình (ticket phải được tạo trước khi submit graph)."""


class SqlTicketStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, ticket: NewTicket, *, turn_id: str, security_events: NewEvents = ()) -> None:
        for event_type, detail in security_events:  # lỗi lập trình nổ TRƯỚC khi mở transaction
            check_event(event_type, detail)
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(_TICKETS).values(
                    ticket_id=ticket.ticket_id, requester_id=ticket.requester_id,
                    requester_role=ticket.requester_role, requester_dept=ticket.requester_dept,
                    session_id=ticket.session_id, redacted_request=ticket.redacted_request,
                    created_at=ticket.created_at,
                )
            )  # fmt: skip
            await conn.execute(
                insert(_TURNS).values(
                    turn_id=turn_id, ticket_id=ticket.ticket_id, session_id=ticket.session_id,
                    event_type="submit", started_at=ticket.created_at,
                )
            )  # fmt: skip
            for event_type, detail in security_events:
                await insert_event(
                    conn, event_type, occurred_at=ticket.created_at, user_id=ticket.requester_id,
                    route=CREATE_ROUTE, ticket_id=ticket.ticket_id, detail=detail,
                )  # fmt: skip

    async def get(self, ticket_id: str) -> TicketRow | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(*(_TICKETS.c[c] for c in _ROW_COLUMNS)).where(
                        _TICKETS.c.ticket_id == ticket_id
                    )
                )
            ).first()
        if row is None:
            return None
        values = dict(row._mapping)
        values["created_at"] = values["created_at"].astimezone(UTC)
        if values["closed_at"] is not None:
            values["closed_at"] = values["closed_at"].astimezone(UTC)
        return TicketRow(**values)

    async def created_at(self, ticket_id: str) -> datetime:
        async with self._engine.connect() as conn:
            value = (
                await conn.execute(
                    select(_TICKETS.c.created_at).where(_TICKETS.c.ticket_id == ticket_id)
                )
            ).scalar()
        if value is None:
            raise TicketMissing(ticket_id)
        return value.astimezone(UTC)  # type: ignore[no-any-return]

    async def count_turns(self, ticket_id: str) -> int:
        async with self._engine.connect() as conn:
            count = await conn.execute(
                select(func.count()).select_from(_TURNS).where(_TURNS.c.ticket_id == ticket_id)
            )
            return int(count.scalar_one())

    async def finalize_once(self, ticket_id: str, summary: FinalSummary) -> FinalSummary:
        values = {c: getattr(summary, c) for c in _FINAL_COLUMNS}
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_TICKETS)
                .where(_TICKETS.c.ticket_id == ticket_id, _TICKETS.c.final_state.is_(None))
                .values(**values)
            )
            row = (
                await conn.execute(
                    select(*(_TICKETS.c[c] for c in _FINAL_COLUMNS)).where(
                        _TICKETS.c.ticket_id == ticket_id
                    )
                )
            ).first()
        if row is None:
            raise TicketMissing(ticket_id)
        stored = dict(row._mapping)
        stored["closed_at"] = stored["closed_at"].astimezone(UTC)
        return FinalSummary(**stored)

    # ---- Phase 5 T20b (P3, P7) ------------------------------------------------------------------------------------------

    async def create_child(self, child_id: str, *, parent_id: str, redacted_request: str, created_at: datetime) -> str:
        """`INSERT … SELECT` từ dòng cha (người gửi, vai trò, phòng ban, phiên) — trong transaction của `effects.once("child_create")`;
        cha không có dòng → `TicketMissing`. Không dòng `turns` (lượt đầu do `ChildOps.start_missing` mở)."""
        p = _TICKETS.c
        stmt = insert(_TICKETS).from_select(
            ["ticket_id", "parent_ticket_id", "session_id", "requester_id", "requester_role", "requester_dept",
             "redacted_request", "created_at"],
            select(literal(child_id), p.ticket_id, p.session_id, p.requester_id, p.requester_role, p.requester_dept,
                   literal(redacted_request), literal(created_at)).where(p.ticket_id == parent_id),
        )  # fmt: skip
        conn = current_tx()
        if conn is not None:
            done = await conn.execute(stmt)
        else:
            async with self._engine.begin() as own:
                done = await own.execute(stmt)
        if done.rowcount != 1:
            raise TicketMissing(parent_id)
        return child_id

    async def mark_parent_once(self, ticket_id: str) -> bool:
        async with self._engine.begin() as conn:
            done = await conn.execute(
                update(_TICKETS).where(_TICKETS.c.ticket_id == ticket_id, _TICKETS.c.is_parent.is_(False)).values(is_parent=True)
            )
        return done.rowcount == 1

    async def children_view(
        self, parent_id: str, children: Sequence[str], *, delivered_round: int | None = None
    ) -> list[ChildView]:
        n = _NOTICES.c
        unsent = n.delivered_at.is_(None) if delivered_round is None else n.delivered_round == delivered_round
        async with self._engine.connect() as conn:
            finals: dict[str, str | None] = dict((await conn.execute(
                select(_TICKETS.c.ticket_id, _TICKETS.c.final_state).where(_TICKETS.c.ticket_id.in_(list(children)))
            )).tuples().all())  # fmt: skip
            running: set[str] = set((await conn.execute(
                select(_TURNS.c.ticket_id).where(_TURNS.c.ticket_id.in_(list(children)), _TURNS.c.ended_at.is_(None))
            )).scalars().all())  # fmt: skip
            rows = (await conn.execute(
                select(n.notice_id, n.child_ticket_id, n.source_step, n.kind, n.needs, n.body, n.created_at)
                .where(n.parent_ticket_id == parent_id, n.child_ticket_id.in_(list(children)), unsent)
                .order_by(n.created_at, n.notice_id)
            )).all()  # fmt: skip
        pending: dict[str, list[Notice]] = {cid: [] for cid in children}
        for r in rows:
            pending[r.child_ticket_id].append(
                Notice(int(r.notice_id), r.child_ticket_id, r.source_step, r.kind, r.needs, r.body, r.created_at)
            )
        # Con "kết thúc" = có `final_state` VÀ không còn lượt mở (soát lượt 2: B20 của con ghi `final_state` TRƯỚC notice escalation —
        # cha đối soát giữa hai việc đó sẽ đóng mà notice không bao giờ được gửi)
        return [ChildView(cid, child_index(cid), None if cid in running else finals.get(cid), tuple(pending[cid]))
                for cid in children]  # fmt: skip

    async def deliver_round(self, parent_id: str, round_no: int, notice_ids: Sequence[int], at: datetime) -> str:
        """Trong transaction của `effects.once("notify_user", sub=f"round:{n}")` — dòng `side_effects` và đánh dấu cùng commit (P7)."""
        stmt = (
            update(_NOTICES)
            .where(_NOTICES.c.notice_id.in_(list(notice_ids)), _NOTICES.c.parent_ticket_id == parent_id,
                   _NOTICES.c.delivered_at.is_(None))
            .values(delivered_round=round_no, delivered_at=at)
        )  # fmt: skip
        conn = current_tx()
        if conn is not None:
            await conn.execute(stmt)
        else:
            async with self._engine.begin() as own:
                await own.execute(stmt)
        return f"digest:{parent_id}:{round_no}"

    async def children_progress_rows(self, parent_id: str, children: Sequence[str]) -> list[ChildProgressRow]:
        raise NotImplementedError("T20b S12")
