"""Lượt `submit` của API chạy nền (2b-3, chốt g): `tickets.create` (ticket + lượt, một transaction) →
`runner.run_new`. Process chết giữa hai bước → worker phục hồi từ dòng `tickets`, giữ `turn_id`;
`run_new` tới muộn không bao giờ chạy lại từ START đè lên thread đang có."""

from datetime import timedelta
from typing import Any, cast

import pytest
from app.db.tickets import NewTicket
from app.domain.states import S_ESCALATED, S_PENDING_APPROVAL
from app.graph.worker_jobs import WorkerJobs
from tests.fakes.graph import Crash, GraphHarness
from tests.fakes.identity import REQUESTER, SESSION


async def _create(h: GraphHarness, ticket: str, turn: str) -> None:
    await h.tickets.create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee",
                  requester_dept="it", session_id=SESSION, redacted_request="VPN lỗi",
                  created_at=h.clock.now()),
        turn_id=turn,
    )  # fmt: skip


def _jobs(h: GraphHarness) -> WorkerJobs:
    return WorkerJobs(h.runner, h.deadlines, h.turns, stale_after=timedelta(minutes=2))


def _identity_rows(h: GraphHarness, ticket: str) -> int:
    return len(h.audit.of(ticket, "identity_established"))


@pytest.mark.asyncio
async def test_run_new_runs_initial_state_from_ticket_row() -> None:
    h = GraphHarness()
    await _create(h, "t1", "turn-1")
    r = await h.runner.run_new("t1", "turn-1")
    assert r is not None and (r.status, r.turn_id) == (S_PENDING_APPROVAL, "turn-1")
    assert r.values["redacted_request"] == "VPN lỗi" and r.values["session_id"] == SESSION
    assert h.turns.rows["turn-1"]["ended_at"] is not None


@pytest.mark.asyncio
async def test_crash_before_first_checkpoint_recovers() -> None:
    """Process chết sau khi commit `tickets.create`, trước khi task nền kịp chạy: lượt mở, snapshot
    rỗng → worker chạy state đầu với CÙNG turn_id."""
    h = GraphHarness()
    await _create(h, "t1", "turn-1")  # task nền chưa bao giờ chạy
    h.restart(can_execute=False)  # "process mới" (worker)
    h.clock.advance(timedelta(minutes=3))
    assert await _jobs(h).scan_stale_turns() == 1
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["turn_id"]) == (S_PENDING_APPROVAL, "turn-1")
    assert h.approvals.count("t1") == 1
    assert [t["turn_id"] for t in h.turns.of("t1")] == ["turn-1"]
    assert h.turns.rows["turn-1"]["ended_at"] is not None


@pytest.mark.asyncio
async def test_background_after_recover_noop() -> None:
    """Lượt đầu chết GIỮA chừng (đã có checkpoint của B1…): `run_new` tới lần nữa không được chạy lại
    từ START; recover chạy tiếp đúng chỗ."""
    h = GraphHarness()
    await _create(h, "t1", "turn-1")
    h.approvals.crash_on_create = True
    with pytest.raises(Crash):
        await h.runner.run_new("t1", "turn-1")
    assert _identity_rows(h, "t1") == 1
    h.restart()
    assert await h.runner.run_new("t1", "turn-1") is None  # thread đã có state → không đụng
    assert _identity_rows(h, "t1") == 1
    h.clock.advance(timedelta(minutes=3))
    await _jobs(h).scan_stale_turns()
    snap = await h.runner.snapshot("t1")
    assert snap.values["status"] == S_PENDING_APPROVAL
    assert _identity_rows(h, "t1") == 1 and h.approvals.count("t1") == 1


@pytest.mark.asyncio
async def test_run_new_on_closed_turn_is_noop() -> None:
    h = GraphHarness()
    await _create(h, "t1", "turn-1")
    await h.runner.run_new("t1", "turn-1")
    assert await h.runner.run_new("t1", "turn-1") is None
    assert _identity_rows(h, "t1") == 1


