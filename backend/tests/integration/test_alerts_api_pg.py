"""M9 A3 — cảnh báo trên Postgres 16 thật (chốt Q-M9-A3-2 ở #10, Q-M9-A3-1 ở #6, duyệt plan A3).

- Đọc: `monitor.queries.alerts.list_alerts` bằng role `app_monitor` — thứ tự, `truncated`, lọc `status`/`audience` bằng SQL
  trước `LIMIT`, ngoặc quanh `OR`, `REGISTRY` giả (`rule_id` lạ → `("manager",)`).
- Ghi: `AlertWriter.ack` bằng role `app_rw` — nguyên tử khi hai người ack cùng lúc, 404/409 không ghi, thử lại một lần khi
  dòng còn `open`, log `alert_acked` (qua `JsonFormatter` thật).
- HTTP (app thật, auth giả): manager thấy cảnh báo luật `("dev",)`; ack 200 → 409 → 404 đúng chữ; ack không cần DSN monitor;
  thời gian ISO 8601 có múi giờ; `detail` không phải object → `{}`; bảng rỗng; GET chạy trong snapshot `app_monitor`.
- Review PR #30 lượt 1: route nối đủ `status`/`audience`/`limit`/`truncated`, mặc định 200; lọc `status` trước `LIMIT`;
  `acked_by` chỉ từ token; dòng lạ (`severity`, `detail.audience`) không làm 500; GET trả đúng giá trị cột; thử lại vẫn `open`
  → log ERROR `alert_ack_still_open`.

Database riêng cho module; mỗi test xoá sạch `alerts` trước (bảng không có cửa sổ thời gian để tách test). Dữ liệu dựng bằng
`AlertWriter.raise_once` (thẻ A3), `created_at` theo `FakeClock`. `acked_by` có FK `users` → `ensure_user` trước.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pyotp
import pytest
import pytest_asyncio
from alembic import command
from app.audit.alerts import AckResult, AlertWriter
from app.auth.mfa import MfaCipher, enroll
from app.core.clock import FakeClock
from app.core.logging import JsonFormatter
from app.domain.alerts import AlertDraft
from app.main import create_app
from app.monitor.queries.alerts import AlertPage, audience_of, list_alerts
from app.monitor.rules import RuleSpec
from app.settings import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.fakes.auth import (
    DEMO_PASSWORD,
    FakeIdentityProvider,
    InMemoryAuthStore,
    RecordingSink,
)
from tests.fakes.identity import MemoryAlerts
from tests.fakes.runtime import no_runtime
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.unit.auth_helpers import BASE_URL, auth_settings

pytestmark = pytest.mark.asyncio

T0 = datetime(2030, 6, 1, tzinfo=UTC)
MANAGER = "quan.tm"  # it_mgr01 trong AD giả
LIST = "/api/alerts"
VIEW_KEYS = {
    "alert_id", "rule_id", "subject", "severity", "value", "window_start", "status", "detail", "audience", "acked_by",
    "acked_at", "created_at",
}  # fmt: skip
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
    assert audience_of("r_x", FAKE_REGISTRY) == ("manager",)  # nhãn của luật lạ (api gắn bằng `audience_of`)


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


async def test_status_filter_before_limit(rw: AsyncEngine, mon: AsyncEngine, clock: FakeClock) -> None:
    """Review PR #30 (2): lọc `status` bằng SQL TRƯỚC `LIMIT`. 1 dòng `open` CŨ + 4 dòng `acked` mới hơn: `status=open&limit=2`
    vẫn ra dòng `open`, `truncated=false` (lọc bằng Python sau `LIMIT` ra 0 mục, `truncated=true`); `status=acked&limit=2` → 2
    dòng mới nhất, `truncated=true`."""
    writer = AlertWriter(rw, clock)
    opened = await _raise(writer, rw, "r_mgr", "old-open")
    acked = []
    for i in range(4):
        clock.set(T0 + timedelta(hours=1, minutes=i))
        acked.append(await _raise(writer, rw, "r_mgr", f"acked-{i}"))
        assert (await writer.ack(acked[-1], "mgr-a")).outcome == "acked"
    page = await _list(mon, status="open", limit=2)
    assert ([r.alert_id for r in page.rows], page.truncated) == ([opened], False)
    page = await _list(mon, status="acked", limit=2)
    assert ([r.alert_id for r in page.rows], page.truncated) == ([acked[3], acked[2]], True)


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


async def test_ack_still_open_logs_error(rw: AsyncEngine, clock: FakeClock, caplog: pytest.LogCaptureFixture) -> None:
    """Q-M9-A3-9 (review PR #30): thử lại vẫn `open` → đúng 1 dòng ERROR `alert_ack_still_open` có `alert_id` (trong message —
    `JsonFormatter` bỏ `extra` — và trong `extra`) ngay trước `RuntimeError`; không có `alert_acked`. Trượt 1 lần rồi ack được
    → không có dòng ERROR."""
    writer = AlertWriter(rw, clock)
    once = await _raise(writer, rw, "r_mgr", "once")
    stuck = await _raise(writer, rw, "r_mgr", "stuck")
    caplog.set_level(logging.INFO, logger="app.audit.alerts")

    def errors() -> list[logging.LogRecord]:
        return [r for r in caplog.records if r.name == "app.audit.alerts" and r.levelno >= logging.ERROR]

    assert (await _MissingWriter(rw, clock, misses=1).ack(once, "mgr-a")).outcome == "acked"
    assert errors() == []
    with pytest.raises(RuntimeError):
        await _MissingWriter(rw, clock, misses=2).ack(stuck, "mgr-a")
    [record] = errors()
    assert (record.levelno, record.getMessage().split()[0]) == (logging.ERROR, "alert_ack_still_open")
    assert record.alert_id == stuck  # type: ignore[attr-defined]
    assert f"alert_id={stuck}" in json.loads(JsonFormatter().format(record))["msg"]
    acked = [r for r in caplog.records if r.getMessage().startswith("alert_acked")]
    assert [r.alert_id for r in acked] == [once]  # type: ignore[attr-defined]


# ---- HTTP (app thật, auth giả, FakeClock dùng chung với writer của test) ------------------------------------------------


@dataclass
class Http:
    """App thật qua ASGI trong event loop của test (khuôn `test_b15_pg.py` `_desk`/`Desk`); auth giả như `auth_env`."""

    client: httpx.AsyncClient
    clock: FakeClock
    store: InMemoryAuthStore
    sink: RecordingSink
    settings: Settings

    async def token(self, username: str) -> str:
        """Đăng nhập; manager bắt buộc MFA — lần đầu 401, `enroll` (hàm CLI dùng) rồi đăng nhập kèm OTP (khuôn
        `test_b15_pg.Desk.headers`, `test_approvals_inbox._login` — bản `await`, không `asyncio.run`)."""
        body = {"username": username, "password": DEMO_PASSWORD}
        r = await self.client.post("/api/auth/login", json=body)
        if r.status_code != 200:
            assert r.status_code == 401, r.text
            key = self.settings.mfa_enc_key
            assert key is not None
            enrolled = await enroll(self.store, self.sink, MfaCipher(key), username=username, by="ops", reason="test")
            r = await self.client.post(
                "/api/auth/login", json={**body, "otp": pyotp.TOTP(enrolled.secret).at(self.clock.now())}
            )
        assert r.status_code == 200, r.text
        return str(r.json()["access_token"])


@asynccontextmanager
async def http(db: PgUrls, clock: FakeClock, *, monitor: bool = True) -> AsyncIterator[Http]:
    """`create_app` với DATABASE_URL = app_rw, MONITOR_DATABASE_URL = app_monitor (hoặc thiếu); auth giả (tham số như
    `auth_helpers.auth_env`), không runtime graph."""
    settings = auth_settings(
        database_url=db.role("app_rw"), monitor_database_url=db.role("app_monitor") if monitor else None
    )
    sink = RecordingSink(clock)
    store = InMemoryAuthStore(sink)
    app = create_app(
        settings, health_checks={}, idp=FakeIdentityProvider(), store=store, sink=sink, alerts=MemoryAlerts(),
        clock=clock, runtime=no_runtime,
    )  # fmt: skip
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 50000))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        yield Http(client, clock, store, sink, settings)


@pytest_asyncio.fixture
async def env(db: PgUrls, clock: FakeClock) -> AsyncIterator[Http]:
    async with http(db, clock) as e:
        yield e


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _alerts(env: Http, token: str, **params: Any) -> tuple[int, Any]:
    r = await env.client.get(LIST, params=params, headers=_bearer(token))
    return r.status_code, r.json()


async def _ack(env: Http, token: str, alert_id: int) -> tuple[int, Any]:
    r = await env.client.post(f"{LIST}/{alert_id}/ack", headers=_bearer(token))
    return r.status_code, r.json()


async def test_empty_alerts(rw: AsyncEngine, env: Http) -> None:
    assert await _alerts(env, await env.token(MANAGER)) == (200, {"items": [], "truncated": False})


async def test_manager_sees_dev_alert(rw: AsyncEngine, env: Http, clock: FakeClock) -> None:
    """Q-M9-A3-1: manager (role duy nhất có `alert:read`) thấy cảnh báo của luật `("dev",)` (luật 15 `finalize_failed`,
    REGISTRY thật) với nhãn `["dev"]`. Lọc theo role ∈ audience thì danh sách rỗng."""
    alert_id = await _raise(AlertWriter(rw, clock), rw, "finalize_failed", "tk-dev")
    status, body = await _alerts(env, await env.token(MANAGER))
    assert status == 200, body
    assert [(i["alert_id"], i["rule_id"], i["audience"]) for i in body["items"]] == [
        (alert_id, "finalize_failed", ["dev"]),
    ]  # fmt: skip


async def test_ack_200_409_404(rw: AsyncEngine, env: Http, clock: FakeClock) -> None:
    """200 trả `AlertView` sau ack (`acked_by` = người trong token, `acked_at` = Clock của app); ack lại (giờ đã khác) →
    409 `already_acked`, DB giữ mốc cũ; id lạ → 404 `not_found` (thân đúng chữ — chốt ghim)."""
    alert_id = await _raise(AlertWriter(rw, clock), rw, "r_mgr", "http")
    token = await env.token(MANAGER)
    status, body = await _ack(env, token, alert_id)
    assert status == 200, body
    assert set(body) == VIEW_KEYS
    assert (body["alert_id"], body["status"], body["acked_by"]) == (alert_id, "acked", "it_mgr01")
    assert datetime.fromisoformat(body["acked_at"]) == clock.now()
    first_at = clock.now()
    # Tua NỬA thời hạn access token (app dùng chung clock này để kiểm `exp`): đủ để `acked_at` mới khác mốc cũ, token vẫn
    # còn hạn → lần 2 tới được route (tua quá hạn thì ra 401 trước khi ack).
    clock.advance(timedelta(minutes=env.settings.access_ttl_minutes) / 2)
    assert clock.now() != first_at
    assert await _ack(env, token, alert_id) == (409, {"detail": "already_acked"})
    assert await _row(rw, alert_id) == ("acked", "it_mgr01", first_at)
    assert await _ack(env, token, 987_654_321) == (404, {"detail": "not_found"})


async def test_ack_works_without_monitor_dsn(rw: AsyncEngine, db: PgUrls, clock: FakeClock) -> None:
    """Ack ghi bằng app_rw, không đụng engine monitor → thiếu DSN monitor vẫn 200 (503 chỉ áp cho GET)."""
    alert_id = await _raise(AlertWriter(rw, clock), rw, "r_mgr", "no-dsn")
    async with http(db, clock, monitor=False) as e:
        token = await e.token(MANAGER)
        assert await _alerts(e, token) == (503, {"detail": "monitor_unavailable"})
        status, body = await _ack(e, token, alert_id)
    assert (status, body["status"]) == (200, "acked")


async def test_items_iso8601_tz(rw: AsyncEngine, env: Http, clock: FakeClock) -> None:
    """Mọi trường thời gian ISO 8601 có múi giờ; `value` null hoặc số; `detail` là object."""
    writer = AlertWriter(rw, clock)
    acked = await _raise(writer, rw, "r_mgr", "iso-a", count=3)
    await writer.ack(acked, "mgr-a")
    assert await writer.raise_once(AlertDraft(rule_id="r_mgr", subject="iso-b", window_start=T0, severity="critical",
                                              value=0.42))  # fmt: skip
    status, body = await _alerts(env, await env.token(MANAGER))
    assert status == 200, body
    tz = re.compile(r"(Z|[+-]\d\d:\d\d)$")
    for item in body["items"]:
        for key in ("window_start", "created_at", "acked_at"):
            assert item[key] is None or tz.search(item[key]), (key, item[key])
        assert item["value"] is None or isinstance(item["value"], float)
        assert isinstance(item["detail"], dict)
    by_subject = {i["subject"]: i for i in body["items"]}
    assert (by_subject["iso-a"]["detail"], by_subject["iso-a"]["acked_at"] is not None) == ({"count": 3}, True)
    assert by_subject["iso-b"]["value"] == 0.42


async def test_detail_non_object_becomes_empty(rw: AsyncEngine, env: Http) -> None:
    """Duyệt plan A3 bổ sung 4: dòng `alerts` có `detail` là mảng / chuỗi (ghi tay, không qua writer) → 200, `detail = {}`;
    không làm 500 cả danh sách."""
    async with rw.begin() as conn:
        for subject, detail in (("arr", "[1, 2]"), ("str", '"x"')):
            await conn.execute(text(
                "INSERT INTO alerts (rule_id, subject, window_start, severity, detail, created_at) "
                "VALUES ('r_mgr', :s, :w, 'warning', CAST(:d AS jsonb), :w)"
            ), {"s": subject, "w": T0, "d": detail})  # fmt: skip
    status, body = await _alerts(env, await env.token(MANAGER))
    assert status == 200, body
    assert sorted((i["subject"], i["detail"]) for i in body["items"]) == [("arr", {}), ("str", {})]


async def test_routes_run_in_snapshot_alerts(env: Http, monkeypatch: pytest.MonkeyPatch) -> None:
    """`GET /api/alerts` chạy trong giao dịch `REPEATABLE READ, READ ONLY` của `app_monitor`: hàm truy vấn của route được
    thay bằng hàm đọc ba giá trị ngay trên `conn` route truyền vào."""
    seen: list[tuple[Any, ...]] = []

    async def spy(conn: AsyncConnection, **_: Any) -> AlertPage:
        seen.append(tuple((await conn.execute(text(
            "SELECT current_setting('transaction_isolation'), current_setting('transaction_read_only'), current_user"
        ))).one()))  # fmt: skip
        return AlertPage(rows=(), truncated=False)

    monkeypatch.setattr("app.api.alerts.list_alerts", spy)
    assert await _alerts(env, await env.token(MANAGER)) == (200, {"items": [], "truncated": False})
    assert seen == [("repeatable read", "on", "app_monitor")]


# ---- HTTP: review PR #30 (Tuấn Anh, lượt 1) — code đã đúng, các test dưới giữ cho khỏi lùi --------------------------------


async def test_route_params_status_audience_limit(rw: AsyncEngine, env: Http, clock: FakeClock) -> None:
    """Review PR #30 (1): route nối đúng `status` / `audience` / `limit` / `truncated` xuống truy vấn (REGISTRY thật). a = luật 15
    `finalize_failed` ("dev") mở; b = `execution_failed` ("manager", "ops") đã ack; c = luật lạ (→ "manager") mở; c mới nhất.
    Route bỏ một tham số, hoặc luôn `truncated=false`, thì một trong các lời gọi dưới ra sai."""
    writer = AlertWriter(rw, clock)
    a = await _raise(writer, rw, "finalize_failed", "p-dev")
    clock.advance(timedelta(minutes=1))
    b = await _raise(writer, rw, "execution_failed", "p-acked")
    assert (await writer.ack(b, "mgr-a")).outcome == "acked"
    clock.advance(timedelta(minutes=1))
    c = await _raise(writer, rw, "zzz_luat_la", "p-x")
    token = await env.token(MANAGER)

    async def ids(**params: Any) -> tuple[list[int], bool]:
        status, body = await _alerts(env, token, **params)
        assert status == 200, body
        return [i["alert_id"] for i in body["items"]], body["truncated"]

    assert await ids() == ([c, b, a], False)
    assert await ids(status="open") == ([c, a], False)
    assert await ids(status="acked") == ([b], False)
    assert await ids(audience="dev") == ([a], False)
    assert await ids(audience="ops") == ([b], False)
    assert await ids(limit=1) == ([c], True)


async def test_route_default_limit_200(rw: AsyncEngine, env: Http) -> None:
    """Review PR #30 (1): không tham số → `limit` mặc định 200 (chốt Q-M9-A3-2): 201 dòng → 200 mục, mới nhất trước,
    `truncated=true` (dòng cũ nhất bị cắt)."""
    async with rw.begin() as conn:
        await conn.execute(text(
            "INSERT INTO alerts (rule_id, subject, window_start, severity, detail, created_at) "
            "SELECT 'r_mgr', 'bulk-' || g, :w, 'warning', CAST('{}' AS jsonb), "
            "CAST(:w AS timestamptz) + g * interval '1 minute' FROM generate_series(1, 201) AS g"
        ), {"w": T0})  # fmt: skip
    status, body = await _alerts(env, await env.token(MANAGER))
    assert status == 200, body
    assert (len(body["items"]), body["truncated"]) == (200, True)
    subjects = [i["subject"] for i in body["items"]]
    assert (subjects[0], subjects[-1]) == ("bulk-201", "bulk-2")


async def test_ack_ignores_acked_by_input(rw: AsyncEngine, env: Http, clock: FakeClock) -> None:
    """Review PR #30 (3): `acked_by` = người trong token, không nhận từ query hay body. `mgr-a` / `mgr-b` là user có thật trong
    `users` — lấy nhầm từ input thì vẫn ghi được (không vấp FK), nên test thấy được."""
    writer = AlertWriter(rw, clock)
    by_query = await _raise(writer, rw, "r_mgr", "by-query")
    by_body = await _raise(writer, rw, "r_mgr", "by-body")
    headers = _bearer(await env.token(MANAGER))
    sent = (
        (by_query, await env.client.post(f"{LIST}/{by_query}/ack", params={"acked_by": "mgr-a"}, headers=headers)),
        (by_body, await env.client.post(f"{LIST}/{by_body}/ack", json={"acked_by": "mgr-b"}, headers=headers)),
    )
    for alert_id, r in sent:
        assert (r.status_code, r.json()["acked_by"]) == (200, "it_mgr01"), r.text
        assert (await _row(rw, alert_id))[:2] == ("acked", "it_mgr01")


async def test_odd_row_severity_and_detail_audience(rw: AsyncEngine, env: Http) -> None:
    """Review PR #30 (4): một dòng lạ không làm 500 cả danh sách — `severity` ngoài info/warning/critical (cột không có CHECK)
    → 200, trả nguyên giá trị. `detail.audience` có trong dòng nhưng nhãn vẫn lấy từ `REGISTRY` (luật 15 → `["dev"]`);
    `detail` giữ nguyên."""
    async with rw.begin() as conn:
        for subject, rule_id, severity, detail in (
            ("odd", "finalize_failed", "zzz-la", '{"audience": ["ops"]}'),
            ("ok", "r_mgr", "warning", "{}"),
        ):
            await conn.execute(text(
                "INSERT INTO alerts (rule_id, subject, window_start, severity, detail, created_at) "
                "VALUES (:r, :s, :w, :sev, CAST(:d AS jsonb), :w)"
            ), {"r": rule_id, "s": subject, "w": T0, "sev": severity, "d": detail})  # fmt: skip
    status, body = await _alerts(env, await env.token(MANAGER))
    assert status == 200, body
    by_subject = {i["subject"]: i for i in body["items"]}
    assert set(by_subject) == {"odd", "ok"}
    odd = by_subject["odd"]
    assert (odd["severity"], odd["audience"], odd["detail"]) == ("zzz-la", ["dev"], {"audience": ["ops"]})


async def test_list_returns_column_values(rw: AsyncEngine, env: Http, clock: FakeClock) -> None:
    """Review PR #30 (5): GET trả ĐÚNG giá trị từng cột. `window_start` = T0 khác `created_at` = T0 + 30 phút; sau ack
    (T0 + 45 phút, `mgr-a`) có `acked_by`, `acked_at`."""
    writer = AlertWriter(rw, clock)
    clock.set(T0 + timedelta(minutes=30))
    alert_id = await _raise(writer, rw, "r_mgr", "cols")
    clock.set(T0 + timedelta(minutes=45))
    assert (await writer.ack(alert_id, "mgr-a")).outcome == "acked"
    status, body = await _alerts(env, await env.token(MANAGER))
    assert status == 200, body
    [item] = body["items"]
    assert (item["alert_id"], item["status"], item["acked_by"]) == (alert_id, "acked", "mgr-a")
    times = [datetime.fromisoformat(item[k]) for k in ("window_start", "created_at", "acked_at")]
    assert times == [T0, T0 + timedelta(minutes=30), T0 + timedelta(minutes=45)]
