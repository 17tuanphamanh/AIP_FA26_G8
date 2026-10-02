"""M9-B1 GĐ2 — job `monitor_rules_minute` (`worker.MonitorRulesJob`) trên Postgres 16 thật: đọc bằng `app_monitor`,
GHI `alerts` bằng `AlertWriter` (app_rw) như worker.

Module riêng = DB riêng (Q-M9-B1-14 a): job ghi cả cảnh báo cho dữ liệu "tương lai" của test khác trong cùng DB (loader
không có chặn trên theo `now`), nên mọi assert là SỐ DÒNG `alerts` của subject của chính test — không dựa cờ "vừa tạo
mới" của `raise_once`, không đếm toàn bảng, không dựa số `ghi=` trong log.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from app.audit.alerts import AlertWriter
from app.core.clock import FakeClock
from app.db.session import Engines
from app.domain.alerts import AlertDraft
from app.monitor.evaluator import LOADERS
from app.monitor.rules import REGISTRY, RuleContext, RuleSpec
from app.worker import MonitorRulesJob
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_rules_seed as rs
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

H = timedelta(hours=1)
MIN = timedelta(minutes=1)
MS = timedelta(milliseconds=1)


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


class Writer:
    """`AlertWriter` thật; `fail_rule` → ném lỗi cho mọi draft của luật đó (mô phỏng một draft ghi lỗi)."""

    def __init__(self, inner: AlertWriter, fail_rule: str | None = None) -> None:
        self._inner = inner
        self._fail_rule = fail_rule

    async def raise_once(self, draft: AlertDraft) -> bool:
        if draft.rule_id == self._fail_rule:
            raise RuntimeError("ghi lỗi giả")
        return await self._inner.raise_once(draft)


def make_job(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock, fail_rule: str | None = None) -> MonitorRulesJob:
    return MonitorRulesJob(
        Engines(main=rw, lock=rw, monitor=mon), Writer(AlertWriter(rw, clock), fail_rule), clock,
        cap_usd=38.0, warn_ratio=0.8,
    )  # fmt: skip


async def rows(rw: AsyncEngine, rule_id: str, subject: str) -> list[tuple[datetime, dict[str, Any]]]:
    """Dòng `alerts` của MỘT (luật, đối tượng) — đối tượng của chính test (Q-M9-B1-14 b)."""
    async with rw.connect() as conn:
        result = await conn.execute(
            text("SELECT window_start, detail FROM alerts WHERE rule_id = :r AND subject = :s ORDER BY alert_id"),
            {"r": rule_id, "s": subject},
        )
        return [(r.window_start, r.detail) for r in result]


async def seed_all(rw: AsyncEngine, at: datetime | list[datetime]) -> dict[str, tuple[str, datetime]]:
    """Một nguồn cho mỗi luật trong 7 luật B1 (thời điểm chung hoặc riêng từng luật). Trả {luật: (subject, window)}."""
    times = at if isinstance(at, list) else [at] * len(rs.B1_RULES)
    async with rw.begin() as conn:
        return {r: await rs.seed_rule(conn, r, at=t) for r, t in zip(rs.B1_RULES, times, strict=True)}


async def assert_one_row_each(rw: AsyncEngine, seeded: dict[str, tuple[str, datetime]]) -> None:
    for rule_id, (subject, window) in seeded.items():
        assert [w for w, _ in await rows(rw, rule_id, subject)] == [window], rule_id


# ---- không trùng, không sót -----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_twice_no_duplicates(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Chạy job, +60 s, chạy lại → mỗi (luật, đối tượng) đúng 1 dòng, `window_start` = mốc DB (khoá ổn định)."""
    now = rs.day(1)
    seeded = await seed_all(rw, now - H)
    clock = FakeClock(now)
    job = make_job(rw, mon, clock)
    await job.minute()
    await assert_one_row_each(rw, seeded)
    clock.advance(MIN)
    await job.minute()
    await assert_one_row_each(rw, seeded)


