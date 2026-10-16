"""M9-B3 cụm 4 — job tuần `monitor_rules_weekly` (luật 8 `drift`) trên Postgres 16 thật: job dựng bằng
`setup_monitor_jobs` (writer = `AlertWriter(engines.main)` thật, app_rw), đọc bằng role `app_monitor`. Scheduler không
start: test tự gọi `jobs["weekly"].run()` và chỉnh đồng hồ.

Cô lập: module riêng = DB riêng. Luật 8 đếm TOÀN HỆ THỐNG → mỗi ca một `rs.weekly_now(k)` (02:00 thứ Hai giờ VN, cách
nhau 8 tuần) → `W = rs.week_mark(k) = now − 2 giờ`. Ký hiệu tuần `B(a) = [W + 7a ngày, W + 7(a + 1) ngày)`; mỗi ca đọc
trong `[W − 21 ngày, W + 14 ngày)` = 35 ngày < 56 ngày giữa hai slot. Mốc `m` so tuần đo `[m − 7, m)` với tuần mốc
`[m − 14, m − 7)`; mỗi lượt đánh giá 2 mốc `week_start(now) − 7 ngày` và `week_start(now)` (Q-M9-B3-7). `override_count`
đã ready → job tuần không có dòng "luật bỏ qua"; mọi lượt kiểm NGUYÊN danh sách dòng bắt đầu bằng tên job.

Cặp lệch (`pair`): `B(−2)` = 1 E3 + 4 E5 + 5 không mã, `B(−1)` = 5 E3 + 5 không mã; mọi lá intent vpn, đã kết thúc,
không audit. Mốc W: e3 [0,1; 0,9] → [0,5; 0,5] = PSI_HALF (báo); escalation 5/10 → 5/10 (E5 bù cho E3) = 0; intent,
override giống nhau = 0; confidence/top_score 0 mẫu → None. Mốc W − 7: tuần mốc `B(−3)` trống → mọi phân bố None.

Số kỳ vọng tính tay (không gọi hàm đang test):
- PSI_HALF = 0,4·ln 5 + 0,4·ln(9/5) = 0,6437751650 + 0,2351146660 = 0,8788898309. PSI đối xứng theo hai phía nên
  [0,5; 0,5] → [0,1; 0,9] cũng ra PSI_HALF.
- PSI_OVERRIDE (0/10 → 5/10, ε = 1e-4) = 0,4999·ln(0,5 / 1e-4) + 0,5·ln 2 = 4,2577448764 + 0,3465735903 = 4,6043184667.

Nguồn: thẻ B3 (chia việc :341 "job tuần (thứ Hai 02:00 giờ VN)"); chốt #15 comment 6127685951 đồng ý mặc định ở comment
6110081162 — Q-M9-B3-7 ("mỗi lượt đánh giá 2 mốc … để tuần bị lỡ vẫn được đánh giá"), Q-M9-B3-10 ("chạy bù lúc khởi
động, giống job ngày").
"""

import logging
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.db.session import Engines
from app.settings import Settings
from app.worker import MonitorRulesJob, setup_monitor_jobs
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_rules_seed as rs
from tests.integration.pg import PgUrls, alembic_config, fresh_database

REPO = Path(__file__).resolve().parents[3]
H = timedelta(hours=1)
DAY = timedelta(days=1)
WEEK = timedelta(days=7)
TOL = 1e-6
PSI_HALF = 0.8788898309
PSI_OVERRIDE = 4.6043184667
JOB = "monitor_rules_weekly"


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


def weekly_job(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock, tmp_path: Path) -> MonitorRulesJob:
    """Job tuần do `setup_monitor_jobs` dựng — mỗi lần gọi là một instance mới (như worker vừa khởi động)."""
    jobs = setup_monitor_jobs(AsyncIOScheduler(timezone="UTC"),
                              Settings(worker_heartbeat_path=tmp_path / "hb", config_dir=REPO / "config"),
                              Engines(main=rw, lock=rw, monitor=mon), clock)  # fmt: skip
    assert jobs is not None
    return jobs["weekly"]


