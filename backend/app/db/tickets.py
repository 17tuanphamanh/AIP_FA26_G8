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

from sqlalchemy import (
    RowMapping,
    Table,
    exists,
    func,
    insert,
    literal,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import Approval, ChildNotice, Ticket, TicketHidden, Turn
from app.db.runtime import current_tx
from app.db.security_events import check_event, insert_event
from app.domain.children import (
    ChildHandoffRow,
    ChildProgressRow,
    ChildView,
    Notice,
    child_index,
    child_ref,
)
from app.domain.dedup import OpenCandidate
from app.domain.final import FinalSummary

_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]
_TURNS: Table = Turn.__table__  # type: ignore[assignment]
_NOTICES: Table = ChildNotice.__table__  # type: ignore[assignment]
_HIDDEN: Table = TicketHidden.__table__  # type: ignore[assignment]
_APPROVALS: Table = Approval.__table__  # type: ignore[assignment]
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
    # D-67 (migration 0013): chiến lược M5 chụp lúc tạo (None = không ghi → B12 coi là `hybrid`), nguồn ticket (`real`/`sim`/`eval`)
    strategy: str | None = None
    source: str = "real"


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
# T20b P11 `children_progress`: chỉ DB (không đọc checkpoint con) — phiếu duyệt `pending`; notice chưa gửi `needs ≠ none` của CHA này
_PROGRESS_ROWS = text(
    "SELECT c.ticket_id, c.final_state, "
    "EXISTS (SELECT 1 FROM approvals a WHERE a.ticket_id = c.ticket_id AND a.status = 'pending') AS pending_approval, "
    "EXISTS (SELECT 1 FROM child_notices n WHERE n.child_ticket_id = c.ticket_id AND n.parent_ticket_id = :parent "
    "        AND n.delivered_at IS NULL AND n.needs <> 'none') AS ready "
    "FROM tickets c WHERE c.parent_ticket_id = :parent AND c.ticket_id = ANY(:children)"
)
# Q-T20b-9 (i): trạng thái từng con cho ghi chú bàn giao của cha lỗi — `needs` của notice `needs ≠ none` MỚI NHẤT (cùng cách chọn với
# `SqlDeadlineStore.orphan_children`); `executed` = có dòng `transaction_log` (B17 đã bắt đầu lệnh ghi).
_HANDOFF_ROWS = text(
    "SELECT c.ticket_id, c.final_state, "
    "EXISTS (SELECT 1 FROM side_effects s WHERE s.ticket_id = :parent AND s.kind = 'child_submit' "
    "        AND s.result_ref = 'started:' || c.ticket_id) AS started, "
    "EXISTS (SELECT 1 FROM transaction_log x WHERE x.ticket_id = c.ticket_id) AS executed, "
    "EXISTS (SELECT 1 FROM approvals a WHERE a.ticket_id = c.ticket_id AND a.status = 'pending') AS pending_approval, "
    "(SELECT n.needs FROM child_notices n WHERE n.child_ticket_id = c.ticket_id AND n.needs <> 'none' "
    " ORDER BY n.created_at DESC, n.notice_id DESC LIMIT 1) AS needs "
    "FROM tickets c WHERE c.parent_ticket_id = :parent"
)
# M1 (B3 báo trùng): ticket LÁ còn mở của một người từ `since` + `intent` của dòng audit B3 `intent_classified` mới nhất (`tickets.intent` NULL tới
# B20). "Còn mở" (ĐP 08/11) = `final_state IS NULL` HOẶC (`S_ESCALATED` VÀ `close_reason IS NULL` — chờ kỹ thuật viên). Chỉ đọc; `ix_tickets_requester_created_at` + `ix_audit_logs_ticket`. Lọc ở đây chỉ để thu nhỏ tập — quyết định ở `pick_duplicate`.
_OPEN_CANDIDATES = text(
    "SELECT t.ticket_id, t.requester_id, t.final_state, t.close_reason, t.is_parent, t.parent_ticket_id, t.created_at, "
    "(SELECT a.intent FROM audit_logs a WHERE a.ticket_id = t.ticket_id AND a.step = 'B3' AND a.event = 'intent_classified' "
    " AND a.intent IS NOT NULL ORDER BY a.log_id DESC LIMIT 1) AS intent "
    "FROM tickets t WHERE t.requester_id = :requester AND t.created_at >= :since AND t.is_parent = false "
    "AND (t.final_state IS NULL OR (t.final_state = 'S_ESCALATED' AND t.close_reason IS NULL))"
)
_STARTED = text("SELECT result_ref FROM side_effects WHERE ticket_id = :parent AND kind = 'child_submit'")
STARTED_PREFIX = "started:"  # `result_ref` của `child_submit` (`graph.children._started`)
CREATE_ROUTE = "/api/tickets"  # `security_events.route` của sự kiện ghi lúc tạo ticket

