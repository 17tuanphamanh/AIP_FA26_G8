"""Job worker (P1 mục 7): quét hạn chờ → timeout qua đúng `deliver_event`; job lỗi không sập."""

from datetime import timedelta

import pytest
from app.db.runtime import DueWait
from app.domain.states import S_CLARIFYING, S_ESCALATED, S_PENDING_APPROVAL, S_RESOLVED
from app.graph.late_event import deliver_event
from app.graph.worker_jobs import WorkerJobs
from tests.fakes.graph import GraphHarness


def jobs(h: GraphHarness) -> WorkerJobs:
    return WorkerJobs(h.runner, h.deadlines, h.turns)


@pytest.mark.asyncio
async def test_clarify_deadline_fires_once_as_e4() -> None:
    h = GraphHarness()
    await h.submit("t1", b11_slots="missing")
    h.clock.advance(timedelta(hours=23))
    assert (await jobs(h).scan_deadlines()).delivered == 0
    h.clock.advance(timedelta(hours=2))
    report = await jobs(h).scan_deadlines()
    assert report.delivered == 1
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["exit_code"]) == (S_ESCALATED, "E4")
    assert (await jobs(h).scan_deadlines()).delivered == 0  # đã đánh dấu fired_at
    assert h.audit.of("t1", "late_event") == []


@pytest.mark.asyncio
async def test_approval_deadline_fires_e6_and_closes_approval() -> None:
    h = GraphHarness()
    await h.submit("t1")
    h.clock.advance(timedelta(minutes=31))
    assert (await jobs(h).scan_deadlines()).delivered == 1
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["exit_code"]) == (S_ESCALATED, "E6")
    assert h.approvals._table["1"]["status"] == "timeout"
    assert h.executor.calls["t1"] == 0


@pytest.mark.asyncio
async def test_confirm_deadline_auto_closes_48h() -> None:
    h = GraphHarness()
    await h.submit("t1", b12_assess="auto")
    h.clock.advance(timedelta(hours=49))
    await jobs(h).scan_deadlines()
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["close_reason"]) == (
        S_RESOLVED, "resolved_auto_timeout_48h")


@pytest.mark.asyncio
async def test_timeout_after_ticket_moved_on_is_late_from_worker() -> None:
    h = GraphHarness()
    await h.submit("t1", b11_slots=["missing", "complete"])
    await deliver_event(h.runner, "t1", S_CLARIFYING, {"kind": "user_reply", "text": "x"})
    # ticket đã sang chờ duyệt; hạn clarify (24 giờ) đến trước hạn duyệt (30 phút tính từ lúc này)
    h.approvals._table["1"]["deadline"] += timedelta(days=1)
    h.clock.advance(timedelta(hours=24, minutes=1))
    report = await jobs(h).scan_deadlines()
    assert (report.delivered, report.late) == (0, 1)
    [late] = h.audit.of("t1", "late_event")
    assert late["detail"]["source"] == "worker" and late["step"] == "B11"
    assert (await h.runner.snapshot("t1")).values["status"] == S_PENDING_APPROVAL
    assert (await jobs(h).scan_deadlines()).late == 0  # đã đánh dấu, không bắn lại


@pytest.mark.asyncio
async def test_new_clarify_round_supersedes_old_deadline() -> None:
    h = GraphHarness()
    await h.submit("t1", b11_slots="missing")
    h.clock.advance(timedelta(hours=20))
    await deliver_event(h.runner, "t1", S_CLARIFYING, {"kind": "user_reply", "text": "x"})
    h.clock.advance(timedelta(hours=5))  # hạn vòng 1 đã qua, vòng 2 còn 19 giờ
    assert (await jobs(h).scan_deadlines()).delivered == 0
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["clarification_turns"]) == (S_CLARIFYING, 2)


@pytest.mark.asyncio
async def test_one_bad_item_does_not_stop_the_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    h = GraphHarness()
    await h.submit("t1", b11_slots="missing")
    await h.submit("t2", b11_slots="missing")
    real_due = h.deadlines.due

    async def due_with_ghost(now, limit):  # type: ignore[no-untyped-def]
        return [DueWait("khong-co", "clarify", "x"), *await real_due(now, limit)]

    monkeypatch.setattr(h.deadlines, "due", due_with_ghost)
    real_resume = h.runner.resume_locked

    async def boom_for_t1(ticket_id, event, **kw):  # type: ignore[no-untyped-def]
        if ticket_id == "t1":
            raise RuntimeError("hỏng")
        return await real_resume(ticket_id, event, **kw)

    monkeypatch.setattr(h.runner, "resume_locked", boom_for_t1)
    h.clock.advance(timedelta(hours=25))
    report = await jobs(h).scan_deadlines()
    assert (report.delivered, report.late, report.failed) == (1, 1, 1)
    assert (await h.runner.snapshot("t2")).values["exit_code"] == "E4"


@pytest.mark.asyncio
async def test_busy_ticket_is_retried_next_cycle() -> None:
    h = GraphHarness(lock_timeout=0.05)
    await h.submit("t1", b11_slots="missing")
    h.clock.advance(timedelta(hours=25))
    async with h.lock.hold("t1"):
        report = await jobs(h).scan_deadlines()
    assert report.busy == 1
    assert (await jobs(h).scan_deadlines()).delivered == 1


@pytest.mark.asyncio
async def test_stale_turn_scan_skips_fresh_turns() -> None:
    h = GraphHarness()
    await h.submit("t1")
    assert await jobs(h).scan_stale_turns() == 0
