"""/api/health — 200 khi mọi phụ thuộc lõi sống, 503 kèm tên phụ thuộc lỗi (P9 mục 7).
Không cần DB/Qdrant thật: kiểm tra tiêm vào create_app; kiểm Qdrant thật bằng respx."""

import asyncio

import httpx
import pytest
import respx
from app.main import _default_checks, create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from tests.fakes.runtime import no_runtime


def _settings(**over: object) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg, arg-type]


async def ok() -> None:
    return None


async def broken() -> None:
    raise ConnectionError("không kết nối được")


async def slow() -> None:
    await asyncio.sleep(1)


def _get(checks: dict[str, object], **over: object) -> httpx.Response:
    app = create_app(_settings(**over), health_checks=checks, runtime=no_runtime)  # type: ignore[arg-type]
    with TestClient(app) as client:
        return client.get("/api/health")


def test_all_ok_returns_200() -> None:
    r = _get({"db": ok, "qdrant": ok})
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"db": "ok", "qdrant": "ok"}, "failed": [],
                        "runtime": "down"}  # fmt: skip


def test_one_dependency_down_returns_503_with_name() -> None:
    r = _get({"db": ok, "qdrant": broken})
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["failed"] == ["qdrant"]
    assert body["checks"]["qdrant"] == "error: ConnectionError"


def test_slow_dependency_times_out() -> None:
    r = _get({"db": slow, "qdrant": ok}, health_timeout=0.05)
    assert r.status_code == 503
    assert r.json()["checks"]["db"] == "timeout"


def test_default_checks_are_db_qdrant_mock() -> None:
    app = create_app(_settings())
    assert set(app.state.health_checks) == {"db", "qdrant", "mock"}


@pytest.mark.asyncio
@respx.mock
async def test_mock_check_calls_health() -> None:
    settings = _settings(mock_url="http://mock.test:8100/")
    checks = _default_checks(settings, create_app(settings))
    route = respx.get("http://mock.test:8100/health").mock(return_value=httpx.Response(200))
    await checks["mock"]()
    assert route.called
    route.mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await checks["mock"]()


@pytest.mark.asyncio
@respx.mock
async def test_qdrant_check_calls_readyz() -> None:
    settings = _settings(qdrant_url="http://qdrant.test:6333/")
    checks = _default_checks(settings, create_app(settings))
    route = respx.get("http://qdrant.test:6333/readyz").mock(return_value=httpx.Response(200))
    await checks["qdrant"]()
    assert route.called
    route.mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await checks["qdrant"]()
