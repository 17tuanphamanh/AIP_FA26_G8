"""M9-B2 GĐ2 cụm 1 — D5 (thẻ B2, "Từ D5 PR #24"): job `monitor_rules_minute` chạy HAI lượt liên tiếp trên Postgres 16
thật — lượt 1 `ghi=N trùng=0`, lượt 2 `ghi=0 trùng=N−1` (luật 3 đối soát thấy cảnh báo của lượt 1 nên không nháp lại) —
với đủ 10 luật phút: 7 luật B1 + luật 4, 6 có dữ liệu thật + luật 5 bị bỏ qua (nguồn `tool_spans` pending, Q-M9-4).

Module riêng = DB riêng, MỘT test: số `ghi=`/`trùng=` của dòng tổng và số dòng `alerts` toàn bảng chỉ đếm được khi DB
không có dữ liệu của test khác (loader không có chặn trên theo `now` — Q-M9-B1-14).
"""

import logging
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.audit.alerts import AlertWriter
from app.core.clock import FakeClock
from app.db.session import Engines
from app.domain.alerts import AlertDraft
from app.monitor.window import hour_start
from app.worker import MONITOR_RULES_MINUTE, MonitorRulesJob
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration import monitor_rules_seed as rs
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

H = timedelta(hours=1)
MIN = timedelta(minutes=1)
N = len(rs.B1_RULES) + 2  # 7 luật B1 + e9_spike + e6_spike; breaker_open bỏ qua
# Lượt 2: luật 3 `password_bruteforce` là luật ĐỐI SOÁT (rules.py `password_bruteforce`): cảnh báo lượt 1 ghi với
# `window_start = occurred_at` → lượt 2 loader đọc lại nó (`ALERTS_SQL`, từ `since − 60 s`), lệch 0 ≤ RECONCILE_TOLERANCE
# → luật bỏ qua, KHÔNG nháp. Mọi luật khác nháp lại và gặp khoá đã có (trùng).
RERUN = N - 1


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


def lines(caplog: pytest.LogCaptureFixture, marker: str) -> list[tuple[int, str]]:
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "app.worker" and marker in r.getMessage()]


class RecordingWriter:
    """`AlertWriter` thật; ghi lại `rule_id` của mọi draft job gửi tới — biết CHÍNH XÁC luật nào nháp ở mỗi lượt."""

    def __init__(self, inner: AlertWriter) -> None:
        self._inner = inner
        self.rule_ids: list[str] = []

    async def raise_once(self, draft: AlertDraft) -> bool:
        self.rule_ids.append(draft.rule_id)
        return await self._inner.raise_once(draft)


async def alerts_per_rule(rw: AsyncEngine) -> dict[str, int]:
    async with rw.connect() as conn:
        result = await conn.execute(text("SELECT rule_id, count(*) AS n FROM alerts GROUP BY rule_id"))
        return {r.rule_id: r.n for r in result}


@pytest.mark.asyncio
async def test_job_two_runs_written_then_duplicate(
    rw: AsyncEngine, mon: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    now = rs.day(1)
    async with rw.begin() as conn:
        for rule_id in rs.B1_RULES:
            await rs.seed_rule(conn, rule_id, at=now - H)
        for code in ("E9", "E6"):
            await rs.spike_leaves(conn, code, hour=hour_start(now - H), n=3)
        await rs.tool_span(conn, name=seed.new_id("tool:ad"), at=now - 5 * MIN)  # có dữ liệu mà vẫn bỏ qua (pending)
    clock = FakeClock(now)
    writer = RecordingWriter(AlertWriter(rw, clock))
    job = MonitorRulesJob(Engines(main=rw, lock=rw, monitor=mon), writer, clock, cap_usd=38.0, warn_ratio=0.8)
    expected = {**dict.fromkeys(rs.B1_RULES, 1), "e9_spike": 1, "e6_spike": 1}  # mỗi luật 1 dòng; không có breaker_open
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        await job.minute()
        first, writer.rule_ids = writer.rule_ids, []
        after_first = await alerts_per_rule(rw)
        clock.advance(MIN)
        await job.minute()
    summary = f"{MONITOR_RULES_MINUTE}: nháp="
    assert lines(caplog, summary) == [
        (logging.INFO, f"{summary}{N} ghi={N} trùng=0 lỗi=0 luật_lỗi=0"),
        (logging.DEBUG, f"{summary}{RERUN} ghi=0 trùng={RERUN} lỗi=0 luật_lỗi=0"),
    ]
    skipped = f"{MONITOR_RULES_MINUTE}: luật bỏ qua (nguồn chưa có): breaker_open"
    assert lines(caplog, "luật bỏ qua") == [(logging.INFO, skipped), (logging.DEBUG, skipped)]
    # Luật vắng mặt ở lượt 2 đúng là luật 3 (đối soát), không phải luật nào khác.
    assert sorted(first) == sorted(expected)
    assert sorted(writer.rule_ids) == sorted(r for r in expected if r != "password_bruteforce")
    per_rule = await alerts_per_rule(rw)
    assert after_first == expected
    assert per_rule == expected  # lượt 2 không thêm dòng nào
    assert sum(per_rule.values()) == N and per_rule["password_bruteforce"] == 1
