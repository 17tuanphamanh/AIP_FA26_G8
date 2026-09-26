"""SQL của 2b-3 trên Postgres 16 thật: `approval/store.SqlApprovals` (khoá hàng, ghi có điều kiện) và
`db/tickets.SqlTicketStore.create/get` (ticket + lượt trong MỘT transaction)."""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from app.approval.store import SqlApprovals
from app.core.clock import FakeClock
from app.db.tickets import NewTicket, SqlTicketStore
from app.domain.states import S_PENDING_APPROVAL
from app.graph.worker_jobs import WorkerJobs
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.graph import Crash
from tests.integration.graph_pg import (
    APPROVER,
    REQUESTER,
    SESSION,
    open_pg_runtime,
    scalar,
    seed_users,
)
from tests.integration.pg import PgUrls, alembic_config, fresh_database

NOW = datetime(2026, 9, 26, 8, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


def _ticket(ticket_id: str, *, at: datetime = NOW) -> NewTicket:
    return NewTicket(ticket_id=ticket_id, requester_id=REQUESTER, requester_role="employee",
                     requester_dept="it", session_id=SESSION, redacted_request="VPN lỗi",
                     created_at=at)  # fmt: skip


async def _approval(rw: AsyncEngine) -> tuple[str, str]:
    ticket = f"tk-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(_ticket(ticket), turn_id=f"turn-{uuid4().hex[:8]}")
    aid = await SqlApprovals(rw).create(ticket, APPROVER, NOW + timedelta(minutes=30), "h" * 64)
    return ticket, aid


# ---- tickets.create / get ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_writes_ticket_and_turn_with_app_clock(rw: AsyncEngine) -> None:
    at = datetime(2031, 1, 2, 3, 4, 5, tzinfo=UTC)  # khác hẳn now() của Postgres
    await SqlTicketStore(rw).create(_ticket("tk-clock", at=at), turn_id="turn-clock")
    assert await scalar(rw, "SELECT created_at = :a FROM tickets WHERE ticket_id='tk-clock'", a=at)
    assert await scalar(rw, "SELECT started_at = :a AND event_type = 'submit' AND ended_at IS NULL "
                            "FROM turns WHERE turn_id='turn-clock'", a=at)  # fmt: skip
    row = await SqlTicketStore(rw).get("tk-clock")
    assert row is not None and (row.created_at, row.session_id, row.final_state) == (at, SESSION, None)
    assert row.created_at.tzinfo == UTC
    assert await SqlTicketStore(rw).get("khong-co") is None


@pytest.mark.asyncio
async def test_create_atomic(rw: AsyncEngine) -> None:
    """Lượt không ghi được (turn_id trùng) → KHÔNG còn dòng ticket (cùng một transaction)."""
    await SqlTicketStore(rw).create(_ticket("tk-a1"), turn_id="turn-dup")
    with pytest.raises(IntegrityError):
        await SqlTicketStore(rw).create(_ticket("tk-a2"), turn_id="turn-dup")
    assert await scalar(rw, "SELECT count(*) FROM tickets WHERE ticket_id='tk-a2'") == 0


# ---- approvals ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_only_from_pending(rw: AsyncEngine) -> None:
    _, aid = await _approval(rw)
    store = SqlApprovals(rw)
    await store.close(aid, "approved", NOW, decided_by=APPROVER)
    await store.close(aid, "timeout", NOW + timedelta(hours=1))  # B16 chạy lại / worker trễ
    row = await store.get(aid)
    assert row is not None and (row.status, row.decided_by) == ("approved", APPROVER)


@pytest.mark.asyncio
async def test_close_rejected_needs_note(rw: AsyncEngine) -> None:
    _, aid = await _approval(rw)
    with pytest.raises(IntegrityError):
        await SqlApprovals(rw).close(aid, "rejected", NOW, decided_by=APPROVER, note=None)
    await SqlApprovals(rw).close(aid, "rejected", NOW, decided_by=APPROVER, note="lý do")
    row = await SqlApprovals(rw).get(aid)
    assert row is not None and (row.status, row.note) == ("rejected", "lý do")


@pytest.mark.asyncio
async def test_lock_row_blocks_update(db: PgUrls, rw: AsyncEngine) -> None:
    """`lock_row` giữ khoá hàng suốt khối: kết nối khác UPDATE phiếu đó → hết lock_timeout."""
    _, aid = await _approval(rw)
    other = create_async_engine(db.role("app_rw"), connect_args={"options": "-c lock_timeout=200"})
    try:
        async with SqlApprovals(rw).lock_row(aid) as a:
            assert a is not None and a.status == "pending"
            with pytest.raises(OperationalError) as err:
                async with other.begin() as conn:
                    await conn.execute(text("UPDATE approvals SET note='x' WHERE approval_id=:a"),
                                       {"a": int(aid)})  # fmt: skip
            assert isinstance(err.value.orig, psycopg.errors.LockNotAvailable)
        async with other.begin() as conn:  # ra khỏi khối → khoá nhả
            await conn.execute(text("UPDATE approvals SET note='y' WHERE approval_id=:a"), {"a": int(aid)})
    finally:
        await other.dispose()


@pytest.mark.asyncio
async def test_lock_row_missing_or_bad_id_is_none(rw: AsyncEngine) -> None:
    for aid in ("999999", "abc"):
        async with SqlApprovals(rw).lock_row(aid) as a:
            assert a is None
        assert await SqlApprovals(rw).get(aid) is None


@pytest.mark.asyncio
async def test_row_fields_are_utc(rw: AsyncEngine) -> None:
    _, aid = await _approval(rw)
    async with SqlApprovals(rw).lock_row(aid) as a:
        assert a is not None and a.deadline == NOW + timedelta(minutes=30) and a.deadline.tzinfo == UTC




@pytest.mark.asyncio
async def test_approval_insert_rolls_back_with_side_effect(db: PgUrls, rw: AsyncEngine) -> None:
    """Phiếu ghi trong CÙNG transaction với dòng `side_effects` (`current_tx()`): process chết giữa hai
    việc → cả hai cùng mất; phục hồi tạo đúng 1 phiếu. Ghi riêng thì phiếu mồ côi còn lại, lần chạy
    lại tạo phiếu thứ hai (hoặc vấp UNIQUE một-phiếu-pending → E9)."""
    ticket, turn = f"tk-{uuid4().hex[:8]}", f"turn-{uuid4().hex[:8]}"
    clock = FakeClock()
    await SqlTicketStore(rw).create(_ticket(ticket, at=clock.now()), turn_id=turn)
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        rt.approvals.crash_after_insert = True
        with pytest.raises(Crash):
            await rt.runner.run_new(ticket, turn)
    assert await scalar(rw, "SELECT count(*) FROM approvals WHERE ticket_id=:t", t=ticket) == 0
    assert await scalar(rw, "SELECT count(*) FROM side_effects WHERE ticket_id=:t "
                            "AND kind='approval_create'", t=ticket) == 0  # fmt: skip
    clock.advance(timedelta(minutes=3))
    async with open_pg_runtime(db.role("app_rw"), clock=clock, can_execute=False) as rt:
        assert await WorkerJobs(rt.runner, rt.deadlines, rt.turns).scan_stale_turns() >= 1
        assert (await rt.runner.snapshot(ticket)).values["status"] == S_PENDING_APPROVAL
    assert await scalar(rw, "SELECT count(*) FROM approvals WHERE ticket_id=:t "
                            "AND status='pending'", t=ticket) == 1  # fmt: skip
