"""Dựng runtime graph trên Postgres: store SQL + checkpoint + khoá + runner (composition root).

Worker dùng `can_execute=False` (không có SVC_EXECUTOR_TOKEN — D-03, quyết định 26/09/2026). Executor (3h, P7): chỉ `main.py`
(API) dựng `PlanExecutor` rồi truyền `executor=` vào; không truyền (worker, API thiếu token) → `RefusingExecutor` đọc
`transaction_log` (soát S12 NGHI-3: `begun` có sẵn → E7 `exec_interrupted`). Module này KHÔNG import
`executor.wiring`/adapter ghi (hợp đồng import-linter 3). Node
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
`config/action_metadata.yaml`; sai → không khởi động, trước DB. Luật M5 (3h, Q-3h-1): `check_policy_config` cùng chỗ.
Hạn cho cả lượt: `Runner(turn_budget_s, safety_margin_s)`.
LLM gateway (3d): `check_llm` cùng luật fail-closed (LLM_BACKEND, pricing, prompt, preset — trước khi đụng DB); gateway
ghi cache/trace/chi tiêu vào Postgres, trace gắn lượt + span node qua `tracing.trace_parent`.
Người duyệt (4b): roster `config/approvers.yaml` (kiểm trước DB) → `NodeDeps.approvers`; `NodeDeps.approver_users` =
`auth.user_sync.AuthApproverUsers` trên `SqlAuthStore` + `SecurityEventWriter` + khoá HMAC username ma qua `username_hash.resolve_key`
(backend: dẫn xuất từ `JWT_SIGNING_KEY` — cùng hàm với `TokenSigner.username_key`; worker: `USERNAME_HMAC_KEY` — A2 bn-a; lệch → không
khởi động). Thiếu khoá → WARNING, `available=False` (B15 → E2 `approver_sync_unavailable` theo ticket) — KHÔNG đổi điều kiện khởi động
của backend (Q-4b-5); worker tự từ chối thiếu khoá ở `worker.require_worker_keys`.
M5 lớp 2 (Phase 6 6C, P1/P10, N2/N5): chiến lược = `Settings.strategy` (Q-6C-1 = B — `manual` bị từ chối ở mọi chế độ, còn lại
`check_strategy`) và calibrator (`m5.calibrator_version` → CHỈ `load_calibrator`; null → None = không AUTO) kiểm TRƯỚC DB ở cả backend
lẫn worker; `NodeDeps.estimator` = `LlmRiskEstimator` trên cùng gateway, `eval_mode` cùng nguồn Settings với gateway (N2).
Email (notify-email): `Settings.email_active` (EMAIL_ENABLED=true và không EVAL_MODE) → `notify_user` của ticket thường/cha bọc
`notify.notifier.EmailingNotifier` (bên trong `ChildAwareNotifier` — con không email), phiếu duyệt dùng `EmailingApprovals` (B15
`notify_approver` thêm dòng outbox); cùng privacy guard với `NodeDeps.privacy`. Tắt → y như cũ, không dòng `email_outbox` nào.
"""

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

import httpx
from qdrant_client import AsyncQdrantClient

