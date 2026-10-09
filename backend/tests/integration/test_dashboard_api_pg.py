"""M9 A3 — `/api/dashboard/*` qua HTTP trên Postgres 16 thật (kế hoạch M9 4.5, 5.1–5.3; duyệt plan A3 ở #10).

App thật (`create_app`) với `DATABASE_URL` = app_rw, `MONITOR_DATABASE_URL` = app_monitor; auth bằng bản giả (AD, store trong
bộ nhớ), FakeClock `NOW`. Dữ liệu dựng bằng `monitor_seed` (role app_rw), mỗi test một ngày riêng của tháng 3/2031.

- manager → `scope="all"`, đủ 10 khoá; L1 → `scope="own"`, đúng 3 khoá, chỉ số của chính mình (2 L1 không thấy số nhau;
  `?approver_id=<L1 khác>&scope=all` không mở rộng được). AI → đủ 14 khoá, pending trong `unavailable`.
- `from`/`to` trả lại ở UTC; mặc định 7 ngày theo Clock.
- Mỗi response chạy trong một giao dịch `REPEATABLE READ, READ ONLY` của `app_monitor` — đọc ngay trên `conn` mà route truyền
  cho hàm truy vấn; dữ liệu commit GIỮA hai chỉ số không lọt vào response (một response = một snapshot, review PR #30).
- Ngày dùng riêng: 1–5 (chỉ số), 6 (echo UTC, không dữ liệu), 7 (snapshot spy), 9–10 (một snapshot).
"""

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
from app.auth.mfa import MfaCipher, enroll
from app.core.clock import FakeClock
from app.main import create_app
from app.monitor.metrics import is_pending
from app.monitor.queries import ai, business
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

NOW = datetime(2031, 3, 31, 8, tzinfo=UTC)
BUSINESS, AI = "/api/dashboard/business", "/api/dashboard/ai"
MANAGER = "quan.tm"  # it_mgr01 trong AD giả
L1_A, L1_B = "l1_01", "l1_02"  # ha.lt, duc.pv trong AD giả (`tests/fakes/auth.py`)
SNAPSHOT_SQL = "SELECT current_setting('transaction_isolation'), current_setting('transaction_read_only'), current_user"


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
async def env(db: PgUrls) -> AsyncIterator[Http]:
    async with http(db, FakeClock(NOW)) as e:
        yield e


def win(day: int) -> dict[str, str]:
    frm = datetime(2031, 3, day, tzinfo=UTC)
    return {"from": frm.isoformat(), "to": (frm + timedelta(days=1)).isoformat()}


def at(day: int) -> datetime:
    return datetime(2031, 3, day, 1, tzinfo=UTC)


async def _get(env: Http, route: str, token: str, **params: str) -> tuple[int, Any]:
    r = await env.client.get(route, params=params, headers={"Authorization": f"Bearer {token}"})
    return r.status_code, r.json()


def _utc(value: str) -> datetime:
    assert value.endswith(("Z", "+00:00")), value
    return datetime.fromisoformat(value)


async def _expired(conn: AsyncConnection, day: int, approver: str) -> None:
    """Một lá E6 có phiếu `timeout` giao cho `approver` (+ điểm log 4 `approval_required`)."""
    ticket = await seed.leaf_ticket(
        conn, created_at=at(day), exit_code="E6", final_state="S_ESCALATED", resolution_path="escalated"
    )
    await seed.approval(conn, ticket, approver_id=approver, created_at=at(day), status="timeout")
    await seed.audit_point4(conn, ticket, created_at=at(day), policy_decision="approval_required", matched_rule_id="R10")


async def test_manager_business_all_keys(rw: AsyncEngine, env: Http) -> None:
    async with rw.begin() as conn:
        await seed.leaf_ticket(conn, created_at=at(1), final_state="S_RESOLVED", resolution_path="auto")
    status, body = await _get(env, BUSINESS, await env.token(MANAGER), **win(1))
    assert status == 200, body
    assert body["scope"] == "all"
    assert set(body["metrics"]) == set(business.BUSINESS_METRICS)
    assert (_utc(body["from"]), _utc(body["to"])) == (datetime(2031, 3, 1, tzinfo=UTC), datetime(2031, 3, 2, tzinfo=UTC))
    assert body["unavailable"] == []
    assert body["metrics"]["automation_rate"] == 1.0
    assert body["metrics"]["e3_cases"] == {"items": [], "truncated": False}
    # Review PR #30 (nhỏ): thêm vài giá trị tính tay — 1 lá đã xong, không exit_code / E6 / dòng ghi đè.
    counts = {k: body["metrics"][k] for k in ("escalation_rate_raw", "approval_expired_count", "override_count")}
    assert counts == {"escalation_rate_raw": 0.0, "approval_expired_count": 0, "override_count": 0}


