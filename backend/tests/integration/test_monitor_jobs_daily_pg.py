"""M9-B2 GĐ2 cụm 3 — job ngày `monitor_rules_daily` (luật 1, 7, 12, 13) trên Postgres 16 thật: job dựng bằng
`setup_monitor_jobs` (writer = `AlertWriter(engines.main)` thật, app_rw), đọc bằng role `app_monitor`. Scheduler không
start: test tự gọi `jobs["daily"].run()` và chỉnh đồng hồ.

Cô lập: module riêng = DB riêng; mỗi ca một mốc `rs.daily_now(k)` (19:00 UTC = 02:00 giờ VN, cách nhau 30 ngày) → `d0 =
now − 2 giờ`. Luật 7 theo người quyết (`new_id`). Lá của luật 7/12/13 có `final_state` NULL → không vào mẫu số luật 1.
Module này KHÔNG vá `is_pending` → luật 12/13 luôn `skipped` (nguồn pending tới Phase 5). Mọi lượt kiểm dòng tổng
`luật_lỗi=0` và dòng "luật bỏ qua (nguồn chưa có): b2_degraded, b3_degraded" (thứ tự đăng ký trong `rules.py`).

Nguồn: thẻ B2 (chia việc :326 "ranh giới luật 1: vượt → `policy_versions` không đổi … đúng 1 dòng `alerts`"; :329 chạy
hai lượt); chốt #14 5959974287 — Q-M9-B2-4 (chạy muộn không sinh trùng), Q-M9-B2-15 ("worker nghỉ 2 mốc thì ngày ở giữa
vẫn được đánh giá, chạy lại không trùng"). Luật 3 (đối soát) là luật PHÚT → không tham gia số nào ở đây: lượt 2
`trùng = N`. Số luật 1 tính tay ở `test_monitor_rules_daily_pg.py` (ca `vuot`): weighted 0.6000000000000002, raw 0,6.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
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
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_rules_seed as rs
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

REPO = Path(__file__).resolve().parents[3]
H = timedelta(hours=1)
DAY = timedelta(days=1)
JOB = "monitor_rules_daily"
SKIPPED = f"{JOB}: luật bỏ qua (nguồn chưa có): b2_degraded, b3_degraded"
ESCALATION_DETAIL = {"weighted": 0.6000000000000002, "raw": 0.6, "threshold": 0.4, "days": 7}
REFLEX_DETAIL = {"count": 3, "ambiguous_views": 0, "threshold": 3}


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


def daily_job(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock, tmp_path: Path) -> MonitorRulesJob:
    """Job ngày do `setup_monitor_jobs` dựng — mỗi lần gọi là một instance mới (như worker vừa khởi động)."""
    spend = load_llm_config(REPO / "config" / "llm.yaml").spend
    assert (spend.cap_usd, spend.warn_ratio) == (38.0, 0.8)
    jobs = setup_monitor_jobs(AsyncIOScheduler(timezone="UTC"),
                              Settings(worker_heartbeat_path=tmp_path / "hb", config_dir=REPO / "config"),
                              Engines(main=rw, lock=rw, monitor=mon), clock)  # fmt: skip
    assert jobs is not None
    return jobs["daily"]


def lines(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    """Dòng tổng + dòng "luật bỏ qua" của job ngày, theo thứ tự."""
    return [(r.levelno, r.getMessage()) for r in caplog.records
            if r.name == "app.worker" and r.getMessage().startswith(f"{JOB}:")]  # fmt: skip


def summary(n: int, written: int, duplicate: int) -> str:
    return f"{JOB}: nháp={n} ghi={written} trùng={duplicate} lỗi=0 luật_lỗi=0"


async def rows(rw: AsyncEngine, rule_id: str, subject: str) -> list[tuple[datetime, float, dict[str, Any]]]:
    async with rw.connect() as conn:
        result = await conn.execute(text(
            "SELECT window_start, value, detail FROM alerts WHERE rule_id = :r AND subject = :s ORDER BY alert_id"
        ), {"r": rule_id, "s": subject})  # fmt: skip
        return [(r.window_start, r.value, r.detail) for r in result]


async def escalation_rows(rw: AsyncEngine, d0: datetime) -> list[tuple[float, dict[str, Any]]]:
    """Luật 1 (subject `""` chung mọi slot) — chỉ dòng của mốc `d0` của chính test."""
    async with rw.connect() as conn:
        result = await conn.execute(text(
            "SELECT value, detail FROM alerts WHERE rule_id = 'escalation_rate_high' AND subject = '' "
            "AND window_start = :w ORDER BY alert_id"
        ), {"w": d0})  # fmt: skip
        return [(r.value, r.detail) for r in result]


async def escalation_over(conn: AsyncConnection, d0: datetime) -> None:
    """Luật 1 vượt (ca `vuot` của cụm 2): R(2 lá, 1 escalate) A(1, 1) S(2, 1) tạo `d0 − 3 ngày` → weighted 0.600…02."""
    for group, (n, escalated) in {"routine": (2, 1), "approval": (1, 1), "sensitive": (2, 1)}.items():
        for i in range(n):
            await rs.n3_leaf(conn, group=group, escalated=i < escalated, created_at=d0 - 3 * DAY)


async def fast(conn: AsyncConnection, approver: str, decided_at: datetime, n: int = 3) -> None:
    """`n` phiếu "không xem" (B16 nhanh) của `approver`, quyết lúc `decided_at`."""
    for _ in range(n):
        await rs.reflex_decision(conn, approver=approver, decided_at=decided_at)


@pytest.mark.asyncio
async def test_daily_two_runs_written_then_duplicate(
    rw: AsyncEngine, mon: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Luật 1 vượt + người A 3 phiếu nhanh → N = 2. Lượt 02:00 VN `ghi=2 trùng=0`; lượt 03:00 VN cùng ngày `ghi=0
    trùng=2`, không thêm dòng (khoá `d0`)."""
    now = rs.daily_now(0)
    d0 = now - 2 * H
    a = seed.new_id("l1")
    async with rw.begin() as conn:
        await escalation_over(conn, d0)
        await fast(conn, a, d0 - 12 * H)
    clock = FakeClock(now)
    job = daily_job(rw, mon, clock, tmp_path)
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        await job.run()
        assert await escalation_rows(rw, d0) == [(0.6000000000000002, ESCALATION_DETAIL)]
        assert await rows(rw, "reflex_approval", a) == [(d0, 3.0, REFLEX_DETAIL)]
        clock.advance(H)
        await job.run()
    assert lines(caplog) == [
        (logging.INFO, SKIPPED), (logging.INFO, summary(2, 2, 0)),
        (logging.DEBUG, SKIPPED), (logging.DEBUG, summary(2, 0, 2)),
    ]  # fmt: skip
    assert await escalation_rows(rw, d0) == [(0.6000000000000002, ESCALATION_DETAIL)]
    assert await rows(rw, "reflex_approval", a) == [(d0, 3.0, REFLEX_DETAIL)]


