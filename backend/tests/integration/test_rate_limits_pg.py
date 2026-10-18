"""Gói 2b — chống spam (D-54 a) trên Postgres 16 thật: `SqlRateGate` (bộ A trên `tickets`, bộ B trên `rate_hits`) và app dựng
lại trên cùng DB. Viết TỪ ĐẶC TẢ trước code (không mở `db/rate_limits.py`, `0010`): `claude/dac-ta-bat-2-model.md` 4.8 + 8 (gói 2b
— "bảng `rate_hits` (test Postgres)"), PLAN-2B1 mục 3.2–3.3 và ca P1–P7.

Database RIÊNG cho cả module (`fresh_database` + `alembic upgrade head`): test ghi `rate_limited` vào `security_events` (append-only,
downgrade 0010 dừng khi có dòng — 4.8). Mỗi test dùng người gửi riêng (`_user`) nên không lẫn số đếm/sự kiện của nhau.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.db.rate_limits import RateLimits, SqlRateGate
from app.main import create_app
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.auth import EPOCH, FakeIdentityProvider, seed_ad_users
from tests.fakes.desk import MaskingGuard, ad_directory
from tests.integration.graph_pg import pg_runtime_factory
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.unit.auth_helpers import BASE_URL, auth_settings

pytestmark = pytest.mark.asyncio

T0 = datetime(2031, 5, 1, 9, 0, tzinfo=UTC)
MESSAGES = "/api/tickets/{ticket_id}/messages"
TICKETS = "/api/tickets"
BIG = 100000


def secs(n: float) -> timedelta:
    return timedelta(seconds=n)


def limits(*, ticket_10min: int = BIG, ticket_hour: int = BIG, message_10min: int = BIG) -> RateLimits:
    return RateLimits(ticket_10min=ticket_10min, ticket_hour=ticket_hour, message_10min=message_10min)


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


async def _user(rw: AsyncEngine) -> str:
    """Dòng `users` mới (FK của `rate_hits.user_id`, `tickets.requester_id`, `security_events.user_id`)."""
    uid = f"rl-{uuid4().hex[:10]}"
    async with rw.begin() as conn:
        await conn.execute(text("INSERT INTO users (user_id, username, role) VALUES (:u, :n, 'employee')"),
                           {"u": uid, "n": f"{uid}.name"})  # fmt: skip
    return uid


async def _hits(rw: AsyncEngine, user_id: str) -> list[datetime]:
    async with rw.connect() as conn:
        rows = await conn.execute(
            text("SELECT created_at FROM rate_hits WHERE user_id = :u ORDER BY created_at, hit_id"), {"u": user_id}
        )
        return [r[0] for r in rows]


async def _insert_hits(rw: AsyncEngine, user_id: str, times: list[datetime]) -> None:
    """Dòng `rate_hits` dựng tay — mô phỏng dòng cũ / dòng lọt quá ngưỡng do hai request song song (4.8)."""
    async with rw.begin() as conn:
        for t in times:
            await conn.execute(text("INSERT INTO rate_hits (user_id, created_at) VALUES (:u, :t)"), {"u": user_id, "t": t})


async def _ticket(
    rw: AsyncEngine, user_id: str, created_at: datetime, *, parent: str | None = None, is_parent: bool = False
) -> str:
    tid = f"tk-{uuid4().hex[:10]}"
    async with rw.begin() as conn:
        await conn.execute(text(
            "INSERT INTO tickets (ticket_id, parent_ticket_id, requester_id, requester_role, redacted_request, created_at, "
            "is_parent) VALUES (:t, :p, :u, 'employee', 'x', :c, :ip)"
        ), {"t": tid, "p": parent, "u": user_id, "c": created_at, "ip": is_parent})  # fmt: skip
    return tid


async def _events(rw: AsyncEngine, user_id: str) -> list[Any]:
    async with rw.connect() as conn:
        rows = await conn.execute(text(
            "SELECT user_id, route, ticket_id, detail, occurred_at FROM security_events "
            "WHERE event_type = 'rate_limited' AND user_id = :u ORDER BY event_id"
        ), {"u": user_id})  # fmt: skip
        return list(rows.all())


# ---- P1: request bị 429 không ghi dòng -----------------------------------------------------------------------------------------


async def test_p1_messages_until_limit_then_429_writes_no_row(rw: AsyncEngine) -> None:
    """P1 (4.8 "đủ ngưỡng thì 429, không INSERT"; 8 "request bị 429 không ghi dòng"): ngưỡng 3 → 3 lần cho qua (3 dòng, giờ = `now`
    truyền vào — Clock của app), lần 4, 5 → số giây `Retry-After`, `count(rate_hits)` vẫn 3. Bắt mutation 20 và 11."""
    gate = SqlRateGate(rw, limits(message_10min=3))
    u = await _user(rw)
    for i in range(3):
        assert await gate.messages(u, T0 + secs(i), MESSAGES) is None
    assert await _hits(rw, u) == [T0, T0 + secs(1), T0 + secs(2)]
    for i in (3, 4):
        retry = await gate.messages(u, T0 + secs(i), MESSAGES)
        assert isinstance(retry, int) and retry >= 1
    assert len(await _hits(rw, u)) == 3


# ---- P2: dọn dòng cũ của chính người gửi ----------------------------------------------------------------------------------------


async def test_p2_cleanup_only_own_rows_older_than_10min(rw: AsyncEngine) -> None:
    """P2 (4.8 "Dọn dòng cũ ngay trong transaction đó, chỉ dòng của người đang gửi"; 8): sau 1 request, người gửi không còn dòng
    `created_at ≤ now − 10 phút` (biên đúng bằng cũng bị dọn); dòng cũ của người khác giữ nguyên. Bắt mutation 21."""
    gate = SqlRateGate(rw, limits(message_10min=30))
    u, other = await _user(rw), await _user(rw)
    old = [T0 - secs(3600), T0 - secs(601), T0 - secs(600)]
    keep = T0 - secs(599)
    await _insert_hits(rw, u, [*old, keep])
    await _insert_hits(rw, other, old)
    assert await gate.messages(u, T0, MESSAGES) is None
    assert await _hits(rw, u) == [keep, T0]
    assert await _hits(rw, other) == old


# ---- P3: dựng lại app không mất số đếm ------------------------------------------------------------------------------------------


@asynccontextmanager
async def _app(db: PgUrls, clock: FakeClock, **rates: int) -> AsyncIterator[httpx.AsyncClient]:
    """`create_app` KHÔNG truyền `rate` → lifespan dựng `SqlRateGate(engines.main, RateLimits.from_settings(settings))` (hợp đồng)."""
    url = db.role("app_rw")
    settings = auth_settings(database_url=url, fake_approver_id="l1_01", **rates)
    app = create_app(
        settings, health_checks={}, idp=FakeIdentityProvider(), clock=clock, guard=MaskingGuard(),
        runtime=pg_runtime_factory(url, clock=clock, ad=ad_directory(seed_ad_users())),
    )  # fmt: skip
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 50000))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        assert app.state.runtime_status == "up"
        yield client
        await app.state.background.drain()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    r = await client.post("/api/auth/login", json={"username": username, "password": "Demo@2026!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_p3_restart_app_keeps_message_count(db: PgUrls, rw: AsyncEngine) -> None:
    """P3 (4.8 "số đếm còn khi khởi động lại"; 8 "dựng lại app (như khởi động lại) không mất số đếm"): app 1 — 2 tin (404 vẫn đếm),
    tin 3 → 429; đóng lifespan, mở app 2 cùng DB → tin kế tiếp vẫn 429; `rate_hits` của an.nv đúng 2 dòng."""
    clock = FakeClock(EPOCH)
    async with _app(db, clock, message_rate_10min=2) as client:
        an = await _login(client, "an.nv")
        for _ in range(2):
            assert (await client.post("/api/tickets/khong-co/messages", json={"text": "x"}, headers=an)).status_code == 404
        r = await client.post("/api/tickets/khong-co/messages", json={"text": "x"}, headers=an)
        assert (r.status_code, r.json()) == (429, {"detail": "rate_limited"})
    clock.advance(secs(30))
    async with _app(db, clock, message_rate_10min=2) as client:
        an = await _login(client, "an.nv")
        r = await client.post("/api/tickets/khong-co/messages", json={"text": "x"}, headers=an)
        assert (r.status_code, r.json()) == (429, {"detail": "rate_limited"})
        assert int(r.headers["retry-after"]) == 600 - 30
    assert len(await _hits(rw, "nv001")) == 2


# ---- P4: Retry-After với giờ thật trong DB ----------------------------------------------------------------------------------------


async def test_p4_retry_after_from_db_rows(rw: AsyncEngine) -> None:
    """P4 (4.8 công thức; PLAN 3.3): 3 request qua cổng lúc T0, +100, +200 giây (ngưỡng 3), request lúc +250 → 350."""
    gate = SqlRateGate(rw, limits(message_10min=3))
    u = await _user(rw)
    for i in (0, 100, 200):
        assert await gate.messages(u, T0 + secs(i), MESSAGES) is None
    assert await gate.messages(u, T0 + secs(250), MESSAGES) == 350
    assert len(await _hits(rw, u)) == 3  # 429 không ghi (mutation 20 làm lệch cả số dòng lẫn Retry-After lần sau)
    assert await gate.messages(u, T0 + secs(260), MESSAGES) == 340


async def test_p4_retry_after_with_leaked_rows_244(rw: AsyncEngine) -> None:
    """P4 ca có dòng lọt (PLAN 3.3 ví dụ 2): 32 dòng (2 dòng lọt do song song), ngưỡng 30, ba dòng cũ nhất 09:00:01, 09:00:02,
    09:00:03.4; request 09:06:00 → request thứ (32 − 30 + 1) = 09:00:03.4 → 243,4 → 244."""
    gate = SqlRateGate(rw, limits(message_10min=30))
    u = await _user(rw)
    oldest = [T0 + secs(1), T0 + secs(2), T0 + secs(3.4)]
    rest = [T0 + secs(60 + 8 * i) for i in range(29)]  # 09:01:00 … 09:04:44 — đều trong 10 phút tính tới 09:06:00
    await _insert_hits(rw, u, [*oldest, *rest])
    assert await gate.messages(u, T0 + secs(360), MESSAGES) == 244
    assert len(await _hits(rw, u)) == 32


async def test_p4_tickets_retry_after_from_tickets_table(rw: AsyncEngine) -> None:
    """P4 bộ A (PLAN 3.3 ví dụ 1 trên bảng `tickets`): 10 ticket 09:00:00 … 09:04:30, request 09:05:00 → 300; cửa sổ giờ 10 < 30."""
    gate = SqlRateGate(rw, limits(ticket_10min=10, ticket_hour=30))
    u = await _user(rw)
    for i in range(10):
        await _ticket(rw, u, T0 + secs(30 * i))
    assert await gate.tickets(u, T0 + secs(300), TICKETS) == 300


# ---- P5: bộ A trên tickets thật ------------------------------------------------------------------------------------------------


async def test_p5_child_tickets_not_counted_parent_counted(rw: AsyncEngine) -> None:
    """P5 (4.8 bộ A: `parent_ticket_id IS NULL`; PLAN 3.2: ticket cha `is_parent = true` có tính): cha + 3 con → đếm 1 (< 2) → cho qua;
    thêm 1 ticket thường → đếm 2 → vượt, `Retry-After` theo ticket CHA (T0 − 60 + 600 − T0 = 540). Bắt mutation 12."""
    gate = SqlRateGate(rw, limits(ticket_10min=2))
    u = await _user(rw)
    parent = await _ticket(rw, u, T0 - secs(60), is_parent=True)
    for _ in range(3):
        await _ticket(rw, u, T0 - secs(50), parent=parent)
    assert await gate.tickets(u, T0, TICKETS) is None
    await _ticket(rw, u, T0 - secs(30))
    assert await gate.tickets(u, T0, TICKETS) == 540


async def test_p5_window_boundary_strict_and_other_user(rw: AsyncEngine) -> None:
    """P5 biên: ticket lúc đúng `now − 10 phút` nằm NGOÀI cửa sổ (chặt); ticket của người khác không tính; bộ A chỉ đọc, không ghi
    `rate_hits`."""
    gate = SqlRateGate(rw, limits(ticket_10min=1))
    u, other = await _user(rw), await _user(rw)
    await _ticket(rw, u, T0 - secs(600))
    await _ticket(rw, other, T0 - secs(10))
    assert await gate.tickets(u, T0, TICKETS) is None
    assert await _hits(rw, u) == []
    await _ticket(rw, u, T0 - secs(599))
    assert await gate.tickets(u, T0, TICKETS) == 1


# ---- P6: rate_limited một lần mỗi đợt ---------------------------------------------------------------------------------------------


async def test_p6_messages_one_event_per_burst_columns(rw: AsyncEngine) -> None:
    """P6 (4.8 "Sự kiện"; Q-2B1-4): ngưỡng 1 → lần 2, 3, 4 bị 429 → đúng 1 dòng `rate_limited` (cột `user_id`, `route` mẫu, `detail` 3
    khoá, `ticket_id IS NULL`, `occurred_at` = giờ của lần 429 đầu); sau một độ dài cửa sổ vượt lại → dòng thứ 2. Bắt mutation 14."""
    gate = SqlRateGate(rw, limits(message_10min=1))
    u = await _user(rw)
    assert await gate.messages(u, T0, MESSAGES) is None
    for i in (1, 2, 3):
        assert await gate.messages(u, T0 + secs(i), MESSAGES) is not None
    [event] = await _events(rw, u)
    assert (event.user_id, event.route, event.ticket_id) == (u, MESSAGES, None)
    assert event.detail == {"counter": "messages", "window": "10m", "limit": 1}
    assert event.occurred_at == T0 + secs(1)
    assert await gate.messages(u, T0 + secs(600), MESSAGES) is None  # dòng T0 ra khỏi cửa sổ (chặt)
    assert await gate.messages(u, T0 + secs(601), MESSAGES) is not None  # sự kiện T0+1 không còn > since → đợt mới
    assert [e.occurred_at for e in await _events(rw, u)] == [T0 + secs(1), T0 + secs(601)]


async def test_p6_tickets_two_windows_two_events_once(rw: AsyncEngine) -> None:
    """P6 bộ A (Q-2B1-4): hai cửa sổ cùng vượt → 2 dòng (`10m`, `1h`), lặp lại không thêm; `route` = `/api/tickets`."""
    gate = SqlRateGate(rw, limits(ticket_10min=1, ticket_hour=1))
    u = await _user(rw)
    await _ticket(rw, u, T0 - secs(10))
    for i in range(3):
        assert await gate.tickets(u, T0 + secs(i), TICKETS) is not None
    events = await _events(rw, u)
    assert sorted(e.detail["window"] for e in events) == ["10m", "1h"]
    assert all((e.route, e.ticket_id, e.detail["counter"], e.detail["limit"]) == (TICKETS, None, "tickets", 1) for e in events)
    assert all(set(e.detail) == {"counter", "window", "limit"} for e in events)


# ---- P7: quyền -----------------------------------------------------------------------------------------------------------------


async def test_p7_grants_rw_select_insert_delete_no_update_monitor_none(db: PgUrls) -> None:
    """P7 (4.8 "Quyền"): `app_rw` SELECT/INSERT/DELETE được (INSERT cần USAGE trên sequence `hit_id`), UPDATE bị từ chối;
    `app_monitor` không SELECT được `rate_hits`."""
    rw = create_engine(db.role("app_rw"))
    mon = create_engine(db.role("app_monitor"))
    uid = f"rl-{uuid4().hex[:10]}"
    try:
        with rw.begin() as conn:
            conn.execute(text("INSERT INTO users (user_id, username, role) VALUES (:u, :n, 'employee')"),
                         {"u": uid, "n": f"{uid}.name"})  # fmt: skip
            conn.execute(text("INSERT INTO rate_hits (user_id, created_at) VALUES (:u, :t)"), {"u": uid, "t": T0})
            assert conn.execute(text("SELECT count(*) FROM rate_hits WHERE user_id = :u"), {"u": uid}).scalar() == 1
            conn.execute(text("DELETE FROM rate_hits WHERE user_id = :u"), {"u": uid})
        with pytest.raises(DBAPIError, match="permission denied"), rw.begin() as conn:
            conn.execute(text("UPDATE rate_hits SET created_at = created_at WHERE user_id = :u"), {"u": uid})
        with pytest.raises(DBAPIError, match="permission denied"), mon.connect() as conn:
            conn.execute(text("SELECT count(*) FROM rate_hits"))
    finally:
        rw.dispose()
        mon.dispose()
