"""Runtime graph trên Postgres thật cho test integration: store SQL, `AsyncPostgresSaver`,
`pg_advisory_lock`. Dùng chung bởi `test_graph_pg.py` và tiến trình con `_crash_after_approval.py`.

Mỗi `open_pg_runtime` tự mở engine + pool checkpoint riêng → đóng rồi mở lại = "khởi động lại backend".
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from app.approval.store import NoticeKind, SqlApprovals
from app.audit.alerts import AlertWriter
from app.audit.security_events import SecurityEventWriter
from app.audit.writer import AuditWriter
from app.auth.service import auth_config, lock_policy
from app.auth.store import SqlAuthStore
from app.auth.user_sync import AdUserSync, AuthApproverUsers
from app.core.clock import FakeClock
from app.db.escalations import SqlEscalationStore
from app.db.identity import SqlIdentityReads
from app.db.runtime import SqlDeadlineStore, SqlEffectStore, SqlSpanSink, SqlTurnStore
from app.db.session import Engines, create_engines
from app.db.tickets import SqlTicketStore
from app.executor.txlog import SqlTxLog
from app.graph.builder import build_graph, fake_nodes, real_nodes
from app.graph.checkpoint import open_postgres_saver
from app.graph.fakes import ApproverUsers, FakeScenario, NodeDeps
from app.graph.lock import PgTicketLock
from app.graph.runner import Runner
from app.graph.wiring import Runtime
from app.llm import LlmPort
from app.rag.ports import RagPort
from app.settings import Settings, get_escalation_templates, get_policy, open_approvers
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.fakes.ad_seed import ROSTER_CHAIN, seed_ad_records
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.graph import (
    HARNESS_USERNAME_KEY,
    LOCKOUT,
    CountingExecutor,
    Crash,
    RecordingNotifier,
)
from tests.fakes.identity import FakeAd, ad_user, fake_directory
from tests.fakes.llm import make_gateway
from tests.fakes.rag import FakeRag
from tests.fakes.vpn import SeedVpn

REQUESTER = "nv-graph"
APPROVER = "l1-fake"  # NodeDeps.approver_id mặc định
SESSION = "sess-graph"  # phiên thật của REQUESTER (B1 đọc bảng `sessions`)


class RecordingApprovals(SqlApprovals):
    """`approval/store.SqlApprovals` thật + ghi lại lời gọi báo người duyệt (đếm thông báo)."""

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.notified: list[tuple[str, str]] = []
        self.reminded: list[tuple[str, str, str]] = []  # 4c P3
        self.crash_after_insert = False  # process "chết" SAU INSERT phiếu, TRƯỚC commit side_effects

    async def create(
        self, ticket_id: str, approver_id: str, deadline: datetime, action_plan_hash: str, *,
        backup_approver_id: str | None, conflict_detected: bool, conflict_type: str | None,
    ) -> str:  # fmt: skip
        approval_id = await super().create(
            ticket_id, approver_id, deadline, action_plan_hash, backup_approver_id=backup_approver_id,
            conflict_detected=conflict_detected, conflict_type=conflict_type,
        )  # fmt: skip
        if self.crash_after_insert:
            self.crash_after_insert = False
            raise Crash(f"process chết giữa transaction tạo phiếu {approval_id}")
        return approval_id

    async def notify_approver(self, approval_id: str, approver_id: str, kind: NoticeKind = "new") -> str:
        if kind != "new":
            self.reminded.append((approval_id, approver_id, kind))
            return f"r{len(self.reminded)}"
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
    deps: NodeDeps  # 4b: test PG gọi thẳng một node (vd B15 thật) trên CÙNG store SQL mà graph dùng


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
    rag: RagPort | None = None,
    llm: LlmPort | None = None,
    nodes: Literal["fake", "real"] = "fake",
    audit: AuditWriter | None = None,
    approver_users: ApproverUsers | None = None,
    roster_in_ad: bool = True,
) -> AsyncIterator[PgRuntime]:
    """`roster_in_ad` (4b): gộp người trong roster + chuỗi quản lý (seed.json, `ad_seed.ROSTER_CHAIN`) vào `ad` — như
    `GraphHarness`; không đè người test đã dựng."""
    settings = Settings(database_url=rw_url, ticket_lock_timeout=lock_timeout)
    engines = create_engines(settings)
    scenario = scenario or FakeScenario()
    deadlines, turns = SqlDeadlineStore(engines.main), SqlTurnStore(engines.main)
    approvals, notifier, executor = RecordingApprovals(engines.main), RecordingNotifier(), CountingExecutor()
    ad = ad or FakeAd(ad_user(REQUESTER))
    if roster_in_ad:
        ad.add(*seed_ad_records(clock.now(), ROSTER_CHAIN))
    ticket_store = tickets or SqlTicketStore(engines.main)
    security = SecurityEventWriter(engines.main, clock)
    if approver_users is None:  # 4b: bảng `users` THẬT, cùng khoá HMAC với harness in-memory
        approver_users = AuthApproverUsers(AdUserSync(
            store=SqlAuthStore(engines.main), sink=security, username_key=HARNESS_USERNAME_KEY,
            lock=lock_policy(auth_config(settings, get_policy().constants)),
        ))  # fmt: skip
    deps = NodeDeps(
        notifier=notifier, approvals=approvals, executor=executor, txlog=SqlTxLog(engines.main, clock), deadlines=deadlines,
        constants=get_policy().constants, identity=SqlIdentityReads(engines.main),
        # 3f: B6 thật — VPN giả đọc mock_services/seed.json (tests/fakes/vpn.py)
        directory=fake_directory(ad, clock, SeedVpn(clock).handlers()), alerts=AlertWriter(engines.main, clock),
        lockout=LOCKOUT, tickets=ticket_store,
        escalations=SqlEscalationStore(engines.main), templates=get_escalation_templates(),
        ml=FakeMlService().client(clock), rag=rag or FakeRag(), llm=llm or make_gateway(clock=clock).client,
        scenario=scenario, approver_id=approver_id,
        security_events=security, approvers=open_approvers(settings).root, approver_users=approver_users,
    )  # fmt: skip
    build_nodes = real_nodes if nodes == "real" else fake_nodes
    try:
        async with open_postgres_saver(rw_url, max_size=5) as saver:
            runner = Runner(
                build_graph(build_nodes(deps), saver), lock=PgTicketLock(engines.lock),
                turns=turns, audit=audit or AuditWriter(engines.main), effects=SqlEffectStore(engines.main),
                spans=SqlSpanSink(engines.main), clock=clock, can_execute=can_execute,
                turn_budget_s=settings.turn_budget_s, safety_margin_s=settings.safety_margin_s,
                tickets=ticket_store, txlog=deps.txlog,
            )  # fmt: skip
            yield PgRuntime(runner, engines, deadlines, turns, approvals, notifier, executor,
                            scenario, clock, ad, ticket_store, deps)  # fmt: skip
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
    nodes: Literal["fake", "real"] = "fake",
    llm: LlmPort | None = None,
    rag: RagPort | None = None,
    audit: AuditWriter | None = None,
    roster_in_ad: bool = True,
) -> Callable[..., AbstractAsyncContextManager[Runtime]]:
    """`create_app(runtime=…)` trên Postgres thật: store SQL, `AsyncPostgresSaver`, B1 đọc bảng
    `sessions` thật (phiên do route đăng nhập ghi), AD giả qua registry thật, người duyệt giả mặc định
    l1_01 (phải đăng nhập một lần để có dòng `users` — Q4)."""

    @asynccontextmanager
    async def factory(*_: Any) -> AsyncIterator[Runtime]:
        async with open_pg_runtime(
            rw_url, clock=clock, scenario=scenario, ad=ad, approver_id=approver_id,
            can_execute=can_execute, nodes=nodes, llm=llm, rag=rag, audit=audit, roster_in_ad=roster_in_ad,
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


@dataclass(frozen=True)
class OwnRequester:
    """Người gửi RIÊNG của một ca test (dòng `users` + một phiên còn hạn + bản AD giả tương ứng).

    DB `migrated` dùng chung cả phiên pytest và không dọn giữa các ca (audit/tickets append-only), còn B3 báo trùng (M1)
    đọc MỌI ticket còn mở cùng `requester_id` trong 24 giờ: ca nào đếm tin/`side_effects` của ticket chạy B3 thật mà dùng
    chung `REQUESTER` thì dính ticket do ca khác để lại → thêm tin `duplicate`. Mỗi ca một người gửi thì không lẫn."""

    user_id: str
    session_id: str

    def ad(self) -> FakeAd:
        """AD giả chỉ có người này (B1 tra theo `sessions.user_id`); truyền vào `open_pg_runtime(ad=…)`."""
        return FakeAd(ad_user(self.user_id))


async def seed_requester(engine: AsyncEngine) -> OwnRequester:
    """Một người gửi mới (mã ngẫu nhiên) + phiên còn hạn rất xa (FakeClock ở năm 2026) — cùng cách `seed_users`."""
    user_id = f"nv-{uuid4().hex[:10]}"
    session_id = f"sess-{user_id}"
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (user_id, username, role) VALUES (:u, :n, 'employee')"),
            {"u": user_id, "n": f"{user_id}.nv"},
        )  # fmt: skip
        await conn.execute(
            text("INSERT INTO sessions (session_id, user_id, token_family_id, expires_at) "
                 "VALUES (:s, :u, gen_random_uuid(), '2100-01-01T00:00:00Z')"),
            {"s": session_id, "u": user_id},
        )  # fmt: skip
    return OwnRequester(user_id, session_id)


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