@pytest.mark.asyncio
async def test_worker_down_1h_still_caught(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Worker "chết" 1 giờ: nguồn rải trong `[T+1′, T+49′]`, chạy MỘT lần ở `T+60′` → đủ cảnh báo (lookback 24 giờ)."""
    t = rs.day(2) - H
    seeded = await seed_all(rw, [t + (1 + 8 * i) * MIN for i in range(len(rs.B1_RULES))])
    await make_job(rw, mon, FakeClock(t + 60 * MIN)).minute()
    await assert_one_row_each(rw, seeded)


@pytest.mark.asyncio
async def test_future_event_same_key_across_runs(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-B1-12: nguồn ở `now + 10′` → lần chạy ở `now` ghi 6 luật (luật 3 hoãn); lần ở `now + 15′` → đủ 7, mỗi cái
    đúng 1 dòng, `window_start` = mốc DB (không đổi giữa hai lần)."""
    now = rs.day(3)
    seeded = await seed_all(rw, now + 10 * MIN)
    clock = FakeClock(now)
    job = make_job(rw, mon, clock)
    await job.minute()
    for rule_id, (subject, window) in seeded.items():
        expected = [] if rule_id == "password_bruteforce" else [window]
        assert [w for w, _ in await rows(rw, rule_id, subject)] == expected, rule_id
    clock.set(now + 15 * MIN)
    await job.minute()
    await assert_one_row_each(rw, seeded)


# ---- luật 3: đối soát với cảnh báo auth -----------------------------------------------------------------------------


async def locked_user(rw: AsyncEngine, at: datetime) -> tuple[str, datetime]:
    user = seed.new_id("u")
    async with rw.begin() as conn:
        await seed.ensure_user(conn, user)
    return user, await rs.auth_lock(rw, user_id=user, username=f"seed.{user}", at=at)


@pytest.mark.asyncio
async def test_bruteforce_auth_wrote_m9_adds_nothing(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Auth đã ghi (lock_start trước `occurred_at` 3 ms, writer thật) → M9 chạy → vẫn đúng 1 dòng, của auth."""
    now = rs.day(4)
    user, _ = await locked_user(rw, now - 2 * MIN)
    await make_job(rw, mon, FakeClock(now)).minute()
    got = await rows(rw, "password_bruteforce", user)
    assert [(w, d["source"]) for w, d in got] == [(now - 2 * MIN, "login")]


@pytest.mark.asyncio
async def test_bruteforce_auth_row_deleted_m9_creates_one(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Xoá dòng của auth → M9 tạo đúng 1 (`source="m9_reconcile"`, `window_start = occurred_at`); chạy lại → vẫn 1."""
    now = rs.day(5)
    user, occurred = await locked_user(rw, now - 2 * MIN)
    async with rw.begin() as conn:
        await conn.execute(text("DELETE FROM alerts WHERE rule_id = 'password_bruteforce' AND subject = :s"), {"s": user})
    clock = FakeClock(now)
    job = make_job(rw, mon, clock)
    await job.minute()
    clock.advance(MIN)
    await job.minute()
    got = await rows(rw, "password_bruteforce", user)
    assert [(w, d["source"]) for w, d in got] == [(occurred, "m9_reconcile")]


@pytest.mark.asyncio
async def test_bruteforce_other_rule_alert_same_subject(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Cảnh báo `refresh_reuse` cùng user, lệch 3 ms không che đợt khoá → job vẫn tạo 1 dòng `password_bruteforce`."""
    now = rs.day(6)
    async with rw.begin() as conn:
        user, window = await rs.seed_rule(conn, "password_bruteforce", at=now - H)
        await rs.alert(conn, rule_id="refresh_reuse", subject=user, window_start=now - H + 3 * MS)
    await make_job(rw, mon, FakeClock(now)).minute()
    assert [w for w, _ in await rows(rw, "password_bruteforce", user)] == [window]


# ---- lỗi cục bộ không lan ------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_rule_sql_error_others_still_written(
    rw: AsyncEngine, mon: AsyncEngine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Loader `refresh_reuse` lỗi SQL thật → 6 luật kia vẫn ghi; log có tên luật."""
    now = rs.day(7)

    async def broken(conn: AsyncConnection, ctx: RuleContext) -> list[object]:
        await conn.execute(text("SELECT * FROM bang_khong_ton_tai"))
        return []

    monkeypatch.setitem(LOADERS, "refresh_reuse", broken)
    seeded = await seed_all(rw, now - H)
    with caplog.at_level(logging.WARNING, logger="app.worker"):
        await make_job(rw, mon, FakeClock(now)).minute()
    for rule_id, (subject, window) in seeded.items():
        expected = [] if rule_id == "refresh_reuse" else [window]
        assert [w for w, _ in await rows(rw, rule_id, subject)] == expected, rule_id
    assert any("luật lỗi: refresh_reuse" in r.getMessage() for r in caplog.records if r.name == "app.worker")


@pytest.mark.asyncio
async def test_one_draft_write_error_others_written(
    rw: AsyncEngine, mon: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """Ghi draft của MỘT luật lỗi → dòng của các luật khác vẫn ghi; log chỉ `rule_id` + tên lớp, không traceback."""
    now = rs.day(8)
    seeded = await seed_all(rw, now - H)
    with caplog.at_level(logging.WARNING, logger="app.worker"):
        await make_job(rw, mon, FakeClock(now), fail_rule="injection_detected").minute()
    for rule_id, (subject, window) in seeded.items():
        expected = [] if rule_id == "injection_detected" else [window]
        assert [w for w, _ in await rows(rw, rule_id, subject)] == expected, rule_id
    worker_logs = [r for r in caplog.records if r.name == "app.worker"]
    assert any("injection_detected lỗi: RuntimeError" in r.getMessage() for r in worker_logs)
    assert all(r.exc_info is None for r in worker_logs)


@pytest.mark.asyncio
async def test_job_reads_via_app_monitor(rw: AsyncEngine, mon: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cấp JOB (mutation G10): luật tạm ghi lại `current_user` của connection mà job mở → phải là `app_monitor` (job lấy
    engine qua `monitor_engine`, không bao giờ engine chính app_rw)."""
    seen: list[str] = []

    async def whoami(conn: AsyncConnection, ctx: RuleContext) -> list[object]:
        seen.append((await conn.execute(text("SELECT current_user"))).scalar_one())
        return []

    monkeypatch.setitem(REGISTRY, "probe_whoami", RuleSpec("probe_whoami", "minute", lambda data, ctx: [], ("dev",)))
    monkeypatch.setitem(LOADERS, "probe_whoami", whoami)
    await make_job(rw, mon, FakeClock(rs.day(9))).minute()
    assert seen == ["app_monitor"]