def lines(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    """Mọi dòng của job tuần bắt đầu bằng `monitor_rules_weekly:` (dòng tổng, dòng "luật bỏ qua"), theo thứ tự."""
    return [(r.levelno, r.getMessage()) for r in caplog.records
            if r.name == "app.worker" and r.getMessage().startswith(f"{JOB}:")]  # fmt: skip


def summary(n: int, written: int, duplicate: int) -> str:
    return f"{JOB}: nháp={n} ghi={written} trùng={duplicate} lỗi=0 luật_lỗi=0"


async def week(
    conn: AsyncConnection, start: datetime, *, e3: int = 0, e5: int = 0, plain: int = 0, override: bool = False
) -> None:  # fmt: skip
    """Một tuần bắt đầu ở `start`: `e3` lá E3, `e5` lá E5, `plain` lá không mã (`override` → mỗi lá không mã có ghi đè);
    mọi lá intent vpn, đã kết thúc."""
    if e3:
        await rs.drift_leaves(conn, e3, created_at=start + H, intent="vpn", exit_code="E3")
    if e5:
        await rs.drift_leaves(conn, e5, created_at=start + 2 * H, intent="vpn", exit_code="E5")
    if plain:
        await rs.drift_leaves(conn, plain, created_at=start + 3 * H, intent="vpn", override=override)


async def pair(conn: AsyncConnection, w: datetime, *, override: bool = False) -> None:
    """Cặp lệch của docstring module: `B(−2)` 1 E3 + 4 E5 + 5 không mã → `B(−1)` 5 E3 + 5 không mã (`override` → 5 lá
    không mã của `B(−1)` có ghi đè)."""
    await week(conn, w - 2 * WEEK, e3=1, e5=4, plain=5)
    await week(conn, w - WEEK, e3=5, plain=5, override=override)


async def drift_rows(rw: AsyncEngine, frm: datetime, to: datetime) -> list[tuple[str, datetime, float]]:
    """Dòng `alerts` luật 8 có `window_start ∈ [frm, to]` (chỉ slot của chính test), theo thứ tự ghi."""
    async with rw.connect() as conn:
        result = await conn.execute(text(
            "SELECT subject, window_start, value FROM alerts WHERE rule_id = 'drift' "
            "AND window_start BETWEEN :f AND :t ORDER BY alert_id"
        ), {"f": frm, "t": to})  # fmt: skip
        return [(r.subject, r.window_start, r.value) for r in result]


def psi_ok(got: list[tuple[str, datetime, float]], expected: list[tuple[str, datetime, float]]) -> bool:
    return [(s, w) for s, w, _ in got] == [(s, w) for s, w, _ in expected] and all(
        abs(g - e) <= TOL for (_, _, g), (_, _, e) in zip(got, expected, strict=True)
    )


@pytest.mark.asyncio
async def test_weekly_two_runs_written_then_duplicate(
    rw: AsyncEngine, mon: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """P1. Cặp lệch + override 0/10 → 5/10 ở `B(−1)` → N = 2 (`e3_rate`, `override` ở mốc W). Lượt 02:00 thứ Hai VN
    `ghi=2 trùng=0` (INFO); lượt 03:00 cùng instance `ghi=0 trùng=2` (DEBUG), không thêm dòng (khoá mốc W)."""
    now, w = rs.weekly_now(0), rs.week_mark(0)
    async with rw.begin() as conn:
        await pair(conn, w, override=True)
    clock = FakeClock(now)
    job = weekly_job(rw, mon, clock, tmp_path)
    expected = [("e3_rate", w, PSI_HALF), ("override", w, PSI_OVERRIDE)]
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        await job.run()
        assert psi_ok(await drift_rows(rw, w - 3 * WEEK, w + 2 * WEEK), expected)
        clock.advance(H)
        await job.run()
    assert lines(caplog) == [(logging.INFO, summary(2, 2, 0)), (logging.DEBUG, summary(2, 0, 2))]
    assert psi_ok(await drift_rows(rw, w - 3 * WEEK, w + 2 * WEEK), expected)


@pytest.mark.asyncio
async def test_weekly_worker_down_one_mark_catchup(
    rw: AsyncEngine, mon: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """P2. Worker chạy lúc T1 = 02:00 thứ Hai (mốc W − 7, W) → cặp lệch `nháp=1 ghi=1`. Trong lúc worker chết thêm
    `B(0)` = 1 E3 + 4 E5 + 5 không mã; worker lỡ lượt 02:00 thứ Hai ngày W + 7, khởi động lại (instance mới) thứ Tư
    T2 = T1 + 9 ngày → chạy bù mốc W, W + 7. Mốc W: dữ liệu không đổi → trùng. Mốc W + 7 bị lỡ: `B(0)` so `B(−1)` — e3
    0,5 → 0,1 = PSI_HALF, escalation 5/10 → 5/10 = 0 → ghi mới. T2 `nháp=2 ghi=1 trùng=1`; mỗi mốc đúng một dòng."""
    now, w = rs.weekly_now(1), rs.week_mark(1)
    async with rw.begin() as conn:
        await pair(conn, w)
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        await weekly_job(rw, mon, FakeClock(now), tmp_path).run()
        assert psi_ok(await drift_rows(rw, w - 3 * WEEK, w + 2 * WEEK), [("e3_rate", w, PSI_HALF)])
        async with rw.begin() as conn:
            await week(conn, w, e3=1, e5=4, plain=5)
        await weekly_job(rw, mon, FakeClock(now + WEEK + 2 * DAY), tmp_path).run()  # worker vừa khởi động lại
    assert lines(caplog) == [(logging.INFO, summary(1, 1, 0)), (logging.INFO, summary(2, 1, 1))]
    assert psi_ok(await drift_rows(rw, w - 3 * WEEK, w + 2 * WEEK),
                  [("e3_rate", w, PSI_HALF), ("e3_rate", w + WEEK, PSI_HALF)])  # fmt: skip


@pytest.mark.asyncio
async def test_weekly_worker_down_two_marks_previous_mark(
    rw: AsyncEngine, mon: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """P3 (Q-M9-B3-7 ở tầng job). T1 như P2 → `ghi=1` ở W. Thêm `B(0)` như P2 và `B(1)` y hệt `B(0)`; worker chết qua
    HAI mốc W + 7 và W + 14, khởi động lại 07:00 thứ Hai T3 = T1 + 14 ngày + 5 giờ → mốc W + 7, W + 14. Mốc W + 7 bị lỡ
    được đánh giá nhờ mốc trước → ghi; mốc W + 14: `B(1)` giống hệt `B(0)` → PSI 0 (có dữ liệu thật, không phải trống)
    → không báo; mốc W ngoài 2 mốc → không nháp lại. T3 `nháp=1 ghi=1 trùng=0` (1, không phải 2)."""
    now, w = rs.weekly_now(2), rs.week_mark(2)
    async with rw.begin() as conn:
        await pair(conn, w)
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        await weekly_job(rw, mon, FakeClock(now), tmp_path).run()
        async with rw.begin() as conn:
            await week(conn, w, e3=1, e5=4, plain=5)
            await week(conn, w + WEEK, e3=1, e5=4, plain=5)
        await weekly_job(rw, mon, FakeClock(now + 2 * WEEK + 5 * H), tmp_path).run()  # worker vừa khởi động lại
    assert lines(caplog) == [(logging.INFO, summary(1, 1, 0)), (logging.INFO, summary(1, 1, 0))]
    assert psi_ok(await drift_rows(rw, w - 3 * WEEK, w + 2 * WEEK),
                  [("e3_rate", w, PSI_HALF), ("e3_rate", w + WEEK, PSI_HALF)])  # fmt: skip