@pytest.mark.asyncio
async def test_create_is_atomic() -> None:
    """Lượt không ghi được (turn_id trùng) → không có dòng ticket (bản giả làm như transaction SQL)."""
    h = GraphHarness()
    await _create(h, "t1", "turn-1")
    with pytest.raises(ValueError, match="PK turns"):
        await _create(h, "t2", "turn-1")
    assert "t2" not in h.tickets.rows


def _assert_e9_once(h: GraphHarness, ticket: str, turn: str) -> dict[str, object]:
    final = h.tickets.final(ticket)
    assert final is not None and (final.final_state, final.exit_code) == (S_ESCALATED, "E9")
    [esc] = h.escalations.of(ticket)
    assert (esc["exit_code"], esc["reason_detail"]) == ("E9", "recover_exhausted")
    assert [t["turn_id"] for t in h.turns.of(ticket)] == [turn]
    assert h.turns.rows[turn]["ended_at"] is not None and h.turns.rows[turn]["recover_attempts"] == 4
    assert h.notifier.count(ticket) == 1  # đúng 1 tin E9 cho người dùng
    [row] = h.audit.of(ticket, "recover_exhausted")
    assert (row["from_status"], row["to_status"], row["exit_code"]) == ("S_NEW", S_ESCALATED, "E9")
    return row


async def _die_four_times(h: GraphHarness) -> None:
    with pytest.raises(Crash):
        await h.runner.run_new("t1", "turn-1")
    for _ in range(3):
        h.clock.advance(timedelta(minutes=3))
        with pytest.raises(Crash):
            await _jobs(h).scan_stale_turns()
    h.clock.advance(timedelta(minutes=3))
    assert await _jobs(h).scan_stale_turns() == 1


@pytest.mark.asyncio
async def test_killed_in_b1_every_time_goes_e9() -> None:
    """2b-Q6: process chết giữa B1 ở lượt đầu và cả 3 lần phục hồi → lần quét thứ 4 ra E9
    `recover_exhausted` qua B20. (LangGraph đã ghi checkpoint input trước B1 → đường `_give_up`.)"""
    h = GraphHarness()
    h.ad.crash = Crash("SIGKILL giữa B1")
    await _create(h, "t1", "turn-1")
    await _die_four_times(h)
    row = _assert_e9_once(h, "t1", "turn-1")
    detail = cast(dict[str, Any], row["detail"])
    assert detail["node"] == "b01_identity" and "no_checkpoint" not in detail
    assert h.ad.calls == 4  # B1 chạy 4 lần; lần thứ 5 bẻ thẳng sang B20


@pytest.mark.asyncio
async def test_killed_before_first_checkpoint_every_time_goes_e9() -> None:
    """Khe hẹp hơn: chết TRƯỚC checkpoint đầu tiên (sau commit `tickets.create`) cả 4 lần → thread
    rỗng. Không được đóng lượt bỏ rơi ticket: dựng state từ dòng `tickets` → E9 → B20."""
    h = GraphHarness()
    real_get, deaths = h.tickets.get, [4]

    async def dying_get(ticket_id: str) -> object:  # bước ngay trước ainvoke của state đầu
        if deaths[0] > 0:
            deaths[0] -= 1
            raise Crash("SIGKILL trước checkpoint đầu")
        return await real_get(ticket_id)

    h.tickets.get = dying_get  # type: ignore[method-assign,assignment]
    await _create(h, "t1", "turn-1")
    await _die_four_times(h)
    row = _assert_e9_once(h, "t1", "turn-1")
    assert cast(dict[str, Any], row["detail"]).items() >= {"recover_attempts": 3, "node": "b01_identity",
                                     "no_checkpoint": True}.items()  # fmt: skip
    assert h.ad.calls == 0  # B1 chưa từng chạy