@pytest.mark.asyncio
async def test_escalation_boundary_policy_unchanged(rw: AsyncEngine, mon: AsyncEngine, tmp_path: Path) -> None:
    """Ranh giới luật 1 (thẻ B2): vượt 0,40 → đúng 1 dòng `alerts`, chính sách KHÔNG đổi — `policy_versions` (mọi cột,
    mọi dòng) và số dòng `policy_rules` trước/sau bằng nhau, đọc bằng app_rw (`app_monitor` không có quyền đọc bảng
    này — migration 0001 `MONITOR_TABLES`)."""
    now = rs.daily_now(1)
    d0 = now - 2 * H

    async def policy_snapshot() -> tuple[list[tuple[Any, ...]], int]:
        async with rw.connect() as conn:
            versions = await conn.execute(text(
                "SELECT version_id, version, policy_json, is_current, updated_by, updated_at FROM policy_versions "
                "ORDER BY version_id"
            ))  # fmt: skip
            n_rules: int = (await conn.execute(text("SELECT count(*) FROM policy_rules"))).scalar_one()
            return [tuple(r) for r in versions], n_rules

    async with rw.begin() as conn:
        await conn.execute(text(
            "INSERT INTO policy_versions (version, policy_json, is_current) "
            "VALUES ('m9-ranh-gioi', CAST('{\"rules\": []}' AS jsonb), true)"
        ))  # fmt: skip
        await escalation_over(conn, d0)
    before = await policy_snapshot()
    assert len(before[0]) == 1  # có dữ liệu để so — không so hai danh sách rỗng
    await daily_job(rw, mon, FakeClock(now), tmp_path).run()
    assert await escalation_rows(rw, d0) == [(0.6000000000000002, ESCALATION_DETAIL)]
    assert await policy_snapshot() == before


