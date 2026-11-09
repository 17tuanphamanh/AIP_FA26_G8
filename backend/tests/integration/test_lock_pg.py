"""G1 trên Postgres 16 thật (testcontainers): khoá ticket bằng `hashtextextended(:t, 0)` (bigint).

- Khoá rồi mở ĐÚNG khoá: trong `hold` có đúng 1 khoá advisory cấp session khớp `hashtextextended(ticket, 0)` (classid = 32 bit cao,
  objid = 32 bit thấp, objsubid = 1); ra khỏi `hold` không còn khoá nào (unlock cùng khoá — nếu lệch, khoá ở lại trên kết nối đã trả pool).
- Hai ticket KHÁC nhau không chặn nhau; CÙNG ticket thì lượt thứ hai chờ `lock_timeout` rồi `TicketBusy`.
- `pg_advisory_xact_lock(hashtextextended('m5_strategy_changes', 0))` chạy được bằng role `app_rw`.
- `hashtextextended` cho bigint thật: một ticket có khoá vượt int4 (không còn bị nén vào 32 bit).
Chỉ chạy ở verify/CI (testcontainers) — KHÔNG nằm trong `uv run pytest backend/tests/unit`.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from app.graph.lock import PgTicketLock
from app.graph.ports import TicketBusy
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.pg import PgUrls

pytestmark = pytest.mark.asyncio

KEY_SQL = "SELECT hashtextextended(:t, 0)"
HELD_SQL = (
    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objsubid = 1 AND granted "
    "AND classid::bigint = ((CAST(:k AS bigint) >> 32) & 4294967295) AND objid::bigint = (CAST(:k AS bigint) & 4294967295)"
)


@pytest_asyncio.fixture
async def lock_engine(migrated: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        migrated.role("app_rw"), pool_size=4, max_overflow=0, connect_args={"options": "-c lock_timeout=500"},
    )  # fmt: skip
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def probe(migrated: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated.role("app_rw"), pool_size=2)
    yield engine
    await engine.dispose()


async def _key(probe: AsyncEngine, ticket: str) -> int:
    async with probe.connect() as conn:
        return int((await conn.execute(text(KEY_SQL), {"t": ticket})).scalar_one())


async def _held(probe: AsyncEngine, key: int) -> int:
    async with probe.connect() as conn:
        return int((await conn.execute(text(HELD_SQL), {"k": key})).scalar_one())


async def test_hold_takes_the_64_bit_key_and_unlock_releases_exactly_it(lock_engine: AsyncEngine, probe: AsyncEngine) -> None:
    lock = PgTicketLock(lock_engine)
    key = await _key(probe, "g1-ticket-a")
    assert await _held(probe, key) == 0
    async with lock.hold("g1-ticket-a"):
        assert await _held(probe, key) == 1
    assert await _held(probe, key) == 0  # kết nối đã trả pool KHÔNG còn giữ khoá (unlock đúng khoá)
    async with lock.hold("g1-ticket-a"):  # lấy lại ngay — không bị TicketBusy
        assert await _held(probe, key) == 1


async def test_unlock_runs_when_the_body_raises(lock_engine: AsyncEngine, probe: AsyncEngine) -> None:
    lock = PgTicketLock(lock_engine)
    key = await _key(probe, "g1-ticket-err")
    with pytest.raises(RuntimeError):
        async with lock.hold("g1-ticket-err"):
            raise RuntimeError("lượt lỗi")
    assert await _held(probe, key) == 0


async def test_two_different_tickets_do_not_block_each_other(lock_engine: AsyncEngine, probe: AsyncEngine) -> None:
    lock = PgTicketLock(lock_engine)
    ka, kb = await _key(probe, "g1-ticket-b"), await _key(probe, "g1-ticket-c")
    assert ka != kb
    inside = asyncio.Event()
    release = asyncio.Event()

    async def hold_b() -> None:
        async with lock.hold("g1-ticket-b"):
            inside.set()
            await release.wait()

    task = asyncio.create_task(hold_b())
    await asyncio.wait_for(inside.wait(), 5)
    try:
        async with lock.hold("g1-ticket-c"):  # ticket khác: vào ngay, không chờ lock_timeout
            assert (await _held(probe, ka), await _held(probe, kb)) == (1, 1)
    finally:
        release.set()
        await task
    assert (await _held(probe, ka), await _held(probe, kb)) == (0, 0)


async def test_same_ticket_second_turn_gets_ticket_busy(lock_engine: AsyncEngine) -> None:
    lock = PgTicketLock(lock_engine)
    async with lock.hold("g1-ticket-d"):
        with pytest.raises(TicketBusy):
            async with lock.hold("g1-ticket-d"):
                pytest.fail("không được vào khi ticket đang bị giữ")


async def test_hashtextextended_is_a_real_bigint(probe: AsyncEngine) -> None:
    """Có ticket mà khoá vượt int4 → chứng tỏ không bị nén vào 32 bit như `hashtext`."""
    keys = [await _key(probe, f"g1-wide-{i}") for i in range(32)]
    assert any(not (-(2**31) <= k < 2**31) for k in keys)


async def test_m5_strategy_xact_lock_runs_under_app_rw(probe: AsyncEngine) -> None:
    from app.db.m5_strategy import _LOCK

    async with probe.begin() as conn:
        await conn.execute(_LOCK)
