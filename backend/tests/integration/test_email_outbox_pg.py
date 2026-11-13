"""Notify-email trên Postgres 16 thật: migration 0012 lên/xuống, đồng bộ `users.email`, `email_outbox` ghi CÙNG transaction
`effects.once` (rollback → không dòng; chạy lại → không trùng), skipped (thiếu email / có bí mật + `security_events`), ticket con không
email, thông báo người duyệt (B15 + nhắc), job `send_emails` (sent / thử lại theo backoff / failed sau 5 lần / SKIP LOCKED), đọc cho API.
Mỗi module một database riêng (`fresh_database`)."""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.audit.security_events import SecurityEventWriter
from app.auth.models import UserSync
from app.auth.store import SqlAuthStore
from app.auth.user_sync import AdUserSync, LockPolicy
from app.core.clock import FakeClock
from app.db.runtime import SqlEffectStore, bind_effect
from app.graph.fakes import LoggingNotifier
from app.guard.privacy import RegexPrivacyGuard
from app.notify.child import ChildAwareNotifier
from app.notify.notifier import ApproverEmailNotice, EmailingApprovals, EmailingNotifier
from app.notify.outbox import SqlEmailOutbox, recent_outbox
from app.notify.smtp import EMAIL_CLAIM_LEASE, EMAIL_MAX_ATTEMPTS, EmailSendJob, backoff
from app.settings import Settings
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.pg import PgUrls, alembic_config, fresh_database

NOW = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)
BASE = "https://desk.congty-abc.vn"
BODY = "Đã reset phiên VPN của bạn. Vui lòng kết nối lại."
REQ, REQ_NO_MAIL, APPROVER, APPROVER_NO_MAIL = "em_req", "em_req_nomail", "em_l1", "em_l1_nomail"
REQ_MAIL, APPROVER_MAIL = "an.nv@congty-abc.vn", "ha.lt@congty-abc.vn"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbiJ9.c2lnbmF0dXJlLXRlc3Q"


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO users (user_id, username, role, email) VALUES "
            f"('{REQ}', 'em.req', 'employee', '{REQ_MAIL}'), ('{REQ_NO_MAIL}', 'em.req2', 'employee', NULL), "
            f"('{APPROVER}', 'em.l1', 'l1', '{APPROVER_MAIL}'), ('{APPROVER_NO_MAIL}', 'em.l1b', 'l1', NULL) "
            "ON CONFLICT DO NOTHING"
        ))  # fmt: skip
    yield engine
    await engine.dispose()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def outbox(rw: AsyncEngine, clock: FakeClock) -> SqlEmailOutbox:
    guard = RegexPrivacyGuard.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    return SqlEmailOutbox(rw, guard, clock, BASE)


async def _ticket(rw: AsyncEngine, requester: str = REQ, *, parent: str | None = None, ticket_id: str | None = None) -> str:
    ticket = ticket_id or str(uuid4())
    async with rw.begin() as conn:
        await conn.execute(
            text("INSERT INTO tickets (ticket_id, parent_ticket_id, requester_id, requester_role, redacted_request) "
                 "VALUES (:t, :p, :u, 'employee', 'yêu cầu thử')"),
            {"t": ticket, "p": parent, "u": requester},
        )  # fmt: skip
    return ticket


async def _approval(rw: AsyncEngine, ticket: str, approver: str = APPROVER) -> str:
    async with rw.begin() as conn:
        row = await conn.execute(
            text("INSERT INTO approvals (ticket_id, approver_id, deadline, action_plan_hash) "
                 "VALUES (:t, :a, :d, :h) RETURNING approval_id"),
            {"t": ticket, "a": approver, "d": NOW + timedelta(minutes=30), "h": "a" * 64},
        )  # fmt: skip
        return str(row.scalar_one())


