"""FastAPI app — /api/health, auth (P6), ticket + sự kiện + duyệt (2b-3), hàng đợi L2.

`create_app` là điểm nối (composition root): auth chỉ biết port (`auth/ports.py`); ở đây gắn adapter
AD (`tools`), writer `security_events` + `alerts` (`audit`), store SQL, runtime graph. Test tiêm `idp`,
`store`, `sink`, `alerts`, `escalations` (hàng đợi L2), `runtime` (factory), `guard`, `clock`.

Thiếu `JWT_SIGNING_KEY` (hoặc thiếu `SVC_AGENT_TOKEN` khi không tiêm idp) → route auth trả 503; app
vẫn khởi động và `/api/health` vẫn chạy. Runtime graph mở lỗi → route ticket/duyệt trả 503,
`/api/health` báo `"runtime": "down"`.

Fail-closed (2b-Q2, 2b-Q3): thành phần giả (guard không che, `FAKE_APPROVER_ID`) chỉ nạp khi
`APP_ENV` ∈ {dev, test} — kiểm NGAY trong `create_app`, sai thì không có app nào được dựng.
Body > `MAX_REQUEST_BODY_BYTES` → 413 trước mọi kiểm quyền (`api/limits.py`).
"""

import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from datetime import timedelta

import httpx
from fastapi import FastAPI

from app.api.approvals import router as approvals_router
from app.api.auth import auth_error_handler
from app.api.auth import router as auth_router
from app.api.background import BackgroundRuns
from app.api.desk import Desk, retry_after
from app.api.errors import install_graph_errors
from app.api.escalations import EscalationQueue
from app.api.escalations import router as escalations_router
from app.api.health import HealthCheck
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
from app.graph.ports import ToolCaller
from app.graph.wiring import Runtime, fake_approver, open_runtime
from app.guard.privacy import NotRedactingGuard, PrivacyGuard
from app.settings import Settings, get_policy, get_settings
from app.tools.adapters.ad_read import AdIdentityProvider
from app.tools.specs import READ_TIMEOUT_S
from app.tools.wiring import build_read_registry

log = logging.getLogger(__name__)

type RuntimeFactory = Callable[
    [Settings, Engines, Clock, ToolCaller | None], AbstractAsyncContextManager[Runtime]
]


def _default_runtime(
    settings: Settings, engines: Engines, clock: Clock, directory: ToolCaller | None
) -> AbstractAsyncContextManager[Runtime]:
    # Backend giữ SVC_EXECUTOR_TOKEN (D-03) → can_execute=True; worker thì không.
    return open_runtime(settings, engines, clock, can_execute=True, directory=directory)


def _default_guard(settings: Settings) -> PrivacyGuard:
    settings.require_dev_fakes("NotRedactingGuard (privacy guard không che)")
    return NotRedactingGuard()


def _default_checks(settings: Settings, app: FastAPI) -> dict[str, HealthCheck]:
    async def db() -> None:
        await ping(app.state.engines.main)

    async def qdrant() -> None:
        async with httpx.AsyncClient(timeout=settings.health_timeout) as client:
            (await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz")).raise_for_status()

    async def mock() -> None:  # hệ thống ngoài giả lập (P5) — /health không cần token
        async with httpx.AsyncClient(timeout=settings.health_timeout) as client:
            (await client.get(f"{settings.mock_url.rstrip('/')}/health")).raise_for_status()

    return {"db": db, "qdrant": qdrant, "mock": mock}


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
) -> FastAPI:
    settings = settings or get_settings()
    clock = clock or SystemClock()
    guard = guard or _default_guard(settings)  # sai APP_ENV → RuntimeError, không dựng app
    fake_approver(settings)  # như trên cho FAKE_APPROVER_ID (worker kiểm lại trong open_runtime)
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
            app.state.auth = _build_auth(
                settings,
                clock,
                auth_store,
                sink or SecurityEventWriter(engines.main, clock),
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
                    runner=rt.runner, tickets=rt.tickets, approvals=rt.approvals, guard=guard,
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
    app.state.auth = None  # dựng trong lifespan
    app.state.desk = None
    app.state.runtime_status = "down"
    app.state.background = background
    app.add_exception_handler(AuthError, auth_error_handler)
    install_graph_errors(app, lock_retry)
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
