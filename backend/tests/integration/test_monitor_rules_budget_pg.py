"""M9-B2 GĐ2 cụm 2 — loader luật giờ 14 `llm_budget` (`queries/rules_data.py`) + `evaluate("hourly")` trên Postgres 16
thật, đọc bằng role `app_monitor`; cảnh báo ghi thật qua `AlertWriter.raise_once` rồi đọc lại.

Cô lập: luật 14 cộng `llm_calls.cost_usd` TOÀN BẢNG (không cửa sổ, không `v_leaf` — Q-M9-6, docstring `llm_budget`) nên
không tách được theo mốc thời gian như luật khác → MỖI TEST MỘT DB (`fresh_database` + migrate head).

Hằng tính tay: `NOW = 2035-05-20T03:00Z` = 10:00 giờ VN ngày 20/05 → `day_start` = 00:00 VN 20/05 = `2035-05-19T17:00Z`.
Ngưỡng `0,8 × 38 − 1e-9` (Q-M9-B2-7): 30,4 báo, 30,02 (79 %) không. Tổng hai số thực cộng theo thứ tự nào cũng ra cùng
giá trị (10.4 + 20.0 = 30.4; 10.0 + 20.02 = 30.02). Để cụm 3 (cần job): chạy lại cùng ngày không thêm dòng.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.audit.alerts import AlertWriter
from app.core.clock import FakeClock
from app.domain.alerts import SYSTEM_SUBJECT, AlertDraft
from app.monitor.evaluator import LOADERS, EvalResult, evaluate
from app.monitor.rules import RuleContext
from app.monitor.window import VN_TZ
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration import monitor_rules_seed as rs
from tests.integration.pg import PgUrls, alembic_config, fresh_database

NOW = datetime(2035, 5, 20, 3, 0, tzinfo=UTC)
DAY_START = datetime(2035, 5, 19, 17, 0, tzinfo=UTC)
CTX = RuleContext(now=NOW, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)
OLD = NOW - timedelta(days=40)  # ngoài mọi cửa sổ ngày/tuần — luật 14 vẫn phải cộng


@pytest.fixture
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


async def spent(mon: AsyncEngine) -> object:
    async with mon.connect() as conn:
        return await LOADERS["llm_budget"](conn, CTX)


async def run(mon: AsyncEngine) -> list[AlertDraft]:
    async with mon.connect() as conn:
        result: EvalResult = await evaluate("hourly", conn, CTX)
    assert (result.failed_rules, result.skipped_rules) == ([], [])
    return result.drafts


@pytest.mark.asyncio
async def test_budget_empty_table_zero(mon: AsyncEngine) -> None:
    """Bảng rỗng → `COALESCE` ra 0 kiểu float (không `None` → luật không vào `failed_rules`, Q-M9-B2-16), 0 draft."""
    total = await spent(mon)
    assert total == 0.0 and type(total) is float
    assert await run(mon) == []


@pytest.mark.asyncio
async def test_budget_79_percent_no_alert(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """10,0 (lời gọi 40 ngày trước) + 20,02 (lời gọi của ticket CHA) = 30,02 = 79 % × 38 → không báo; tổng đọc đủ cả hai."""
    async with rw.begin() as conn:
        await rs.llm_cost(conn, cost_usd=10.0, at=OLD)
        await rs.llm_cost(conn, cost_usd=20.02, at=NOW - timedelta(hours=1), parent=True)
    assert await spent(mon) == 30.02
    assert await run(mon) == []


@pytest.mark.asyncio
async def test_budget_80_percent_alert_written(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """10,4 (40 ngày trước) + 20,0 (ticket cha) + 1 lời gọi `cost_usd NULL` (SUM bỏ qua) = 30,4 = đúng 80 % → 1 draft,
    `window_start` = đầu ngày VN. Thêm cửa sổ ngày (mất 10,4) hoặc lọc lá (mất 20,0) → 0 draft. Giá trị là `float`
    (không `Decimal`) nên ghi được vào `alerts.value` (Float) và `alerts.detail` (JSONB, kiểu number)."""
    async with rw.begin() as conn:
        await rs.llm_cost(conn, cost_usd=10.4, at=OLD)
        await rs.llm_cost(conn, cost_usd=20.0, at=NOW - timedelta(hours=1), parent=True)
        await rs.llm_cost(conn, cost_usd=None, at=NOW - timedelta(hours=2))
    total = await spent(mon)
    assert total == 30.4 and type(total) is float
    expected = AlertDraft(
        rule_id="llm_budget", subject=SYSTEM_SUBJECT, window_start=DAY_START, severity="critical", value=30.4,
        detail={"spent_usd": 30.4, "cap_usd": 38.0, "warn_ratio": 0.8},
    )  # fmt: skip
    drafts = await run(mon)
    assert drafts == [expected]
    assert await AlertWriter(rw, FakeClock(NOW)).raise_once(drafts[0]) is True
    async with rw.connect() as conn:
        row = (await conn.execute(text(
            "SELECT subject, window_start, value, jsonb_typeof(detail->'spent_usd') AS kind, detail->>'spent_usd' AS shown, "
            "detail FROM alerts WHERE rule_id = 'llm_budget'"
        ))).one()  # fmt: skip
    assert (row.subject, row.window_start, row.value, row.kind, row.shown) == (SYSTEM_SUBJECT, DAY_START, 30.4, "number", "30.4")
    assert row.detail == {"spent_usd": 30.4, "cap_usd": 38.0, "warn_ratio": 0.8}
