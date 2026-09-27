"""Runtime graph trên Postgres thật cho test integration: store SQL, `AsyncPostgresSaver`,
`pg_advisory_lock`. Dùng chung bởi `test_graph_pg.py` và tiến trình con `_crash_after_approval.py`.

Mỗi `open_pg_runtime` tự mở engine + pool checkpoint riêng → đóng rồi mở lại = "khởi động lại backend".
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.approval.store import SqlApprovals
from app.audit.alerts import AlertWriter
from app.audit.writer import AuditWriter
from app.core.clock import FakeClock
from app.db.escalations import SqlEscalationStore
from app.db.identity import SqlIdentityReads
from app.db.runtime import SqlDeadlineStore, SqlEffectStore, SqlSpanSink, SqlTurnStore
from app.db.session import Engines, create_engines
from app.db.tickets import SqlTicketStore
from app.graph.builder import build_graph, fake_nodes
from app.graph.checkpoint import open_postgres_saver
from app.graph.fakes import FakeScenario, NodeDeps
from app.graph.lock import PgTicketLock
from app.graph.runner import Runner
from app.graph.wiring import Runtime
from app.settings import Settings, get_escalation_templates, get_policy
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.graph import LOCKOUT, CountingExecutor, Crash, RecordingNotifier
from tests.fakes.identity import FakeAd, ad_user, fake_directory

REQUESTER = "nv-graph"
APPROVER = "l1-fake"  # NodeDeps.approver_id mặc định
SESSION = "sess-graph"  # phiên thật của REQUESTER (B1 đọc bảng `sessions`)


class RecordingApprovals(SqlApprovals):
    """`approval/store.SqlApprovals` thật + ghi lại lời gọi báo người duyệt (đếm thông báo)."""

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.notified: list[tuple[str, str]] = []
        self.crash_after_insert = False  # process "chết" SAU INSERT phiếu, TRƯỚC commit side_effects

    async def create(
        self, ticket_id: str, approver_id: str, deadline: datetime, action_plan_hash: str
    ) -> str:
        approval_id = await super().create(ticket_id, approver_id, deadline, action_plan_hash)
        if self.crash_after_insert:
            self.crash_after_insert = False
            raise Crash(f"process chết giữa transaction tạo phiếu {approval_id}")
        return approval_id

    async def notify_approver(self, approval_id: str, approver_id: str) -> str:
        self.notified.append((approval_id, approver_id))
        return f"n{len(self.notified)}"


@dataclass
class PgRuntime:
    runner: Runner
    engines: Engines
    deadlines: SqlDeadlineStore
    turns: SqlTurnStore
    approvals: RecordingApprovals
    notifier: RecordingNotifier
    executor: CountingExecutor
    scenario: FakeScenario
    clock: FakeClock
    ad: FakeAd
    tickets: SqlTicketStore


@asynccontextmanager
async def open_pg_runtime(
    rw_url: str,
    *,
    clock: FakeClock,
    scenario: FakeScenario | None = None,
    can_execute: bool = True,
    lock_timeout: float = 5.0,
    ad: FakeAd | None = None,
    tickets: SqlTicketStore | None = None,
    approver_id: str | None = APPROVER,
) -> AsyncIterator[PgRuntime]:
    settings = Settings(database_url=rw_url, ticket_lock_timeout=lock_timeout)
    engines = create_engines(settings)
    scenario = scenario or FakeScenario()
    deadlines, turns = SqlDeadlineStore(engines.main), SqlTurnStore(engines.main)
    approvals, notifier, executor = RecordingApprovals(engines.main), RecordingNotifier(), CountingExecutor()
    ad = ad or FakeAd(ad_user(REQUESTER))
    ticket_store = tickets or SqlTicketStore(engines.main)
    deps = NodeDeps(
        notifier=notifier, approvals=approvals, executor=executor, deadlines=deadlines,
        constants=get_policy().constants, identity=SqlIdentityReads(engines.main),
        directory=fake_directory(ad, clock), alerts=AlertWriter(engines.main, clock),
        lockout=LOCKOUT, tickets=ticket_store,
        escalations=SqlEscalationStore(engines.main), templates=get_escalation_templates(),
        ml=FakeMlService().client(clock), scenario=scenario, approver_id=approver_id,
    )  # fmt: skip
    try:
        async with open_postgres_saver(rw_url, max_size=5) as saver:
            runner = Runner(
                build_graph(fake_nodes(deps), saver), lock=PgTicketLock(engines.lock),
                turns=turns, audit=AuditWriter(engines.main), effects=SqlEffectStore(engines.main),
                spans=SqlSpanSink(engines.main), clock=clock, can_execute=can_execute,
                tickets=ticket_store,
            )  # fmt: skip
            yield PgRuntime(runner, engines, deadlines, turns, approvals, notifier, executor,
                            scenario, clock, ad, ticket_store)  # fmt: skip
    finally:
        await engines.dispose()


def pg_runtime_factory(
    rw_url: str,
    *,
    clock: FakeClock,
    ad: FakeAd,
    scenario: FakeScenario | None = None,
    approver_id: str | None = "l1_01",
    can_execute: bool = True,
) -> Callable[..., AbstractAsyncContextManager[Runtime]]:
    """`create_app(runtime=…)` trên Postgres thật: store SQL, `AsyncPostgresSaver`, B1 đọc bảng
    `sessions` thật (phiên do route đăng nhập ghi), AD giả qua registry thật, người duyệt giả mặc định
    l1_01 (phải đăng nhập một lần để có dòng `users` — Q4)."""

    @asynccontextmanager
    async def factory(*_: Any) -> AsyncIterator[Runtime]:
        async with open_pg_runtime(
            rw_url, clock=clock, scenario=scenario, ad=ad, approver_id=approver_id,
            can_execute=can_execute,
        ) as rt:  # fmt: skip
            yield Runtime(runner=rt.runner, deadlines=rt.deadlines, turns=rt.turns,
                          tickets=rt.tickets, approvals=rt.approvals)  # fmt: skip

    return factory


async def seed_users(engine: AsyncEngine) -> None:
    """Người gửi + người duyệt, và một phiên còn hạn rất xa của người gửi (FakeClock ở năm 2026)."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO users (user_id, username, role) VALUES "
            f"('{REQUESTER}', 'graph.nv', 'employee'), ('{APPROVER}', 'graph.l1', 'l1') "
            "ON CONFLICT DO NOTHING"
        ))  # fmt: skip
        await conn.execute(text(
            "INSERT INTO sessions (session_id, user_id, token_family_id, expires_at) VALUES "
            f"('{SESSION}', '{REQUESTER}', gen_random_uuid(), '2100-01-01T00:00:00Z') "
            "ON CONFLICT DO NOTHING"
        ))  # fmt: skip


async def create_ticket(
    engine: AsyncEngine, ticket_id: str, *, created_at: datetime | None = None
) -> None:
    """Dịch vụ ticket thật làm ở 2b-3; ở đây chỉ INSERT dòng `tickets` cho khoá ngoại. `created_at`
    tường minh khi test đo thời lượng theo FakeClock (mặc định: `now()` thật của Postgres)."""
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, "
                 "created_at) VALUES (:t, :u, 'employee', 'yêu cầu thử', COALESCE(:c, now()))"),
            {"t": ticket_id, "u": REQUESTER, "c": created_at},
        )  # fmt: skip


async def scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()
