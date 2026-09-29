"""Dựng runtime graph trên Postgres: store SQL + checkpoint + khoá + runner (composition root).

Worker dùng `can_execute=False` (không có SVC_EXECUTOR_TOKEN — D-03, quyết định 26/09/2026). Node
chưa có logic thật dùng port không làm gì (`fakes.LoggingNotifier`…); phase sau thay bằng dịch vụ thật.
Phiếu duyệt ghi bảng `approvals` thật (`approval/store.SqlApprovals`, 2b-Q3) ở CẢ backend lẫn worker —
worker bắn timeout thì B16 giả ghi `timeout` lên phiếu. Người duyệt của B15 giả = `FAKE_APPROVER_ID`,
chỉ nạp khi `APP_ENV` ∈ {dev, test} (kiểm TRƯỚC khi đụng DB — fail-closed); `FAKE_SCENARIO` /
`FAKE_NODE_DELAY` (kịch bản node giả trên stack, 2b-4) cùng luật.
B1 (2b) đọc AD qua registry tool đọc (token svc_agent): truyền `directory` vào để dùng chung breaker
với nơi khác trong cùng process; không truyền thì tự dựng (và tự đóng client HTTP khi thoát).
ml-service (3a): `MlClient` thật (`ML_SERVICE_URL`, `ML_SERVICE_TOKEN`) — thiếu token → từ chối khởi động
TRƯỚC khi đụng DB (3-Q21), ở cả backend lẫn worker.
Guard (3e): `check_guard` — file mẫu `config/privacy_patterns.json` (và mẫu injection) hỏng → không khởi động, trước DB.
Intent (3f): `check_intent_config` — `ENABLED_INTENTS` ⊆ `slots.yaml` `intents`, mọi `action_type` có dòng trong
`config/action_metadata.yaml`; sai → không khởi động, trước DB. Hạn cho cả lượt: `Runner(turn_budget_s, safety_margin_s)`.
LLM gateway (3d): `check_llm` cùng luật fail-closed (LLM_BACKEND, pricing, prompt, preset — trước khi đụng DB); gateway
ghi cache/trace/chi tiêu vào Postgres, trace gắn lượt + span node qua `tracing.trace_parent`.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

import httpx
from qdrant_client import AsyncQdrantClient

from app.approval.store import SqlApprovals
from app.audit.alerts import AlertWriter
from app.audit.security_events import SecurityEventWriter
from app.audit.writer import AuditWriter
from app.core.clock import Clock
from app.db.escalations import SqlEscalationStore
from app.db.identity import SqlIdentityReads
from app.db.runtime import SqlDeadlineStore, SqlEffectStore, SqlSpanSink, SqlTurnStore
from app.db.session import Engines
from app.db.tickets import SqlTicketStore
from app.graph.builder import build_graph, fake_nodes, real_nodes
from app.graph.checkpoint import open_postgres_saver
from app.graph.fakes import (
    FakeScenario,
    LoggingNotifier,
    NodeDeps,
    RefusingExecutor,
    StackScenario,
    UnconfiguredDirectory,
)
from app.graph.lock import PgTicketLock
from app.graph.ports import (
    ApprovalRepo,
    DeadlineStore,
    TicketRepo,
    ToolCaller,
    TurnStore,
)
from app.graph.runner import Runner
from app.graph.tracing import NodeFn, trace_parent
from app.guard.output import OutputGuard
from app.guard.patterns import check_guard
from app.guard.privacy import guard_from_settings
from app.llm import LlmPort
from app.llm.wiring import check_llm, open_llm
from app.ml import MlClient, MlPort
from app.rag.bm25 import load_lexicon
from app.rag.ingest.kbversion import pipeline_sha
from app.rag.ports import RagPort
from app.rag.retriever import RagConfig, Retriever
from app.rag.vector_store import QdrantIndex
from app.settings import (
    Settings,
    check_intent_config,
    get_action_metadata,
    get_escalation_templates,
    get_policy,
    get_slots,
)
from app.tools.wiring import build_read_registry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Runtime:
    """`runner` + store mà API/worker cần (Protocol — test tiêm bản in-memory `tests/fakes/graph.py`)."""

    runner: Runner
    deadlines: DeadlineStore
    turns: TurnStore
    tickets: TicketRepo  # create, get (API); B20
    approvals: ApprovalRepo  # lock_row (route duyệt); create/close (B15/B16)


def fake_approver(settings: Settings) -> str | None:
    """`FAKE_APPROVER_ID` chỉ ở dev/test (2b-Q3). Chưa đặt → None (B15 giả → E9)."""
    if settings.fake_approver_id is not None:
        settings.require_dev_fakes("FAKE_APPROVER_ID (người duyệt giả của B15)")
    return settings.fake_approver_id


def fake_scenario(settings: Settings) -> FakeScenario:
    """`FAKE_SCENARIO` / `FAKE_NODE_DELAY` chỉ ở dev/test (2b-4, fail-closed như 2b-Q3). Không đặt →
    kịch bản mặc định (thẻ `[fake:…]` bị bỏ qua). Preset lạ → `ValueError` (không khởi động)."""
    if settings.fake_node_delay is not None:
        settings.require_dev_fakes("FAKE_NODE_DELAY (điểm dừng node giả)")
    if settings.fake_scenario is None:
        if settings.fake_node_delay is not None:
            raise RuntimeError("FAKE_NODE_DELAY chỉ có nghĩa khi đặt FAKE_SCENARIO — từ chối khởi động")
        return FakeScenario()
    settings.require_dev_fakes("FAKE_SCENARIO (kịch bản node giả theo thẻ)")
    return StackScenario(settings.fake_scenario, delay=settings.fake_node_delay or 0.0)


@asynccontextmanager
async def open_runtime(
    settings: Settings,
    engines: Engines,
    clock: Clock,
    *,
    can_execute: bool,
    directory: ToolCaller | None = None,
) -> AsyncIterator[Runtime]:
    approver_id = fake_approver(settings)  # trước mọi kết nối: sai môi trường → không khởi động
    scenario = fake_scenario(settings)  # như trên (2b-4)
    ml_token = settings.require_ml_token()  # như trên (3-Q21)
    llm_setup = check_llm(settings)  # như trên (3-Q26, PLAN-3d Q-3d-13): LLM_BACKEND, pricing, prompt, preset
    check_guard(settings)  # như trên (3e): file mẫu guard hỏng → không khởi động
    # như trên (3f, phase3 9.2): intent bật phải có slot; mọi action_type phải có metadata
    check_intent_config(settings, get_slots(), get_action_metadata())
    async with AsyncExitStack() as stack:
        ml_http = httpx.AsyncClient(base_url=settings.ml_service_url)
        stack.push_async_callback(ml_http.aclose)
        ml = MlClient(ml_http, ml_token.get_secret_value(), clock=clock)
        qdrant = AsyncQdrantClient(
            url=settings.qdrant_url, timeout=int(settings.rag_qdrant_timeout_s), check_compatibility=False
        )  # AsyncQdrantClient.timeout: int | None — rag_qdrant_timeout_s (float, mục 3.5) làm tròn xuống
        stack.push_async_callback(qdrant.close)
        llm = await stack.enter_async_context(
            open_llm(llm_setup, settings, engine=engines.main, clock=clock, trace=trace_parent)
        )
        rag: RagPort = Retriever(
            QdrantIndex(qdrant), ml, RagConfig.from_settings(settings),
            threshold=get_policy().constants.RETRIEVAL_THRESHOLD,
            pipeline_sha=pipeline_sha(settings.config_dir),
            lexicon=load_lexicon(settings.config_dir), clock=clock,
        )  # fmt: skip
        if directory is None:
            if settings.svc_agent_token is None:
                log.warning("SVC_AGENT_TOKEN chưa cấu hình — B1 không đọc được AD, ticket sẽ ra E2")
                directory = UnconfiguredDirectory()
            else:
                registry, http = build_read_registry(settings, clock)
                stack.push_async_callback(http.aclose)
                directory = registry
        opened = _open(
            settings, engines, clock, can_execute=can_execute, directory=directory,
            approver_id=approver_id, scenario=scenario, ml=ml, rag=rag, llm=llm,
        )  # fmt: skip
        yield await stack.enter_async_context(opened)


def select_nodes(settings: Settings, deps: NodeDeps) -> dict[str, NodeFn]:
    """3-Q32 cách A: `FAKE_SCENARIO` đặt → toàn bộ node giả (gate2 không đổi); không đặt → node giả + node
    thật đã có (`builder.real_nodes`)."""
    return fake_nodes(deps) if settings.fake_scenario is not None else real_nodes(deps)


@asynccontextmanager
async def _open(
    settings: Settings, engines: Engines, clock: Clock, *, can_execute: bool, directory: ToolCaller,
    approver_id: str | None, scenario: FakeScenario, ml: MlPort, rag: RagPort, llm: LlmPort,
) -> AsyncIterator[Runtime]:  # fmt: skip
    deadlines = SqlDeadlineStore(engines.main)
    turns = SqlTurnStore(engines.main)
    tickets = SqlTicketStore(engines.main)
    approvals = SqlApprovals(engines.main)
    deps = NodeDeps(
        notifier=LoggingNotifier(), approvals=approvals, executor=RefusingExecutor(),
        deadlines=deadlines, constants=get_policy().constants,
        identity=SqlIdentityReads(engines.main), directory=directory,
        alerts=AlertWriter(engines.main, clock), lockout=timedelta(minutes=settings.lockout_minutes),
        tickets=tickets, escalations=SqlEscalationStore(engines.main),
        templates=get_escalation_templates(), ml=ml, rag=rag, llm=llm, approver_id=approver_id,
        scenario=scenario, security_events=SecurityEventWriter(engines.main, clock),
        slots=get_slots(), action_metadata=get_action_metadata().root,
        enabled_intents=frozenset(settings.enabled_intents),
        enable_proactive_diagnosis=settings.enable_proactive_diagnosis,
        output_guard=OutputGuard.from_config(settings.config_dir, settings.output_canaries),
        privacy=guard_from_settings(settings),
    )  # fmt: skip
    async with open_postgres_saver(
        settings.database_url, max_size=settings.checkpoint_pool_size
    ) as saver:
        runner = Runner(
            build_graph(select_nodes(settings, deps), saver),
            lock=PgTicketLock(engines.lock), turns=turns, audit=AuditWriter(engines.main),
            effects=SqlEffectStore(engines.main), spans=SqlSpanSink(engines.main), clock=clock,
            turn_budget_s=settings.turn_budget_s, safety_margin_s=settings.safety_margin_s,
            concurrency=settings.graph_concurrency, can_execute=can_execute,
            rediagnose_on_new_slot=settings.rediagnose_on_new_slot,
            recursion_limit=settings.graph_recursion_limit,
            max_recover_attempts=settings.max_recover_attempts, tickets=tickets,
        )  # fmt: skip
        yield Runtime(runner=runner, deadlines=deadlines, turns=turns, tickets=tickets,
                      approvals=approvals)  # fmt: skip
