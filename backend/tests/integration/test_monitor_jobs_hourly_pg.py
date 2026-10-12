"""M9-B2 GĐ2 cụm 3 — job giờ `monitor_rules_hourly` (luật 14 `llm_budget`) trên Postgres 16 thật: job dựng bằng
`setup_monitor_jobs` (writer = `AlertWriter(engines.main)` thật, app_rw), đọc bằng role `app_monitor`.

Cô lập: luật 14 cộng `llm_calls.cost_usd` TOÀN BẢNG → MỖI TEST MỘT DB (như `test_monitor_rules_budget_pg.py`).
Scheduler không start: test tự gọi `jobs["hourly"].run()` và chỉnh đồng hồ.

Hằng tính tay: `NOW = 2035-05-20T03:00Z` = 10:00 giờ VN 20/05 → đầu ngày VN `DAY1 = 2035-05-19T17:00Z`.
`LAST = 2035-05-20T16:59:59.999999Z` = 23:59:59.999999 VN 20/05 → vẫn `DAY1`. `NEXT = 2035-05-20T17:00Z` = 00:00 VN 21/05
→ `DAY2 = NEXT`. Ngưỡng `0,8 × 38 − 1e-9` (Q-M9-B2-7): 30,4 báo, 30,02 (79 %) không. Job giờ chỉ có luật 14 → N = 1;
không có luật đối soát (luật 3 là luật phút) nên lượt 2 `trùng = N`.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.db.session import Engines
from app.llm.config import load_llm_config
from app.settings import Settings
from app.worker import MonitorRulesJob, setup_monitor_jobs
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration import monitor_rules_seed as rs
from tests.integration.pg import PgUrls, alembic_config, fresh_database

REPO = Path(__file__).resolve().parents[3]
NOW = datetime(2035, 5, 20, 3, 0, tzinfo=UTC)
DAY1 = datetime(2035, 5, 19, 17, 0, tzinfo=UTC)
LAST = datetime(2035, 5, 20, 16, 59, 59, 999999, tzinfo=UTC)
NEXT = DAY2 = datetime(2035, 5, 20, 17, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=40)
H = timedelta(hours=1)
JOB = "monitor_rules_hourly"


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


def hourly_job(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock, tmp_path: Path) -> MonitorRulesJob:
    """Job giờ do `setup_monitor_jobs` dựng (cấu hình thật `config/llm.yaml`) — ngưỡng tính tay dựa trên 38 / 0,8."""
    spend = load_llm_config(REPO / "config" / "llm.yaml").spend
    assert (spend.cap_usd, spend.warn_ratio) == (38.0, 0.8)
    jobs = setup_monitor_jobs(AsyncIOScheduler(timezone="UTC"),
                              Settings(worker_heartbeat_path=tmp_path / "hb", config_dir=REPO / "config"),
                              Engines(main=rw, lock=rw, monitor=mon), clock)  # fmt: skip
    assert jobs is not None
    return jobs["hourly"]


async def budget_rows(rw: AsyncEngine) -> list[tuple[str, datetime, float, dict[str, Any]]]:
    async with rw.connect() as conn:
        result = await conn.execute(text(
            "SELECT subject, window_start, value, detail FROM alerts WHERE rule_id = 'llm_budget' ORDER BY alert_id"
        ))  # fmt: skip
        return [(r.subject, r.window_start, r.value, r.detail) for r in result]


def summaries(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [(r.levelno, r.getMessage()) for r in caplog.records
            if r.name == "app.worker" and r.getMessage().startswith(f"{JOB}: nháp=")]  # fmt: skip


@pytest.mark.asyncio
async def test_hourly_79_percent_no_row(
    rw: AsyncEngine, mon: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """10,0 (40 ngày trước) + 20,02 (ticket cha) = 30,02 = 79 % × 38 → job giờ chạy, 0 dòng `alerts`."""
    async with rw.begin() as conn:
        await rs.llm_cost(conn, cost_usd=10.0, at=OLD)
        await rs.llm_cost(conn, cost_usd=20.02, at=NOW - H, parent=True)
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        await hourly_job(rw, mon, FakeClock(NOW), tmp_path).run()
    assert summaries(caplog) == [(logging.INFO, f"{JOB}: nháp=0 ghi=0 trùng=0 lỗi=0 luật_lỗi=0")]
    assert await budget_rows(rw) == []


@pytest.mark.asyncio
async def test_hourly_80_percent_runs_then_next_vn_day(
    rw: AsyncEngine, mon: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """10,4 + 20,0 (ticket cha) + 1 lời gọi `cost_usd NULL` = 30,4 = đúng 80 %. Lượt 1 `ghi=1`, lượt 2 (giờ sau) `ghi=0
    trùng=1`, lượt cuối ngày VN vẫn trùng → 1 dòng; sang ngày VN kế tiếp (tổng vẫn vượt) → đúng 1 dòng mới, khoá mới."""
    async with rw.begin() as conn:
        await rs.llm_cost(conn, cost_usd=10.4, at=OLD)
        await rs.llm_cost(conn, cost_usd=20.0, at=NOW - H, parent=True)
        await rs.llm_cost(conn, cost_usd=None, at=NOW - 2 * H)
    clock = FakeClock(NOW)
    job = hourly_job(rw, mon, clock, tmp_path)
    detail = {"spent_usd": 30.4, "cap_usd": 38.0, "warn_ratio": 0.8}
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        await job.run()
        assert await budget_rows(rw) == [("", DAY1, 30.4, detail)]
        for at in (NOW + H, LAST):
            clock.set(at)
            await job.run()
        assert await budget_rows(rw) == [("", DAY1, 30.4, detail)]
        clock.set(NEXT)
        await job.run()
    assert await budget_rows(rw) == [("", DAY1, 30.4, detail), ("", DAY2, 30.4, detail)]
    new, dup = (f"{JOB}: nháp=1 ghi={g} trùng={t} lỗi=0 luật_lỗi=0" for g, t in ((1, 0), (0, 1)))
    assert summaries(caplog) == [(logging.INFO, new), (logging.DEBUG, dup), (logging.DEBUG, dup), (logging.INFO, new)]
