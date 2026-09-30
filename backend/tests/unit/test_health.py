"""/api/health — 200 khi mọi phụ thuộc lõi sống, 503 kèm tên phụ thuộc lỗi (P9 mục 7).
Không cần DB/Qdrant thật: kiểm tra tiêm vào create_app; kiểm Qdrant thật bằng respx."""

import asyncio
from typing import Any

import httpx
import httpx2
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


async def kb_missing() -> str | None:
    return None


def kb_ready(name: str) -> object:
    async def probe() -> str | None:
        return name

    return probe


async def kb_broken() -> str | None:
    raise httpx.ConnectError("qdrant chết")


def _get(checks: dict[str, object], *, kb_probe: Any = kb_missing, **over: object) -> httpx2.Response:
    app = create_app(_settings(**over), health_checks=checks, runtime=no_runtime,  # type: ignore[arg-type]
                     kb_probe=kb_probe)  # fmt: skip
    with TestClient(app) as client:
        return client.get("/api/health")


def test_all_ok_returns_200() -> None:
    r = _get({"db": ok, "qdrant": ok})
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok", "checks": {"db": "ok", "qdrant": "ok"}, "failed": [], "runtime": "down",
        "kb": {"alias": "kb_current", "collection": None, "status": "missing"},
    }  # fmt: skip


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


def test_default_checks_are_db_qdrant_mock_ml() -> None:
    app = create_app(_settings())
    assert set(app.state.health_checks) == {"db", "qdrant", "mock", "ml"}  # ml: 3-Q9


@pytest.mark.asyncio
@respx.mock
async def test_ml_check_calls_health_without_token() -> None:
    settings = _settings(ml_service_url="http://ml.test:8200/")
    checks = _default_checks(settings, create_app(settings))
    route = respx.get("http://ml.test:8200/health").mock(return_value=httpx.Response(200))
    await checks["ml"]()
    assert route.called
    assert "X-Service-Token" not in route.calls.last.request.headers
    route.mock(return_value=httpx.Response(503, json={"status": "loading"}))  # đang nạp model
    with pytest.raises(httpx.HTTPStatusError):
        await checks["ml"]()


def test_ml_down_makes_health_503() -> None:
    async def down() -> None:
        raise httpx.ConnectError("ml-service chết")

    r = _get({"db": ok, "ml": down})
    assert r.status_code == 503
    assert r.json()["failed"] == ["ml"] and r.json()["checks"]["ml"] == "error: ConnectError"


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


# ---- 3c, c20: trường "kb" — CHỈ báo, không bao giờ đổi mã 200/503 --------------------------------


def test_c20b_kb_status_ready_when_probe_returns_collection() -> None:
    name = "kb_" + "a" * 64
    r = _get({"db": ok, "qdrant": ok}, kb_probe=kb_ready(name))
    assert r.status_code == 200
    assert r.json()["kb"] == {"alias": "kb_current", "collection": name, "status": "ready"}


def test_c20c_kb_status_unknown_when_probe_fails_alongside_qdrant_down() -> None:
    r = _get({"db": ok, "qdrant": broken}, kb_probe=kb_broken)
    assert r.status_code == 503  # mã do check "qdrant" quyết — kb không đổi mã
    body = r.json()
    assert body["failed"] == ["qdrant"]
    assert body["kb"] == {"alias": "kb_current", "collection": None, "status": "unknown"}


def test_kb_probe_error_is_logged_with_type_only(caplog: pytest.LogCaptureFixture) -> None:
    """S14: lỗi probe không được nuốt im lặng (bug `/collections/aliases` ở S12 ẩn vì thế) — log tên lớp lỗi,
    không log thông điệp (có URL)."""
    with caplog.at_level("WARNING", logger="app.api.health"):
        r = _get({"db": ok}, kb_probe=kb_broken)
    assert r.json()["kb"]["status"] == "unknown"
    messages = [rec.getMessage() for rec in caplog.records if rec.name == "app.api.health"]
    assert messages == ["kb probe lỗi: ConnectError"]


@pytest.mark.asyncio
@respx.mock
async def test_c20a_default_kb_probe_reads_aliases() -> None:
    from app.main import _default_kb_probe

    settings = _settings(qdrant_url="http://qdrant.test:6333/")
    route = respx.get("http://qdrant.test:6333/aliases").mock(
        return_value=httpx.Response(200, json={
            "status": "ok", "time": 0.0,
            "result": {"aliases": [{"alias_name": "kb_current", "collection_name": "kb_" + "b" * 64},
                                   {"alias_name": "other", "collection_name": "kb_" + "c" * 64}]},
        }),
    )  # fmt: skip
    probe = _default_kb_probe(settings)
    assert await probe() == "kb_" + "b" * 64
    assert route.called
    route.mock(return_value=httpx.Response(200, json={"status": "ok", "time": 0.0,
                                                       "result": {"aliases": []}}))  # fmt: skip
    assert await probe() is None  # chưa ingest — alias chưa tồn tại


def test_c20d_kb_probe_result_cached_ten_seconds() -> None:
    calls = 0

    async def counting_probe() -> str | None:
        nonlocal calls
        calls += 1
        return None

    app = create_app(_settings(), health_checks={"db": ok, "qdrant": ok}, runtime=no_runtime,  # type: ignore[arg-type]
                     kb_probe=counting_probe)  # fmt: skip
    now = [1000.0]
    app.state.kb_monotonic = lambda: now[0]
    with TestClient(app) as client:
        client.get("/api/health")
        client.get("/api/health")
        assert calls == 1  # lần thứ 2 trong 10 s → dùng cache
        now[0] += 10.0
        client.get("/api/health")
        assert calls == 2  # qua 10 s → gọi lại
