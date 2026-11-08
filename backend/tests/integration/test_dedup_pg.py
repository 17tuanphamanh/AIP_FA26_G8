"""M1 — `SqlTicketStore.open_candidates` trên Postgres 16 thật (testcontainers): truy vấn mà B3 dùng để báo trùng yêu cầu.

`tickets.intent` chỉ được ghi ở B20 → ticket CÒN MỞ có `intent` NULL; intent lấy từ dòng audit B3 `intent_classified` MỚI NHẤT. Kiểm:
chỉ ticket của đúng người gửi, chỉ ticket lá còn mở (`final_state IS NULL`), từ `since` (gồm mốc), `intent` đúng dòng audit B3,
ticket chưa có dòng B3 → `intent` None; chạy được bằng role `app_rw`. Quyết định cuối ở
`domain.dedup.pick_duplicate` (unit: `test_dedup_domain.py`); ở đây nối cả hai trên dữ liệu thật.
Chỉ chạy ở verify/CI (testcontainers) — KHÔNG nằm trong `uv run pytest backend/tests/unit`.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.db.tickets import SqlTicketStore
from app.domain.dedup import pick_duplicate
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import REQUESTER, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database

NOW = datetime(2026, 11, 8, 3, 0, tzinfo=UTC)
SINCE = NOW - timedelta(hours=24)
OTHER = "nv-khac"

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO users (user_id, username, role) VALUES (:u, :u, 'employee') ON CONFLICT DO NOTHING"),
                           {"u": OTHER})  # fmt: skip
    yield engine
    await engine.dispose()


async def put(rw: AsyncEngine, tid: str, *, requester: str = REQUESTER, age_h: float = 1.0, final: str | None = None,
              is_parent: bool = False, parent: str | None = None, intents: tuple[str, ...] = ("vpn",)) -> None:  # fmt: skip
    """Một ticket + (các) dòng audit B3 `intent_classified` theo thứ tự `intents` (dòng cuối = mới nhất)."""
    async with rw.begin() as conn:
        await conn.execute(
            text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, created_at, final_state, "
                 "is_parent, parent_ticket_id) VALUES (:t, :u, 'employee', 'yêu cầu thử', :c, :f, :p, :pp)"),
            {"t": tid, "u": requester, "c": NOW - timedelta(hours=age_h), "f": final, "p": is_parent, "pp": parent},
        )  # fmt: skip
        for intent in intents:
            await conn.execute(
                text("INSERT INTO audit_logs (ticket_id, step, event, intent) VALUES (:t, 'B3', 'intent_classified', :i)"),
                {"t": tid, "i": intent},
            )


async def test_returns_only_requesters_open_leaf_tickets_since_cutoff_with_audit_intent(rw: AsyncEngine) -> None:
    store = SqlTicketStore(rw)
    await put(rw, "d-open")  # khớp
    await put(rw, "d-edge", age_h=24)  # đúng mốc → gồm
    await put(rw, "d-old", age_h=24.5)  # ngoài cửa sổ
    await put(rw, "d-closed", final="S_RESOLVED")  # đã qua B20
    await put(rw, "d-parent", is_parent=True)  # cha
    await put(rw, "d-other", requester=OTHER)  # người khác
    got = {c.ticket_id: c for c in await store.open_candidates(REQUESTER, since=SINCE)}
    assert set(got) == {"d-open", "d-edge"}
    assert got["d-open"].intent == "vpn" and got["d-open"].final_state is None and got["d-open"].created_at.tzinfo is not None
    assert got["d-open"].requester_id == REQUESTER and got["d-open"].is_parent is False


async def test_intent_is_the_latest_b3_audit_row(rw: AsyncEngine) -> None:
    store = SqlTicketStore(rw)
    await put(rw, "d-two", intents=("account", "vpn"))
    [c] = [c for c in await store.open_candidates(REQUESTER, since=SINCE) if c.ticket_id == "d-two"]
    assert c.intent == "vpn"


async def test_ticket_without_b3_row_has_no_intent(rw: AsyncEngine) -> None:
    store = SqlTicketStore(rw)
    await put(rw, "d-nob3", intents=())
    async with rw.begin() as conn:  # dòng audit khác B3 không được tính là intent
        await conn.execute(text("INSERT INTO audit_logs (ticket_id, step, event, intent) VALUES ('d-nob3', 'B6', 'diagnosed', 'vpn')"))
    [c] = [c for c in await store.open_candidates(REQUESTER, since=SINCE) if c.ticket_id == "d-nob3"]
    assert c.intent is None


async def test_end_to_end_with_pick_duplicate_and_child_exclusion(rw: AsyncEngine) -> None:
    store = SqlTicketStore(rw)
    await put(rw, "e-old", age_h=5)
    await put(rw, "e-new", age_h=2)
    cands = await store.open_candidates(REQUESTER, since=SINCE)

    def pick(*, ticket_id: str = "me", parent: str | None = None, intent: str = "vpn") -> str | None:
        return pick_duplicate(cands, ticket_id=ticket_id, parent_ticket_id=parent, requester_id=REQUESTER, intent=intent, since=SINCE)

    assert pick() == "e-new"
    assert pick(intent="account") is None
    assert pick(ticket_id="e-new") == "e-old"  # không báo chính nó
    assert pick(ticket_id="me-1", parent="e-new") == "e-old"  # không báo cha
