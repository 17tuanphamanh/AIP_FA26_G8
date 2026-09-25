"""FastAPI app — Phase 1: chỉ /api/health. Router nghiệp vụ gắn thêm ở các phase sau."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.health import HealthCheck
from app.api.health import router as health_router
from app.core.logging import configure_logging
from app.db.session import create_engines, ping
from app.settings import Settings, get_settings


def _default_checks(settings: Settings, app: FastAPI) -> dict[str, HealthCheck]:
    async def db() -> None:
        await ping(app.state.engines.main)

    async def qdrant() -> None:
        async with httpx.AsyncClient(timeout=settings.health_timeout) as client:
            (await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz")).raise_for_status()

    return {"db": db, "qdrant": qdrant}


def create_app(
    settings: Settings | None = None, health_checks: Mapping[str, HealthCheck] | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engines = create_engines(settings)
        app.state.engines = engines
        try:
            yield
        finally:
            await engines.dispose()

    app = FastAPI(title="servicedesk-agent", lifespan=lifespan)
    app.state.health_timeout = settings.health_timeout
    app.state.health_checks = (
        health_checks if health_checks is not None else _default_checks(settings, app)
    )
    app.include_router(health_router)
    return app


def build() -> FastAPI:
    """Entrypoint cho uvicorn: `uvicorn app.main:build --factory`."""
    configure_logging()
    return create_app()
