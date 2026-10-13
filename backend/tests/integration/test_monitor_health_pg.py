"""M9 A4 — `/api/health` mục `monitor` và lớp chỉ-đọc thứ hai của engine monitor trên Postgres 16 thật.

- Q-M9-B1-6 + kiểm thử 01/10 mục 7: DSN monitor phải chạy ĐÚNG role `app_monitor`. Đặt nhầm DSN `app_rw` → health báo
  `wrong_role` + đúng MỘT dòng ERROR (không chứa DSN), mã HTTP KHÔNG đổi (chỉ báo, như `kb`).
- Lớp hai (`db/session.py`): engine monitor mở mọi giao dịch với `default_transaction_read_only=on` → kể cả khi DSN là
  `app_rw` (role CÓ quyền ghi), INSERT qua engine monitor vẫn bị Postgres từ chối (SQLSTATE 25006).

DB riêng cho module (`fresh_database`) — test có ghi thử `alerts` qua engine chính để đối chứng.
"""

import logging
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from app.db.session import create_engines
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.fakes.runtime import no_runtime
from tests.integration.pg import PASSWORDS, PgUrls, alembic_config, fresh_database


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


def _settings(db: PgUrls, monitor_role: str | None) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=db.role("app_rw"),
        monitor_database_url=db.role(monitor_role) if monitor_role else None,
    )


async def _ok() -> None:
    return None


async def _kb() -> str | None:
    return None


def _health(db: PgUrls, monitor_role: str | None) -> tuple[int, dict[str, Any]]:
    """GET /api/health một lần với engine THẬT (lifespan dựng `create_engines`); 4 phụ thuộc lõi tiêm `ok` để mã
    HTTP chỉ phụ thuộc `checks` — đúng điều cần chứng minh: `monitor` không đổi mã."""
    app = create_app(_settings(db, monitor_role), health_checks={"db": _ok}, runtime=no_runtime, kb_probe=_kb)
    with TestClient(app) as client:
        r = client.get("/api/health")
    return r.status_code, r.json()


def _monitor_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Dòng ERROR về monitor. Lọc theo nội dung vì `runtime=no_runtime` khiến lifespan ghi thêm MỘT dòng ERROR khác
    của `app.main` ("không mở được runtime graph…") — không liên quan tới A4."""
    return [
        r.getMessage() for r in caplog.records
        if r.name == "app.main" and r.levelno >= logging.ERROR and "monitor" in r.getMessage()
    ]  # fmt: skip


def test_health_monitor_ok_with_app_monitor_dsn(db: PgUrls, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="app.main"):
        code, body = _health(db, "app_monitor")
    assert (code, body["monitor"]) == (200, "ok")
    assert _monitor_errors(caplog) == []


def test_health_monitor_wrong_role_with_app_rw_dsn(db: PgUrls, caplog: pytest.LogCaptureFixture) -> None:
    """DSN monitor đặt nhầm sang `app_rw` → `wrong_role`, mã vẫn 200, đúng 1 dòng ERROR về monitor, và KHÔNG dòng
    ERROR nào (của bất kỳ logger nào) lộ mật khẩu / host:port / tên DB / chuỗi DSN."""
    with caplog.at_level(logging.ERROR):
        code, body = _health(db, "app_rw")
    assert (code, body["monitor"]) == (200, "wrong_role")
    assert _monitor_errors(caplog) == ["monitor DSN sai role: app_rw — M9 phải chạy bằng app_monitor"]
    secrets = (PASSWORDS["app_rw"], "postgresql", f"{db.host}:{db.port}", db.db)
    every_error = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert [(m, s) for m in every_error for s in secrets if s in m] == []


def test_health_monitor_not_configured_without_dsn(db: PgUrls) -> None:
    code, body = _health(db, None)
    assert (code, body["monitor"]) == (200, "not_configured")


@pytest.mark.asyncio
async def test_monitor_engine_default_read_only(db: PgUrls) -> None:
    """Lớp hai: engine monitor mặc định READ ONLY; engine chính (app_rw) KHÔNG bị ảnh hưởng."""
    engines = create_engines(_settings(db, "app_monitor"))
    try:
        assert engines.monitor is not None
        async with engines.monitor.connect() as conn:
            assert (await conn.execute(text("SHOW default_transaction_read_only"))).scalar() == "on"
            assert (await conn.execute(text("SELECT current_user"))).scalar() == "app_monitor"
        async with engines.main.connect() as conn:
            assert (await conn.execute(text("SHOW default_transaction_read_only"))).scalar() == "off"
    finally:
        await engines.dispose()


@pytest.mark.asyncio
async def test_monitor_engine_read_only_blocks_write_even_with_rw_dsn(db: PgUrls) -> None:
    """DSN monitor là `app_rw` (role CÓ quyền INSERT `alerts`): INSERT qua engine monitor vẫn lỗi 25006
    (read-only transaction); cùng câu qua engine chính thì được — chứng minh chặn là do lớp hai, không phải do quyền."""
    engines = create_engines(_settings(db, "app_rw"))
    insert = text(
        "INSERT INTO alerts (rule_id, subject, severity, window_start) VALUES (:r, :s, 'low', :w)"
    )
    params = {"r": "a4_read_only_probe", "w": datetime(2030, 9, 9, tzinfo=UTC)}
    try:
        assert engines.monitor is not None
        with pytest.raises(DBAPIError) as caught:
            async with engines.monitor.begin() as conn:
                assert (await conn.execute(text("SELECT current_user"))).scalar() == "app_rw"
                await conn.execute(insert, {**params, "s": "qua-monitor"})
        assert getattr(caught.value.orig, "sqlstate", None) == "25006"
        async with engines.main.begin() as conn:
            await conn.execute(insert, {**params, "s": "qua-main"})
        async with engines.main.connect() as conn:
            subjects: Sequence[Any] = (await conn.execute(
                text("SELECT subject FROM alerts WHERE rule_id = :r ORDER BY subject"), {"r": params["r"]}
            )).scalars().all()  # fmt: skip
        assert subjects == ["qua-main"]  # dòng qua engine monitor KHÔNG được ghi
    finally:
        await engines.dispose()