from app.approval.store import SqlApprovals
from app.audit.alerts import AlertWriter
from app.audit.security_events import SecurityEventWriter
from app.audit.writer import AuditWriter
from app.auth.service import auth_config, lock_policy
from app.auth.store import SqlAuthStore
from app.auth.user_sync import AdUserSync, AuthApproverUsers
from app.auth.username_hash import resolve_key
from app.core.clock import Clock
from app.db.escalations import SqlEscalationStore
from app.db.identity import SqlIdentityReads
from app.db.runtime import SqlDeadlineStore, SqlEffectStore, SqlSpanSink, SqlTurnStore
from app.db.session import Engines
from app.db.tickets import SqlTicketStore
from app.domain.approval import Roster
from app.executor.plans import check_plans
from app.executor.txlog import SqlTxLog
from app.graph.builder import build_graph, fake_nodes, real_nodes
from app.graph.checkpoint import open_postgres_saver
from app.graph.fakes import (
    Executor,
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
from app.notify.child import ChildAwareNotifier, UserNotifier
from app.notify.notifier import (
    ApproverEmailNotice,
    EmailingApprovals,
    EmailingNotifier,
    email_outbox_from_settings,
)
from app.rag.bm25 import load_lexicon
from app.rag.ingest.kbversion import pipeline_sha
from app.rag.ports import RagPort
from app.rag.retriever import RagConfig, Retriever
from app.rag.vector_store import QdrantIndex
from app.risk.calibrator import Calibrator, load_calibrator
from app.risk.estimator import LlmRiskEstimator
from app.risk.strategy import Strategy, check_strategy
from app.settings import (
    Settings,
    approval_sla_minutes,
    check_intent_config,
    check_policy_config,
    get_action_metadata,
    get_escalation_templates,
    get_policy,
    get_slots,
    open_approvers,
)
from app.tools.wiring import build_read_registry

log = logging.getLogger(__name__)

CALIBRATOR_DIR = "calibrators"  # 6C P10: <config_dir>/calibrators/<version>.json (6A P9)
MANUAL_REFUSED = "STRATEGY=manual: manual chỉ tính giải tích ở harness M8, không chạy hệ thống — từ chối khởi động"


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


def m5_strategy(settings: Settings) -> Strategy:
    """6C P1 (Q-6C-1 = B): kiểm `Settings.strategy` lúc khởi động. `manual` (P8 — chỉ tính giải tích ở harness) → từ chối ở MỌI chế
    độ; chiến lược chỉ-để-so-sánh (D-67: `llm_only`, `full_auto`) khi không EVAL_MODE → `StrategyNotAllowed` (cổng 6). Gọi ở
    `open_runtime` TRƯỚC DB (backend + worker, N5) và lại ở `_open` (lớp thứ hai cho nơi dựng runtime không qua `open_runtime`).
    D-67: ngoài EVAL_MODE chiến lược lúc vận hành do DB quyết (`m5_strategy_changes`, chụp lên ticket lúc tạo) — `STRATEGY` chỉ có
    nghĩa khi EVAL_MODE; `rule_only`/`hybrid_guarded` đặt ở env ngoài EVAL_MODE được chấp nhận nhưng BỊ BỎ QUA (log cảnh báo)."""
    strategy = settings.strategy
    if strategy == "manual":
        raise RuntimeError(MANUAL_REFUSED)
    check_strategy(strategy, eval_mode=settings.eval_mode)
    if not settings.eval_mode and strategy != "hybrid":
        log.warning("STRATEGY=%s bị bỏ qua ngoài EVAL_MODE — chiến lược vận hành do DB quyết (PUT /api/admin/strategy)", strategy)
    return strategy


def open_calibrator(settings: Settings, version: str | None) -> Calibrator | None:
    """6C P10: `m5.calibrator_version` null → None (chưa hiệu chỉnh — D-38, không bao giờ AUTO); khác null → CHỈ `load_calibrator`
    (kiểm `VERSION_PATTERN` trước khi ghép đường dẫn, kiểm đuôi băm — 6A). Sai mẫu / thiếu file / file hỏng → không khởi động
    (thông điệp chỉ nêu loại lỗi)."""
    if version is None:
        return None
    try:
        return load_calibrator(version, settings.config_dir / CALIBRATOR_DIR)
    except (ValueError, OSError) as exc:
        raise RuntimeError(
            f"calibrator (policy.json m5.calibrator_version) không nạp được: {type(exc).__name__} — từ chối khởi động"
        ) from None


@asynccontextmanager
async def open_runtime(
    settings: Settings,
    engines: Engines,
    clock: Clock,
    *,
    can_execute: bool,
    directory: ToolCaller | None = None,
    executor: Executor | None = None,
) -> AsyncIterator[Runtime]:
    sla_minutes = approval_sla_minutes(settings)  # 4b P12 — trước mọi kiểm khác và mọi kết nối (dev/test mới được đè)
    approver_id = fake_approver(settings)  # trước mọi kết nối: sai môi trường → không khởi động
    scenario = fake_scenario(settings)  # như trên (2b-4)
    ml_token = settings.require_ml_token()  # như trên (3-Q21)
    llm_setup = check_llm(settings)  # như trên (3-Q26, PLAN-3d Q-3d-13): LLM_BACKEND, pricing, prompt, preset
    check_guard(settings)  # như trên (3e): file mẫu guard hỏng → không khởi động
    # như trên (3f, phase3 9.2): intent bật phải có slot; mọi action_type phải có metadata
    check_intent_config(settings, get_slots(), get_action_metadata())
    # như trên (3h, Q-3h-1): mỗi action_type thuộc đúng một intent; mọi action của luật ∈ action_types của intent luật đó
    check_policy_config(get_policy(), get_slots(), get_action_metadata())
    # như trên (3h, h23): mọi action_type của intent đang bật có PLAN hợp lệ (executor/plans.py) — cả worker lẫn backend
    check_plans(get_action_metadata().root, settings.enabled_intents)
    # như trên (4b P1): `config/approvers.yaml` — mọi intent đang bật có người duyệt chính/dự phòng/Trưởng BP hợp lệ về dạng
    approvers = open_approvers(settings).root
    # như trên (Phase 6 6C P1, N5): chiến lược M5 — `manual` từ chối, chiến lược so sánh chỉ khi EVAL_MODE — cả worker lẫn backend
    m5_strategy(settings)
    # như trên (6C P10): calibrator CHỈ qua `load_calibrator`; null → None (không AUTO); lỗi → không khởi động
    calibrator = open_calibrator(settings, get_policy().m5.calibrator_version)
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
            executor=executor if executor is not None else RefusingExecutor(SqlTxLog(engines.main, clock)),
            approval_sla_minutes=sla_minutes, approvers=approvers,
            calibrator=calibrator,
        )  # fmt: skip
        yield await stack.enter_async_context(opened)


