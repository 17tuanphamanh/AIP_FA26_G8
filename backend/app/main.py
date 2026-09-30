"""FastAPI app — /api/health, auth (P6), ticket + sự kiện + duyệt (2b-3), hàng đợi L2.

`create_app` là điểm nối (composition root): auth chỉ biết port (`auth/ports.py`); ở đây gắn adapter
AD (`tools`), writer `security_events` + `alerts` (`audit`), store SQL, runtime graph. Test tiêm `idp`,
`store`, `sink`, `alerts`, `escalations` (hàng đợi L2), `runtime` (factory), `guard`, `clock`.

Thiếu `JWT_SIGNING_KEY` (hoặc thiếu `SVC_AGENT_TOKEN` khi không tiêm idp) → route auth trả 503; app
vẫn khởi động và `/api/health` vẫn chạy. Runtime graph mở lỗi → route ticket/duyệt trả 503,
`/api/health` báo `"runtime": "down"`.

Fail-closed (2b-Q2, 2b-Q3, 2b-4): thành phần giả (guard không che — `PRIVACY_GUARD=none`, `FAKE_APPROVER_ID`,
`FAKE_SCENARIO`, `FAKE_NODE_DELAY`) chỉ nạp khi `APP_ENV` ∈ {dev, test} — kiểm NGAY trong `create_app`, sai thì không có
app nào được dựng. Mặc định mọi env là guard regex thật (3e); file mẫu guard hỏng → không dựng app (`check_guard`).
Như vậy với `ML_SERVICE_TOKEN` (3-Q21) khi dùng runtime thật: thiếu → không dựng app.
Body > `MAX_REQUEST_BODY_BYTES` → 413 trước mọi kiểm quyền (`api/limits.py`).
"""

import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from datetime import timedelta

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.approvals import router as approvals_router
from app.api.auth import auth_error_handler
from app.api.auth import router as auth_router
from app.api.background import BackgroundRuns
from app.api.desk import Desk, retry_after
from app.api.errors import install_graph_errors, install_request_errors
from app.api.escalations import EscalationQueue
from app.api.escalations import router as escalations_router
from app.api.health import HealthCheck, KbProbe
from app.api.health import router as health_router
from app.api.limits import BodyLimitMiddleware
from app.api.tickets import router as tickets_router
from app.audit.alerts import AlertWriter
from app.audit.security_events import SecurityEventWriter
from app.auth.mfa import MfaCipher
from app.auth.ports import (
    AlertSink,
    AuthStore,
    IdentityProvider,
    IdentityUnavailable,
    SecurityEventSink,
)
from app.auth.service import AuthError, AuthService, auth_config
from app.auth.store import SqlAuthStore
from app.auth.tokens import TokenSigner
from app.core.clock import Clock, SystemClock
from app.core.logging import configure_logging
from app.db.escalations import SqlEscalationStore
from app.db.session import Engines, create_engines, ping
from app.executor.txlog import SqlTxLog
from app.executor.vpn import VpnExecutor
from app.executor.wiring import build_write_registry
from app.graph.ports import ToolCaller
from app.graph.wiring import Runtime, fake_approver, fake_scenario, open_runtime
from app.guard.patterns import check_guard
from app.guard.privacy import PrivacyGuard, guard_from_settings
from app.llm.wiring import check_llm
from app.monitor.db import MonitorUnavailable
from app.rag.ingest.config import ALIAS as KB_ALIAS
from app.settings import Settings, get_policy, get_settings
from app.tools.adapters.ad_read import AdIdentityProvider
from app.tools.specs import READ_TIMEOUT_S
from app.tools.wiring import build_read_registry

log = logging.getLogger(__name__)

type RuntimeFactory = Callable[
    [Settings, Engines, Clock, ToolCaller | None], AbstractAsyncContextManager[Runtime]
]


NO_EXECUTOR_WARNING = "B17 se tu choi thuc thi (khong co SVC_EXECUTOR_TOKEN)"


