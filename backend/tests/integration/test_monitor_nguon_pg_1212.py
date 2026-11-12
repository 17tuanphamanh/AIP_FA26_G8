"""B1 (12/11) trên Postgres 16 thật, đọc bằng role `app_monitor`: tab Nghiệp vụ/AI với `only_sources(("real",))` bỏ lá
`sim`/`eval`; không đặt nguồn → đủ 3 nguồn (luật cảnh báo, như trước B1). Chạy TOÀN BỘ `business_metrics`/`ai_metrics` trong
khối nguồn để mọi câu có `:sources` được Postgres nhận (ép kiểu `text[]`, không thiếu tham số).

Cửa sổ: tháng 4/2030 (DB riêng của file này). Số kỳ vọng tính tay trong chú thích.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.monitor.queries import ai, business
from app.monitor.queries.common import only_sources
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

FRM = datetime(2030, 4, 1, tzinfo=UTC)
TO = FRM + timedelta(days=1)
AT = FRM + timedelta(hours=1)


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


@pytest_asyncio.fixture
async def mon(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_monitor"))
    yield engine
    await engine.dispose()


async def _leaf(conn: AsyncConnection, source: str, **kw: object) -> str:
    tid = await seed.leaf_ticket(conn, created_at=AT, **kw)  # type: ignore[arg-type]
    if source != "real":
        await conn.execute(text("UPDATE tickets SET source = :s WHERE ticket_id = :t"), {"s": source, "t": tid})
    return tid


@pytest.mark.asyncio
async def test_that_vs_du_ba_nguon(rw: AsyncEngine, mon: AsyncEngine) -> None:
    # Thật: 2 tự xử lý + 1 E3. Sim: 3 E5. Eval: 1 E9.
    async with rw.begin() as conn:
        for _ in range(2):
            await _leaf(conn, "real", final_state="S_RESOLVED", resolution_path="auto")
        e3 = await _leaf(conn, "real", final_state="S_ESCALATED", resolution_path="escalated", exit_code="E3")
        await seed.escalation(conn, e3, exit_code="E3", created_at=AT)
        for _ in range(3):
            sim = await _leaf(conn, "sim", final_state="S_ESCALATED", resolution_path="escalated", exit_code="E5")
            await seed.escalation(conn, sim, exit_code="E5", created_at=AT)
        ev = await _leaf(conn, "eval", final_state="S_ESCALATED", resolution_path="escalated", exit_code="E9")
        await seed.escalation(conn, ev, exit_code="E9", created_at=AT)

    async with mon.connect() as conn:
        with only_sources(("real",)):
            assert await business.automation_rate(conn, FRM, TO) == pytest.approx(2 / 3)
            assert await business.escalation_rate_raw(conn, FRM, TO) == pytest.approx(1 / 3)
            assert await ai.e9_count(conn, FRM, TO) == 0
            m = await business.business_metrics(conn, FRM, TO)
            assert m.counts["automation_rate"] == business.RatioCount(num=2, den=3)
            await ai.ai_metrics(conn, FRM, TO)  # mọi câu AI chạy được với `:sources`
            assert (await business.business_metrics(conn, FRM, TO, approver_id="khong-ai")).sample == 0
        # không đặt nguồn (luật cảnh báo): 2 tự xử lý / 7 lá đã kết thúc; 5 lá có exit_code
        assert await business.automation_rate(conn, FRM, TO) == pytest.approx(2 / 7)
        assert await business.escalation_rate_raw(conn, FRM, TO) == pytest.approx(5 / 7)
        assert await ai.e9_count(conn, FRM, TO) == 1
        with only_sources(("real", "sim", "eval")):
            assert await business.automation_rate(conn, FRM, TO) == pytest.approx(2 / 7)