async def test_l1_own_exact_keys(rw: AsyncEngine, env: Http) -> None:
    async with rw.begin() as conn:
        await _expired(conn, 2, L1_A)
    status, body = await _get(env, BUSINESS, await env.token("ha.lt"), **win(2))
    assert status == 200, body
    assert body["scope"] == "own"
    assert set(body["metrics"]) == set(business.OWN_KEYS)
    assert body["metrics"]["approval_expired_count"] == 1


async def test_two_l1_isolated(rw: AsyncEngine, env: Http) -> None:
    """Ngày 3: L1 A có 2 lá E6, L1 B có 1 → mỗi người thấy đúng số của mình (bỏ lọc own thì cả hai ra 3)."""
    async with rw.begin() as conn:
        await _expired(conn, 3, L1_A)
        await _expired(conn, 3, L1_A)
        await _expired(conn, 3, L1_B)
    for username, expected in (("ha.lt", 2), ("duc.pv", 1)):
        status, body = await _get(env, BUSINESS, await env.token(username), **win(3))
        assert (status, body["metrics"]["approval_expired_count"]) == (200, expected), username


async def test_l1_cannot_widen_scope(rw: AsyncEngine, env: Http) -> None:
    """Duyệt plan A3: L1 gửi `?approver_id=<L1 khác>&scope=all` vẫn chỉ nhận số của mình (ngày 4: A 1 lá, B 2 lá)."""
    async with rw.begin() as conn:
        await _expired(conn, 4, L1_A)
        await _expired(conn, 4, L1_B)
        await _expired(conn, 4, L1_B)
    status, body = await _get(env, BUSINESS, await env.token("ha.lt"), approver_id=L1_B, scope="all", **win(4))
    assert status == 200, body
    assert (body["scope"], set(body["metrics"])) == ("own", set(business.OWN_KEYS))
    assert body["metrics"]["approval_expired_count"] == 1


async def test_ai_all_keys_and_unavailable(rw: AsyncEngine, env: Http) -> None:
    async with rw.begin() as conn:
        await seed.leaf_ticket(conn, created_at=at(5), exit_code="E9", final_state="S_ESCALATED", resolution_path="escalated")
    status, body = await _get(env, AI, await env.token(MANAGER), **win(5))
    assert status == 200, body
    assert set(body["metrics"]) == set(ai.AI_METRICS)
    pending = ["multi_intent_first_stop_to_reply_s", "multi_intent_messages_per_turn"]
    assert body["unavailable"] == pending
    assert [body["metrics"][k] for k in pending] == [None, None]
    assert body["metrics"]["e9_count"] == 1
    assert body["metrics"]["e2_llm_count"] == 0  # review PR #30 (nhỏ): lá E9, không có lá E2


async def test_default_window_7_days(env: Http) -> None:
    token = await env.token(MANAGER)  # manager đăng nhập (enroll MFA) MỘT lần cho cả hai route
    for route in (BUSINESS, AI):
        status, body = await _get(env, route, token)
        assert status == 200, body
        assert (_utc(body["from"]), _utc(body["to"])) == (NOW - timedelta(days=7), NOW), route


@pytest.mark.parametrize("route", [BUSINESS, AI], ids=["business", "ai"])
async def test_window_echo_utc(env: Http, route: str) -> None:
    """Gửi `+07:00` (httpx mã hoá `+` thành `%2B`) → trả lại UTC, ở cả hai route (review PR #30: `/ai`)."""
    params = {"from": "2031-03-06T07:00:00+07:00", "to": "2031-03-07T07:00:00+07:00"}
    status, body = await _get(env, route, await env.token(MANAGER), **params)
    assert status == 200, body
    assert (_utc(body["from"]), _utc(body["to"])) == (datetime(2031, 3, 6, tzinfo=UTC), datetime(2031, 3, 7, tzinfo=UTC))