def approver_users(settings: Settings, engines: Engines, sink: SecurityEventWriter) -> AuthApproverUsers:
    """B15 `ensure` (4b P5, TQ-3): `AdUserSync` trên bảng `users` thật, cùng tham số khoá với đăng nhập (`auth_config`). Không có khoá
    HMAC username ma (`resolve_key` → None) → WARNING + `available=False` (Q-4b-5 — không đổi điều kiện khởi động). Khoá không log."""
    key = resolve_key(settings.jwt_signing_key, settings.username_hmac_key)
    if key is None:
        log.warning("thiếu khoá HMAC username ma (JWT_SIGNING_KEY / USERNAME_HMAC_KEY) — B15 không đồng bộ được người duyệt, "
                    "ticket cần duyệt sẽ ra E2")  # fmt: skip
        return AuthApproverUsers(None)
    return AuthApproverUsers(AdUserSync(
        store=SqlAuthStore(engines.main), sink=sink, username_key=key,
        lock=lock_policy(auth_config(settings, get_policy().constants)),
    ))  # fmt: skip


def select_nodes(settings: Settings, deps: NodeDeps) -> dict[str, NodeFn]:
    """3-Q32 cách A: `FAKE_SCENARIO` đặt → toàn bộ node giả (gate2 không đổi); không đặt → node giả + node
    thật đã có (`builder.real_nodes`)."""
    return fake_nodes(deps) if settings.fake_scenario is not None else real_nodes(deps)


@asynccontextmanager
async def _open(
    settings: Settings, engines: Engines, clock: Clock, *, can_execute: bool, directory: ToolCaller,
    approver_id: str | None, scenario: FakeScenario, ml: MlPort, rag: RagPort, llm: LlmPort, executor: Executor,
    approval_sla_minutes: int | None = None, approvers: Mapping[str, Roster] | None = None,
    calibrator: Calibrator | None = None,
) -> AsyncIterator[Runtime]:  # fmt: skip
    m5_strategy(settings)  # lớp thứ hai (6C P1): D-67 — NodeDeps không còn mang chiến lược, nên kiểm ở đây thay cho `strategy=`
    deadlines = SqlDeadlineStore(engines.main)
    security = SecurityEventWriter(engines.main, clock)
    turns = SqlTurnStore(engines.main)
    tickets = SqlTicketStore(engines.main)
    privacy = guard_from_settings(settings)
    outbox = email_outbox_from_settings(settings, engines.main, privacy, clock)  # None = email tắt (hoặc EVAL_MODE)
    approvals = SqlApprovals(engines.main) if outbox is None else EmailingApprovals(engines.main, ApproverEmailNotice(outbox))
    inner: UserNotifier = LoggingNotifier() if outbox is None else EmailingNotifier(LoggingNotifier(), outbox)
    deps = NodeDeps(
        notifier=ChildAwareNotifier.on_engine(engines.main, inner), approvals=approvals, executor=executor, txlog=SqlTxLog(engines.main, clock),
        deadlines=deadlines, constants=get_policy().constants,
        identity=SqlIdentityReads(engines.main), directory=directory,
        alerts=AlertWriter(engines.main, clock), lockout=timedelta(minutes=settings.lockout_minutes),
        tickets=tickets, escalations=SqlEscalationStore(engines.main),
        templates=get_escalation_templates(), ml=ml, rag=rag, llm=llm, approver_id=approver_id,
        scenario=scenario, security_events=security,
        slots=get_slots(), action_metadata=get_action_metadata().root,
        enabled_intents=frozenset(settings.enabled_intents),
        enable_proactive_diagnosis=settings.enable_proactive_diagnosis,
        grounding_gate_actions=settings.grounding_gate_actions, commit_sha=settings.app_git_sha,
        output_guard=OutputGuard.from_config(settings.config_dir, settings.output_canaries),
        privacy=privacy,
        approval_sla_minutes=approval_sla_minutes if approval_sla_minutes is not None else get_policy().constants.SLA_MINUTES,
        approvers=approvers if approvers is not None else open_approvers(settings).root,
        approver_users=approver_users(settings, engines, security),
        estimator=LlmRiskEstimator(llm, p_method=get_policy().m5.p_method, eval_mode=settings.eval_mode),
        calibrator=calibrator, eval_mode=settings.eval_mode,
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
            max_recover_attempts=settings.max_recover_attempts, tickets=tickets, txlog=deps.txlog,
        )  # fmt: skip
        yield Runtime(runner=runner, deadlines=deadlines, turns=turns, tickets=tickets,
                      approvals=approvals)  # fmt: skip