type NewEvents = Sequence[tuple[str, Mapping[str, Any]]]  # (event_type, detail) — không chứa văn bản người dùng


def _ticket_row(mapping: RowMapping) -> TicketRow:
    values = dict(mapping)
    values["created_at"] = values["created_at"].astimezone(UTC)
    if values["closed_at"] is not None:
        values["closed_at"] = values["closed_at"].astimezone(UTC)
    return TicketRow(**values)


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
                    created_at=ticket.created_at, strategy=ticket.strategy, source=ticket.source,
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
        return None if row is None else _ticket_row(row._mapping)

    async def list_own(self, requester_id: str, limit: int) -> list[TicketRow]:
        """P3 "Gần đây": ticket GỐC (`parent_ticket_id IS NULL`) của ĐÚNG `requester_id`, `created_at DESC, ticket_id DESC`, tối đa
        `limit` dòng — trừ ticket người đó đã ẩn (`ticket_hidden`, lọc trong WHERE nên TRƯỚC `LIMIT`). Không checkpoint. Index
        `ix_tickets_requester_created_at` (migration 0010); `NOT EXISTS` đi theo PK `ticket_hidden(user_id, ticket_id)`."""
        t, h = _TICKETS.c, _HIDDEN.c
        hidden = exists().where(h.user_id == requester_id, h.ticket_id == t.ticket_id)
        stmt = (
            select(*(t[c] for c in _ROW_COLUMNS))
            .where(t.requester_id == requester_id, t.parent_ticket_id.is_(None), ~hidden)
            .order_by(t.created_at.desc(), t.ticket_id.desc())
            .limit(limit)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [_ticket_row(r._mapping) for r in rows]

    async def hide(self, user_id: str, ticket_id: str, at: datetime) -> None:
        """P3 menu ⋯ "Xóa": ẩn `ticket_id` khỏi "Gần đây" của `user_id`. Idempotent — `ON CONFLICT DO NOTHING` (lần sau không đổi
        `hidden_at`; quyền `app_rw` chỉ cần INSERT). Không đụng `tickets` hay bảng nào khác. Quyền chủ ticket do route kiểm."""
        stmt = pg_insert(_HIDDEN).values(user_id=user_id, ticket_id=ticket_id, hidden_at=at).on_conflict_do_nothing()
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def open_candidates(self, requester_id: str, *, since: datetime) -> list[OpenCandidate]:
        async with self._engine.connect() as conn:
            rows = (await conn.execute(_OPEN_CANDIDATES, {"requester": requester_id, "since": since})).all()
        return [
            OpenCandidate(
                ticket_id=r.ticket_id, requester_id=r.requester_id, intent=r.intent, final_state=r.final_state,
                close_reason=r.close_reason,
                is_parent=r.is_parent, parent_ticket_id=r.parent_ticket_id, created_at=r.created_at.astimezone(UTC),
            )
            for r in rows
        ]  # fmt: skip

    async def strategy_of(self, ticket_id: str) -> str | None:
        """D-67: chiến lược M5 đã chụp lúc tạo ticket (B12). None = ticket cũ (trước migration 0013) hoặc không ghi."""
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(select(_TICKETS.c.strategy).where(_TICKETS.c.ticket_id == ticket_id))
            ).first()
        if row is None:
            raise TicketMissing(ticket_id)
        return None if row[0] is None else str(row[0])

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

    async def create_child(
        self, child_id: str, *, parent_id: str, redacted_request: str, created_at: datetime, intents: int, intent_type: str
    ) -> str:
        """`INSERT … SELECT` từ dòng cha (người gửi, vai trò, phòng ban, phiên; D-67: `strategy`, `source`) — trong transaction của `effects.once("child_create")`;
        cha không có dòng → `TicketMissing`. Không dòng `turns` (lượt đầu do `ChildOps.start_missing` mở)."""
        p = _TICKETS.c
        stmt = insert(_TICKETS).from_select(
            ["ticket_id", "parent_ticket_id", "session_id", "requester_id", "requester_role", "requester_dept",
             "redacted_request", "created_at", "strategy", "source"],
            select(literal(child_id), p.ticket_id, p.session_id, p.requester_id, p.requester_role, p.requester_dept,
                   literal(redacted_request), literal(created_at), p.strategy, p.source).where(p.ticket_id == parent_id),
        ).returning(_TICKETS.c.ticket_id)  # fmt: skip
        # RETURNING, KHÔNG `rowcount`: SQLAlchemy chỉ giữ `rowcount` của UPDATE/DELETE (INSERT → -1 khi không `preserve_rowcount`) —
        # verify 14/10 đỏ 12 test PG vì vậy
        conn = current_tx()
        if conn is not None:
            made = (await conn.execute(stmt)).scalar_one_or_none()
        else:
            async with self._engine.begin() as own:
                made = (await own.execute(stmt)).scalar_one_or_none()
        if made is None:
            raise TicketMissing(parent_id)
        return child_ref(child_id, intents, intent_type)  # = `result_ref` của `child_create` (Q-T20b-12)

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
            finals: dict[str, str | None] = {r.ticket_id: r.final_state for r in await conn.execute(
                select(_TICKETS.c.ticket_id, _TICKETS.c.final_state).where(_TICKETS.c.ticket_id.in_(list(children)))
            )}  # fmt: skip
            running: set[str] = set((await conn.execute(
                select(_TURNS.c.ticket_id).where(_TURNS.c.ticket_id.in_(list(children)), _TURNS.c.ended_at.is_(None))
            )).scalars().all())  # fmt: skip
            approving: set[str] = set((await conn.execute(
                select(_APPROVALS.c.ticket_id).where(_APPROVALS.c.ticket_id.in_(list(children)), _APPROVALS.c.status == "pending")
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
        return [ChildView(cid, child_index(cid), None if cid in running else finals.get(cid), tuple(pending[cid]),
                          cid in approving and cid not in running)
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
        async with self._engine.connect() as conn:
            rows = (await conn.execute(_PROGRESS_ROWS, {"parent": parent_id, "children": list(children)})).all()
        found = {r.ticket_id: ChildProgressRow(r.ticket_id, r.final_state, bool(r.pending_approval), bool(r.ready)) for r in rows}
        return [found[cid] for cid in children if cid in found]

    async def started_children(self, parent_id: str) -> frozenset[str]:
        async with self._engine.connect() as conn:
            refs: Sequence[str | None] = (await conn.execute(_STARTED, {"parent": parent_id})).scalars().all()
        return frozenset(r.removeprefix(STARTED_PREFIX) for r in refs if r and r.startswith(STARTED_PREFIX))

    async def children_status(self, parent_id: str) -> list[ChildHandoffRow]:
        async with self._engine.connect() as conn:
            rows = (await conn.execute(_HANDOFF_ROWS, {"parent": parent_id})).all()
        out = [ChildHandoffRow(r.ticket_id, bool(r.started), r.final_state, bool(r.executed), bool(r.pending_approval), r.needs)
               for r in rows]  # fmt: skip
        return sorted(out, key=lambda r: child_index(r.child_id))
