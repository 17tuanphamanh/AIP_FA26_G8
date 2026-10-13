"""T20b — sửa theo duyệt MẪU B DỪNG 1 (Q-T20b-5 = A, Q-T20b-6 = A). Agent chính viết (không phải test-writer) — ghi ở báo cáo.

- Q5 (i)+(ii): cha lỗi (E9) → B20 tạo ĐÚNG 1 escalation của cha (+ tin theo mã), cha hiện trong `list_open`; cha đóng bình thường → 0
  escalation của cha, không hiện (D-30 giữ nguyên ở đường thường).
- Q5 (iii) (s3 mở rộng, DỪNG 2 — `CHO_DUNG2`): con đã nhận digest rồi đứng chờ ở `clarify_wait` (notice ĐÃ gửi) + cha E9 → `scan_parents`
  giao `timeout` → con E4 `clarify_timeout`.
- Q6: `start_missing` — pool khoá hết chờ → bỏ qua con đó, cha ghi audit `children_not_started` (`detail.busy`) TRƯỚC interrupt, không E9;
  lần sau khởi động được.
  `deliver` — pool khoá hết chờ → thử lại `busy_retries` lần (sleep tiêm) rồi ném.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from app.domain.states import S_CLASSIFYING, S_CONFIRMING, S_ESCALATED
from app.graph.late_event import wake_parent
from app.graph.worker_jobs import WorkerJobs
from sqlalchemy.exc import TimeoutError as PoolTimeout
from tests.fakes.graph import GraphHarness, MemoryTicketLock
from tests.unit._t20b import (
    PRINTER,
    RESET,
    TC32,
    TC34,
    TC35,
    Flow,
    adobe_item,
    classify,
    extend_item,
    item,
    make_flow,
    oos_item,
    reset_item,
)

pytestmark = pytest.mark.asyncio

CHO_DUNG2 = frozenset({"test_q5_iii_child_waiting_after_digest_parent_e9_gets_worker_timeout"})


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.originalname in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError), reason="T20b DỪNG 2"))


class PoolExhaustedLock(MemoryTicketLock):
    """Pool khoá hết chờ (`sqlalchemy.exc.TimeoutError` khi mượn kết nối) cho các ticket trong `exhausted`."""

    def __init__(self) -> None:
        super().__init__()
        self.exhausted: set[str] = set()

    @asynccontextmanager
    async def hold(self, ticket_id: str) -> AsyncIterator[None]:
        if ticket_id in self.exhausted:
            raise PoolTimeout("QueuePool limit reached, connection timed out")
        async with super().hold(ticket_id):
            yield


def _use(f: Flow, lock: MemoryTicketLock) -> None:
    f.h.lock = lock
    f.h.runner._lock = lock


async def _break_parent(f: Flow, method: str) -> None:
    async def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("lỗi chưa lường ở vòng cha")

    setattr(f.h.runner.children, method, broken)


async def test_q5_parent_e9_has_one_escalation_and_shows_in_l2_queue() -> None:
    f = make_flow(classify(reset_item(), oos_item()))
    await _break_parent(f, "start_missing")
    r = await f.submit(TC32)
    assert (r.status, r.values.get("exit_code")) == (S_ESCALATED, "E9"), f.h.audit.events("T1")
    [esc] = f.h.escalations.of("T1")
    assert esc["exit_code"] == "E9"
    assert "T1" in {i.ticket_id for i in await f.h.escalations.list_open(100)}
    assert [m["kind"] for m in await f.assistant_msgs()] == ["escalation"]  # người dùng THẤY (tin theo mã E9)


async def test_q5_parent_normal_close_no_escalation_not_in_queue() -> None:
    other = item("account", f"{RESET} cho Nguyễn Văn A", action="reset_password",
                 slots={"account_type": "ad", "target_user": "Nguyễn Văn A"})  # fmt: skip
    f = make_flow(classify(other, oos_item()))  # con 1 E5 (người khác, không luật) + con 2 E1 → cha ALL_ESCALATED
    r = await f.submit(f"{RESET} cho Nguyễn Văn A, tiện {PRINTER}")
    assert r.status == S_ESCALATED and r.values.get("exit_code") is None  # cha đóng bình thường (ALL_ESCALATED)
    assert f.h.escalations.of("T1") == []
    queue = {i.ticket_id for i in await f.h.escalations.list_open(100)}
    assert "T1" not in queue and {"T1-1", "T1-2"} <= queue


async def test_q5_iii_child_waiting_after_digest_parent_e9_gets_worker_timeout() -> None:
    f = make_flow([classify(reset_item(), extend_item())] * 2, extract={"duration": "30"})
    r = await f.submit(TC35)
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "parent_reply_wait")
    assert all(n["delivered_round"] == 1 for n in f.h.tickets.notices)  # notice ĐÃ gửi
    await _break_parent(f, "deliver")
    r = await f.deliver("T1", S_CONFIRMING, {"kind": "reply", "items": {"T1-1": {"confirmed": True}, "T1-2": {"answer": "30"}}})
    assert r.values.get("exit_code") == "E9"
    assert (await f.waiting("T1-2")) == "clarify_wait"
    await WorkerJobs(f.h.runner, f.h.deadlines, f.h.turns).scan_parents()
    c2 = await f.values("T1-2")
    assert (c2["status"], c2["exit_code"], c2["escalation_reason_detail"]) == (S_ESCALATED, "E4", "clarify_timeout")


async def test_q6_start_missing_pool_timeout_skips_child_records_name() -> None:
    f = make_flow(classify(reset_item(), adobe_item()))
    lock = PoolExhaustedLock()
    lock.exhausted.add("T1-2")
    _use(f, lock)
    r = await f.submit(TC34)
    assert (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait") and r.values.get("exit_code") is None
    assert (await f.h.runner.snapshot("T1-2")).values == {} and f.h.effects.count("T1", "child_submit") == 1
    [row] = f.h.audit.of("T1", "children_not_started")  # ghi TRƯỚC interrupt (lần chạy đầu)
    assert (row["step"], row["detail"]) == ("B5", {"busy": ["T1-2"], "failed": []})
    lock.exhausted.clear()
    await wake_parent(f.h.runner, "T1")
    assert (await f.h.runner.snapshot("T1-2")).values and f.h.effects.count("T1", "child_submit") == 2


async def test_q6_deliver_pool_timeout_retries_then_raises() -> None:
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    lock = PoolExhaustedLock()
    lock.exhausted.add("T1-1")
    _use(f, lock)
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)

    ops = f.h.runner.children
    ops._sleep = sleep  # type: ignore[attr-defined]
    with pytest.raises(PoolTimeout):
        await ops.deliver("T1-1", "confirm", {"kind": "confirmed", "note": None})
    assert slept == [1.0] * 5


# ---- duyệt MẪU B lượt 2: FAIL-1 (deliver), NGHI "notice bị nuốt", mọi exit_code của cha, audit `failed` ------------------------------


async def test_fail1_a_nested_fails_before_resume_recorded_deliver_raises() -> None:
    """FAIL-1 (a): lượt lồng lỗi TRƯỚC khi con nhận resume (`turns.start` lỗi) → `deliver` NÉM (không báo "đã giao")."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    start = f.h.turns.start

    async def broken(*, ticket_id: str, **kw: Any) -> None:
        if ticket_id == "T1-1":
            raise RuntimeError("DB chập chờn khi mở lượt con")
        await start(ticket_id=ticket_id, **kw)

    f.h.turns.start = broken  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await f.h.runner.children.deliver("T1-1", "confirm", {"kind": "confirmed", "note": None})
    assert (await f.waiting("T1-1")) == "confirm_wait"  # con vẫn chờ, chưa nhận gì


