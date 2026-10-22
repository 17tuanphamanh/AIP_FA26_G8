"""I1 — `GET /api/admin/llm-status` trên Postgres 16 thật: SQL của `monitor.queries.llm_usage` + route qua `app_monitor`.

Dữ liệu tự dựng (`monitor_seed`): ticket A có 3 lời gọi (1,5 + 0,25 USD, một cache hit chi phí 0), ticket B 1 lời gọi (2 USD,
cũ hơn 24 giờ), ticket C 1 lời gọi `cost_usd` NULL (= 0) → tổng 3,75 USD, 5 lời gọi, 3 ticket, 4 lời gọi trong 24 giờ.
Mỗi bài có database riêng (chưa có dữ liệu → số 0 chắc chắn). Role `app_monitor` không ghi được `llm_calls`.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.main import create_app
from app.monitor.db import read_snapshot
from app.monitor.queries.llm_usage import LlmUsage, llm_usage
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.auth import FakeIdentityProvider, InMemoryAuthStore, RecordingSink
from tests.fakes.identity import MemoryAlerts
from tests.fakes.runtime import no_runtime
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.integration.test_alerts_api_pg import Http
from tests.unit.auth_helpers import BASE_URL, auth_settings

pytestmark = pytest.mark.asyncio

NOW = datetime(2030, 6, 1, 12, tzinfo=UTC)
SINCE = NOW - timedelta(hours=24)
URL = "/api/admin/llm-status"
MANAGER = "quan.tm"


@pytest.fixture
def empty_db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def seeded_db(empty_db: PgUrls) -> PgUrls:
    engine = create_async_engine(empty_db.role("app_rw"))
    async with engine.begin() as conn:
        a = await seed.leaf_ticket(conn, created_at=NOW - timedelta(hours=3))
        b = await seed.leaf_ticket(conn, created_at=NOW - timedelta(hours=30))
        c = await seed.leaf_ticket(conn, created_at=NOW - timedelta(hours=2))
        await seed.llm_call_for(conn, a, created_at=NOW - timedelta(hours=3), cost_usd=1.5)
        await seed.llm_call_for(conn, a, created_at=NOW - timedelta(hours=2), cost_usd=0.25)
        await seed.llm_call_for(conn, a, created_at=NOW - timedelta(hours=1), cost_usd=0.0, cache_hit=True)
        await seed.llm_call_for(conn, b, created_at=NOW - timedelta(hours=25), cost_usd=2.0)
        await seed.llm_call_for(conn, c, created_at=NOW - timedelta(hours=1), cost_usd=None)
    await engine.dispose()
    return empty_db


@asynccontextmanager
async def _monitor(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_monitor"))
    try:
        yield engine
    finally:
        await engine.dispose()


async def _usage(db: PgUrls, since: datetime = SINCE) -> LlmUsage:
    async with _monitor(db) as mon, read_snapshot(SimpleNamespace(monitor=mon)) as conn:  # type: ignore[arg-type]
        return await llm_usage(conn, since)


async def test_empty_tables_give_zeros(empty_db: PgUrls) -> None:
    assert await _usage(empty_db) == LlmUsage(spent_usd=0.0, calls_total=0, calls_since=0, tickets=0)


async def test_totals_window_and_tickets(seeded_db: PgUrls) -> None:
    got = await _usage(seeded_db)
    assert got.spent_usd == pytest.approx(3.75)
    assert (got.calls_total, got.calls_since, got.tickets) == (5, 4, 3)


async def test_window_edge_is_inclusive(seeded_db: PgUrls) -> None:
    """`created_at >= since`: since đúng bằng mốc một lời gọi thì lời gọi đó được đếm; muộn hơn 1 µs thì không."""
    edge = NOW - timedelta(hours=3)
    assert (await _usage(seeded_db, edge)).calls_since == 4
    assert (await _usage(seeded_db, edge + timedelta(microseconds=1))).calls_since == 3


async def test_spent_matches_gateway_spend_total(seeded_db: PgUrls) -> None:
    """Cùng nguồn trần chi: `SqlLlmStore.spend_total()` (SUM toàn bảng) = `spent_usd` của trang."""
    from app.llm.store import SqlLlmStore

    async with _monitor(seeded_db) as mon:
        assert await SqlLlmStore(mon).spend_total() == pytest.approx((await _usage(seeded_db)).spent_usd)


async def test_monitor_role_cannot_write_llm_calls(seeded_db: PgUrls) -> None:
    async with _monitor(seeded_db) as mon, read_snapshot(SimpleNamespace(monitor=mon)) as conn:  # type: ignore[arg-type]
        with pytest.raises(DBAPIError):
            await conn.execute(text("UPDATE llm_calls SET cost_usd = 0"))


@asynccontextmanager
async def _http(db: PgUrls, *, monitor: bool = True) -> AsyncIterator[tuple[Http, Any]]:
    clock = FakeClock(NOW)
    settings = auth_settings(
        database_url=db.role("app_rw"), monitor_database_url=db.role("app_monitor") if monitor else None,
        llm_backend="scripted",
    )  # fmt: skip
    sink = RecordingSink(clock)
    store = InMemoryAuthStore(sink)
    app = create_app(
        settings, health_checks={}, idp=FakeIdentityProvider(), store=store, sink=sink, alerts=MemoryAlerts(),
        clock=clock, runtime=no_runtime,
    )  # fmt: skip

    async def kb() -> str | None:
        return "kb_v12"

    app.state.kb_probe = kb
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 50000))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        yield Http(client, clock, store, sink, settings), app


async def test_http_numbers_from_real_sql(seeded_db: PgUrls) -> None:
    async with _http(seeded_db) as (env, _app):
        token = await env.token(MANAGER)
        r = await env.client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["as_of"] == "2030-06-01T12:00:00Z"
    assert body["usage"] == {
        "calls_total": 5, "calls_24h": 4, "tickets_with_calls": 3, "avg_cost_per_ticket_usd": pytest.approx(1.25),
    }  # fmt: skip
    assert body["spend"]["total_usd"] == pytest.approx(3.75)
    assert body["spend"]["percent"] == pytest.approx(3.75 / body["spend"]["cap_usd"] * 100)
    assert body["spend"]["status"] == "ok"
    assert body["kb"] == {"alias": "kb_current", "collection": "kb_v12", "status": "ready"}


async def test_http_empty_db_has_null_average(empty_db: PgUrls) -> None:
    async with _http(empty_db) as (env, _app):
        token = await env.token(MANAGER)
        r = await env.client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["usage"] == {
        "calls_total": 0, "calls_24h": 0, "tickets_with_calls": 0, "avg_cost_per_ticket_usd": None,
    }  # fmt: skip
    assert r.json()["spend"]["percent"] == 0.0


async def test_http_without_monitor_dsn_503(seeded_db: PgUrls) -> None:
    async with _http(seeded_db, monitor=False) as (env, _app):
        token = await env.token(MANAGER)
        r = await env.client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert (r.status_code, r.json()) == (503, {"detail": "monitor_unavailable"})
