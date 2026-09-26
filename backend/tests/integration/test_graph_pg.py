"""Runtime graph trên Postgres 16 thật — cổng 2 + P1 mục 11 (bản unit: tests/unit/test_graph_*.py).

`AsyncPostgresSaver` (bảng do migration 0003 tạo), `pg_advisory_lock` cấp session, store SQL, role
`app_rw`. Database riêng: `audit_logs` append-only, không xoá được giữa các test.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.domain.states import (
    S_CLARIFYING,
    S_CONFIRMING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
    S_RESOLVED,
)
from app.graph.checkpoint import CHECKPOINT_TABLES
from app.graph.late_event import LateEvent, deliver_event
from app.graph.ports import TicketBusy
from app.graph.runner import INTERRUPTED_NOTE
from app.graph.worker_jobs import WorkerJobs
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.graph import Crash
from tests.integration import _crash_after_approval
from tests.integration.graph_pg import (
    create_ticket,
    open_pg_runtime,
    scalar,
    seed_users,
)
from tests.integration.pg import PgUrls, alembic_config, fresh_database

WAIT_PLANS = {S_CLARIFYING: {"b11_slots": "missing"}, S_PENDING_APPROVAL: {},
              S_CONFIRMING: {"b12_assess": "auto"}}  # fmt: skip
VALID_EVENT = {S_CLARIFYING: {"kind": "user_reply", "text": "x"},
               S_PENDING_APPROVAL: {"kind": "approved"}, S_CONFIRMING: {"kind": "confirmed"}}  # fmt: skip


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


async def new_ticket(rw: AsyncEngine) -> str:
    ticket_id = f"g-{uuid4().hex[:12]}"
    await create_ticket(rw, ticket_id)
    return ticket_id


# ---- schema checkpoint ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkpoint_schema_version_matches_library(rw: AsyncEngine) -> None:
    applied = await scalar(rw, "SELECT count(*) FROM checkpoint_migrations")
    assert applied == len(PostgresSaver.MIGRATIONS), "cần migration Alembic mới (xem 0003)"


def test_app_rw_cannot_create_tables(db: PgUrls) -> None:
    dsn = db.role("app_rw").replace("postgresql+psycopg", "postgresql")
    with psycopg.connect(dsn, autocommit=True) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("CREATE TABLE khong_duoc_tao (i int)")
    with psycopg.connect(dsn, autocommit=True) as conn:
        for table in CHECKPOINT_TABLES:  # CRUD được (grant ở 0003)
            conn.execute(f"SELECT count(*) FROM {table}")


# ---- Cổng 2: dừng ở node chờ → khởi động lại → resume -----------------------------------------


@pytest.mark.asyncio
async def test_stop_restart_resume_on_postgres(db: PgUrls, rw: AsyncEngine) -> None:
    clock = FakeClock()
    t1, t2 = await new_ticket(rw), await new_ticket(rw)
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        r = await rt.runner.submit(t1, session_id=None, redacted_request="x")
        assert (r.status, r.waiting_at) == (S_PENDING_APPROVAL, "approval_wait")
        await rt.runner.submit(t2, session_id=None, redacted_request="x")
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:  # process mới
        r = await deliver_event(rt.runner, t1, S_PENDING_APPROVAL, {"kind": "approved"})
        assert (r.status, r.waiting_at) == (S_CONFIRMING, "confirm_wait")
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        r = await deliver_event(rt.runner, t1, S_CONFIRMING, {"kind": "confirmed"})
        assert (r.status, r.values["close_reason"]) == (S_RESOLVED, "resolved_user_confirmed")
    # Thủ công của cổng 2, tự động hoá: mỗi ticket một luồng riêng trong bảng checkpoint.
    threads = await scalar(
        rw, "SELECT count(DISTINCT thread_id) FROM checkpoints WHERE thread_id IN (:a, :b)", a=t1, b=t2
    )
    assert threads == 2
    assert await scalar(rw, "SELECT count(*) FROM turns WHERE ticket_id=:t AND ended_at IS NULL", t=t1) == 0
    assert await scalar(rw, "SELECT status FROM approvals WHERE ticket_id=:t", t=t1) == "approved"
    events = await scalar(
        rw, "SELECT string_agg(event, ',' ORDER BY log_id) FROM audit_logs WHERE ticket_id=:t", t=t1
    )
    assert events.endswith("queued,approved,executed_ok,user_confirmed")


@pytest.mark.asyncio
@pytest.mark.parametrize("actual", sorted(WAIT_PLANS))
async def test_late_event_in_each_wait_state_on_postgres(
    db: PgUrls, rw: AsyncEngine, actual: str
) -> None:
    ticket = await new_ticket(rw)
    async with open_pg_runtime(db.role("app_rw"), clock=FakeClock()) as rt:
        rt.scenario.plan(ticket, **WAIT_PLANS[actual])
        await rt.runner.submit(ticket, session_id=None, redacted_request="x")
        before = await rt.runner.snapshot(ticket)
        for expected in sorted(set(WAIT_PLANS) - {actual}):
            with pytest.raises(LateEvent):
                await deliver_event(rt.runner, ticket, expected, VALID_EVENT[expected])
        after = await rt.runner.snapshot(ticket)
    assert after.values == before.values and after.next == before.next
    rows = await scalar(
        rw, "SELECT count(*) FROM audit_logs WHERE ticket_id=:t AND event='late_event' "
        "AND from_status=:s AND to_status=:s AND detail->>'source'='user'", t=ticket, s=actual,
    )  # fmt: skip
    assert rows == 2


# ---- Không gửi 2 lần: giết process thật sau approval_create → recover ------------------------


@pytest.mark.asyncio
async def test_kill_process_after_approval_create_then_recover(db: PgUrls, rw: AsyncEngine) -> None:
    ticket = await new_ticket(rw)
    env = {**os.environ, "APP_ENV_FILE": "", "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    proc = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, _crash_after_approval.__file__, db.role("app_rw"), ticket],
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert proc.returncode == _crash_after_approval.EXIT_CODE, proc.stderr[-2000:]
    assert await scalar(rw, "SELECT count(*) FROM approvals WHERE ticket_id=:t", t=ticket) == 1
    open_turn = await scalar(rw, "SELECT turn_id FROM turns WHERE ticket_id=:t AND ended_at IS NULL", t=ticket)
    assert open_turn is not None

    clock = FakeClock()
    clock.advance(timedelta(minutes=3))
    async with open_pg_runtime(db.role("app_rw"), clock=clock, can_execute=False) as rt:
        jobs = WorkerJobs(rt.runner, rt.deadlines, rt.turns)
        assert await jobs.scan_stale_turns() >= 1
        snap = await rt.runner.snapshot(ticket)
        notified = list(rt.approvals.notified)
    assert (snap.values["status"], snap.next) == (S_PENDING_APPROVAL, ("approval_wait",))
    assert await scalar(rw, "SELECT count(*) FROM approvals WHERE ticket_id=:t", t=ticket) == 1
    assert len(notified) == 1  # đúng 1 thông báo cho người duyệt
    counts = await scalar(
        rw, "SELECT string_agg(kind || '=' || n, ',' ORDER BY kind) FROM (SELECT kind, count(*) n "
        "FROM side_effects WHERE ticket_id=:t GROUP BY kind) x", t=ticket,
    )  # fmt: skip
    assert counts == "approval_create=1,notify_approver=1"
    assert await scalar(
        rw, "SELECT turn_id FROM audit_logs WHERE ticket_id=:t AND event='queued'", t=ticket
    ) == open_turn  # recover giữ turn_id (D-18)
    assert await scalar(rw, "SELECT count(*) FROM turns WHERE ticket_id=:t", t=ticket) == 1


# ---- Worker không có credential ghi: recover trước B17 → E7 ---------------------------------


@pytest.mark.asyncio
async def test_worker_recover_never_executes(db: PgUrls, rw: AsyncEngine) -> None:
    ticket = await new_ticket(rw)
    clock = FakeClock()
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        rt.scenario.plan(ticket, b12_assess="auto")
        rt.executor.crash_once.add(ticket)
        with pytest.raises(Crash):
            await rt.runner.submit(ticket, session_id=None, redacted_request="x")
    clock.advance(timedelta(minutes=3))
    async with open_pg_runtime(db.role("app_rw"), clock=clock, can_execute=False) as rt:
        await WorkerJobs(rt.runner, rt.deadlines, rt.turns).scan_stale_turns()
        snap = await rt.runner.snapshot(ticket)
        assert rt.executor.calls[ticket] == 0
    assert (snap.values["status"], snap.values["exit_code"]) == (S_ESCALATED, "E7")
    assert snap.values["escalation_note"] == INTERRUPTED_NOTE
    assert await scalar(
        rw, "SELECT count(*) FROM audit_logs WHERE ticket_id=:t AND event='execution_interrupted'",
        t=ticket,
    ) == 1


# ---- TC29 + 10 ticket song song ------------------------------------------------------------


@pytest.mark.asyncio
async def test_tc29_on_postgres_with_parallel_tickets(db: PgUrls, rw: AsyncEngine) -> None:
    bad = await new_ticket(rw)
    others = [await new_ticket(rw) for _ in range(10)]
    async with open_pg_runtime(db.role("app_rw"), clock=FakeClock()) as rt:
        rt.scenario.plan(bad, b08_retrieve="raise")
        results = await asyncio.gather(
            *(rt.runner.submit(t, session_id=None, redacted_request="x") for t in [bad, *others])
        )
    assert (results[0].status, results[0].values["exit_code"]) == (S_ESCALATED, "E9")
    assert all(r.status == S_PENDING_APPROVAL for r in results[1:])
    assert await scalar(
        rw, "SELECT count(*) FROM spans s JOIN turns t USING (turn_id) WHERE t.ticket_id=:t "
        "AND s.status='error' AND s.attributes ? 'traceback'", t=bad,
    ) == 1  # fmt: skip
    assert await scalar(
        rw, "SELECT length(detail->>'traceback') <= 4096 FROM audit_logs WHERE ticket_id=:t "
        "AND event='unhandled_exception' AND exit_code='E9'", t=bad,
    ) is True  # fmt: skip


# ---- Khoá: hai sự kiện đồng thời từ hai "process" ------------------------------------------


@pytest.mark.asyncio
async def test_two_processes_deliver_concurrently_resume_once(db: PgUrls, rw: AsyncEngine) -> None:
    ticket = await new_ticket(rw)
    clock = FakeClock()
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        await rt.runner.submit(ticket, session_id=None, redacted_request="x")
    async with (
        open_pg_runtime(db.role("app_rw"), clock=clock) as a,
        open_pg_runtime(db.role("app_rw"), clock=clock) as b,
    ):
        results = await asyncio.gather(
            deliver_event(a.runner, ticket, S_PENDING_APPROVAL, {"kind": "approved"}),
            deliver_event(b.runner, ticket, S_PENDING_APPROVAL, {"kind": "rejected"}),
            return_exceptions=True,
        )
        executed = a.executor.calls[ticket] + b.executor.calls[ticket]
    assert sum(isinstance(x, LateEvent) for x in results) == 1, results
    assert sum(not isinstance(x, BaseException) for x in results) == 1, results
    assert executed <= 1


@pytest.mark.asyncio
async def test_lock_timeout_gives_ticket_busy(db: PgUrls, rw: AsyncEngine) -> None:
    ticket = await new_ticket(rw)
    async with (
        open_pg_runtime(db.role("app_rw"), clock=FakeClock(), lock_timeout=0.5) as a,
        open_pg_runtime(db.role("app_rw"), clock=FakeClock(), lock_timeout=0.5) as b,
    ):
        async with a.runner.hold(ticket):
            with pytest.raises(TicketBusy):
                async with b.runner.hold(ticket):
                    pass
        async with b.runner.hold(ticket):  # đã nhả → lấy được
            pass


# ---- Worker quét hạn thật (wait_deadlines, approvals.deadline) ------------------------------


@pytest.mark.asyncio
async def test_worker_deadlines_on_postgres(db: PgUrls, rw: AsyncEngine) -> None:
    clarify, approval = await new_ticket(rw), await new_ticket(rw)
    clock = FakeClock()
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        rt.scenario.plan(clarify, b11_slots="missing")
        await rt.runner.submit(clarify, session_id=None, redacted_request="x")
        await rt.runner.submit(approval, session_id=None, redacted_request="x")
    clock.advance(timedelta(hours=25))
    async with open_pg_runtime(db.role("app_rw"), clock=clock, can_execute=False) as rt:
        jobs = WorkerJobs(rt.runner, rt.deadlines, rt.turns)
        first = await jobs.scan_deadlines()
        second = await jobs.scan_deadlines()
        s1 = (await rt.runner.snapshot(clarify)).values
        s2 = (await rt.runner.snapshot(approval)).values
    assert first.delivered >= 2 and second.delivered == 0
    assert (s1["status"], s1["exit_code"]) == (S_ESCALATED, "E4")
    assert (s2["status"], s2["exit_code"]) == (S_ESCALATED, "E6")
    assert await scalar(rw, "SELECT fired_at IS NOT NULL FROM wait_deadlines WHERE ticket_id=:t",
                        t=clarify) is True  # fmt: skip
    assert await scalar(rw, "SELECT status FROM approvals WHERE ticket_id=:t", t=approval) == "timeout"
