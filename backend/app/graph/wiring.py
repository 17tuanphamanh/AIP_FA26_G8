"""Dựng runtime graph trên Postgres: store SQL + checkpoint + khoá + runner (composition root).

Worker dùng `can_execute=False` (không có SVC_EXECUTOR_TOKEN — D-03, quyết định 26/09/2026). Phase 2
dùng node GIẢ với port không làm gì (`fakes.LoggingNotifier`…); phase sau thay bằng dịch vụ thật.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.audit.writer import AuditWriter
from app.core.clock import Clock
from app.db.runtime import SqlDeadlineStore, SqlEffectStore, SqlSpanSink, SqlTurnStore
from app.db.session import Engines
from app.graph.builder import build_graph, fake_nodes
from app.graph.checkpoint import open_postgres_saver
from app.graph.fakes import (
    LoggingNotifier,
    NodeDeps,
    RefusingExecutor,
    UnavailableApprovals,
)
from app.graph.lock import PgTicketLock
from app.graph.runner import Runner
from app.settings import Settings, get_policy


@dataclass(frozen=True)
class Runtime:
    runner: Runner
    deadlines: SqlDeadlineStore
    turns: SqlTurnStore


@asynccontextmanager
async def open_runtime(
    settings: Settings, engines: Engines, clock: Clock, *, can_execute: bool
) -> AsyncIterator[Runtime]:
    deadlines = SqlDeadlineStore(engines.main)
    turns = SqlTurnStore(engines.main)
    deps = NodeDeps(
        notifier=LoggingNotifier(), approvals=UnavailableApprovals(), executor=RefusingExecutor(),
        deadlines=deadlines, constants=get_policy().constants,
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