@asynccontextmanager
async def _default_runtime(
    settings: Settings, engines: Engines, clock: Clock, directory: ToolCaller | None
) -> AsyncIterator[Runtime]:
    """Backend giữ SVC_EXECUTOR_TOKEN (D-03) → can_execute=True; worker thì không. 3h (P7): CHỈ ở đây dựng registry GHI +
    `VpnExecutor` (transaction_log trên engine chính). Không token → `RefusingExecutor` (B17 E7, 0 lời gọi ghi) + WARNING một
    lần lúc khởi động. `FAKE_SCENARIO` (gate2, node giả) → giữ `RefusingExecutor` như Phase 2 (gate2 89/0 không đổi)."""
    async with AsyncExitStack() as stack:
        executor = None
        if settings.svc_executor_token is None:
            log.warning(NO_EXECUTOR_WARNING)
        elif settings.fake_scenario is None:
            write_registry, write_http = build_write_registry(settings, clock)
            stack.push_async_callback(write_http.aclose)
            executor = VpnExecutor(
                write_registry, SqlTxLog(engines.main, clock), clock, tz=get_policy().business_hours.tz
            )
        yield await stack.enter_async_context(
            open_runtime(settings, engines, clock, can_execute=True, directory=directory, executor=executor)
        )


def _default_guard(settings: Settings) -> PrivacyGuard:
    """Mặc định MỌI env: guard regex thật (3e). `PRIVACY_GUARD=none` chỉ dev/test (phase3 mục 8.3, e17)."""
    return guard_from_settings(settings)