async def _rows(rw: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with rw.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def _outbox_of(rw: AsyncEngine, ticket: str) -> list[Any]:
    return await _rows(rw, "SELECT * FROM email_outbox WHERE ticket_id = :t ORDER BY id", t=ticket)


def _key() -> str:
    return uuid4().hex + uuid4().hex


async def _notify_once(
    rw: AsyncEngine, outbox: SqlEmailOutbox, ticket: str, key: str, *, step: str = "B18", text_: str = BODY,
    boom: bool = False,
) -> str | None:  # fmt: skip
    """Như `effects.once("notify_user")` của runtime: `ChildAwareNotifier(EmailingNotifier(LoggingNotifier))` trong `run_once`."""
    notifier = ChildAwareNotifier.on_engine(rw, EmailingNotifier(LoggingNotifier(), outbox))

    async def call() -> str:
        with bind_effect(step, key):
            ref = await notifier.notify_user(ticket, text_, "confirm")
        if boom:
            raise RuntimeError("process chết sau khi ghi, trước commit")
        return ref

    return await SqlEffectStore(rw).run_once(key=key, ticket_id=ticket, kind="notify_user", step=step, turn_id="turn-1", call=call)


# ---- migration 0012 -------------------------------------------------------------------------------------------------


def _state(url: str) -> dict[str, Any]:
    engine = create_engine(url)
    with engine.connect() as conn:
        q = conn.execute
        col = q(text("SELECT data_type, character_maximum_length, is_nullable FROM information_schema.columns "
                     "WHERE table_name = 'users' AND column_name = 'email'")).first()  # fmt: skip
        table = q(text("SELECT to_regclass('public.email_outbox')")).scalar()
        privs = {}
        if table is not None:
            for role, priv in (("app_rw", "SELECT"), ("app_rw", "INSERT"), ("app_rw", "UPDATE"), ("app_rw", "DELETE"),
                               ("app_monitor", "SELECT")):  # fmt: skip
                privs[(role, priv)] = q(text("SELECT has_table_privilege(:r, 'email_outbox', :p)"), {"r": role, "p": priv}).scalar()
            privs[("app_rw", "SEQ")] = q(text("SELECT has_sequence_privilege('app_rw', 'email_outbox_id_seq', 'USAGE')")).scalar()
        version = q(text("SELECT version_num FROM alembic_version")).scalar()
    engine.dispose()
    return {"email": None if col is None else tuple(col), "table": table is not None, "privs": privs, "version": version}


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_migration_0012_up_down_up(pg: PgUrls) -> None:
    with fresh_database(pg) as fresh:
        cfg, url = alembic_config(fresh), fresh.role("app_migrate")
        command.upgrade(cfg, "0012")  # D-67: head nay là 0013 — kiểm đúng mốc 0012
        up = _state(url)
        assert up["version"] == "0012"
        assert up["email"] == ("character varying", 254, "YES")
        assert up["table"] is True
        assert up["privs"] == {
            ("app_rw", "SELECT"): True, ("app_rw", "INSERT"): True, ("app_rw", "UPDATE"): True, ("app_rw", "DELETE"): False,
            ("app_monitor", "SELECT"): False, ("app_rw", "SEQ"): True,
        }  # fmt: skip
        command.downgrade(cfg, "0011")
        assert _state(url) == {"email": None, "table": False, "privs": {}, "version": "0011"}
        command.upgrade(cfg, "0012")
        assert _state(url) == up


# ---- E2: đồng bộ email -----------------------------------------------------------------------------------------------


def _sync(user_id: str, email: str | None) -> UserSync:
    return UserSync(
        user_id=user_id, username=user_id.replace("_", "."), full_name=None, role="employee", department="it",
        manager_id=None, employment_status="active", hired_at=None, is_privileged_account=False, synced_at=NOW, email=email,
    )  # fmt: skip


@pytest.mark.asyncio


async def test_upsert_user_copies_valid_email_else_null(rw: AsyncEngine) -> None:
    store = SqlAuthStore(rw)
    uid = f"sync_{uuid4().hex[:8]}"
    get = "SELECT email FROM users WHERE user_id = :u"
    await store.upsert_user(_sync(uid, f"  {REQ_MAIL} "))
    assert (await _rows(rw, get, u=uid))[0].email == REQ_MAIL
    await store.upsert_user(_sync(uid, "khong-phai-email"))  # sai dạng → NULL, không lỗi
    assert (await _rows(rw, get, u=uid))[0].email is None
    await store.upsert_user(_sync(uid, APPROVER_MAIL))
    await store.upsert_user(_sync(uid, None))  # AD bỏ trường → NULL
    assert (await _rows(rw, get, u=uid))[0].email is None


@dataclass(frozen=True)
class AdWithEmail:
    user_id: str
    username: str
    groups: list[str]
    email: str | None
    manager_id: str | None = None
    department: str = "it"
    full_name: str = "Người thử"
    employment_status: str = "active"
    hired_at: date = date(2024, 1, 1)
    is_privileged_account: bool = False


@pytest.mark.asyncio


async def test_ad_sync_carries_email_into_users(rw: AsyncEngine, clock: FakeClock) -> None:
    sync = AdUserSync(
        store=SqlAuthStore(rw), sink=SecurityEventWriter(rw, clock), username_key=b"k" * 32,
        lock=LockPolicy(failure_window=timedelta(minutes=10), max_failures=5, lockout=timedelta(minutes=15)),
    )  # fmt: skip
    uid = f"ad_{uuid4().hex[:8]}"

    async def no_lookup(_user_id: str) -> None:
        return None

    await sync.sync_user_from_ad(no_lookup, AdWithEmail(uid, f"{uid}.nv", ["IT-Users"], REQ_MAIL), NOW)  # type: ignore[arg-type]
    assert (await _rows(rw, "SELECT email FROM users WHERE user_id = :u", u=uid))[0].email == REQ_MAIL


# ---- E3/E4: ghi outbox cùng transaction ------------------------------------------------------------------------------


@pytest.mark.asyncio


async def test_outbox_row_in_effect_tx_with_effect_key(rw: AsyncEngine, outbox: SqlEmailOutbox) -> None:
    ticket, key = await _ticket(rw), _key()
    assert await _notify_once(rw, outbox, ticket, key) == f"noop:{ticket}"  # tin chat như cũ
    (row,) = await _outbox_of(rw, ticket)
    assert (row.status, row.kind, row.recipient_user_id, row.effect_key, row.attempts) == ("pending", "result", REQ, key, 0)
    assert row.subject == f"[IT Service Desk] Kết quả xử lý yêu cầu của bạn — {ticket[:8].upper()}"
    assert row.body == f"{BODY}\n\nXem chi tiết: {BASE}/chat/{ticket}"
    assert REQ_MAIL not in row.body
    assert await _rows(rw, "SELECT 1 FROM side_effects WHERE effect_key = :k", k=key)


@pytest.mark.asyncio


async def test_rerun_same_effect_no_duplicate(rw: AsyncEngine, outbox: SqlEmailOutbox) -> None:
    ticket, key = await _ticket(rw), _key()
    await _notify_once(rw, outbox, ticket, key)
    await _notify_once(rw, outbox, ticket, key)  # effects.once: đã làm → không gọi lại
    first = await outbox.enqueue_user(ticket_id=ticket, kind="result", text=BODY, effect_key=key)  # gọi thẳng: UNIQUE chặn
    rows = await _outbox_of(rw, ticket)
    assert len(rows) == 1 and first == rows[0].id


@pytest.mark.asyncio


async def test_rollback_leaves_no_row(rw: AsyncEngine, outbox: SqlEmailOutbox) -> None:
    ticket, key = await _ticket(rw), _key()
    with pytest.raises(RuntimeError):
        await _notify_once(rw, outbox, ticket, key, boom=True)
    assert await _outbox_of(rw, ticket) == []
    assert await _rows(rw, "SELECT 1 FROM side_effects WHERE effect_key = :k", k=key) == []


@pytest.mark.asyncio


async def test_b11_question_never_queued(rw: AsyncEngine, outbox: SqlEmailOutbox) -> None:
    ticket = await _ticket(rw)
    await _notify_once(rw, outbox, ticket, _key(), step="B11", text_="Bạn dùng VPN trên máy nào?")
    assert await _outbox_of(rw, ticket) == []


@pytest.mark.asyncio


async def test_skipped_without_email(rw: AsyncEngine, outbox: SqlEmailOutbox) -> None:
    ticket = await _ticket(rw, REQ_NO_MAIL)
    await _notify_once(rw, outbox, ticket, _key(), step="B20")
    (row,) = await _outbox_of(rw, ticket)
    assert (row.status, row.last_error_class, row.kind) == ("skipped", "NoRecipientEmail", "escalation")


@pytest.mark.asyncio


async def test_secret_in_body_skipped_and_audited_once(rw: AsyncEngine, outbox: SqlEmailOutbox) -> None:
    ticket, key = await _ticket(rw), _key()
    await _notify_once(rw, outbox, ticket, key, text_=f"Token của bạn: {JWT}")
    await outbox.enqueue_user(ticket_id=ticket, kind="result", text=f"Token của bạn: {JWT}", effect_key=key)  # lần hai
    (row,) = await _outbox_of(rw, ticket)
    assert (row.status, row.last_error_class) == ("skipped", "SecretInBody")
    assert JWT not in row.body and "[BÍ_MẬT_ĐÃ_ẨN]" in row.body
    events = await _rows(rw, "SELECT detail FROM security_events WHERE event_type = 'privacy_secret_redacted' AND ticket_id = :t", t=ticket)
    assert [e.detail for e in events] == [{"source": "email_outbox", "email_kind": "result", "secrets_found": 1}]


@pytest.mark.asyncio


async def test_child_ticket_no_email(rw: AsyncEngine, outbox: SqlEmailOutbox) -> None:
    parent = await _ticket(rw)
    child = await _ticket(rw, parent=parent)
    ref = await _notify_once(rw, outbox, child, _key())
    assert ref is not None and ref.startswith("notice:")  # D-31: con để lại notice
    assert await _outbox_of(rw, child) == [] and await _outbox_of(rw, parent) == []
    assert await outbox.enqueue_user(ticket_id=child, kind="result", text=BODY, effect_key=_key()) is None  # lớp thứ hai


@pytest.mark.asyncio


async def test_outbox_error_does_not_break_chat(rw: AsyncEngine, clock: FakeClock) -> None:
    class Boom:
        def redact_text(self, text: str) -> Any:
            raise OSError("guard hỏng")

    ticket, key = await _ticket(rw), _key()
    broken = SqlEmailOutbox(rw, Boom(), clock, BASE)  # type: ignore[arg-type]
    assert await _notify_once(rw, broken, ticket, key) == f"noop:{ticket}"  # effect vẫn commit, tin chat như cũ
    assert await _outbox_of(rw, ticket) == []
    assert await _rows(rw, "SELECT 1 FROM side_effects WHERE effect_key = :k", k=key)


# ---- người duyệt -----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio


async def test_approver_new_in_effect_and_reminders_once(rw: AsyncEngine, outbox: SqlEmailOutbox) -> None:
    ticket = await _ticket(rw)
    approval = await _approval(rw, ticket)
    approvals = EmailingApprovals(rw, ApproverEmailNotice(outbox))
    key = _key()

    async def call() -> str:
        with bind_effect("B15", key):
            return await approvals.notify_approver(approval, APPROVER)

    ref = await SqlEffectStore(rw).run_once(key=key, ticket_id=ticket, kind="notify_approver", step="B15", turn_id="t", call=call)
    assert ref == f"log:{approval}"  # result_ref như 2b
    notice = ApproverEmailNotice(outbox)
    await notice(approval, APPROVER, "reminder_1")
    await notice(approval, APPROVER, "reminder_1")  # worker chạy lại: không trùng
    await notice(approval, APPROVER_NO_MAIL, "reminder_2")
    rows = await _outbox_of(rw, ticket)
    assert [(r.kind, r.recipient_user_id, r.status) for r in rows] == [
        ("approval_new", APPROVER, "pending"), ("approval_reminder_1", APPROVER, "pending"),
        ("approval_reminder_2", APPROVER_NO_MAIL, "skipped"),
    ]  # fmt: skip
    assert rows[0].effect_key == key
    assert rows[0].body.endswith(f"Xem chi tiết: {BASE}/approvals/{approval}")
    assert "Hạn phê duyệt: 10:30 24/10/2026" in rows[0].body


# ---- E5: worker gửi ---------------------------------------------------------------------------------------------------


class RecSender:
    def __init__(self, fail: Exception | None = None) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    async def send(self, to: str, subject: str, body: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append((to, subject, body))


async def _drain(rw: AsyncEngine) -> None:
    """Đóng mọi dòng pending của test trước — job chỉ thấy dòng của test này."""
    async with rw.begin() as conn:
        await conn.execute(text("UPDATE email_outbox SET status = 'skipped' WHERE status = 'pending'"))


# be-pii-uuid: ĐÚNG mã ticket từng làm test này đỏ ngẫu nhiên — "0-8471-62786" trong UUID bị che thành <SĐT_1> ở link email
PHONE_LIKE_UUID = "23d1ce34-f9e3-43b0-8471-62786daeeefe"


@pytest.mark.asyncio


async def test_job_sends_pending_and_marks_sent(rw: AsyncEngine, outbox: SqlEmailOutbox, clock: FakeClock) -> None:
    await _drain(rw)
    ticket = await _ticket(rw, ticket_id=PHONE_LIKE_UUID)
    await _notify_once(rw, outbox, ticket, _key())
    sender = RecSender()
    report = await EmailSendJob(outbox, sender, clock).run()
    assert report.sent == 1
    assert sender.sent == [(REQ_MAIL, f"[IT Service Desk] Kết quả xử lý yêu cầu của bạn — {ticket[:8].upper()}",
                            f"{BODY}\n\nXem chi tiết: {BASE}/chat/{ticket}")]  # fmt: skip
    assert "<SĐT" not in sender.sent[0][2] and f"/chat/{PHONE_LIKE_UUID}" in sender.sent[0][2]  # link nguyên vẹn
    (row,) = await _outbox_of(rw, ticket)
    assert (row.status, row.sent_at, row.attempts) == ("sent", NOW, 0)
    assert (await EmailSendJob(outbox, sender, clock).run()).sent == 0  # không gửi lại


@pytest.mark.asyncio


async def test_job_retry_backoff_then_failed(rw: AsyncEngine, outbox: SqlEmailOutbox, clock: FakeClock) -> None:
    await _drain(rw)
    ticket = await _ticket(rw)
    await _notify_once(rw, outbox, ticket, _key())
    job = EmailSendJob(outbox, RecSender(fail=ConnectionRefusedError()), clock)
    for n in range(1, EMAIL_MAX_ATTEMPTS):
        await job.run()
        (row,) = await _outbox_of(rw, ticket)
        assert (row.status, row.attempts, row.last_error_class) == ("pending", n, "ConnectionRefusedError")
        assert row.next_attempt_at == clock.now() + backoff(n)
        assert (await job.run()).retried == 0  # chưa tới lượt: không lấy
        clock.advance(backoff(n))
    await job.run()
    (row,) = await _outbox_of(rw, ticket)
    assert (row.status, row.attempts, row.sent_at) == ("failed", EMAIL_MAX_ATTEMPTS, None)
    clock.advance(timedelta(days=1))
    assert (await job.run()).failed == 0  # failed không bao giờ được lấy lại


@pytest.mark.asyncio


async def test_job_skips_when_email_removed_before_send(rw: AsyncEngine, outbox: SqlEmailOutbox, clock: FakeClock) -> None:
    await _drain(rw)
    uid = f"gone_{uuid4().hex[:6]}"
    async with rw.begin() as conn:
        await conn.execute(text(f"INSERT INTO users (user_id, username, role, email) VALUES ('{uid}', '{uid}', 'employee', 'x@congty-abc.vn')"))
    ticket = await _ticket(rw, uid)
    await _notify_once(rw, outbox, ticket, _key())
    async with rw.begin() as conn:
        await conn.execute(text("UPDATE users SET email = NULL WHERE user_id = :u"), {"u": uid})
    sender = RecSender()
    assert (await EmailSendJob(outbox, sender, clock).run()).skipped == 1
    assert sender.sent == [] and (await _outbox_of(rw, ticket))[0].status == "skipped"


@pytest.mark.asyncio


async def test_claim_skip_locked_and_lease(rw: AsyncEngine, outbox: SqlEmailOutbox, clock: FakeClock) -> None:
    await _drain(rw)
    tickets = [await _ticket(rw) for _ in range(3)]
    for t in tickets:
        await _notify_once(rw, outbox, t, _key())
    ids = sorted([r.id for t in tickets for r in await _outbox_of(rw, t)])
    async with rw.connect() as other:  # worker khác đang giữ khoá dòng đầu
        tx = await other.begin()
        await other.execute(text("SELECT id FROM email_outbox WHERE id = :i FOR UPDATE"), {"i": ids[0]})
        claimed = await outbox.claim(clock.now(), 20, EMAIL_CLAIM_LEASE)
        await tx.rollback()
    assert sorted(c.id for c in claimed) == ids[1:]
    assert all(c.address == REQ_MAIL for c in claimed)
    again = await outbox.claim(clock.now(), 20, EMAIL_CLAIM_LEASE)  # dòng đã lấy đang trong hạn giữ chỗ
    assert [c.id for c in again] == [ids[0]]
    assert len(await outbox.claim(clock.now(), 1, EMAIL_CLAIM_LEASE)) == 0


@pytest.mark.asyncio


async def test_batch_limit_20(rw: AsyncEngine, outbox: SqlEmailOutbox, clock: FakeClock) -> None:
    await _drain(rw)
    ticket = await _ticket(rw)
    for _ in range(23):
        await outbox.enqueue_user(ticket_id=ticket, kind="result", text=BODY, effect_key=_key())
    sender = RecSender()
    assert (await EmailSendJob(outbox, sender, clock).run()).sent == 20
    assert (await EmailSendJob(outbox, sender, clock).run()).sent == 3


# ---- E7: đọc cho API --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio


async def test_recent_outbox_reads_without_body(rw: AsyncEngine, outbox: SqlEmailOutbox) -> None:
    ticket = await _ticket(rw)
    await _notify_once(rw, outbox, ticket, _key())
    rows = await recent_outbox(rw, 200)
    mine = [r for r in rows if r.address == REQ_MAIL]
    assert mine and not hasattr(mine[0], "body") and not hasattr(mine[0], "subject")
    assert all(r.status == "failed" for r in await recent_outbox(rw, 200, "failed"))
