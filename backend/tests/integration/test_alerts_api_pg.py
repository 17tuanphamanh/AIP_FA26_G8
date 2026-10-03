"""M9 A3 — cảnh báo trên Postgres 16 thật (chốt Q-M9-A3-2 ở #10, Q-M9-A3-1 ở #6, duyệt plan A3).

- Đọc: `monitor.queries.alerts.list_alerts` bằng role `app_monitor` — thứ tự, `truncated`, lọc `status`/`audience` bằng SQL
  trước `LIMIT`, ngoặc quanh `OR`, `REGISTRY` giả (`rule_id` lạ → `("manager",)`).
- Ghi: `AlertWriter.ack` bằng role `app_rw` — nguyên tử khi hai người ack cùng lúc, 404/409 không ghi, thử lại một lần khi
  dòng còn `open`, log `alert_acked` (qua `JsonFormatter` thật).

Database riêng cho module; mỗi test xoá sạch `alerts` trước (bảng không có cửa sổ thời gian để tách test). Dữ liệu dựng bằng
`AlertWriter.raise_once` (thẻ A3), `created_at` theo `FakeClock`. `acked_by` có FK `users` → `ensure_user` trước.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from app.audit.alerts import AckResult, AlertWriter
from app.core.clock import FakeClock
from app.core.logging import JsonFormatter
from app.domain.alerts import AlertDraft
from app.monitor.queries.alerts import AlertPage, list_alerts
from app.monitor.rules import RuleSpec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio

T0 = datetime(2030, 6, 1, tzinfo=UTC)
MANAGERS = ("it_mgr01", "mgr-a", "mgr-b")


def _spec(rule_id: str, *audience: str) -> RuleSpec:
    return RuleSpec(rule_id, "minute", lambda data, ctx: [], audience)  # type: ignore[arg-type]


# REGISTRY giả: r_x KHÔNG có ở đây (luật lạ → manager).
FAKE_REGISTRY = {
    "r_dev": _spec("r_dev", "dev"),
    "r_mgr": _spec("r_mgr", "manager"),
    "r_both": _spec("r_both", "manager", "ops"),
}


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM alerts"))
        for user_id in MANAGERS:
            await seed.ensure_user(conn, user_id, role="manager")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def mon(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_monitor"))
    yield engine
    await engine.dispose()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


async def _raise(writer: AlertWriter, rw: AsyncEngine, rule_id: str, subject: str, **detail: Any) -> int:
    """Một cảnh báo mới qua `raise_once` (khoá khác nhau nhờ `subject`); trả `alert_id`."""
    assert await writer.raise_once(AlertDraft(rule_id=rule_id, subject=subject, window_start=T0, severity="warning",
                                              detail=detail))  # fmt: skip
    async with rw.connect() as conn:
        return int((await conn.execute(text("SELECT alert_id FROM alerts WHERE rule_id = :r AND subject = :s"),
                                       {"r": rule_id, "s": subject})).scalar_one())  # fmt: skip


async def _list(mon: AsyncEngine, **kw: Any) -> AlertPage:
    kw.setdefault("status", None)
    kw.setdefault("audience", None)
    kw.setdefault("limit", 200)
    kw.setdefault("registry", FAKE_REGISTRY)
    async with mon.connect() as conn:
        return await list_alerts(conn, **kw)


def _rules(page: AlertPage) -> list[str]:
    return [r.rule_id for r in page.rows]


async def _row(rw: AsyncEngine, alert_id: int) -> tuple[Any, ...]:
    async with rw.connect() as conn:
        return tuple((await conn.execute(text("SELECT status, acked_by, acked_at FROM alerts WHERE alert_id = :i"),
                                         {"i": alert_id})).one())  # fmt: skip


# ---- đọc: list_alerts -------------------------------------------------------------------------------------------------


async def test_list_order_created_desc_then_id_desc(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock) -> None:
    """A, B cùng `created_at` (B id lớn hơn) rồi C tạo SAU nhưng `created_at` SỚM hơn → [B, A, C]. Chỉ xếp theo id ra
    [C, B, A]; bỏ `alert_id DESC` thì A/B không chắc thứ tự."""
    writer = AlertWriter(rw, clock)
    clock.set(T0 + timedelta(hours=1))
    a = await _raise(writer, rw, "r_mgr", "a")
    b = await _raise(writer, rw, "r_mgr", "b")
    clock.set(T0)
    c = await _raise(writer, rw, "r_mgr", "c")
    page = await _list(mon)
    assert [r.alert_id for r in page.rows] == [b, a, c]
    assert page.truncated is False


async def test_truncated_201_rows(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock) -> None:
    """Chốt Q-M9-A3-2: 201 dòng, limit 200 → 200 mục + `truncated=true` (dòng cũ nhất bị cắt); còn đúng 200 → `false`
    (biên); `limit=1` → 1 mục + `true`."""
    writer = AlertWriter(rw, clock)
    ids = []
    for i in range(201):
        clock.set(T0 + timedelta(minutes=i))
        ids.append(await _raise(writer, rw, "r_mgr", f"s{i}"))
    page = await _list(mon, limit=200)
    assert (len(page.rows), page.truncated) == (200, True)
    assert [r.alert_id for r in page.rows] == ids[:0:-1]
    async with rw.begin() as conn:
        await conn.execute(text("DELETE FROM alerts WHERE alert_id = :i"), {"i": ids[0]})
    page = await _list(mon, limit=200)
    assert (len(page.rows), page.truncated) == (200, False)
    page = await _list(mon, limit=1)
    assert ([r.alert_id for r in page.rows], page.truncated) == ([ids[-1]], True)


async def test_status_filter(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock) -> None:
    writer = AlertWriter(rw, clock)
    opened = await _raise(writer, rw, "r_mgr", "open")
    acked = await _raise(writer, rw, "r_mgr", "acked")
    assert (await writer.ack(acked, "mgr-a")).outcome == "acked"
    assert [r.alert_id for r in (await _list(mon, status="open")).rows] == [opened]
    assert [r.alert_id for r in (await _list(mon, status="acked")).rows] == [acked]
    assert {r.alert_id for r in (await _list(mon)).rows} == {opened, acked}


async def test_audience_filter_fake_registry(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock) -> None:
    """Q-M9-A3-1: `manager` → luật có manager + luật lạ (`r_x`); `dev` → chỉ luật có dev; `ops` → chỉ `r_both`; không lọc →
    cả 4 (không ẩn theo role)."""
    writer = AlertWriter(rw, clock)
    for rule_id in ("r_dev", "r_mgr", "r_both", "r_x"):
        await _raise(writer, rw, rule_id, rule_id)
    assert set(_rules(await _list(mon, audience="manager"))) == {"r_mgr", "r_both", "r_x"}
    assert _rules(await _list(mon, audience="dev")) == ["r_dev"]
    assert _rules(await _list(mon, audience="ops")) == ["r_both"]
    assert set(_rules(await _list(mon))) == {"r_dev", "r_mgr", "r_both", "r_x"}


async def test_audience_filter_before_limit(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock) -> None:
    """5 cảnh báo `r_mgr` CŨ hơn 201 cảnh báo `r_dev`. `audience=manager&limit=5` → đủ 5 `r_mgr`, `truncated=false` (lọc sau
    `LIMIT` ra 0 mục); `audience=dev` → 200 mục, `truncated=true`."""
    writer = AlertWriter(rw, clock)
    for i in range(5):
        clock.set(T0 + timedelta(minutes=i))
        await _raise(writer, rw, "r_mgr", f"m{i}")
    for i in range(201):
        clock.set(T0 + timedelta(hours=1, minutes=i))
        await _raise(writer, rw, "r_dev", f"d{i}")
    page = await _list(mon, audience="manager", limit=5)
    assert (_rules(page), page.truncated) == (["r_mgr"] * 5, False)
    page = await _list(mon, audience="dev", limit=200)
    assert (len(page.rows), set(_rules(page)), page.truncated) == (200, {"r_dev"}, True)


async def test_status_and_audience_parenthesized(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock) -> None:
    """Duyệt plan A3: `r_x` (luật lạ) đã ack + `r_mgr` còn mở. `status=open&audience=manager` → chỉ `r_mgr`. Thiếu ngoặc
    quanh `OR` thì `status = 'open' AND rule_id = ANY(...) OR rule_id <> ALL(...)` kéo cả `r_x` đã ack vào."""
    writer = AlertWriter(rw, clock)
    stray = await _raise(writer, rw, "r_x", "x")
    await writer.ack(stray, "mgr-a")
    await _raise(writer, rw, "r_mgr", "m")
    assert _rules(await _list(mon, status="open", audience="manager")) == ["r_mgr"]


# ---- ghi: AlertWriter.ack ---------------------------------------------------------------------------------------------


async def _lock_waiters(conn: AsyncConnection) -> int:
    """Số phiên đang chờ khoá. `conn` phải ở AUTOCOMMIT: `pg_stat_activity` được chụp ở lần đọc đầu của một giao dịch và giữ
    tới hết giao dịch đó — đọc lại trong cùng giao dịch (autobegin của SQLAlchemy) thì mãi thấy bản chụp cũ."""
    return int((await conn.execute(text(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"
    ))).scalar_one())  # fmt: skip


async def test_ack_concurrent_one_winner(rw: AsyncEngine, clock: FakeClock) -> None:
    """Hai người ack cùng lúc. Giao dịch L giữ khoá dòng (`FOR UPDATE`) cho tới khi cả hai lệnh ack đều đang CHỜ khoá
    (`pg_stat_activity`), rồi commit → đúng 1 `acked` + 1 `already_acked`; `acked_by` = người thắng. Bỏ `AND status='open'`
    hoặc làm kiểu SELECT-rồi-UPDATE thì cả hai ra `acked`, người sau ghi đè."""
    writer = AlertWriter(rw, clock)
    alert_id = await _raise(writer, rw, "r_mgr", "race")
    async with rw.connect() as lock, rw.connect() as probe:
        probe = await probe.execution_options(isolation_level="AUTOCOMMIT")  # mỗi lần đọc một giao dịch → bản chụp mới
        await lock.begin()
        await lock.execute(text("SELECT 1 FROM alerts WHERE alert_id = :i FOR UPDATE"), {"i": alert_id})
        tasks = [asyncio.create_task(writer.ack(alert_id, user)) for user in ("mgr-a", "mgr-b")]
        for _ in range(100):  # tối đa ~5 giây
            if await _lock_waiters(probe) >= 2:
                break
            await asyncio.sleep(0.05)
        assert await _lock_waiters(probe) == 2, [t.exception() if t.done() else "chưa xong" for t in tasks]
        await lock.commit()
        results: list[AckResult] = list(await asyncio.gather(*tasks))
    outcomes = sorted(r.outcome for r in results)
    assert outcomes == ["acked", "already_acked"]
    [winner] = [r for r in results if r.outcome == "acked"]
    assert winner.row is not None
    status, acked_by, _ = await _row(rw, alert_id)
    assert (status, acked_by) == ("acked", winner.row["acked_by"])


async def test_ack_not_found(rw: AsyncEngine, clock: FakeClock) -> None:
    result = await AlertWriter(rw, clock).ack(987_654_321, "mgr-a")
    assert result == AckResult("not_found", None)


async def test_ack_already_acked_keeps_row(rw: AsyncEngine, clock: FakeClock) -> None:
    """Ack lần đầu (mgr-a, T0) → `acked`, dòng trả về đủ cột; lần hai (mgr-b, T0 + 1 giờ) → `already_acked`, `acked_by`,
    `acked_at` giữ của mgr-a."""
    writer = AlertWriter(rw, clock)
    alert_id = await _raise(writer, rw, "r_mgr", "twice")
    first = await writer.ack(alert_id, "mgr-a")
    assert first.outcome == "acked" and first.row is not None
    assert (first.row["alert_id"], first.row["status"], first.row["acked_by"], first.row["acked_at"]) == (
        alert_id, "acked", "mgr-a", T0,
    )  # fmt: skip
    clock.advance(timedelta(hours=1))
    assert await writer.ack(alert_id, "mgr-b") == AckResult("already_acked", None)
    assert await _row(rw, alert_id) == ("acked", "mgr-a", T0)


class _MissingWriter(AlertWriter):
    """`_try_ack` "trượt" `misses` lần đầu (như UPDATE ra 0 dòng dù dòng vẫn `open`), sau đó chạy thật."""

    def __init__(self, engine: AsyncEngine, clock: FakeClock, misses: int) -> None:
        super().__init__(engine, clock)
        self.misses = misses
        self.calls = 0

    async def _try_ack(self, conn: AsyncConnection, alert_id: int, user_id: str, now: datetime) -> Any:
        self.calls += 1
        if self.calls <= self.misses:
            return None
        return await super()._try_ack(conn, alert_id, user_id, now)


async def test_ack_retries_once_when_open(rw: AsyncEngine, clock: FakeClock) -> None:
    """Duyệt plan A3 bổ sung 3: bước 2 thấy `open` → chạy lại UPDATE đúng một lần (không trả 409 cho cảnh báo còn mở).
    Trượt 1 lần → `acked` sau 2 lần gọi. Trượt cả 2 lần → `RuntimeError` (Q-M9-A3-9), dòng vẫn `open`, không lần thứ 3."""
    alert_id = await _raise(AlertWriter(rw, clock), rw, "r_mgr", "retry")
    once = _MissingWriter(rw, clock, misses=1)
    result = await once.ack(alert_id, "mgr-a")
    assert (result.outcome, once.calls) == ("acked", 2)
    other = await _raise(AlertWriter(rw, clock), rw, "r_mgr", "retry-2")
    twice = _MissingWriter(rw, clock, misses=2)
    with pytest.raises(RuntimeError):
        await twice.ack(other, "mgr-a")
    assert twice.calls == 2
    assert await _row(rw, other) == ("open", None, None)


async def test_ack_logs_alert_acked(rw: AsyncEngine, clock: FakeClock, caplog: pytest.LogCaptureFixture) -> None:
    """Q-M9-A3-6: ack thành công → đúng 1 dòng INFO `alert_acked` có `alert_id`, `rule_id`, `user_id` (trong message — vì
    `JsonFormatter` bỏ `extra` — và trong `extra`). Format qua `JsonFormatter` thật: chuỗi JSON có đủ 3 trường, KHÔNG có
    `subject`, khoá/giá trị `detail`. 409/404 không ghi log."""
    writer = AlertWriter(rw, clock)
    alert_id = await _raise(writer, rw, "r_mgr", "subj-secret-7f3a", probe_9c1e="probe-val-2b8d")
    caplog.set_level(logging.INFO, logger="app.audit.alerts")
    await writer.ack(alert_id, "mgr-a")
    await writer.ack(alert_id, "mgr-b")  # 409
    await writer.ack(987_654_321, "mgr-a")  # 404
    records = [r for r in caplog.records if r.name == "app.audit.alerts" and r.getMessage().startswith("alert_acked")]
    assert len(records) == 1
    [record] = records
    assert record.levelno == logging.INFO
    assert (record.alert_id, record.rule_id, record.user_id) == (alert_id, "r_mgr", "mgr-a")  # type: ignore[attr-defined]
    out = JsonFormatter().format(record)
    msg = json.loads(out)["msg"]
    for part in (f"alert_id={alert_id}", "rule_id=r_mgr", "user_id=mgr-a"):
        assert part in msg
    for leaked in ("subj-secret-7f3a", "probe_9c1e", "probe-val-2b8d"):
        assert leaked not in out
