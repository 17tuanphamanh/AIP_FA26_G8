"""T20b — đánh thức cha (phase5 P6, P1 §6.1; 5.2.8 w1–w3; 2b-Q7). Viết TỪ ĐẶC TẢ trước code.

w1/w2 trên graph GIẢ (khuôn `test_graph_runtime.test_child_end_wakes_parent_after_releasing_child_lock`): cha `p1` tách bằng node giả,
con `p1-1` submit với `parent_ticket_id`; `runner.wake_parent` thay bằng hàm ghi lại các khoá ĐANG GIỮ lúc gọi (`RecordingLock`).
w3 trên graph THẬT (`_t20b`): lượt lồng từ cha không gọi `after_turn` và không khoá chết (bọc `asyncio.wait_for`).
Ca w1 "kết thúc" và w2 xanh sẵn (ghim hành vi cũ); w1 dừng ở `clarify_wait`/`confirm_wait` và w3 đỏ tới khi có code (DỪNG 1).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_PENDING_APPROVAL
from app.graph.late_event import deliver_event, start_event
from app.graph.runner import RunResult
from tests.fakes.graph import GraphHarness, MemoryTicketLock
from tests.unit._t20b import TC34, adobe_item, classify, make_flow, reset_item

pytestmark = pytest.mark.asyncio





class RecordingLock(MemoryTicketLock):
    def __init__(self) -> None:
        super().__init__()
        self.held: set[str] = set()

    @asynccontextmanager
    async def hold(self, ticket_id: str) -> AsyncIterator[None]:
        async with super().hold(ticket_id):
            self.held.add(ticket_id)
            try:
                yield
            finally:
                self.held.discard(ticket_id)


class Spy:
    def __init__(self, lock: RecordingLock) -> None:
        self.lock = lock
        self.calls: list[tuple[str, frozenset[str]]] = []

    async def __call__(self, parent_id: str) -> None:
        self.calls.append((parent_id, frozenset(self.lock.held)))


async def _parent_and_child(child_plan: dict[str, Any]) -> tuple[GraphHarness, Spy, RunResult]:
    h = GraphHarness()
    lock = RecordingLock()
    h.lock = lock
    h.runner._lock = lock
    await h.submit("p1", b03_classify="split", parent_wait=["wait"] * 6)
    spy = Spy(lock)
    h.runner.wake_parent = spy  # type: ignore[method-assign]
    h.scenario.plan("p1-1", **child_plan)
    r = await h.submit_as("p1-1", "s1", parent_ticket_id="p1")
    return h, spy, r


async def _deliver_via_start_event(h: GraphHarness, ticket_id: str, status: str, event: dict[str, Any]) -> None:
    spawned: list[Any] = []
    await start_event(h.runner, ticket_id, status, event, spawn=lambda coro, **_: spawned.append(coro))
    [coro] = spawned
    await coro


@pytest.mark.parametrize("via", ["deliver_event", "start_event"])
async def test_w1_child_stops_at_clarify_wait_wakes_parent_after_release(via: str) -> None:
    """w1 (P6, M-T20b-13): con dừng ở `clarify_wait` sau một lượt THƯỜNG → `wake_parent(cha)` được gọi SAU khi nhả khoá con."""
    h, spy, r = await _parent_and_child({"b11_slots": "missing"})
    assert r.waiting_at == "clarify_wait"
    spy.calls.clear()
    event = {"kind": "user_reply", "text": "máy LAP-1"}
    if via == "deliver_event":
        r = await deliver_event(h.runner, "p1-1", S_CLARIFYING, event)
        assert r.waiting_at == "clarify_wait"
    else:
        await _deliver_via_start_event(h, "p1-1", S_CLARIFYING, event)
    assert spy.calls == [("p1", frozenset())]  # đúng một lần, không còn giữ khoá con (cũng không giữ khoá nào)


async def test_w1_child_stops_at_confirm_wait_wakes_parent() -> None:
    """w1: con đi từ `approval_wait` (duyệt) tới `confirm_wait` → đánh thức cha, sau khi nhả khoá con."""
    h, spy, r = await _parent_and_child({})
    assert r.waiting_at == "approval_wait"
    spy.calls.clear()
    r = await deliver_event(h.runner, "p1-1", S_PENDING_APPROVAL, {"kind": "approved"})
    assert r.waiting_at == "confirm_wait"
    assert spy.calls == [("p1", frozenset())]


async def test_w1_child_ends_wakes_parent() -> None:
    """w1 (hành vi cũ, ghim): con kết thúc → đánh thức cha sau khi nhả khoá con."""
    h, spy, r = await _parent_and_child({"b12_assess": "auto"})
    assert r.waiting_at == "confirm_wait"
    spy.calls.clear()
    r = await deliver_event(h.runner, "p1-1", S_CONFIRMING, {"kind": "confirmed"})
    assert r.waiting_at is None
    assert spy.calls == [("p1", frozenset())]


async def test_w2_child_stops_at_approval_wait_does_not_wake() -> None:
    """w2 (P6, D-31): con dừng ở `approval_wait` (chờ L1 không phải điểm dừng) → KHÔNG đánh thức."""
    h, spy, r = await _parent_and_child({"b11_slots": ["missing", "complete"]})
    assert r.waiting_at == "clarify_wait"
    spy.calls.clear()
    r = await deliver_event(h.runner, "p1-1", S_CLARIFYING, {"kind": "user_reply", "text": "máy LAP-1"})
    assert r.waiting_at == "approval_wait"
    assert spy.calls == []


async def test_w3_nested_child_turns_never_call_after_turn_no_deadlock() -> None:
    """w3 (P4, P6, 2b-Q7): lượt lồng từ cha (khởi động con trong `parent_wait`) KHÔNG gọi `after_turn` cho con — cha đang giữ khoá
    cha; nếu gọi, `wake_parent` chờ khoá cha → khoá chết. Có hạn thời gian (khoá giả hết hạn 5 s → `TicketBusy` chỉ bị log)."""
    f = make_flow(classify(reset_item(), adobe_item()))
    seen: list[str] = []
    original = f.h.runner.after_turn

    async def after_turn(result: RunResult) -> None:
        seen.append(result.ticket_id)
        await original(result)

    f.h.runner.after_turn = after_turn  # type: ignore[method-assign]
    loop = asyncio.get_running_loop()
    started = loop.time()
    await asyncio.wait_for(f.submit(TC34), timeout=10)
    assert loop.time() - started < 4  # không ngồi chờ khoá cha tới hết `lock_timeout`
    assert seen == ["T1"]  # chỉ lượt của cha; con 1 dừng `confirm_wait` trong lượt LỒNG → không after_turn
    assert [t["event_type"] for t in f.h.turns.of("T1")] == ["submit"]  # cha không bị đánh thức thêm lượt nào
    assert (await f.waiting("T1-1")) == "confirm_wait"
