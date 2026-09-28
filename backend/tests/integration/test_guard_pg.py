"""Privacy guard trên Postgres 16 thật (phase3 mục 8.3, 8.7 e6, e7; PLAN-3e M-3e-14): `create_app` với guard MẶC ĐỊNH
(regex thật, không tiêm), auth SQL, runtime SQL, graph trên node giả.

- e6: guard lỗi → 503, 0 dòng `tickets`/`turns`/`security_events`.
- e7: tạo ticket có mật khẩu → 202 kèm `notices`, đúng 1 dòng `security_events(privacy_secret_redacted)` cùng ticket;
  quét mọi bảng không thấy mật khẩu. INSERT `turns` lỗi → không còn ticket, không còn sự kiện (cùng transaction).
- Canary đầy đủ (chạy hết lượt với B2 thật, checkpoint giải mã, log, LLM): e9 ở S7.
Database riêng (dòng security_events/audit append-only).
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.db.tickets import NewTicket, SqlTicketStore
from app.guard.privacy import NOTICE_SECRET, RedactionResult
from app.main import create_app
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.auth import EPOCH, FakeIdentityProvider, seed_ad_users
from tests.fakes.desk import ad_directory
from tests.integration.graph_pg import pg_runtime_factory
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.integration.scan import scannable_columns, tables_containing
from tests.unit.auth_helpers import BASE_URL, auth_settings

pytestmark = pytest.mark.asyncio

CANARY = "Canary#" + "7781xyz"  # ghép lúc chạy (gitleaks)
PASSWORD_TEXT = f"mật khẩu của tôi là {CANARY}, reset giúp"


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    yield engine
    await engine.dispose()


class BrokenGuard:
    async def redact(self, text_: str) -> RedactionResult:
        raise RuntimeError(f"nổ trên {text_!r}")


@dataclass
class Desk:
    app: FastAPI
    client: httpx.AsyncClient

    async def token(self, username: str) -> dict[str, str]:
        r = await self.client.post("/api/auth/login", json={"username": username, "password": "Demo@2026!"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


@asynccontextmanager
async def desk(db: PgUrls, *, guard: Any = None) -> AsyncIterator[Desk]:
    url, clock = db.role("app_rw"), FakeClock(EPOCH)
    settings = auth_settings(database_url=url, fake_approver_id="l1_01")
    app = create_app(
        settings, health_checks={}, idp=FakeIdentityProvider(), clock=clock, guard=guard,
        runtime=pg_runtime_factory(url, clock=clock, ad=ad_directory(seed_ad_users())),
    )  # fmt: skip
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 50000))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        assert app.state.runtime_status == "up"
        yield Desk(app, client)
        await app.state.background.drain()


async def _count(rw: AsyncEngine, sql: str, **params: Any) -> int:
    async with rw.connect() as conn:
        return int((await conn.execute(text(sql), params)).scalar_one())


async def test_e6_guard_error_503_nothing_inserted_pg(db: PgUrls, rw: AsyncEngine) -> None:
    before = {t: await _count(rw, f"SELECT count(*) FROM {t}") for t in ("tickets", "turns", "security_events")}
    async with desk(db, guard=BrokenGuard()) as d:
        an = await d.token("an.nv")
        events = await _count(rw, "SELECT count(*) FROM security_events")  # sau login_success
        r = await d.client.post("/api/tickets", json={"text": PASSWORD_TEXT}, headers=an)
        await d.app.state.background.drain()
    assert (r.status_code, r.json()) == (503, {"error": "privacy_guard_unavailable"})
    assert await _count(rw, "SELECT count(*) FROM tickets") == before["tickets"]
    assert await _count(rw, "SELECT count(*) FROM turns") == before["turns"]
    assert await _count(rw, "SELECT count(*) FROM security_events") == events
    assert await tables_containing(rw, CANARY) == []


async def test_e7_password_notices_one_event_same_ticket_pg(db: PgUrls, rw: AsyncEngine) -> None:
    async with desk(db) as d:  # guard MẶC ĐỊNH của create_app = RegexPrivacyGuard
        await d.token("ha.lt")
        an = await d.token("an.nv")
        r = await d.client.post("/api/tickets", json={"text": PASSWORD_TEXT}, headers=an)
        await d.app.state.background.drain()
    assert r.status_code == 202 and r.json()["notices"] == [NOTICE_SECRET]
    ticket = r.json()["ticket_id"]
    async with rw.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT event_type, user_id, route, detail FROM security_events WHERE ticket_id = :t"), {"t": ticket},
        )).all()  # fmt: skip
        stored = (await conn.execute(text("SELECT redacted_request FROM tickets WHERE ticket_id = :t"),
                                     {"t": ticket})).scalar_one()  # fmt: skip
    assert [tuple(row) for row in rows] == [("privacy_secret_redacted", "nv001", "/api/tickets", {"count": 1})]
    assert stored == "mật khẩu của tôi là [BÍ_MẬT_ĐÃ_ẨN] reset giúp"
    scanned = {table for table, _, _ in await scannable_columns(rw)}
    assert len(scanned) >= 22, sorted(scanned)
    assert await tables_containing(rw, CANARY) == []


async def test_e7_event_rolls_back_with_ticket_pg(db: PgUrls, rw: AsyncEngine) -> None:
    """M-3e-14: sự kiện ghi CÙNG transaction — INSERT `turns` lỗi (trùng khoá) thì không còn ticket lẫn sự kiện."""
    store = SqlTicketStore(rw)

    def ticket(ticket_id: str) -> NewTicket:
        return NewTicket(ticket_id=ticket_id, requester_id="nv001", requester_role="employee",
                         requester_dept="it", session_id=None, redacted_request="x", created_at=EPOCH)  # fmt: skip

    async with desk(db) as d:
        await d.token("an.nv")  # dòng users cho FK security_events.user_id
    await store.create(ticket("tk-guard-a"), turn_id="turn-guard-dup")
    with pytest.raises(IntegrityError):
        await store.create(ticket("tk-guard-b"), turn_id="turn-guard-dup",
                           security_events=[("privacy_secret_redacted", {"count": 2})])  # fmt: skip
    assert await _count(rw, "SELECT count(*) FROM tickets WHERE ticket_id = 'tk-guard-b'") == 0
    assert await _count(rw, "SELECT count(*) FROM security_events WHERE ticket_id = 'tk-guard-b'") == 0
