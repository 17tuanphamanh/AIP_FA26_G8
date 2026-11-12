"""Phase 4 chặng 4c DỪNG 1 trên Postgres 16 thật — SQL mới/đổi của 4c (PLAN-4c S2):

- c4: HAI worker (hai `SqlDeadlineStore`, hai engine) cùng quét → mỗi mốc nhắc đúng 1 thông báo / người (`mark_reminder_once` =
  câu SQL P3 nguyên văn: `… reminder_n_at IS NULL AND deadline > :now RETURNING …`).
- `due_reminders` lọc thô (pending, chưa tới hạn, đã qua mốc 1, còn cột NULL); `mark_reminder_once` không nhắc sau hạn / phiếu đã đóng /
  cột đã có (M-4c-1b, M-4c-2b chết ở đây — `mutate_4c.py --integration`).
- `SqlApprovals.close` trả số dòng (0/1) + `decided_at` (TQ-4, d1); `SqlDeadlineStore.mark_fired` đóng phiếu `timeout` + `decided_at` (d1).
- B16 từ chối qua graph trên PG: `approvals.note`, cột `audit_logs.note`, tin nhắn cùng bản đã che (Q-4c-1); điểm log 6.

`approvals.created_at` = `now()` của Postgres (A12, TQ-6) → test đặt lại bằng SQL theo FakeClock.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.approval.store import NoticeKind, SqlApprovals
from app.core.clock import FakeClock
from app.core.hashing import hash_action
from app.db.runtime import DueReminder, DueWait, ReminderTarget, SqlDeadlineStore
from app.db.tickets import NewTicket, SqlTicketStore
from app.domain.action import Action
from app.domain.states import S_PENDING_APPROVAL, S_REJECTED
from app.graph.late_event import deliver_event
from app.graph.worker_jobs import WorkerJobs
from app.settings import get_action_metadata
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import (
    APPROVER,
    REQUESTER,
    SESSION,
    open_pg_runtime,
    scalar,
    seed_users,
)
from tests.integration.pg import PgUrls, alembic_config, fresh_database

T0 = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
SLA = timedelta(minutes=30)
BACKUP = "l1-bk"
PHONE = "0912345678"


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)
    async with engine.begin() as conn:
        await conn.execute(text(
            f"INSERT INTO users (user_id, username, role) VALUES ('{BACKUP}', 'graph.l1bk', 'l1') ON CONFLICT DO NOTHING"
        ))  # fmt: skip
    yield engine
    await engine.dispose()


def _ticket(ticket_id: str, at: datetime) -> NewTicket:
    return NewTicket(ticket_id=ticket_id, requester_id=REQUESTER, requester_role="employee", requester_dept="it",
                     session_id=SESSION, redacted_request="VPN", created_at=at)  # fmt: skip


async def _approval(rw: AsyncEngine, *, created: datetime = T0, backup: str | None = BACKUP) -> str:
    """Phiếu `pending` tạo ở `created` (đặt lại `created_at` — server default là giờ Postgres), hạn `created + SLA`."""
    ticket = f"tk-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(_ticket(ticket, created), turn_id=f"turn-{uuid4().hex[:8]}")
    aid = await SqlApprovals(rw).create(ticket, APPROVER, created + SLA, "h" * 64, backup_approver_id=backup,
                                        conflict_detected=False, conflict_type=None)  # fmt: skip
    async with rw.begin() as conn:
        await conn.execute(text("UPDATE approvals SET created_at = :c WHERE approval_id = :a"), {"c": created, "a": int(aid)})
    return aid


async def _row(rw: AsyncEngine, sql: str, **params: Any) -> dict[str, Any]:
    async with rw.connect() as conn:
        return dict((await conn.execute(text(sql), params)).mappings().one())


# ---- mark_reminder_once / due_reminders (SQL P3) ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_reminder_once_first_wins_second_none(rw: AsyncEngine) -> None:
    """`reminder_n_at IS NULL`: lần 1 trả người nhận (+ dự phòng), lần 2 None, giá trị cột giữ lần 1 (M-4c-1b)."""
    aid, store = await _approval(rw), SqlDeadlineStore(rw)
    at = T0 + timedelta(minutes=15)
    assert await store.mark_reminder_once(aid, 1, at) == ReminderTarget(APPROVER, BACKUP)
    assert await store.mark_reminder_once(aid, 1, at + timedelta(minutes=1)) is None
    assert await scalar(rw, "SELECT reminder_1_at = :a AND reminder_2_at IS NULL FROM approvals WHERE approval_id = :i",
                        a=at, i=int(aid))  # fmt: skip
    assert await store.mark_reminder_once(aid, 2, T0 + timedelta(minutes=24)) == ReminderTarget(APPROVER, BACKUP)


@pytest.mark.asyncio
@pytest.mark.parametrize("after", [timedelta(0), timedelta(seconds=1)], ids=["dung-han", "qua-han"])
async def test_mark_reminder_once_not_at_or_after_deadline(rw: AsyncEngine, after: timedelta) -> None:
    """`deadline > :now` (M-4c-2b): đúng hạn hoặc quá hạn → None, cột vẫn NULL; `due_reminders` không trả phiếu đó."""
    aid, store = await _approval(rw), SqlDeadlineStore(rw)
    now = T0 + SLA + after
    assert await store.mark_reminder_once(aid, 1, now) is None
    assert await store.mark_reminder_once(aid, 2, now) is None
    assert await scalar(rw, "SELECT reminder_1_at IS NULL AND reminder_2_at IS NULL FROM approvals WHERE approval_id = :i",
                        i=int(aid))  # fmt: skip
    assert aid not in {d.approval_id for d in await store.due_reminders(now, 500)}


@pytest.mark.asyncio
async def test_mark_reminder_once_skips_closed_approval(rw: AsyncEngine) -> None:
    aid, store = await _approval(rw), SqlDeadlineStore(rw)
    assert await SqlApprovals(rw).close(aid, "approved", T0 + timedelta(minutes=5), decided_by=APPROVER) == 1
    assert await store.mark_reminder_once(aid, 1, T0 + timedelta(minutes=15)) is None
    assert aid not in {d.approval_id for d in await store.due_reminders(T0 + timedelta(minutes=15), 500)}


@pytest.mark.asyncio
async def test_due_reminders_filter(rw: AsyncEngine) -> None:
    """Trước m1 → không; sau m1 → có (đủ trường); cả hai cột đã đặt → không."""
    aid, store = await _approval(rw), SqlDeadlineStore(rw)

    async def ids(minutes: float) -> set[str]:
        return {d.approval_id for d in await store.due_reminders(T0 + timedelta(minutes=minutes), 500)}

    assert aid not in await ids(14.9)
    [due] = [d for d in await store.due_reminders(T0 + timedelta(minutes=15), 500) if d.approval_id == aid]
    assert (due.created_at, due.deadline, due.reminder_1_at, due.reminder_2_at) == (T0, T0 + SLA, None, None)
    await store.mark_reminder_once(aid, 1, T0 + timedelta(minutes=15))
    await store.mark_reminder_once(aid, 2, T0 + timedelta(minutes=24))
    assert aid not in await ids(25)


# ---- c4: hai worker ---------------------------------------------------------------------------------------------------------


class RacingStore(SqlDeadlineStore):
    """Ép đúng ca xấu nhất: cả hai worker ĐỌC `due_reminders` (đều thấy cột NULL) rồi mới cùng `mark_reminder_once` — chỉ câu
    UPDATE có điều kiện (`IS NULL … RETURNING`) chặn được gửi trùng (M-4c-1b chết tất định, không nhờ may rủi lịch chạy)."""

    def __init__(self, engine: AsyncEngine, barrier: asyncio.Barrier) -> None:
        super().__init__(engine)
        self.barrier = barrier

    async def due_reminders(self, now: datetime, limit: int) -> list[DueReminder]:
        rows = await super().due_reminders(now, limit)
        await self.barrier.wait()
        return rows


@pytest.mark.asyncio
async def test_c4_two_workers_one_notification_per_milestone(db: PgUrls, rw: AsyncEngine) -> None:
    """c4: hai worker (hai engine) cùng quét mỗi mốc → mỗi người nhận đúng 1 thông báo / mốc."""
    aid = await _approval(rw)
    sent: list[tuple[str, str, str]] = []

    async def record(approval_id: str, user_id: str, kind: NoticeKind) -> str:
        sent.append((approval_id, user_id, kind))
        return "x"

    clock, barrier = FakeClock(T0), asyncio.Barrier(2)
    other = create_async_engine(db.role("app_rw"))
    try:
        async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
            workers = [WorkerJobs(rt.runner, store, rt.turns, notify_approver=record)
                       for store in (RacingStore(rw, barrier), RacingStore(other, barrier))]  # fmt: skip
            for minute in (15, 16, 24, 25, 29):
                clock.set(T0 + timedelta(minutes=minute))
                reports = await asyncio.wait_for(asyncio.gather(*(w.scan_deadlines() for w in workers)), 30)
                assert all(r.reminder_failed == 0 for r in reports)
    finally:
        await other.dispose()
    mine = [s for s in sent if s[0] == aid]
    assert mine == [(aid, APPROVER, "reminder_1"), (aid, APPROVER, "reminder_2"), (aid, BACKUP, "reminder_2")]


# ---- d1 + TQ-4: decided_at, close trả số dòng ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_returns_rowcount_and_sets_decided_at(rw: AsyncEngine) -> None:
    aid, at = await _approval(rw), T0 + timedelta(minutes=3)
    assert await SqlApprovals(rw).close(aid, "rejected", at, decided_by=APPROVER, note="không") == 1
    assert await SqlApprovals(rw).close(aid, "approved", at + timedelta(minutes=1), decided_by=APPROVER) == 0
    row = await SqlApprovals(rw).get(aid)
    assert row is not None and (row.status, row.decided_at, row.note) == ("rejected", at, "không")


@pytest.mark.asyncio
async def test_d1_mark_fired_timeout_sets_decided_at(rw: AsyncEngine) -> None:
    """d1 (A11): nhánh worker đóng phiếu (ticket đã đi tiếp) đặt `decided_at`."""
    aid = await _approval(rw)
    ticket = await scalar(rw, "SELECT ticket_id FROM approvals WHERE approval_id = :i", i=int(aid))
    at = T0 + SLA + timedelta(seconds=20)
    await SqlDeadlineStore(rw).mark_fired(DueWait(ticket, "approval", aid), at)
    row = await SqlApprovals(rw).get(aid)
    assert row is not None and (row.status, row.decided_at) == ("timeout", at)


# ---- B16 từ chối qua graph (Q-4c-1 điều kiện, c2) -------------------------------------------------------------------------------


def _vpn_action() -> Action:
    m = get_action_metadata().of("vpn")["renew_vpn_cert"]
    return Action(
        type="renew_vpn_cert", target="device:LAP-0501", requested_for=REQUESTER, scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": "LAP-0501"}, facts={"device_owner_is_requester": True},
    )  # fmt: skip


@pytest.mark.asyncio
async def test_b16_rejection_pg_note_masked_everywhere_point6(db: PgUrls, rw: AsyncEngine) -> None:
    clock = FakeClock(T0)
    ticket, turn = f"tk-{uuid4().hex[:8]}", f"turn-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(_ticket(ticket, clock.now()), turn_id=turn)
    action = _vpn_action()
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        await rt.runner.run_new(ticket, turn)
        snap = await rt.runner.snapshot(ticket)
        assert snap.values["status"] == S_PENDING_APPROVAL
        aid = str(snap.values["approval_id"])
        await rt.runner.graph.aupdate_state(rt.runner.config(ticket),
                                            {"intended_action": action, "action_plan_hash": hash_action(action)})  # fmt: skip
        async with rw.begin() as conn:
            await conn.execute(text("UPDATE approvals SET created_at = :c WHERE approval_id = :a"), {"c": T0, "a": int(aid)})
        clock.advance(timedelta(seconds=75))
        ev = {"kind": "rejected", "note": f"gọi {PHONE}", "approver_id": APPROVER, "at": clock.now().isoformat(),
              "reason_code": "wrong_device", "view_duration": None, "decided_as": "primary"}  # fmt: skip
        await deliver_event(rt.runner, ticket, S_PENDING_APPROVAL, ev)
        snap = await rt.runner.snapshot(ticket)
        assert snap.values["status"] == S_REJECTED
        [msg] = [m for m in snap.values["conversation"] if m.get("kind") == "rejection"]
        sent = [t for tid, t, _ in rt.notifier.sent if tid == ticket]
    masked = "gọi <SĐT_1>"
    assert sent == [msg["text"]] and msg["text"].endswith(f"Ghi chú của người duyệt: {masked}")
    audit = await _row(rw, "SELECT approval_result, note, response_time_seconds, detail FROM audit_logs "
                           "WHERE ticket_id = :t AND step = 'B16'", t=ticket)  # fmt: skip
    assert (audit["approval_result"], audit["note"], audit["response_time_seconds"]) == ("rejected", masked, 75.0)
    assert audit["detail"] == {"view_duration": None, "decided_without_view": True, "decided_as": "primary",
                               "reason_code": "wrong_device", "close_applied": 1, "note_suppressed": False,
                               "approver_id": APPROVER}  # fmt: skip  — E12 (12/11): + người đã bấm
    approval = await _row(rw, "SELECT note, decided_at FROM approvals WHERE approval_id = :a", a=int(aid))
    assert (approval["note"], approval["decided_at"]) == (masked, T0 + timedelta(seconds=75))
    assert await scalar(rw, "SELECT count(*) FROM side_effects WHERE ticket_id = :t AND kind = 'notify_user' AND step = 'B16'",
                        t=ticket) == 1  # fmt: skip
    leaks = await scalar(rw, "SELECT count(*) FROM audit_logs WHERE ticket_id = :t AND (note LIKE :p OR detail::text LIKE :p)",
                         t=ticket, p=f"%{PHONE}%")  # fmt: skip
    assert leaks == 0 and PHONE not in repr(snap.values["conversation"])
