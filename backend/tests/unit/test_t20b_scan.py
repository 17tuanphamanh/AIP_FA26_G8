"""T20b — lưới an toàn ở worker `scan_parents` (phase5 P12, P1 §8.2; 5.2.8 s1–s3). Viết TỪ ĐẶC TẢ trước code (không đọc thân
`scan_parents`, `parents_to_wake`, `orphan_children` SQL).

Graph THẬT trên harness `_t20b`; worker = `WorkerJobs(h.runner, h.deadlines, h.turns)` (khuôn `test_graph_runtime`). `MemoryDeadlines`
đã mô phỏng hai truy vấn chỉ-đọc-DB (`parents_to_wake`, `orphan_children`). Mọi ca thuộc DỪNG 2.
"""

from datetime import timedelta
from typing import Any

import pytest
from app.domain.final import FinalSummary
from app.domain.states import S_ESCALATED, S_PENDING_APPROVAL, S_RESOLVED
from app.graph.worker_jobs import (
    PARENT_RECONCILE_INTERVAL,
    ParentScanReport,
    WorkerJobs,
)
from tests.fakes.graph import Crash
from tests.unit._t20b import (
    TC34,
    TC35,
    Flow,
    adobe_item,
    classify,
    extend_item,
    make_flow,
    reset_item,
)


def jobs(f: Flow) -> WorkerJobs:
    return WorkerJobs(f.h.runner, f.h.deadlines, f.h.turns)


def test_parent_reconcile_interval_60s() -> None:
    """P12 + 5.2.12: `PARENT_RECONCILE_INTERVAL` là hằng code 60 s (không biến `.env`)."""
    assert PARENT_RECONCILE_INTERVAL == 60
    assert set(ParentScanReport.__dataclass_fields__) == {"woken", "timeouts", "late", "busy", "failed", "deferred"}  # Q-T20b-10


class WakeCounter:
    def __init__(self, f: Flow) -> None:
        self.f = f
        self.original = f.h.runner.wake_parent
        self.calls: list[str] = []

    async def __call__(self, parent_id: str) -> Any:
        self.calls.append(parent_id)
        return await self.original(parent_id)


@pytest.mark.asyncio
async def test_s1_all_children_stopped_by_db_wakes_parent_once() -> None:
    """s1 (a): cha ở `parent_wait`, mọi con đã dừng theo DB (tín hiệu `after_turn` bị mất) → `wake_parent` 1 lần → digest vòng 1."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)

    async def lost(_: str) -> None:  # tín hiệu đánh thức bị mất (process chết sau khi nhả khoá con)
        return None

    original = f.h.runner.wake_parent
    f.h.runner.wake_parent = lost  # type: ignore[method-assign,assignment]
    await f.deliver("T1-2", S_PENDING_APPROVAL, f.decision("T1-2"))
    f.h.runner.wake_parent = original  # type: ignore[method-assign]
    assert (await f.waiting("T1")) == "parent_wait"
    counter = WakeCounter(f)
    f.h.runner.wake_parent = counter  # type: ignore[method-assign]
    report = await jobs(f).scan_parents()
    assert counter.calls == ["T1"] and report.woken == 1
    assert (await f.waiting("T1")) == "parent_reply_wait"
    assert len([m for m in await f.assistant_msgs() if m.get("kind") == "digest"]) == 1


@pytest.mark.asyncio
async def test_s1_parent_not_at_parent_wait_is_noop() -> None:
    """s1: cha CHƯA/không ở `parent_wait` (đang `parent_reply_wait`) mà DB vẫn báo "mọi con đã dừng" → `wake_parent` không làm gì:
    không lượt mới của cha, không `late_event`, trạng thái giữ nguyên."""
    f = make_flow([classify(reset_item(), extend_item())] * 2, extract={"duration": "30"})
    await f.submit(TC35)
    assert (await f.waiting("T1")) == "parent_reply_wait"
    for n in f.h.tickets.notices:  # DB "lệch": notice như chưa gửi → truy vấn (a) chọn cha
        n["delivered_at"], n["delivered_round"] = None, None
    turns = len(f.h.turns.of("T1"))
    counter = WakeCounter(f)
    f.h.runner.wake_parent = counter  # type: ignore[method-assign]
    await jobs(f).scan_parents()
    assert counter.calls == ["T1"]
    assert len(f.h.turns.of("T1")) == turns and f.h.audit.of("T1", "late_event") == []
    assert (await f.waiting("T1")) == "parent_reply_wait"


@pytest.mark.asyncio
async def test_s2_unstarted_child_wake_starts_it() -> None:
    """s2 (a): con chưa có dòng `turns` (process chết khi đang khởi động con 2) → `scan_parents` đánh thức cha → `parent_wait`
    khởi động con 2 (1 lượt submit, `child_started`)."""
    f = make_flow([classify(reset_item(), adobe_item())] * 2)
    original = f.h.turns.start

    async def start(**kw: Any) -> None:
        if kw["ticket_id"] == "T1-2" and kw["event_type"] == "submit":
            raise Crash("chết khi khởi động con 2")
        await original(**kw)

    f.h.turns.start = start  # type: ignore[method-assign]
    crashed = False
    try:
        await f.submit(TC34)
    except Crash:
        crashed = True
    f.h.turns.start = original  # type: ignore[method-assign]
    assert crashed  # (không `pytest.raises`: ca DỪNG 2 phải đỏ bằng AssertionError)
    assert f.h.turns.of("T1-2") == [] and f.h.audit.of("T1-2", "child_started") == []
    f.h.restart()
    report = await jobs(f).scan_parents()
    assert report.woken == 1
    assert [t["event_type"] for t in f.h.turns.of("T1-2")] == ["submit"]
    assert len(f.h.audit.of("T1-2", "child_started")) == 1


@pytest.mark.asyncio
async def test_s3_parent_closed_child_waiting_gets_worker_timeout() -> None:
    """s3 (b): cha đã có `final_state`, con còn notice chưa gửi `needs≠none` → con nhận `timeout` (`source="worker"`) — con không
    treo vì cha lỗi (P1 §8.2). Con ở `confirm_wait` → `resolved_auto_timeout_48h`; con chờ duyệt (không notice) không bị đụng."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    f.h.clock.advance(timedelta(minutes=5))
    await f.h.tickets.finalize_once("T1", FinalSummary(
        final_state=S_ESCALATED, exit_code=None, block_reason=None, close_reason=None, resolution_path=None,
        aggregate_status="ALL_ESCALATED", auto_closed=False, intent=None, slots=None, total_turns=1,
        total_duration_seconds=300, closed_at=f.h.clock.now(),
    ))  # fmt: skip
    assert (await jobs(f).scan_parents()).timeouts == 0  # Q-T20b-9 (ii): chưa quá 48 h từ lúc notice được tạo/gửi → chưa giao
    assert (await f.waiting("T1-1")) == "confirm_wait"
    f.h.clock.advance(timedelta(hours=48))
    report = await jobs(f).scan_parents()
    assert report.timeouts == 1
    c1 = await f.values("T1-1")
    assert (c1["status"], c1["close_reason"]) == (S_RESOLVED, "resolved_auto_timeout_48h")
    assert (await f.waiting("T1-2")) == "approval_wait"
    assert f.h.audit.of("T1-1", "late_event") == []
