"""2b-4: đường `Settings(FAKE_SCENARIO)` → `graph/wiring.open_runtime` → `NodeDeps.scenario` trên Postgres
thật (store SQL, `AsyncPostgresSaver`, khoá advisory) — cùng đường backend/worker dùng trên stack compose.
Hỏi → đóng runtime, mở runtime MỚI (khởi động lại) → trả lời → đi tiếp, không hỏi lại."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.db.session import create_engines
from app.domain.states import S_CLARIFYING, S_PENDING_APPROVAL
from app.graph.late_event import deliver_event
from app.graph.wiring import Runtime, open_runtime
from app.settings import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.identity import FakeAd, ad_user, fake_directory
from tests.integration.graph_pg import APPROVER, REQUESTER, SESSION, scalar, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


@asynccontextmanager
async def _runtime(db: PgUrls, clock: FakeClock) -> AsyncIterator[Runtime]:
    settings = Settings(
        _env_file=None, database_url=db.role("app_rw"), app_env="test",  # type: ignore[call-arg]
        fake_scenario="approval", fake_approver_id=APPROVER,
    )  # fmt: skip
    engines = create_engines(settings)
    try:
        directory = fake_directory(FakeAd(ad_user(REQUESTER)), clock)
        async with open_runtime(settings, engines, clock, can_execute=True, directory=directory) as rt:
            yield rt
    finally:
        await engines.dispose()


@pytest.mark.asyncio
async def test_tagged_clarify_survives_restart_via_settings_pg(db: PgUrls, rw: AsyncEngine) -> None:
    clock = FakeClock()
    ticket, request = f"tk-{uuid4().hex[:8]}", "[fake:clarify] máy không vào VPN"
    async with rw.begin() as conn:
        await conn.execute(text(
            "INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request) "
            "VALUES (:t, :u, 'employee', :r)"), {"t": ticket, "u": REQUESTER, "r": request})  # fmt: skip
    async with _runtime(db, clock) as rt:
        r = await rt.runner.submit(ticket, session_id=SESSION, redacted_request=request)
        assert r.status == S_CLARIFYING
    async with _runtime(db, clock) as rt:  # "khởi động lại": runtime + StackScenario mới, cùng DB
        r = await deliver_event(rt.runner, ticket, S_CLARIFYING, {"kind": "user_reply", "text": "LAP-1"})
        assert r.status == S_PENDING_APPROVAL
    asked = await scalar(rw, "SELECT count(*) FROM audit_logs WHERE ticket_id=:t AND step='B11' "
                             "AND event='asked'", t=ticket)  # fmt: skip
    assert asked == 1
    assert await scalar(rw, "SELECT count(*) FROM approvals WHERE ticket_id=:t", t=ticket) == 1
