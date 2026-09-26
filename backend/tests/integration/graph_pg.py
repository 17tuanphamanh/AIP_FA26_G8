"""Runtime graph trên Postgres thật cho test integration: store SQL, `AsyncPostgresSaver`,
`pg_advisory_lock`. Dùng chung bởi `test_graph_pg.py` và tiến trình con `_crash_after_approval.py`.

Mỗi `open_pg_runtime` tự mở engine + pool checkpoint riêng → đóng rồi mở lại = "khởi động lại backend".
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.audit.writer import AuditWriter
from app.core.clock import FakeClock
from app.db.models import Approval
from app.db.runtime import (
    SqlDeadlineStore,
    SqlEffectStore,
    SqlSpanSink,
    SqlTurnStore,
    current_tx,
)
from app.db.session import Engines, create_engines
from app.graph.builder import build_graph, fake_nodes
from app.graph.checkpoint import open_postgres_saver
from app.graph.fakes import FakeScenario, NodeDeps
from app.graph.lock import PgTicketLock
from app.graph.runner import Runner
from app.settings import Settings, get_policy
from sqlalchemy import Table, insert, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from tests.fakes.graph import CountingExecutor, RecordingNotifier

REQUESTER = "nv-graph"
APPROVER = "l1-fake"  # NodeDeps.approver_id mặc định
_APPROVALS: Table = Approval.__table__  # type: ignore[assignment]


class SqlApprovals:
    """Port approvals giả nhưng ghi bảng `approvals` thật — CÙNG transaction với `side_effects`."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self.notified: list[tuple[str, str]] = []

    async def _exec(self, fn: Any) -> Any:
        conn = current_tx()
        if conn is not None:
            return await fn(conn)
        async with self._engine.begin() as own:
            return await fn(own)

    async def create(
        self, ticket_id: str, approver_id: str, deadline: datetime, action_plan_hash: str
    ) -> str:
        async def run(conn: AsyncConnection) -> str:
            row = await conn.execute(
                insert(_APPROVALS)
                .values(ticket_id=ticket_id, approver_id=approver_id, deadline=deadline,
                        action_plan_hash=action_plan_hash)
                .returning(_APPROVALS.c.approval_id)
            )
            return str(row.scalar_one())

        return str(await self._exec(run))

    async def notify_approver(self, approval_id: str, approver_id: str) -> str:
        self.notified.append((approval_id, approver_id))
        return f"n{len(self.notified)}"

    async def record_result(self, approval_id: str, result: str, at: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_APPROVALS)
                .where(_APPROVALS.c.approval_id == int(approval_id), _APPROVALS.c.status == "pending")
                .values(status=result, decided_at=at,
                        note="(node giả)" if result == "rejected" else None)
            )


@dataclass
class PgRuntime:
    runner: Runner
    engines: Engines
    deadlines: SqlDeadlineStore
    turns: SqlTurnStore
    approvals: SqlApprovals
    notifier: RecordingNotifier
    executor: CountingExecutor
    scenario: FakeScenario
    clock: FakeClock


@asynccontextmanager
async def open_pg_runtime(
    rw_url: str,
    *,
    clock: FakeClock,
    scenario: FakeScenario | None = None,
    can_execute: bool = True,
    lock_timeout: float = 5.0,
) -> AsyncIterator[PgRuntime]:
    settings = Settings(database_url=rw_url, ticket_lock_timeout=lock_timeout)
    engines = create_engines(settings)
    scenario = scenario or FakeScenario()
    deadlines, turns = SqlDeadlineStore(engines.main), SqlTurnStore(engines.main)
    approvals, notifier, executor = SqlApprovals(engines.main), RecordingNotifier(), CountingExecutor()
    deps = NodeDeps(
        notifier=notifier, approvals=approvals, executor=executor, deadlines=deadlines,
        constants=get_policy().constants, scenario=scenario, approver_id=APPROVER,
    )  # fmt: skip
    try:
        async with open_postgres_saver(rw_url, max_size=5) as saver:
            runner = Runner(
                build_graph(fake_nodes(deps), saver), lock=PgTicketLock(engines.lock),
                turns=turns, audit=AuditWriter(engines.main), effects=SqlEffectStore(engines.main),
                spans=SqlSpanSink(engines.main), clock=clock, can_execute=can_execute,
            )  # fmt: skip
            yield PgRuntime(runner, engines, deadlines, turns, approvals, notifier, executor,
                            scenario, clock)  # fmt: skip
    finally:
        await engines.dispose()


async def seed_users(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO users (user_id, username, role) VALUES "
            f"('{REQUESTER}', 'graph.nv', 'employee'), ('{APPROVER}', 'graph.l1', 'l1') "
            "ON CONFLICT DO NOTHING"
        ))  # fmt: skip


async def create_ticket(engine: AsyncEngine, ticket_id: str) -> None:
    """Dịch vụ ticket thật làm ở chặng 2b; ở đây chỉ INSERT dòng `tickets` cho khoá ngoại."""
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request) "
                 "VALUES (:t, :u, 'employee', 'yêu cầu thử')"),
            {"t": ticket_id, "u": REQUESTER},
        )  # fmt: skip


async def scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()