def _default_checks(settings: Settings, app: FastAPI) -> dict[str, HealthCheck]:
    async def db() -> None:
        await ping(app.state.engines.main)

    async def qdrant() -> None:
        async with httpx.AsyncClient(timeout=settings.health_timeout) as client:
            (await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz")).raise_for_status()

    async def mock() -> None:  # hệ thống ngoài giả lập (P5) — /health không cần token
        async with httpx.AsyncClient(timeout=settings.health_timeout) as client:
            (await client.get(f"{settings.mock_url.rstrip('/')}/health")).raise_for_status()

    async def ml() -> None:  # ml-service (P4, 3-Q9) — /health không cần token; 503 khi đang nạp model
        async with httpx.AsyncClient(timeout=settings.health_timeout) as client:
            (await client.get(f"{settings.ml_service_url.rstrip('/')}/health")).raise_for_status()

    return {"db": db, "qdrant": qdrant, "mock": mock, "ml": ml}


def _default_kb_probe(settings: Settings) -> KbProbe:
    """3c, Q-3c-5: `GET {qdrant_url}/aliases` — ĐÚNG như PLAN-3c mục 5.4 ghi. S7 từng "sửa" sang
    `/collections/aliases`, dựa trên đọc nhầm `qdrant_client.http.api.aliases_api`: đường đó là của
    `update_aliases` (POST, ĐỔI alias — khác thao tác), không phải của `get_collections_aliases()` (đọc mọi
    alias, mà `AsyncQdrantClient.get_aliases()`/`QdrantIndex.alias_target()` dùng) — hàm đó gọi
    `_build_for_get_collections_aliases()`, `url="/aliases"`. Phát hiện lại ở S12/L5: Qdrant thật trả 404
    "Collection `aliases` doesn't exist" cho `/collections/aliases` (hiểu thành `/collections/{name}`); xác
    nhận `GET /aliases` trả `{"result": {"aliases": [{"alias_name", "collection_name"}]}, "status", "time"}`
    trên Qdrant 1.19.1 thật (không chỉ suy từ client SDK nữa). httpx thô — KHÔNG import qdrant-client."""

    async def probe() -> str | None:
        async with httpx.AsyncClient(timeout=settings.health_timeout) as client:
            resp = await client.get(f"{settings.qdrant_url.rstrip('/')}/aliases")
            resp.raise_for_status()
        aliases = resp.json()["result"]["aliases"]
        return next((a["collection_name"] for a in aliases if a["alias_name"] == KB_ALIAS), None)

    return probe


def _build_auth(
    settings: Settings,
    clock: Clock,
    store: AuthStore,
    sink: SecurityEventSink,
    alerts: AlertSink,
    idp: IdentityProvider | None,
) -> AuthService | None:
    if settings.jwt_signing_key is None:
        log.warning("JWT_SIGNING_KEY chưa cấu hình — route auth trả 503")
        return None
    if idp is None:
        log.warning("SVC_AGENT_TOKEN chưa cấu hình — không gọi được AD, route auth trả 503")
        return None
    signer = TokenSigner(
        settings.jwt_signing_key, timedelta(minutes=settings.access_ttl_minutes), clock
    )
    cipher = MfaCipher(settings.mfa_enc_key) if settings.mfa_enc_key is not None else None
    return AuthService(
        store=store, idp=idp, sink=sink, alerts=alerts, clock=clock, signer=signer, cipher=cipher,
        config=auth_config(settings, get_policy().constants),
    )  # fmt: skip


async def _monitor_unavailable(_: Request, exc: Exception) -> JSONResponse:  # M9 (A0): body giống `runtime_unavailable`
    return JSONResponse({"detail": "monitor_unavailable"}, status_code=503)


def create_app(
    settings: Settings | None = None,
    health_checks: Mapping[str, HealthCheck] | None = None,
    *,
    idp: IdentityProvider | None = None,
    store: AuthStore | None = None,
    sink: SecurityEventSink | None = None,
    alerts: AlertSink | None = None,
    escalations: EscalationQueue | None = None,
    runtime: RuntimeFactory | None = None,
    guard: PrivacyGuard | None = None,
    clock: Clock | None = None,
    kb_probe: KbProbe | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    clock = clock or SystemClock()
    check_guard(settings)  # file mẫu guard hỏng → PatternFileError, không dựng app (3e)
    guard = guard or _default_guard(settings)  # PRIVACY_GUARD=none ngoài dev/test → RuntimeError, không dựng app
    fake_approver(settings)  # như trên cho FAKE_APPROVER_ID (worker kiểm lại trong open_runtime)
    fake_scenario(settings)  # như trên cho FAKE_SCENARIO / FAKE_NODE_DELAY (2b-4)
    if runtime is None:  # runtime thật gọi ml-service: thiếu ML_SERVICE_TOKEN → không dựng app (3-Q21)
        settings.require_ml_token()
        check_llm(settings)  # như trên: LLM_BACKEND thiếu/sai, scripted ngoài dev/test, model thiếu giá (3-Q26)
    runtime_factory = runtime or _default_runtime
    background = BackgroundRuns()
    lock_retry = retry_after(settings.ticket_lock_timeout)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:  # đóng ngược thứ tự: runtime → client AD → engines
            engines = create_engines(settings)
            stack.push_async_callback(engines.dispose)
            app.state.engines = engines
            app.state.escalations = escalations or SqlEscalationStore(engines.main)
            registry = None
            identity = idp
            if identity is None and settings.svc_agent_token is not None:
                registry, ad_http = build_read_registry(settings, clock)
                stack.push_async_callback(ad_http.aclose)
                identity = AdIdentityProvider(
                    ad_http, registry, timeout=READ_TIMEOUT_S, unavailable=IdentityUnavailable
                )
            auth_store = store or SqlAuthStore(engines.main)
            security = sink or SecurityEventWriter(engines.main, clock)  # auth + guard (3e) dùng chung
            app.state.auth = _build_auth(
                settings,
                clock,
                auth_store,
                security,
                alerts or AlertWriter(engines.main, clock),
                identity,
            )
            try:
                rt = await stack.enter_async_context(
                    runtime_factory(settings, engines, clock, registry)
                )
            except Exception:
                log.exception("không mở được runtime graph — route ticket/duyệt trả 503")
                app.state.desk, app.state.runtime_status = None, "down"
            else:
                app.state.desk = Desk(
                    runner=rt.runner, tickets=rt.tickets, approvals=rt.approvals, guard=guard, security=security,
                    users=auth_store, clock=clock, background=background,
                    retry_after_seconds=lock_retry,
                )  # fmt: skip
                app.state.runtime_status = "up"
            try:
                yield
            finally:
                # lượt nền còn chạy: chờ tối đa N giây rồi huỷ — lượt dở để worker phục hồi
                await background.shutdown(settings.background_shutdown_seconds)
                app.state.desk, app.state.runtime_status = None, "down"

    app = FastAPI(title="servicedesk-agent", lifespan=lifespan)
    app.state.health_timeout = settings.health_timeout
    app.state.health_checks = (
        health_checks if health_checks is not None else _default_checks(settings, app)
    )
    app.state.kb_probe = kb_probe or _default_kb_probe(settings)
    app.state.kb_monotonic = time.monotonic  # test tiêm đồng hồ giả bằng gán trực tiếp app.state
    app.state.auth = None  # dựng trong lifespan
    app.state.desk = None
    app.state.runtime_status = "down"
    app.state.background = background
    app.add_exception_handler(AuthError, auth_error_handler)
    install_graph_errors(app, lock_retry)
    install_request_errors(app)  # 422 không trả `input`, guard lỗi → 503 (phase3 mục 8.3)
    # ---- M9 ---- thiếu MONITOR_DATABASE_URL → 503, không rơi về app_rw (kế hoạch M9 mục 4.1)
    app.add_exception_handler(MonitorUnavailable, _monitor_unavailable)
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(tickets_router)
    app.include_router(approvals_router)
    app.include_router(escalations_router)
    return app


def build() -> FastAPI:
    """Entrypoint cho uvicorn: `uvicorn app.main:build --factory`."""
    configure_logging()
    return create_app()
