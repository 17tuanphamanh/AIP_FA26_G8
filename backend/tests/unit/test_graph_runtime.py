"""Runtime graph trên bản giả (InMemorySaver + store in-memory) — P1 mục 11 + cổng 2 (huong-dan 5.1).

Cùng các luồng chạy lại trên Postgres thật ở `tests/integration/test_graph_pg.py`.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from app.domain.states import (
    S_CLARIFYING,
    S_CLASSIFYING,
    S_CONFIRMING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
    S_REJECTED,
    S_RESOLVED,
)
from app.graph.boundary import with_error_boundary
from app.graph.late_event import (
    InvalidEvent,
    LateEvent,
    TicketNotFound,
    deliver_event,
    wake_parent,
)
from app.graph.runner import INTERRUPTED_NOTE
from app.graph.tracing import TRACEBACK_LIMIT
from langgraph.errors import GraphInterrupt
from tests.fakes.graph import Crash, GraphHarness, MemoryTicketLock

WAIT_PLANS: dict[str, dict[str, Any]] = {  # cách đưa ticket tới từng trạng thái chờ
    S_CLARIFYING: {"b11_slots": "missing"},
    S_PENDING_APPROVAL: {},
    S_CONFIRMING: {"b12_assess": "auto"},
}
WAIT_NODE = {S_CLARIFYING: "clarify_wait", S_PENDING_APPROVAL: "approval_wait",
             S_CONFIRMING: "confirm_wait"}  # fmt: skip
VALID_EVENT = {S_CLARIFYING: {"kind": "user_reply", "text": "máy LAP-1"},
               S_PENDING_APPROVAL: {"kind": "approved"}, S_CONFIRMING: {"kind": "confirmed"}}  # fmt: skip


def _open_turns(h: GraphHarness) -> list[str]:
    return [t for t, r in h.turns.rows.items() if r["ended_at"] is None]


# ---- Cổng 2: dừng ở node chờ → khởi động lại → resume đúng chỗ ------------------------------


@pytest.mark.asyncio
async def test_stops_at_approval_restart_then_resumes_at_same_place() -> None:
    h = GraphHarness()
    r = await h.submit("t1")
    assert (r.status, r.waiting_at) == (S_PENDING_APPROVAL, "approval_wait")
    h.restart()  # "khởi động lại backend": graph + runner mới, cùng checkpoint
    r = await deliver_event(h.runner, "t1", S_PENDING_APPROVAL, {"kind": "approved"})
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "confirm_wait")
    assert h.executor.calls["t1"] == 1
    h.restart()
    r = await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "confirmed"})
    assert (r.status, r.waiting_at) == (S_RESOLVED, None)
    assert r.values["close_reason"] == "resolved_user_confirmed"
    assert h.audit.events("t1")[-5:] == [
        ("B15", "queued"), ("B16", "approved"), ("B18", "executed_ok"), ("B19", "user_confirmed"),
        ("B20", "closed"),  # điểm log 8 (B20 thật, 2b-2)
    ]
    assert _open_turns(h) == []
    assert [t["event_type"] for t in h.turns.of("t1")] == ["submit", "resume", "resume"]


@pytest.mark.asyncio
@pytest.mark.parametrize("wait_status", sorted(WAIT_PLANS))
async def test_each_wait_state_survives_restart(wait_status: str) -> None:
    h = GraphHarness()
    r = await h.submit("t1", **WAIT_PLANS[wait_status])
    assert (r.status, r.waiting_at) == (wait_status, WAIT_NODE[wait_status])
    h.restart()
    r = await deliver_event(h.runner, "t1", wait_status, VALID_EVENT[wait_status])
    assert r.status != wait_status or r.waiting_at is not None


@pytest.mark.asyncio
async def test_resume_carries_new_turn_id_into_state() -> None:
    h = GraphHarness()
    r1 = await h.submit("t1")
    r2 = await deliver_event(h.runner, "t1", S_PENDING_APPROVAL, {"kind": "approved"})
    assert r2.values["turn_id"] == r2.turn_id != r1.turn_id
    b16 = h.audit.of("t1", "approved")[0]
    assert b16["turn_id"] == r2.turn_id


# ---- Cổng 2: sự kiện muộn ở cả 3 trạng thái chờ → 409, trạng thái không đổi -----------------


LATE_PAIRS = [(a, e) for a in sorted(WAIT_PLANS) for e in sorted(WAIT_PLANS) if a != e]


@pytest.mark.asyncio
@pytest.mark.parametrize(("actual", "expected"), LATE_PAIRS)
async def test_late_event_in_every_wait_state(actual: str, expected: str) -> None:
    h = GraphHarness()
    await h.submit("t1", **WAIT_PLANS[actual])
    before = await h.runner.snapshot("t1")
    with pytest.raises(LateEvent) as err:
        await deliver_event(h.runner, "t1", expected, VALID_EVENT[expected])
    assert err.value.http_status == 409
    after = await h.runner.snapshot("t1")
    assert after.values == before.values and after.next == before.next
    late = h.audit.of("t1", "late_event")
    assert len(late) == 1
    assert late[0]["from_status"] == late[0]["to_status"] == actual
    assert late[0]["detail"] == {"expected_status": expected, "actual_status": actual,
                                 "event_kind": VALID_EVENT[expected]["kind"], "source": "user"}  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.parametrize("wait_status", sorted(WAIT_PLANS))
async def test_event_after_ticket_closed_is_late(wait_status: str) -> None:
    """TC27: thao tác đến sau khi ticket đã đóng (ví dụ duyệt sau khi hết hạn)."""
    h = GraphHarness()
    await h.submit("t1", b12_assess="deny")  # E5 → kết thúc
    with pytest.raises(LateEvent):
        await deliver_event(h.runner, "t1", wait_status, VALID_EVENT[wait_status])
    assert (await h.runner.snapshot("t1")).values["status"] == S_ESCALATED


@pytest.mark.asyncio
async def test_approval_after_timeout_is_late_and_never_executes() -> None:
    h = GraphHarness()
    await h.submit("t1")
    r = await deliver_event(h.runner, "t1", S_PENDING_APPROVAL, {"kind": "timeout"}, source="worker")
    assert (r.status, r.values["exit_code"]) == (S_ESCALATED, "E6")
    with pytest.raises(LateEvent):
        await deliver_event(h.runner, "t1", S_PENDING_APPROVAL, {"kind": "approved"})
    assert h.executor.calls["t1"] == 0  # hết hạn duyệt không bao giờ tự thực thi


@pytest.mark.asyncio
async def test_invalid_event_kind_and_unknown_ticket() -> None:
    h = GraphHarness()
    await h.submit("t1")
    with pytest.raises(InvalidEvent):
        await deliver_event(h.runner, "t1", S_PENDING_APPROVAL, {"kind": "confirmed"})
    assert (await h.runner.snapshot("t1")).next == ("approval_wait",)
    with pytest.raises(TicketNotFound):
        await deliver_event(h.runner, "khong-co", S_PENDING_APPROVAL, {"kind": "approved"})


@pytest.mark.asyncio
async def test_other_outcomes_of_waits() -> None:
    h = GraphHarness()
    await h.submit("rej")
    r = await deliver_event(h.runner, "rej", S_PENDING_APPROVAL, {"kind": "rejected", "note": "không duyệt"})
    assert (r.status, r.values["close_reason"]) == (S_REJECTED, "rejected_by_approver")
    await h.submit("unres", b12_assess="auto")
    r = await deliver_event(h.runner, "unres", S_CONFIRMING, {"kind": "unresolved"})
    assert (r.status, r.values["exit_code"]) == (S_ESCALATED, "E8")
    await h.submit("info", b10_route="info")
    r = await deliver_event(h.runner, "info", S_CONFIRMING, {"kind": "timeout"}, source="worker")
    assert (r.status, r.values["close_reason"]) == (S_RESOLVED, "resolved_auto_timeout_48h")


@pytest.mark.asyncio
async def test_clarify_loop_until_max_turns_then_e4() -> None:
    h = GraphHarness()
    await h.submit("t1", b11_slots="missing")
    for n in range(2, 4):
        r = await deliver_event(h.runner, "t1", S_CLARIFYING, {"kind": "user_reply", "text": "x"})
        assert (r.status, r.values["clarification_turns"]) == (S_CLARIFYING, n)
    r = await deliver_event(h.runner, "t1", S_CLARIFYING, {"kind": "user_reply", "text": "x"})
    assert (r.status, r.values["exit_code"]) == (S_ESCALATED, "E4")
    # mỗi vòng hỏi đúng 1 câu (3) + 1 tin "chuyển kỹ thuật viên" của B20 khi ra E4
    assert h.notifier.count("t1") == 4
    assert len(r.values["conversation"]) == 4
    assert r.values["conversation"][-1]["kind"] == "escalation"


# ---- Không gửi thông báo 2 lần (đếm bản ghi) ------------------------------------------------


@pytest.mark.asyncio
async def test_resume_twice_does_not_notify_twice() -> None:
    h = GraphHarness()
    await h.submit("t1")
    for status in (S_CLARIFYING, S_CONFIRMING):  # sự kiện sai chỗ: node chờ không chạy lại
        with pytest.raises(LateEvent):
            await deliver_event(h.runner, "t1", status, VALID_EVENT[status])
    h.restart()
    await deliver_event(h.runner, "t1", S_PENDING_APPROVAL, {"kind": "approved"})
    assert len(h.approvals.notified) == 1
    assert h.approvals.count("t1") == 1
    assert h.effects.count("t1", "notify_approver") == h.effects.count("t1", "approval_create") == 1
    assert h.notifier.count("t1") == h.effects.count("t1", "notify_user") == 1  # B18


@pytest.mark.asyncio
async def test_crash_after_approval_create_then_recover_gives_one_approval_one_notice() -> None:
    """P1 mục 11: giết process ngay sau approvals.create, trước checkpoint → recover (D-18)."""
    h = GraphHarness()

    def die(_: Any) -> None:
        raise Crash("chết ngay sau approval_create")

    h.scenario.on("t1", "after_approval_create", die)
    with pytest.raises(Crash):
        await h.submit("t1")
    [open_turn] = _open_turns(h)
    assert h.approvals.count("t1") == 1 and h.approvals.notified == []
    h.scenario.on("t1", "after_approval_create", lambda _: None)
    h.restart(can_execute=False)
    h.clock.advance(timedelta(minutes=3))
    from app.graph.worker_jobs import WorkerJobs

    assert await WorkerJobs(h.runner, h.deadlines, h.turns).scan_stale_turns() == 1
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.next) == (S_PENDING_APPROVAL, ("approval_wait",))
    assert h.approvals.count("t1") == 1  # đúng 1 phiếu
    assert len(h.approvals.notified) == 1  # đúng 1 thông báo
    assert snap.values["approval_id"] == "1"
    assert [r["turn_id"] for r in h.audit.of("t1", "queued")] == [open_turn]  # giữ turn_id
    assert _open_turns(h) == []
    assert len(h.turns.of("t1")) == 1  # recover không tạo lượt mới


# ---- Worker không có SVC_EXECUTOR_TOKEN: recover không chạy B17 → E7 ------------------------


@pytest.mark.asyncio
async def test_worker_recover_before_execute_goes_e7_without_executing() -> None:
    h = GraphHarness()
    h.executor.crash_once.add("t1")
    with pytest.raises(Crash):
        await h.submit("t1", b12_assess="auto")
    assert h.executor.calls["t1"] == 1  # lần chạy bị "giết" giữa chừng
    [open_turn] = _open_turns(h)
    h.restart(can_execute=False)
    r = await h.runner.recover("t1", open_turn)
    assert r is not None
    assert (r.status, r.values["exit_code"]) == (S_ESCALATED, "E7")
    assert r.values["escalation_note"] == INTERRUPTED_NOTE
    assert r.values["escalation_reason_detail"] == "execution_interrupted"
    assert h.executor.calls["t1"] == 1  # KHÔNG thực thi lại
    [row] = h.audit.of("t1", "execution_interrupted")
    assert (row["step"], row["from_status"], row["to_status"], row["turn_id"]) == (
        "B17", "S_EXECUTING", S_ESCALATED, open_turn)
    assert r.waiting_at is None and _open_turns(h) == []


@pytest.mark.asyncio
async def test_backend_recover_may_rerun_execute() -> None:
    """Đối chứng: runner có credential (backend) thì recover chạy tiếp B17 như P1 mục 7."""
    h = GraphHarness()
    h.executor.crash_once.add("t1")
    with pytest.raises(Crash):
        await h.submit("t1", b12_assess="auto")
    [open_turn] = _open_turns(h)
    r = await h.restart(can_execute=True).recover("t1", open_turn)
    assert r is not None and r.status == S_CONFIRMING
    assert h.executor.calls["t1"] == 2


@pytest.mark.asyncio
async def test_recover_of_closed_turn_is_noop() -> None:
    h = GraphHarness()
    r = await h.submit("t1")
    assert await h.runner.recover("t1", r.turn_id) is None


# ---- E9 (TC29), lỗi ở B1/B2 (D-29), B20, recursion ------------------------------------------


@pytest.mark.asyncio
async def test_tc29_node_raises_goes_e9_with_error_span_and_others_finish() -> None:
    h = GraphHarness()
    others = [f"ok{i}" for i in range(10)]
    results = await asyncio.gather(
        h.submit("bad", b06_diagnose="raise"), *(h.submit(t) for t in others)
    )
    bad = results[0]
    assert (bad.status, bad.values["exit_code"]) == (S_ESCALATED, "E9")
    assert bad.values["escalation_note"] == "Lỗi hệ thống không lường trước tại b06_diagnose"
    assert all(r.status == S_PENDING_APPROVAL for r in results[1:])
    [row] = h.audit.of("bad", "unhandled_exception")
    assert row["exit_code"] == "E9" and row["step"] == "b06_diagnose"
    assert "ValueError: lỗi giả tại b06_diagnose" in row["detail"]["traceback"]
    assert len(row["detail"]["traceback"]) <= TRACEBACK_LIMIT
    [span] = [s for s in h.spans.spans if s.name == "node:b06_diagnose" and s.status == "error"]
    assert span.attributes["unhandled_exception"].startswith("ValueError")
    assert len(span.attributes["traceback"]) <= TRACEBACK_LIMIT


@pytest.mark.asyncio
@pytest.mark.parametrize("node", ["b01_identity", "b02_screen"])
async def test_error_in_b1_b2_does_not_get_stuck(node: str) -> None:
    h = GraphHarness()
    if node == "b01_identity":  # B1 thật: lỗi chưa lường trước từ phụ thuộc của node
        h.identity.fail = RuntimeError("lỗi giả tại b01_identity")
        r = await h.submit("t1")
    else:
        r = await h.submit("t1", **{node: "raise"})
    assert (r.status, r.values["exit_code"], r.waiting_at) == (S_ESCALATED, "E9", None)
    assert [x["step"] for x in h.audit.of("t1", "unhandled_exception")] == [node]


@pytest.mark.asyncio
async def test_error_in_b20_reraises_and_keeps_turn_open() -> None:
    """2b-Q6: lỗi ở B20 (trạng thái đã kết thúc) → audit `unhandled_exception` khoá theo lượt rồi
    NÉM TIẾP — lượt không đóng để worker chạy lại; không kết thúc thread khi chưa có final_state."""
    h = GraphHarness()
    h.tickets.fail = RuntimeError("lỗi giả tại b20")
    with pytest.raises(RuntimeError, match="lỗi giả tại b20"):
        await h.submit("t1", b12_assess="deny")
    [row] = h.audit.of("t1", "unhandled_exception")
    assert row["step"] == "b20_audit" and row["idempotency_key"] is not None
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["exit_code"], snap.next) == (
        S_ESCALATED, "E5", ("b20_audit",))
    assert len(_open_turns(h)) == 1 and h.tickets.final("t1") is None


@pytest.mark.asyncio
async def test_boundary_does_not_swallow_graph_interrupt() -> None:
    async def waits(state: Any) -> dict[str, Any]:
        raise GraphInterrupt(())

    with pytest.raises(GraphInterrupt):
        await with_error_boundary("x", waits)({"ticket_id": "t", "status": "S_NEW"})


@pytest.mark.asyncio
async def test_recursion_limit_goes_e9() -> None:
    h = GraphHarness(recursion_limit=5)
    r = await h.submit("t1")
    assert (r.status, r.values["exit_code"], r.waiting_at) == (S_ESCALATED, "E9", None)
    [row] = h.audit.of("t1", "recursion_limit")
    assert row["step"] == "runner"


@pytest.mark.asyncio
async def test_spans_record_interrupted_and_ok() -> None:
    h = GraphHarness()
    await h.submit("t1")
    statuses = {(s.name, s.status) for s in h.spans.spans}
    assert ("node:approval_wait", "interrupted") in statuses
    assert ("node:b15_prepare_approval", "ok") in statuses
    assert len({s.trace_id for s in h.spans.spans}) == 1


# ---- Khoá: hai sự kiện đồng thời → đúng một lần chạy tiếp -----------------------------------


@pytest.mark.asyncio
async def test_two_concurrent_events_resume_once() -> None:
    h = GraphHarness()
    await h.submit("t1")
    results = await asyncio.gather(
        deliver_event(h.runner, "t1", S_PENDING_APPROVAL, {"kind": "approved"}),
        deliver_event(h.runner, "t1", S_PENDING_APPROVAL, {"kind": "rejected", "note": "không duyệt"}),
        return_exceptions=True,
    )
    assert sum(isinstance(x, LateEvent) for x in results) == 1
    assert sum(not isinstance(x, BaseException) for x in results) == 1
    assert len(h.audit.of("t1", "late_event")) == 1
    assert h.executor.calls["t1"] <= 1


# ---- Ticket cha: wake_parent (D-17) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_wake_parent_only_when_parent_waits() -> None:
    h = GraphHarness()
    r = await h.submit("p1", b03_classify="split", parent_wait=["wait", "wait", "done"])
    assert (r.status, r.waiting_at, r.values["is_parent"]) == (S_CLASSIFYING, "parent_wait", True)
    r2 = await wake_parent(h.runner, "p1")
    assert r2 is not None
    assert (r2.status, r2.values["aggregate_status"]) == (S_RESOLVED, "ALL_RESOLVED")
    assert r2.values.get("close_reason") is None and r2.values.get("exit_code") is None  # D-30
    assert await wake_parent(h.runner, "p1") is None  # cha đã đóng: im lặng, không late_event
    assert h.audit.of("p1", "late_event") == []


@pytest.mark.asyncio
async def test_parent_digest_then_reply_goes_back_to_parent_wait() -> None:
    h = GraphHarness()
    r = await h.submit("p1", b03_classify="split", parent_wait=["digest", "wait"])
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "parent_reply_wait")
    r = await deliver_event(h.runner, "p1", S_CONFIRMING, {"kind": "reply", "items": {}})
    assert (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait")
    assert h.notifier.count("p1") == 1  # một tin tổng hợp cho một vòng


# ---- wake_parent SAU khi nhả khoá ticket con (2b-Q7) ----------------------------------------


class RecordingLock(MemoryTicketLock):
    """Ghi lại các khoá đang giữ tại mỗi lần lấy khoá."""

    def __init__(self) -> None:
        super().__init__()
        self.held: set[str] = set()
        self.acquired: list[tuple[str, frozenset[str]]] = []

    @asynccontextmanager
    async def hold(self, ticket_id: str) -> AsyncIterator[None]:
        async with super().hold(ticket_id):
            self.acquired.append((ticket_id, frozenset(self.held)))
            self.held.add(ticket_id)
            try:
                yield
            finally:
                self.held.discard(ticket_id)


@pytest.mark.asyncio
async def test_child_end_wakes_parent_after_releasing_child_lock() -> None:
    h = GraphHarness()
    lock = RecordingLock()
    h.lock = lock
    h.runner._lock = lock
    await h.submit("p1", b03_classify="split", parent_wait=["wait", "wait"])
    parent_turns = len(h.turns.of("p1"))
    h.scenario.plan("p1-1", b12_assess="deny")  # con kết thúc ngay (E5) → B20
    r = await h.submit_as("p1-1", "s1", parent_ticket_id="p1")
    assert r.waiting_at is None
    assert len(h.turns.of("p1")) == parent_turns + 1  # cha được đánh thức (một lượt resume)
    [(_, held_when_waking)] = [(t, held) for t, held in lock.acquired if t == "p1"][-1:]
    assert held_when_waking == frozenset()  # không còn giữ khoá con khi lấy khoá cha


@pytest.mark.asyncio
async def test_wake_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    h = GraphHarness()
    await h.submit("p1", b03_classify="split", parent_wait="wait")

    async def broken(parent_id: str) -> None:
        raise RuntimeError("cha lỗi")

    h.runner.wake_parent = broken  # type: ignore[method-assign]
    h.scenario.plan("p1-1", b12_assess="deny")
    r = await h.submit_as("p1-1", "s1", parent_ticket_id="p1")
    assert r.values["exit_code"] == "E5"  # con vẫn đóng bình thường
    assert "không đánh thức được ticket cha p1" in caplog.text