@pytest.mark.parametrize("route", ["business", "ai"])
async def test_routes_run_in_snapshot(env: Http, monkeypatch: pytest.MonkeyPatch, route: str) -> None:
    """Hàm truy vấn của route được thay bằng hàm đọc mức cô lập / read-only / role NGAY TRÊN `conn` route truyền vào →
    `('repeatable read', 'on', 'app_monitor')`."""
    seen: list[tuple[Any, ...]] = []

    async def spy_business(conn: AsyncConnection, frm: datetime, to: datetime, **_: Any) -> business.BusinessMetrics:
        seen.append(tuple((await conn.execute(text(SNAPSHOT_SQL))).one()))
        return business.BusinessMetrics(values=dict.fromkeys(business.BUSINESS_METRICS), unavailable=())

    async def spy_ai(conn: AsyncConnection, frm: datetime, to: datetime) -> ai.AiMetrics:
        seen.append(tuple((await conn.execute(text(SNAPSHOT_SQL))).one()))
        return ai.AiMetrics(values=dict.fromkeys(ai.AI_METRICS), unavailable=())

    if route == "business":
        monkeypatch.setattr("app.api.dashboard.business_metrics", spy_business)
    else:
        monkeypatch.setattr("app.api.dashboard.ai_metrics", spy_ai)
    status, body = await _get(env, BUSINESS if route == "business" else AI, await env.token(MANAGER), **win(7))
    assert status == 200, body
    assert seen == [("repeatable read", "on", "app_monitor")]


async def _e9_leaf(conn: AsyncConnection, day: int) -> None:
    await seed.leaf_ticket(conn, created_at=at(day), exit_code="E9", final_state="S_ESCALATED", resolution_path="escalated")


@pytest.mark.parametrize("route", ["business", "ai"])
async def test_response_is_one_snapshot(
    rw: AsyncEngine, env: Http, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """Review PR #30 (6): một response = MỘT snapshot. Truy vấn của chỉ số đầu tiên (không pending) được bọc: chạy truy vấn gốc
    trên `conn` của route (chốt snapshot), rồi — chỉ lần đầu — COMMIT thêm dữ liệu vào cửa sổ bằng giao dịch app_rw RIÊNG. Các
    chỉ số tính sau trong CÙNG response không được thấy dòng mới; GET lần hai thì thấy (dòng đã commit thật — test không rỗng).
    Mỗi chỉ số một giao dịch (commit giữa các chỉ số) thì response đầu đã thấy.

    business (ngày 9/3): 1 lá `S_RESOLVED`/auto; chen 1 lá E6 có phiếu `timeout` → trước 1,0 / 0,0 / 0, sau 0,5 / 0,5 / 1.
    ai (ngày 10/3): 1 lá E9; chen thêm 1 lá E9 → `e9_count` trước 1, sau 2."""
    watch: tuple[str, ...]
    before: tuple[Any, ...]
    after: tuple[Any, ...]
    if route == "business":
        day, path, queries, keys = 9, BUSINESS, business.QUERIES, business.BUSINESS_METRICS
        watch = ("automation_rate", "escalation_rate_raw", "approval_expired_count")
        before, after = (1.0, 0.0, 0), (0.5, 0.5, 1)
    else:
        day, path, queries, keys = 10, AI, ai.QUERIES, ai.AI_METRICS
        watch, before, after = ("e9_count",), (1,), (2,)
    async with rw.begin() as conn:
        if route == "business":
            await seed.leaf_ticket(conn, created_at=at(day), final_state="S_RESOLVED", resolution_path="auto")
        else:
            await _e9_leaf(conn, day)
    key = next(k for k in keys if not is_pending(k))
    original = queries[key]
    assert original is not None
    writes: list[str] = []

    async def write_between(conn: AsyncConnection, frm: datetime, to: datetime, **kw: Any) -> Any:
        got = await original(conn, frm, to, **kw)
        if not writes:
            async with rw.begin() as other:
                await (_expired(other, day, L1_A) if route == "business" else _e9_leaf(other, day))
            writes.append(key)
        return got

    monkeypatch.setitem(queries, key, write_between)
    token = await env.token(MANAGER)
    seen: list[tuple[Any, ...]] = []
    for _ in range(2):
        status, body = await _get(env, path, token, **win(day))
        assert status == 200, body
        seen.append(tuple(body["metrics"][k] for k in watch))
    assert writes == [key]
    assert seen == [before, after]
