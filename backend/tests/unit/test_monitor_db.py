"""M9 A0 — engine chỉ-đọc fail-closed (kế hoạch M9 mục 4.1): thiếu DSN → MonitorUnavailable/503, không bao giờ
rơi về engines.main. Không cần DB: engine SQLAlchemy dựng lười, route thử chỉ đọc `url.username`."""

import secrets

import pytest
from app.db.session import Engines, create_engines
from app.main import create_app
from app.monitor.db import MonitorUnavailable, monitor_engine
from app.settings import Settings
from fastapi import Request
from fastapi.testclient import TestClient
from tests.fakes.runtime import no_runtime


def _settings(**over: object) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg, arg-type]


def _monitor_dsn(password: str = "x") -> str:
    # mật khẩu truyền vào lúc chạy — không để DSN có mật khẩu dạng literal trong repo (gitleaks)
    return f"postgresql+psycopg://app_monitor:{password}@localhost:1/servicedesk"


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = 0

    async def dispose(self) -> None:
        self.disposed += 1


@pytest.fixture(autouse=True)
def _no_monitor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONITOR_DATABASE_URL", raising=False)


def test_monitor_engine_raises_when_dsn_missing() -> None:
    main, lock = FakeEngine(), FakeEngine()
    engines = Engines(main=main, lock=lock, monitor=None)  # type: ignore[arg-type]
    with pytest.raises(MonitorUnavailable):
        monitor_engine(engines)


def test_monitor_engine_returns_monitor_not_main() -> None:
    main, lock, monitor = FakeEngine(), FakeEngine(), FakeEngine()
    engines = Engines(main=main, lock=lock, monitor=monitor)  # type: ignore[arg-type]
    got = monitor_engine(engines)
    assert got is monitor
    assert got is not main


def test_settings_monitor_dsn_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _settings().monitor_database_url is None
    monkeypatch.setenv("MONITOR_DATABASE_URL", "")  # compose/.env để trống = chưa đặt (env_ignore_empty)
    assert _settings().monitor_database_url is None


def test_settings_repr_hides_monitor_password() -> None:
    password = secrets.token_hex(8)
    settings = _settings(monitor_database_url=_monitor_dsn(password))
    assert password not in repr(settings)
    assert password not in str(settings)


@pytest.mark.asyncio
async def test_create_engines_without_dsn_has_no_monitor() -> None:
    engines = create_engines(_settings())
    try:
        assert engines.monitor is None
    finally:
        await engines.dispose()


@pytest.mark.asyncio
async def test_create_engines_monitor_uses_monitor_dsn() -> None:
    engines = create_engines(_settings(monitor_database_url=_monitor_dsn()))
    try:
        assert engines.monitor is not None
        assert engines.monitor.url.username == "app_monitor"
        assert engines.monitor is not engines.main
        assert engines.main.url.username == "app_rw"
    finally:
        await engines.dispose()


@pytest.mark.asyncio
async def test_dispose_closes_monitor() -> None:
    main, lock, monitor = FakeEngine(), FakeEngine(), FakeEngine()
    await Engines(main=main, lock=lock, monitor=monitor).dispose()  # type: ignore[arg-type]
    assert (main.disposed, lock.disposed, monitor.disposed) == (1, 1, 1)
    main2, lock2 = FakeEngine(), FakeEngine()
    await Engines(main=main2, lock=lock2, monitor=None).dispose()  # type: ignore[arg-type]
    assert (main2.disposed, lock2.disposed) == (1, 1)


def _probe_client_get(settings: Settings) -> tuple[int, object]:
    app = create_app(settings, health_checks={}, runtime=no_runtime)

    async def probe(request: Request) -> dict[str, str | None]:  # route thử — chỉ có trong test, không có ở app thật
        return {"user": monitor_engine(request.app.state.engines).url.username}

    app.add_api_route("/_m9_probe", probe)
    with TestClient(app) as client:
        resp = client.get("/_m9_probe")
    return resp.status_code, resp.json()


def test_route_returns_503_monitor_unavailable() -> None:
    assert _probe_client_get(_settings()) == (503, {"detail": "monitor_unavailable"})


def test_route_uses_monitor_engine_when_configured() -> None:
    assert _probe_client_get(_settings(monitor_database_url=_monitor_dsn())) == (200, {"user": "app_monitor"})
