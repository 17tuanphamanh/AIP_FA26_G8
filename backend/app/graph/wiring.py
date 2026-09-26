"""Dựng runtime graph trên Postgres: store SQL + checkpoint + khoá + runner (composition root).

Worker dùng `can_execute=False` (không có SVC_EXECUTOR_TOKEN — D-03, quyết định 26/09/2026). Node
chưa có logic thật dùng port không làm gì (`fakes.LoggingNotifier`…); phase sau thay bằng dịch vụ thật.
B1 (2b) đọc AD qua registry tool đọc (token svc_agent): truyền `directory` vào để dùng chung breaker
với nơi khác trong cùng process; không truyền thì tự dựng (và tự đóng client HTTP khi thoát).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from app.audit.alerts import AlertWriter
from app.audit.writer import AuditWriter
from app.core.clock import Clock
from app.db.identity import SqlIdentityReads
from app.db.runtime import SqlDeadlineStore, SqlEffectStore, SqlSpanSink, SqlTurnStore
from app.db.session import Engines
from app.graph.builder import build_graph, fake_nodes
from app.graph.checkpoint import open_postgres_saver
from app.graph.fakes import (
    LoggingNotifier,
    NodeDeps,
    RefusingExecutor,
    UnavailableApprovals,
    UnconfiguredDirectory,
)
from app.graph.lock import PgTicketLock
from app.graph.ports import ToolCaller
from app.graph.runner import Runner
from app.settings import Settings, get_policy
from app.tools.wiring import build_read_registry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Runtime:
    runner: Runner
    deadlines: SqlDeadlineStore
    turns: SqlTurnStore


@asynccontextmanager
async def open_runtime(
    settings: Settings,
    engines: Engines,
    clock: Clock,
    *,
    can_execute: bool,
    directory: ToolCaller | None = None,
) -> AsyncIterator[Runtime]:
    async with AsyncExitStack() as stack:
        if directory is None:
            if settings.svc_agent_token is None:
                log.warning("SVC_AGENT_TOKEN chưa cấu hình — B1 không đọc được AD, ticket sẽ ra E2")
                directory = UnconfiguredDirectory()
            else:
                registry, http = build_read_registry(settings, clock)
                stack.push_async_callback(http.aclose)
                directory = registry
        yield await stack.enter_async_context(
            _open(settings, engines, clock, can_execute=can_execute, directory=directory)
        )


@asynccontextmanager
async def _open(
    settings: Settings, engines: Engines, clock: Clock, *, can_execute: bool, directory: ToolCaller
) -> AsyncIterator[Runtime]:
    deadlines = SqlDeadlineStore(engines.main)
    turns = SqlTurnStore(engines.main)
    deps = NodeDeps(
        notifier=LoggingNotifier(), approvals=UnavailableApprovals(), executor=RefusingExecutor(),
        deadlines=deadlines, constants=get_policy().constants,
        identity=SqlIdentityReads(engines.main), directory=directory,
        alerts=AlertWriter(engines.main, clock), lockout=timedelta(minutes=settings.lockout_minutes),
    )  # fmt: skip
    async with open_postgres_saver(
        settings.database_url, max_size=settings.checkpoint_pool_size
    ) as saver:
        runner = Runner(
            build_graph(fake_nodes(deps), saver),
            lock=PgTicketLock(engines.lock), turns=turns, audit=AuditWriter(engines.main),
            effects=SqlEffectStore(engines.main), spans=SqlSpanSink(engines.main), clock=clock,
            concurrency=settings.graph_concurrency, can_execute=can_execute,
            rediagnose_on_new_slot=settings.rediagnose_on_new_slot,
            recursion_limit=settings.graph_recursion_limit,
        )  # fmt: skip
        yield Runtime(runner=runner, deadlines=deadlines, turns=turns)
