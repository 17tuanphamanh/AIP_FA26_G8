"""Fail-closed theo APP_ENV (2b-Q2, 2b-Q3, 2b-4 `FAKE_SCENARIO`/`FAKE_NODE_DELAY`) + lifespan: runtime lỗi → route ticket 503, `/api/health`
vẫn 200 kèm `"runtime"`."""

from contextlib import asynccontextmanager
from typing import Any

import pytest
from app.db.session import create_engines
from app.graph.wiring import open_runtime
from app.guard.privacy import NotRedactingGuard, RegexPrivacyGuard
from app.main import _default_guard, create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.fakes.desk import desk_env
from tests.fakes.runtime import no_runtime


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


@pytest.mark.parametrize("env", [None, "staging", "prod"])
def test_e17_refuses_privacy_guard_none_outside_dev_test(env: str | None) -> None:
    """phase3 8.7 e17 (3e): `PRIVACY_GUARD=none` (NotRedactingGuard) ngoài dev/test → không dựng app."""
    with pytest.raises(RuntimeError, match="PRIVACY_GUARD=none"):
        create_app(_settings(app_env=env, privacy_guard="none"), health_checks={}, runtime=no_runtime)


@pytest.mark.parametrize("env", [None, "dev", "test", "staging", "prod"])
def test_default_guard_is_regex_in_every_env(env: str | None) -> None:
    """3e: mặc định MỌI env là guard regex thật (trước 3e: prod không tiêm guard thì từ chối khởi động)."""
    assert isinstance(_default_guard(_settings(app_env=env)), RegexPrivacyGuard)
    create_app(_settings(app_env=env), health_checks={}, runtime=no_runtime)  # không ném


@pytest.mark.parametrize("env", ["dev", "test"])
def test_privacy_guard_none_only_when_explicit_in_dev_test(env: str) -> None:
    assert isinstance(_default_guard(_settings(app_env=env, privacy_guard="none")), NotRedactingGuard)


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


# ---- FAKE_SCENARIO / FAKE_NODE_DELAY (2b-4) — cùng luật fail-closed -------------------------


@pytest.mark.parametrize("env", [None, "staging", "prod"])
@pytest.mark.parametrize(("over", "name"), [
    ({"fake_scenario": "approval"}, "FAKE_SCENARIO"),
    ({"fake_scenario": "approval", "fake_node_delay": 5}, "FAKE_NODE_DELAY"),
    ({"fake_node_delay": 5}, "FAKE_NODE_DELAY"),
])  # fmt: skip
def test_prod_refuses_fake_scenario(env: str | None, over: dict[str, Any], name: str) -> None:
    # guard được tiêm, không có FAKE_APPROVER_ID → chỉ còn kịch bản giả để chặn
    with pytest.raises(RuntimeError, match=name):
        create_app(_settings(app_env=env, **over), health_checks={}, runtime=no_runtime,
                   guard=NotRedactingGuard())  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.parametrize("env", [None, "prod"])
async def test_worker_runtime_refuses_fake_scenario(env: str | None) -> None:
    settings = _settings(app_env=env, fake_scenario="approval")
    engines = create_engines(settings)
    with pytest.raises(RuntimeError, match="FAKE_SCENARIO"):
        async with open_runtime(settings, engines, clock=None, can_execute=False):  # type: ignore[arg-type]
            pass
    await engines.dispose()


@pytest.mark.parametrize("env", ["dev", "test"])
def test_dev_test_start_with_fake_scenario(env: str) -> None:
    settings = _settings(app_env=env, fake_scenario="kill_b06", fake_node_delay=40)
    assert create_app(settings, health_checks={}, runtime=no_runtime) is not None


def test_unknown_preset_refuses_start() -> None:
    with pytest.raises(ValueError, match="FAKE_SCENARIO"):
        create_app(_settings(app_env="dev", fake_scenario="khong-co"), health_checks={}, runtime=no_runtime)


def test_delay_without_scenario_refuses_start() -> None:
    with pytest.raises(RuntimeError, match="FAKE_NODE_DELAY chỉ có nghĩa"):
        create_app(_settings(app_env="dev", fake_node_delay=5), health_checks={}, runtime=no_runtime)


def test_delay_must_stay_below_half_stale_turn() -> None:
    assert _settings(fake_node_delay=59.9).fake_node_delay == 59.9  # stale mặc định 120 giây
    with pytest.raises(ValidationError, match="FAKE_NODE_DELAY"):
        _settings(fake_node_delay=60)
    with pytest.raises(ValidationError, match="FAKE_NODE_DELAY"):
        _settings(fake_node_delay=20, worker_stale_turn_seconds=40)
    with pytest.raises(ValidationError):
        _settings(fake_node_delay=-1)


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



# ---- ML_SERVICE_TOKEN (3-Q21, Q-3a-5) — bắt buộc mọi môi trường, kể cả dev/test ----------------


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_backend_refuses_without_ml_token(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ML_SERVICE_TOKEN")
    settings = _settings(app_env=env)
    assert settings.ml_service_token is None
    with pytest.raises(RuntimeError, match="ML_SERVICE_TOKEN"):
        create_app(settings, health_checks={}, guard=NotRedactingGuard())  # runtime thật (mặc định)


def test_backend_starts_with_ml_token() -> None:
    settings = _settings(app_env="test")
    assert settings.ml_service_token is not None  # conftest gốc đặt token ngẫu nhiên
    assert create_app(settings, health_checks={}) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("env", ["dev", "prod"])
async def test_worker_runtime_refuses_without_ml_token(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker (`open_runtime`) — chặn TRƯỚC khi đụng DB (engine chưa từng kết nối)."""
    monkeypatch.delenv("ML_SERVICE_TOKEN")
    settings = _settings(app_env=env)
    engines = create_engines(settings)
    with pytest.raises(RuntimeError, match="ML_SERVICE_TOKEN"):
        async with open_runtime(settings, engines, clock=None, can_execute=False):  # type: ignore[arg-type]
            pass
    await engines.dispose()
