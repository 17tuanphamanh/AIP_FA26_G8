"""B1 trên Postgres 16 thật (B01 mục 11 — integration): `SqlIdentityReads` (phiên theo họ token,
`locked_until`), `AlertWriter` (khoá (rule_id, subject, window_start) — migration 0004, Q1), B1 chạy
trong runtime thật (`AsyncPostgresSaver`, audit, store SQL) với AD giả qua registry thật.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.audit.alerts import AlertWriter
from app.core.clock import FakeClock
from app.db.identity import SqlIdentityReads
from app.domain.alerts import BRUTEFORCE_RULE_ID, SYSTEM_SUBJECT, AlertDraft
from app.domain.states import S_BLOCKED, S_ESCALATED, S_PENDING_APPROVAL
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.graph import LOCKOUT
from tests.fakes.identity import FakeAd, ad_user
from tests.integration.graph_pg import (
    REQUESTER,
    SESSION,
    create_ticket,
    open_pg_runtime,
    scalar,
    seed_users,
)
from tests.integration.pg import PgUrls, alembic_config, fresh_database

NOW = datetime(2026, 9, 26, 8, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


async def _exec(engine: AsyncEngine, sql: str, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


async def _session(
    engine: AsyncEngine, sid: str, family: str, *, expires: datetime, revoked: str | None = None
) -> None:
    await _exec(
        engine,
        "INSERT INTO sessions (session_id, user_id, token_family_id, expires_at, revoked_at, "
        "revoke_reason) VALUES (:s, :u, CAST(:f AS uuid), :e, :r, :why)",
        s=sid, u=REQUESTER, f=family, e=expires, r=NOW if revoked else None, why=revoked,
    )  # fmt: skip


async def _ticket(engine: AsyncEngine) -> str:
    ticket = f"b1-{uuid4().hex[:12]}"
    await create_ticket(engine, ticket)
    return ticket


# ---- SqlIdentityReads ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_session_follows_token_family(rw: AsyncEngine) -> None:
    reads = SqlIdentityReads(rw)
    fam, later = str(uuid4()), NOW + timedelta(hours=8)
    await _session(rw, "fam-old", fam, expires=later, revoked="rotated")
    await _session(rw, "fam-new", fam, expires=later)
    live = await reads.active_session("fam-old", NOW)
    assert live is not None and (live.session_id, live.user_id) == ("fam-old", REQUESTER)

    await _exec(rw, "UPDATE sessions SET revoked_at = :t, revoke_reason = 'logout' "
                    "WHERE session_id = 'fam-new'", t=NOW)  # fmt: skip
    assert await reads.active_session("fam-old", NOW) is None
    assert await reads.active_session("fam-new", NOW) is None
    assert await reads.active_session("khong-co", NOW) is None

    await _session(rw, "short", str(uuid4()), expires=NOW + timedelta(minutes=1))
    assert await reads.active_session("short", NOW) is not None
    assert await reads.active_session("short", NOW + timedelta(minutes=1)) is None  # hết hạn


@pytest.mark.asyncio
async def test_locked_until_is_utc(rw: AsyncEngine) -> None:
    reads = SqlIdentityReads(rw)
    await _exec(rw, "UPDATE users SET locked_until = NULL WHERE user_id = :u", u=REQUESTER)
    assert await reads.locked_until(REQUESTER) is None
    await _exec(rw, "UPDATE users SET locked_until = :t WHERE user_id = :u", t=NOW, u=REQUESTER)
    value = await reads.locked_until(REQUESTER)
    assert value == NOW and value is not None and value.tzinfo is UTC
    assert await reads.locked_until("khong-co") is None
    await _exec(rw, "UPDATE users SET locked_until = NULL WHERE user_id = :u", u=REQUESTER)


# ---- AlertWriter + khoá (rule_id, subject, window_start) ------------------------------------


@pytest.mark.asyncio
async def test_alert_writer_idempotent_per_subject(rw: AsyncEngine) -> None:
    writer = AlertWriter(rw, FakeClock(NOW))
    window = NOW + timedelta(days=1)  # khác mọi test khác trong module
    a = AlertDraft("rule_x", "nv001", window, "critical", detail={"source": "login"})
    b = AlertDraft("rule_x", "nv002", window, "critical")
    assert await writer.raise_once(a) is True
    assert await writer.raise_once(a) is False  # chạy lại / nơi thứ hai → không thêm dòng
    assert await writer.raise_once(b) is True  # người khác, cùng thời điểm → dòng riêng (Q1)
    count = await scalar(rw, "SELECT count(*) FROM alerts WHERE rule_id = 'rule_x'")
    assert count == 2
    assert await scalar(rw, "SELECT detail->>'source' FROM alerts WHERE subject = 'nv001' "
                            "AND rule_id = 'rule_x'") == "login"  # fmt: skip


@pytest.mark.asyncio
async def test_alert_subject_has_no_default(rw: AsyncEngine) -> None:
    """INSERT quên `subject` phải lỗi (M9 viết SQL cho 14 luật — quên subject = gộp cảnh báo = FN);
    luật tổng hợp truyền `SYSTEM_SUBJECT` tường minh."""
    window = NOW + timedelta(days=2)
    with pytest.raises(IntegrityError, match="subject"):
        await _exec(rw, "INSERT INTO alerts (rule_id, severity, window_start) "
                        "VALUES ('agg', 'warning', :w)", w=window)  # fmt: skip
    writer = AlertWriter(rw, FakeClock(NOW))
    assert await writer.raise_once(AlertDraft("agg", SYSTEM_SUBJECT, window, "warning")) is True
    assert await writer.raise_once(AlertDraft("agg", SYSTEM_SUBJECT, window, "warning")) is False
    assert await scalar(rw, "SELECT subject FROM alerts WHERE rule_id = 'agg'") == ""


def test_migration_0004_down_refuses_clashing_rows_then_clean_roundtrip(pg: PgUrls) -> None:
    with fresh_database(pg) as fresh:
        cfg = alembic_config(fresh)
        command.upgrade(cfg, "0004")
        rw = create_engine(fresh.role("app_rw"))
        insert = text("INSERT INTO alerts (rule_id, subject, severity, window_start) "
                      "VALUES ('r', :s, 'critical', :w)")  # fmt: skip
        try:
            with rw.begin() as conn:
                conn.execute(insert, {"s": "nv001", "w": NOW})
                conn.execute(insert, {"s": "nv002", "w": NOW})
            with pytest.raises(RuntimeError, match="Không hạ được migration 0004.*1 cặp"):
                command.downgrade(cfg, "0003")
            with rw.begin() as conn:
                conn.execute(text("DELETE FROM alerts"))  # alerts không append-only
            command.downgrade(cfg, "0003")
            with rw.begin() as conn:  # khoá cũ (rule_id, window_start) quay lại
                conn.execute(text("INSERT INTO alerts (rule_id, severity, window_start) "
                                  "VALUES ('r', 'critical', :w)"), {"w": NOW})  # fmt: skip
            with pytest.raises(IntegrityError, match="uq_alerts_rule_id_window_start"), rw.begin() as c:
                c.execute(text("INSERT INTO alerts (rule_id, severity, window_start) "
                               "VALUES ('r', 'warning', :w)"), {"w": NOW})  # fmt: skip
            command.upgrade(cfg, "head")
            with rw.begin() as conn:
                conn.execute(insert, {"s": "nv009", "w": NOW})
        finally:
            rw.dispose()


# ---- B1 trong runtime thật -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b1_valid_session_on_postgres(db: PgUrls, rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    async with open_pg_runtime(db.role("app_rw"), clock=FakeClock(NOW)) as rt:
        r = await rt.runner.submit(ticket, session_id=SESSION, redacted_request="x")
        assert r.status == S_PENDING_APPROVAL
        ctx = (await rt.runner.snapshot(ticket)).values["requester_context"]  # đọc lại từ checkpoint
        assert (ctx.user_id, ctx.role, ctx.department) == (REQUESTER, "employee", "finance")
    assert await scalar(
        rw, "SELECT to_status FROM audit_logs WHERE ticket_id = :t AND step = 'B1'", t=ticket
    ) == "S_SCREENING"


@pytest.mark.asyncio
async def test_b1_revoked_session_blocks_with_audit(db: PgUrls, rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    await _session(rw, f"rv-{ticket}", str(uuid4()), expires=NOW + timedelta(hours=8), revoked="admin")
    async with open_pg_runtime(db.role("app_rw"), clock=FakeClock(NOW)) as rt:
        r = await rt.runner.submit(ticket, session_id=f"rv-{ticket}", redacted_request="x")
    assert (r.status, r.values["close_reason"]) == (S_BLOCKED, "blocked_invalid_credentials")
    async with rw.connect() as conn:
        row = (await conn.execute(text(
            "SELECT event, to_status, block_reason, close_reason FROM audit_logs "
            "WHERE ticket_id = :t AND step = 'B1'"), {"t": ticket})).one()  # fmt: skip
    assert tuple(row) == ("session_invalid", "S_BLOCKED", "invalid_credentials",
                          "blocked_invalid_credentials")  # fmt: skip


@pytest.mark.asyncio
async def test_b1_locked_user_one_alert_row_across_tickets(db: PgUrls, rw: AsyncEngine) -> None:
    lock_start = NOW - timedelta(minutes=2)
    await _exec(rw, "UPDATE users SET locked_until = :t WHERE user_id = :u",
                t=lock_start + LOCKOUT, u=REQUESTER)  # fmt: skip
    try:
        tickets = [await _ticket(rw), await _ticket(rw)]
        async with open_pg_runtime(db.role("app_rw"), clock=FakeClock(NOW)) as rt:
            for t in tickets:
                r = await rt.runner.submit(t, session_id=SESSION, redacted_request="x")
                assert (r.status, r.values["block_reason"]) == (S_BLOCKED, "repeated_auth_failure")
        rows = await scalar(
            rw, "SELECT count(*) FROM alerts WHERE rule_id = :r AND subject = :u AND window_start = :w",
            r=BRUTEFORCE_RULE_ID, u=REQUESTER, w=lock_start,
        )  # fmt: skip
        assert rows == 1
    finally:
        await _exec(rw, "UPDATE users SET locked_until = NULL WHERE user_id = :u", u=REQUESTER)


@pytest.mark.asyncio
async def test_b1_ad_down_is_e2_on_postgres(db: PgUrls, rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    ad = FakeAd(ad_user(REQUESTER))
    ad.down = True
    async with open_pg_runtime(db.role("app_rw"), clock=FakeClock(NOW), ad=ad) as rt:
        r = await rt.runner.submit(ticket, session_id=SESSION, redacted_request="x")
    assert (r.status, r.values["exit_code"]) == (S_ESCALATED, "E2")
    assert await scalar(rw, "SELECT count(*) FROM audit_logs WHERE ticket_id = :t "
                            "AND event = 'unhandled_exception'", t=ticket) == 0  # fmt: skip
    assert await scalar(rw, "SELECT exit_code FROM audit_logs WHERE ticket_id = :t "
                            "AND event = 'identity_unverifiable'", t=ticket) == "E2"  # fmt: skip


@pytest.mark.asyncio
async def test_b1_second_lock_after_expiry_gives_new_alert(db: PgUrls, rw: AsyncEngine) -> None:
    """Cùng một người bị khoá lần 2 sau khi hết khoá → dòng cảnh báo mới (2 dòng tổng)."""
    first = NOW + timedelta(days=10)  # tách khỏi các test khác trong module
    second = first + LOCKOUT + timedelta(hours=1)
    sql = "SELECT count(*) FROM alerts WHERE rule_id = :r AND subject = :u AND window_start IN (:a, :b)"
    try:
        for lock_start in (first, second):
            await _exec(rw, "UPDATE users SET locked_until = :t WHERE user_id = :u",
                        t=lock_start + LOCKOUT, u=REQUESTER)  # fmt: skip
            ticket = await _ticket(rw)
            clock = FakeClock(lock_start + timedelta(minutes=1))
            async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
                r = await rt.runner.submit(ticket, session_id=SESSION, redacted_request="x")
            assert r.values["block_reason"] == "repeated_auth_failure"
        count = await scalar(rw, sql, r=BRUTEFORCE_RULE_ID, u=REQUESTER, a=first, b=second)
        assert count == 2
    finally:
        await _exec(rw, "UPDATE users SET locked_until = NULL WHERE user_id = :u", u=REQUESTER)
