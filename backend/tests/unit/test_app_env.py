"""Fail-closed theo APP_ENV (2b-Q2, 2b-Q3) + lifespan: runtime lỗi → route ticket 503, `/api/health`
vẫn 200 kèm `"runtime"`."""

from contextlib import asynccontextmanager
from typing import Any

import pytest
from app.db.session import create_engines
from app.graph.wiring import open_runtime
from app.guard.privacy import NotRedactingGuard
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from tests.fakes.desk import desk_env
from tests.fakes.runtime import no_runtime


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


@pytest.mark.parametrize("env", [None, "staging", "prod"])
def test_prod_refuses_not_redacting_guard(env: str | None) -> None:
    with pytest.raises(RuntimeError, match="NotRedactingGuard"):
        create_app(_settings(app_env=env), health_checks={}, runtime=no_runtime)


@pytest.mark.parametrize("env", [None, "staging", "prod"])
def test_prod_refuses_fake_approver(env: str | None) -> None:
    # guard được tiêm (giả lập guard thật) → vẫn phải chặn FAKE_APPROVER_ID
    with pytest.raises(RuntimeError, match="FAKE_APPROVER_ID"):
        create_app(_settings(app_env=env, fake_approver_id="l1_01"), health_checks={},
                   runtime=no_runtime, guard=NotRedactingGuard())  # fmt: skip


@pytest.mark.parametrize("env", ["dev", "test"])
def test_dev_test_start(env: str) -> None:
    app = create_app(_settings(app_env=env, fake_approver_id="l1_01"), health_checks={},
                     runtime=no_runtime)  # fmt: skip
    assert app is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("env", [None, "prod"])
async def test_worker_runtime_refuses_fake_approver(env: str | None) -> None:
    """Worker (`open_runtime`) cùng luật — chặn TRƯỚC khi đụng DB (engine chưa từng kết nối)."""
    settings = _settings(app_env=env, fake_approver_id="l1_01")
    engines = create_engines(settings)
    with pytest.raises(RuntimeError, match="FAKE_APPROVER_ID"):
        async with open_runtime(settings, engines, clock=None, can_execute=False):  # type: ignore[arg-type]
            pass
    await engines.dispose()


def test_runtime_failure_health_still_up() -> None:
    app = create_app(_settings(), health_checks={}, runtime=no_runtime)
    with TestClient(app) as client:
        h = client.get("/api/health")
        assert (h.status_code, h.json()["runtime"]) == (200, "down")


@pytest.mark.asyncio
async def test_runtime_failure_ticket_routes_503() -> None:
    async with desk_env(runtime=no_runtime) as env:
        an = await env.token("an.nv")  # auth vẫn chạy
        assert (await env.client.get("/api/health")).json()["runtime"] == "down"
        r = await env.client.post("/api/tickets", json={"text": "x"}, headers=an)
        assert r.status_code == 503
        l1 = await env.token("ha.lt")
        r = await env.client.post("/api/approvals/1/decision", json={"decision": "approved"}, headers=l1)
        assert r.status_code == 503
        r = await env.client.get("/api/tickets/x", headers=an)
        assert r.status_code == 503


@pytest.mark.asyncio
async def test_health_runtime_up() -> None:
    async with desk_env() as env:
        body = (await env.client.get("/api/health")).json()
        assert (body["status"], body["runtime"]) == ("ok", "up")


def test_runtime_factory_exception_is_contained() -> None:
    @asynccontextmanager
    async def boom(*_: Any) -> Any:
        raise ConnectionError("Postgres chết")
        yield  # pragma: no cover

    app = create_app(_settings(), health_checks={}, runtime=lambda *a: boom())
    with TestClient(app) as client:
        assert client.get("/api/health").json()["runtime"] == "down"