@pytest.mark.asyncio
async def test_reflex_rows_subject_and_window(
    rw: AsyncEngine, mon: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Luật 7 qua job: hai người quyết, mỗi người 3 phiếu nhanh trong ngày VN hôm trước → 2 dòng `alerts` (2 đối tượng
    → 2 cảnh báo), subject = người quyết, `window_start = d0`."""
    now = rs.daily_now(2)
    d0 = now - 2 * H
    b, c = seed.new_id("l1"), seed.new_id("l1")
    async with rw.begin() as conn:
        await fast(conn, b, d0 - 12 * H)
        await fast(conn, c, d0 - 12 * H)
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        await daily_job(rw, mon, FakeClock(now), tmp_path).run()
    assert lines(caplog) == [(logging.INFO, SKIPPED), (logging.INFO, summary(2, 2, 0))]
    assert await rows(rw, "reflex_approval", b) == [(d0, 3.0, REFLEX_DETAIL)]
    assert await rows(rw, "reflex_approval", c) == [(d0, 3.0, REFLEX_DETAIL)]


@pytest.mark.asyncio
async def test_worker_down_two_marks_catchup(
    rw: AsyncEngine, mon: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Q-M9-B2-15 qua job: worker chạy lúc T1 = now − 2 ngày (mốc d0 − 8 … d0 − 2 ngày), rồi chết qua 2 mốc 02:00
    (d0 − 1 ngày, d0); khởi động lại lúc T2 = now + 5 giờ (07:00 VN, cùng d0) → chạy bù đánh giá 7 mốc d0 − 6 … d0.

    Người D: pha 1 có 3 phiếu nhanh ở mốc d0 − 7 ngày và 3 ở mốc d0 − 2 ngày → T1 `ghi=2`. Pha 2 (phiếu quyết trong lúc
    worker chết) thêm 3 ở mốc d0 − 1 ngày và 3 ở mốc d0 → T2 `nháp=3 ghi=2 trùng=1`: d0 − 2 ngày đã có (trùng), hai mốc
    bị lỡ ghi mới, mốc d0 − 7 ngày nằm ngoài 7 mốc nên không nháp lại (3, không phải 4). Mỗi mốc đúng một dòng."""
    now = rs.daily_now(3)
    d0 = now - 2 * H
    d = seed.new_id("l1")
    async with rw.begin() as conn:
        await fast(conn, d, d0 - 7 * DAY - 12 * H)
        await fast(conn, d, d0 - 2 * DAY - 12 * H)
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        await daily_job(rw, mon, FakeClock(now - 2 * DAY), tmp_path).run()
        assert [w for w, _, _ in await rows(rw, "reflex_approval", d)] == [d0 - 7 * DAY, d0 - 2 * DAY]
        async with rw.begin() as conn:
            await fast(conn, d, d0 - DAY - 12 * H)
            await fast(conn, d, d0 - 12 * H)
        await daily_job(rw, mon, FakeClock(now + 5 * H), tmp_path).run()  # instance mới = worker vừa khởi động lại
    assert lines(caplog) == [
        (logging.INFO, SKIPPED), (logging.INFO, summary(2, 2, 0)),
        (logging.INFO, SKIPPED), (logging.INFO, summary(3, 2, 1)),
    ]  # fmt: skip
    got = await rows(rw, "reflex_approval", d)
    assert [w for w, _, _ in got] == [d0 - 7 * DAY, d0 - 2 * DAY, d0 - DAY, d0]
    assert all((value, detail) == (3.0, REFLEX_DETAIL) for _, value, detail in got)


@pytest.mark.asyncio
async def test_degraded_skipped_no_rows(
    rw: AsyncEngine, mon: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Luật 12/13: có dữ liệu vượt ngưỡng thật (dòng audit B2 và B3 do tầng LLM quyết — hàm A đếm dòng; theo dòng hay
    theo lá phân biệt: chờ chốt Q-M9-B2-27) mà job vẫn bỏ qua cả hai (nguồn pending tới Phase 5) → không có dòng
    `alerts` nào của hai luật trên TOÀN bảng (module này không vá `is_pending`)."""
    now = rs.daily_now(4)
    d0 = now - 2 * H
    async with rw.begin() as conn:
        await rs.b2_point(conn, created_at=d0 - 12 * H, layer="llm")
        await rs.b3_point(conn, created_at=d0 - 12 * H, layer="llm")
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        await daily_job(rw, mon, FakeClock(now), tmp_path).run()
    assert lines(caplog) == [(logging.INFO, SKIPPED), (logging.INFO, summary(0, 0, 0))]
    async with rw.connect() as conn:
        n: int = (await conn.execute(text(
            "SELECT count(*) FROM alerts WHERE rule_id IN ('b2_degraded', 'b3_degraded')"
        ))).scalar_one()  # fmt: skip
    assert n == 0
