"""FastAPI app — /api/health + auth (P6). Router nghiệp vụ gắn thêm ở các phase sau.

`create_app` là điểm nối (composition root): auth chỉ biết port (`auth/ports.py`); ở đây gắn adapter
AD (`tools`), writer `security_events` (`audit`), store SQL. Test tiêm `idp`, `store`, `sink`, `clock`.

Thiếu `JWT_SIGNING_KEY` (hoặc thiếu `SVC_AGENT_TOKEN` khi không tiêm idp) → route auth trả 503; app
vẫn khởi động và `/api/health` vẫn chạy.
"""

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from fastapi import FastAPI

from app.api.auth import auth_error_handler
from app.api.auth import router as auth_router
from app.api.health import HealthCheck
from app.api.health import router as health_router
from app.audit.security_events import SecurityEventWriter
from app.auth.mfa import MfaCipher
from app.auth.ports import (
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
from app.db.session import create_engines, ping
from app.settings import Settings, get_policy, get_settings
from app.tools.adapters.ad_read import AdIdentityProvider
from app.tools.specs import READ_TIMEOUT_S
from app.tools.wiring import build_read_registry

log = logging.getLogger(__name__)


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
        store=store, idp=idp, sink=sink, clock=clock, signer=signer, cipher=cipher,
        config=auth_config(settings, get_policy().constants),
    )  # fmt: skip


def create_app(
    settings: Settings | None = None,
    health_checks: Mapping[str, HealthCheck] | None = None,
    *,
    idp: IdentityProvider | None = None,
    store: AuthStore | None = None,
    sink: SecurityEventSink | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    clock = clock or SystemClock()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engines = create_engines(settings)
        app.state.engines = engines
        ad_http = None
        identity = idp
        if identity is None and settings.svc_agent_token is not None:
            registry, ad_http = build_read_registry(settings, clock)
            identity = AdIdentityProvider(
                ad_http, registry, timeout=READ_TIMEOUT_S, unavailable=IdentityUnavailable
            )
        app.state.auth = _build_auth(
            settings,
            clock,
            store or SqlAuthStore(engines.main),
            sink or SecurityEventWriter(engines.main, clock),
            identity,
        )
        try:
            yield
        finally:
            if ad_http is not None:
                await ad_http.aclose()
            await engines.dispose()

    app = FastAPI(title="servicedesk-agent", lifespan=lifespan)
    app.state.health_timeout = settings.health_timeout
    app.state.health_checks = (
        health_checks if health_checks is not None else _default_checks(settings, app)
    )
    app.state.auth = None  # dựng trong lifespan
    app.add_exception_handler(AuthError, auth_error_handler)
    app.include_router(health_router)
    app.include_router(auth_router)
    return app


def build() -> FastAPI:
    """Entrypoint cho uvicorn: `uvicorn app.main:build --factory`."""
    configure_logging()
    return create_app()
