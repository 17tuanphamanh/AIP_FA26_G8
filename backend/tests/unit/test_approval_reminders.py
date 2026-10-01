"""Nhắc duyệt 50 %/80 % — Phase 4 chặng 4c P3 (phase4 6.1, 6.2 c3), Q-4c-2 = A (truy vấn trên `DeadlineStore`), test d2, d3, d5, d6.

- Mốc: m1 = created_at + 0,5·SLA, m2 = created_at + 0,8·SLA (biên `>=`); tới hạn thì không nhắc.
- Nhắc chạy Ở CUỐI `WorkerJobs.scan_deadlines`; lỗi bắt riêng (`reminder_failed`), không làm hỏng phần quét hạn.
- Nhắc 1 → người duyệt; nhắc 2 → người duyệt + dự phòng (nếu có). Qua m2 mà chưa nhắc 1 → CHỈ nhắc 2, cả hai cột có giá trị.
- Gửi qua MỘT hàm (`approval.store.log_approver_notice`, mặc định của `WorkerJobs`) — B15 gọi `notify_approver` không truyền `kind`
  vẫn như 4b (d3).

Bản giả `MemoryDeadlines` mang cùng ngữ nghĩa câu SQL; câu SQL thật kiểm ở `integration/test_b16_reminders_pg.py` (c4).
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from app.approval.store import NoticeKind, SqlApprovals, log_approver_notice
from app.db.runtime import DueReminder, DueWait, ReminderTarget
from app.domain.approval import ReminderN, next_reminder
from app.domain.states import S_ESCALATED, S_PENDING_APPROVAL
from app.graph.worker_jobs import WorkerJobs
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.fakes.graph import GraphHarness, MemoryDeadlines

APPROVER, BACKUP = "l1-fake", "l1_02"
T0 = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
SLA = timedelta(minutes=30)


# ---- next_reminder (thuần) --------------------------------------------------------------------------------------------------


def _m(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.mark.parametrize(
    ("now", "r1", "r2", "expected"),
    [
        pytest.param(_m(14), None, None, None, id="truoc-moc-1"),
        pytest.param(_m(15), None, None, 1, id="dung-moc-1-bien-bao-gom"),
        pytest.param(_m(16), _m(15), None, None, id="da-nhac-1"),
        pytest.param(_m(23.9), _m(15), None, None, id="truoc-moc-2"),
        pytest.param(_m(24), _m(15), None, 2, id="dung-moc-2"),
        pytest.param(_m(24), None, None, 2, id="qua-moc-2-chua-nhac-1-chi-nhac-2"),
        pytest.param(_m(25), None, _m(24), None, id="sau-moc-2-khong-bao-gio-nhac-1"),
        pytest.param(_m(25), _m(15), _m(24), None, id="da-nhac-ca-hai"),
        pytest.param(_m(30), _m(15), None, None, id="dung-han-khong-nhac"),
        pytest.param(_m(30), None, None, None, id="dung-han-chua-nhac-gi"),
        pytest.param(_m(31), None, None, None, id="qua-han"),
    ],
)
def test_next_reminder_table(now: datetime, r1: datetime | None, r2: datetime | None, expected: ReminderN | None) -> None:
    assert next_reminder(T0, T0 + SLA, r1, r2, now) == expected


def test_next_reminder_dev_sla_2_minutes() -> None:
    """`APPROVAL_SLA_MINUTES_DEV=2` (gate4 g4-03): nhắc 1 ở 60 s, nhắc 2 ở 96 s."""
    deadline = T0 + timedelta(minutes=2)
    assert next_reminder(T0, deadline, None, None, T0 + timedelta(seconds=59)) is None
    assert next_reminder(T0, deadline, None, None, T0 + timedelta(seconds=60)) == 1
    assert next_reminder(T0, deadline, T0, None, T0 + timedelta(seconds=96)) == 2


# ---- WorkerJobs + bản giả -----------------------------------------------------------------------------------------------------


def _jobs(h: GraphHarness, deadlines: Any = None) -> WorkerJobs:
    return WorkerJobs(h.runner, deadlines or h.deadlines, h.turns, notify_approver=h.approvals.notify_approver)


async def _pending(h: GraphHarness, ticket: str = "t1", *, backup: str | None = BACKUP) -> dict[str, Any]:
    await h.submit(ticket)
    snap = await h.runner.snapshot(ticket)
    assert snap.values["status"] == S_PENDING_APPROVAL
    row = h.deadlines.approvals[str(snap.values["approval_id"])]
    row["backup_approver_id"] = backup
    assert row["deadline"] - row["created_at"] == SLA  # SLA_MINUTES của policy.json (B15 giả)
    return row


@pytest.mark.asyncio
async def test_c3_reminders_once_each_at_15_and_24_none_at_deadline() -> None:
    """c3 (FakeClock, SLA 30): quét ở 14/15/16/24/25/30 phút → nhắc 1 đúng 1 lần ở 15 (người duyệt); nhắc 2 đúng 1 lần ở 24
    (người duyệt + dự phòng); không nhắc ở hạn."""
    h = GraphHarness()
    row = await _pending(h)
    created = row["created_at"]
    seen: dict[int, list[tuple[str, str, str]]] = {}
    counts: dict[int, int] = {}
    for minute in (14, 15, 16, 24, 25, 30):
        h.clock.set(created + timedelta(minutes=minute))
        report = await _jobs(h).scan_deadlines()
        seen[minute], counts[minute] = list(h.approvals.reminded), report.reminded
        assert report.reminder_failed == 0
    r1 = [("1", APPROVER, "reminder_1")]
    r2 = [("1", APPROVER, "reminder_2"), ("1", BACKUP, "reminder_2")]
    assert seen == {14: [], 15: r1, 16: r1, 24: r1 + r2, 25: r1 + r2, 30: r1 + r2}
    assert counts == {14: 0, 15: 1, 16: 0, 24: 2, 25: 0, 30: 0}
    assert (row["reminder_1_at"], row["reminder_2_at"]) == (created + timedelta(minutes=15), created + timedelta(minutes=24))
    assert row["status"] == "pending"
    h.clock.set(created + timedelta(minutes=31))
    report = await _jobs(h).scan_deadlines()
    assert (report.delivered, report.reminded) == (1, 0)
    assert (await h.runner.snapshot("t1")).values["exit_code"] == "E6"
    assert h.approvals.reminded == r1 + r2


@pytest.mark.asyncio
async def test_d5_reminder_2_without_backup_notifies_approver_only() -> None:
    h = GraphHarness()
    row = await _pending(h, backup=None)
    h.clock.set(row["created_at"] + timedelta(minutes=24))
    await _jobs(h).scan_deadlines()
    assert h.approvals.reminded == [("1", APPROVER, "reminder_2")]


@pytest.mark.asyncio
async def test_d6_worker_down_past_m2_sends_only_reminder_2_sets_both_columns() -> None:
    """d6 (P3): worker chết từ trước m1 tới sau m2 → chỉ nhắc 2 (2 người), cả `reminder_1_at` lẫn `reminder_2_at` có giá trị; quét
    lại không gửi gì thêm."""
    h = GraphHarness()
    row = await _pending(h)
    now = row["created_at"] + timedelta(minutes=25)
    h.clock.set(now)
    report = await _jobs(h).scan_deadlines()
    assert h.approvals.reminded == [("1", APPROVER, "reminder_2"), ("1", BACKUP, "reminder_2")]
    assert report.reminded == 2
    assert (row["reminder_1_at"], row["reminder_2_at"]) == (now, now)
    h.clock.advance(timedelta(minutes=1))
    assert (await _jobs(h).scan_deadlines()).reminded == 0
    assert len(h.approvals.reminded) == 2


@pytest.mark.asyncio
async def test_d6_other_worker_marked_2_but_not_1_yet_no_late_reminder_1() -> None:
    """Chen giữa hai câu P3 (worker khác đã đặt `reminder_2_at`, chưa kịp ghi sổ `reminder_1_at`) → không gửi nhắc 1 muộn."""
    h = GraphHarness()
    row = await _pending(h)
    row["reminder_2_at"] = row["created_at"] + timedelta(minutes=24)
    h.clock.set(row["created_at"] + timedelta(minutes=25))
    assert (await _jobs(h).scan_deadlines()).reminded == 0
    assert h.approvals.reminded == []


@pytest.mark.asyncio
async def test_reminder_skips_closed_approval() -> None:
    h = GraphHarness()
    row = await _pending(h)
    row.update(status="approved", decided_at=row["created_at"])
    h.clock.set(row["created_at"] + timedelta(minutes=20))
    assert (await _jobs(h).scan_deadlines()).reminded == 0
    assert h.approvals.reminded == []


# ---- d2: lỗi phần nhắc không làm hỏng phần quét hạn --------------------------------------------------------------------------


class BrokenReminders:
    """`DeadlineStore` bọc bản giả: hỏng `due_reminders` hoặc `mark_reminder_once` của một số phiếu."""

    def __init__(self, inner: MemoryDeadlines, *, fail_due: bool = False, fail_ids: tuple[str, ...] = ()) -> None:
        self.inner, self.fail_due, self.fail_ids = inner, fail_due, fail_ids

    async def set(self, ticket_id: str, kind: str, deadline: datetime, created_turn: str) -> str:
        return await self.inner.set(ticket_id, kind, deadline, created_turn)

    async def due(self, now: datetime, limit: int) -> list[DueWait]:
        return await self.inner.due(now, limit)

    async def mark_fired(self, due: DueWait, at: datetime) -> None:
        await self.inner.mark_fired(due, at)

    async def due_reminders(self, now: datetime, limit: int) -> list[DueReminder]:
        if self.fail_due:
            raise RuntimeError("db lỗi khi đọc nhắc")
        return await self.inner.due_reminders(now, limit)

    async def mark_reminder_once(self, approval_id: str, n: ReminderN, now: datetime) -> ReminderTarget | None:
        if approval_id in self.fail_ids:
            raise RuntimeError("db lỗi khi đánh dấu nhắc")
        return await self.inner.mark_reminder_once(approval_id, n, now)


@pytest.mark.asyncio
async def test_d2_reminder_query_error_does_not_break_deadline_scan() -> None:
    h = GraphHarness()
    await _pending(h, "t1")
    h.clock.advance(timedelta(minutes=31))
    report = await _jobs(h, BrokenReminders(h.deadlines, fail_due=True)).scan_deadlines()
    assert (report.delivered, report.failed, report.reminder_failed) == (1, 0, 1)
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["exit_code"]) == (S_ESCALATED, "E6")


@pytest.mark.asyncio
async def test_d2_one_approval_error_other_still_reminded() -> None:
    h = GraphHarness()
    first = await _pending(h, "t1")
    await _pending(h, "t2")
    h.clock.set(first["created_at"] + timedelta(minutes=16))
    report = await _jobs(h, BrokenReminders(h.deadlines, fail_ids=("1",))).scan_deadlines()
    assert (report.reminded, report.reminder_failed) == (1, 1)
    assert h.approvals.reminded == [("2", APPROVER, "reminder_1")]


@pytest.mark.asyncio
async def test_d2_notify_error_counted_not_raised() -> None:
    h = GraphHarness()
    row = await _pending(h)
    h.clock.set(row["created_at"] + timedelta(minutes=16))

    async def broken(approval_id: str, approver_id: str, kind: NoticeKind) -> str:
        raise RuntimeError("kênh thông báo lỗi")

    report = await WorkerJobs(h.runner, h.deadlines, h.turns, notify_approver=broken).scan_deadlines()
    assert (report.reminded, report.reminder_failed) == (0, 1)
    assert row["reminder_1_at"] is not None  # đánh dấu TRƯỚC, gửi SAU (TQ-7 — tối đa 1 lần)


# ---- d3: B15 không truyền kind; một hàm log --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d3_b15_notify_without_kind_unchanged() -> None:
    h = GraphHarness()
    row = await _pending(h)
    assert h.approvals.notified == [("1", APPROVER)]
    h.clock.set(row["created_at"] + timedelta(minutes=24))
    await _jobs(h).scan_deadlines()
    assert h.approvals.notified == [("1", APPROVER)]  # nhắc không chen vào danh sách của B15
    assert h.effects.count("t1", "notify_approver") == 1
    store = SqlApprovals(cast(AsyncEngine, None))  # notify không đụng DB
    assert await store.notify_approver("7", "l1_01") == "log:7"  # result_ref như 4b
    assert await store.notify_approver("7", "l1_01", "reminder_1") == "log:7:reminder_1"


@pytest.mark.asyncio
async def test_d3_default_worker_notice_is_shared_log(caplog: pytest.LogCaptureFixture) -> None:
    """Q-4c-2 điều kiện: worker mặc định gửi qua `log_approver_notice` — MỘT hàm với `SqlApprovals.notify_approver`."""
    assert WorkerJobs.__init__.__kwdefaults__ is not None
    assert WorkerJobs.__init__.__kwdefaults__["notify_approver"] is log_approver_notice
    h = GraphHarness()
    row = await _pending(h)
    h.clock.set(row["created_at"] + timedelta(minutes=16))
    with caplog.at_level(logging.INFO, logger="app.approval.store"):
        report = await WorkerJobs(h.runner, h.deadlines, h.turns).scan_deadlines()
    assert report.reminded == 1
    assert any("reminder_1" in r.getMessage() and APPROVER in r.getMessage() for r in caplog.records)