async def test_fail1_b_nested_fails_after_resume_recorded_deliver_does_not_raise() -> None:
    """FAIL-1 (b): con ĐÃ nhận resume rồi lỗi giữa chừng (B20 ném tiếp) → `deliver` KHÔNG ném, trả "delivered"; lượt con còn mở
    (worker phục hồi)."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    f.h.tickets.fail, f.h.tickets.fail_times = RuntimeError("B20 lỗi sau khi con nhận xác nhận"), 1
    out = await f.h.runner.children.deliver("T1-1", "confirm", {"kind": "confirmed", "note": None})
    assert out == "delivered"
    assert [t["event_type"] for t in f.h.turns.of("T1-1") if t["ended_at"] is None] == ["resume"]
    assert (await f.waiting("T1-1")) == "b20_audit" and f.h.audit.of("T1-1", "user_confirmed")  # đã qua confirm_wait, dở ở B20


async def test_nghi_child_final_with_open_turn_not_counted_ended_notice_not_swallowed() -> None:
    """NGHI "notice bị nuốt": con E1 ghi `final_state` rồi B20 lỗi TRƯỚC khi ghi escalation + notice (lượt còn mở) → cha KHÔNG coi con đã
    kết thúc (chưa đóng); worker phục hồi con → B20 xong, notice có → cha đóng với khối `escalation` của con."""
    f = make_flow(classify(reset_item(), oos_item()))
    create = f.h.escalations.create
    calls: list[str] = []

    async def flaky(**kw: Any) -> str:
        if kw["ticket_id"] == "T1-2" and not calls:
            calls.append("x")
            raise RuntimeError("lỗi tạm khi tạo escalation của con")
        return await create(**kw)

    f.h.escalations.create = flaky  # type: ignore[method-assign]
    r = await f.submit(TC32)
    assert f.h.tickets.final("T1-2") is not None  # final_state đã ghi
    assert f.h.tickets.notices_of("T1-2") == []  # notice escalation CHƯA ghi
    assert (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait")  # cha chưa đóng
    [turn] = [t["turn_id"] for t in f.h.turns.of("T1-2") if t["ended_at"] is None]
    await f.h.runner.recover("T1-2", turn)  # worker phục hồi con → after_turn đánh thức cha
    [d] = [m for m in (await f.values("T1")).get("conversation") or [] if m.get("kind") == "digest"]
    assert [i["child_id"] for i in d["items"] if i["kind"] == "escalation"] == ["T1-2"]


async def test_q5_parent_any_exit_code_escalates_e7() -> None:
    """Mọi `exit_code` của cha đều tạo escalation (bỏ giới hạn E2/E9): cha có `begun` (theo ticket) + lỗi chưa lường ở vòng cha → E7."""
    h = GraphHarness()
    await h.txlog.begin("p1", "turn-x", "fake_step")
    r = await h.submit("p1", b03_classify="split", parent_wait="raise")
    assert r.values.get("exit_code") == "E7"
    [esc] = h.escalations.of("p1")
    assert esc["exit_code"] == "E7" and "p1" in {i.ticket_id for i in await h.escalations.list_open(100)}


async def test_q6_failed_child_recorded_before_interrupt() -> None:
    """Soát S10 B-ii + duyệt lượt 2 (iii): con khởi động lỗi trước checkpoint đầu → `children_not_started.detail.failed`."""
    f = make_flow(classify(reset_item(), adobe_item()))
    graph = f.h.runner.graph
    original = graph.aupdate_state

    async def broken(config: Any, values: Any, *args: Any, **kw: Any) -> Any:
        if config["configurable"]["thread_id"] == "T1-2":
            raise RuntimeError("lỗi DB tạm thời khi gieo con 2")
        return await original(config, values, *args, **kw)

    graph.aupdate_state = broken  # type: ignore[method-assign]
    await f.submit(TC34)
    [row] = f.h.audit.of("T1", "children_not_started")
    assert row["detail"] == {"busy": [], "failed": ["T1-2"]}
