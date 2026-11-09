"""T20b — seed + khởi động ticket con + chạy lại (phase5 5.2.3, P3, P4; 5.2.8 c1–c4, k1–k2; D-18). Viết TỪ ĐẶC TẢ trước code.

Graph THẬT trên harness `_t20b`. Giả lập process chết bằng `Crash` (BaseException — boundary không bắt, LangGraph không kịp ghi
checkpoint của node đang chạy): `MemoryAudit.crash_once` (chết ngay TRƯỚC khi ghi dòng audit) hoặc thay `turns.start`. Chạy lại =
`h.restart()` (process mới, cùng checkpoint/DB giả) + `runner.recover` lượt còn mở. Mọi ca thuộc DỪNG 1.
"""

from datetime import timedelta

import pytest
from app.domain.states import S_CLASSIFYING, S_DIAGNOSING, S_ESCALATED
from app.domain.ticket_state import check_state_keys
from app.graph.late_event import wake_parent
from tests.fakes.graph import Crash, GraphHarness
from tests.unit._t20b import (
    PRINTER,
    RESET,
    SESSION_NV001,
    TC32,
    TC34,
    TWO_APPROVALS,
    Flow,
    adobe_item,
    classify,
    grant_item,
    make_flow,
    oos_item,
    reset_item,
)

pytestmark = pytest.mark.asyncio





SEED_KEYS = {
    "ticket_id", "parent_ticket_id", "session_id", "redacted_request", "status", "intent", "intent_confidence", "span",
    "slots", "facts", "conversation", "clarification_turns", "off_topic_streak", "reasoning_loops", "is_parent", "children",
}  # fmt: skip


def open_turns(f: Flow, ticket_id: str) -> list[str]:
    return [t["turn_id"] for t in f.h.turns.of(ticket_id) if t["ended_at"] is None]


def submits(f: Flow, ticket_id: str) -> int:
    return sum(1 for t in f.h.turns.of(ticket_id) if t["event_type"] == "submit")


# ---- c1: seed ------------------------------------------------------------------------------------------------------------------


async def test_c1_seed_runnable_child_exact_keys_and_values() -> None:
    """c1 (bảng 5.2.3): đúng từng khoá; `facts == {}`; KHÔNG `requester_context` trong seed (đọc lại từ cha lúc khởi động), không
    khoá lạ; `reasoning_loops` = loops của cha."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    parent = await f.values("T1")
    seed = parent["child_seeds"]["T1-1"]
    assert set(seed) == SEED_KEYS, set(seed) ^ SEED_KEYS
    check_state_keys(list(seed))
    assert seed == {
        "ticket_id": "T1-1", "parent_ticket_id": "T1", "session_id": SESSION_NV001, "redacted_request": RESET,
        "status": S_CLASSIFYING, "intent": "account", "intent_confidence": 0.92, "span": RESET,
        "slots": {"action": "reset_password", "account_type": "ad"}, "facts": {}, "conversation": [],
        "clarification_turns": 0, "off_topic_streak": 0, "reasoning_loops": parent["reasoning_loops"], "is_parent": False,
        "children": [],
    }  # fmt: skip


async def test_c1_seed_e1_child_no_intent_has_exit_code() -> None:
    """c1 (bảng 5.2.3, ý E1 #1): không đặt `intent`; thêm `exit_code="E1"` + `escalation_reason_detail`."""
    f = make_flow(classify(reset_item(), oos_item()))
    await f.submit(TC32)
    seed = (await f.values("T1"))["child_seeds"]["T1-2"]
    assert "intent" not in seed and "requester_context" not in seed
    assert (seed["exit_code"], seed["escalation_reason_detail"]) == ("E1", "out_of_scope")
    assert (seed["ticket_id"], seed["parent_ticket_id"], seed["span"], seed["redacted_request"]) == (
        "T1-2", "T1", PRINTER, PRINTER)  # fmt: skip
    assert (seed["status"], seed["facts"], seed["is_parent"], seed["children"]) == (S_CLASSIFYING, {}, False, [])
    check_state_keys(list(seed))


async def test_c1_child_checkpoint_requester_context_from_parent() -> None:
    """c1: checkpoint con có `requester_context` == của cha (bản frozen của B1); `facts` do B6 của CON tính (seed `{}`)."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    parent, child = await f.values("T1"), await f.values("T1-1")
    assert child["requester_context"] == parent["requester_context"]
    assert (child["ticket_id"], child["parent_ticket_id"], child["session_id"]) == ("T1-1", "T1", SESSION_NV001)
    check_state_keys(list(child))


# ---- c2: goto của con -----------------------------------------------------------------------------------------------------------


async def test_c2_child_goto_audit_rows() -> None:
    """c2: `child_started` (`CLASSIFYING → DIAGNOSING`, step B5) / `child_not_runnable` (`→ ESCALATED`, E1)."""
    f = make_flow(classify(reset_item(), oos_item()))
    await f.submit(TC32)
    [ok] = f.h.audit.of("T1-1", "child_started")
    [bad] = f.h.audit.of("T1-2", "child_not_runnable")
    assert (ok["step"], ok["from_status"], ok["to_status"], ok.get("exit_code")) == ("B5", S_CLASSIFYING, S_DIAGNOSING, None)
    assert (bad["step"], bad["from_status"], bad["to_status"], bad["exit_code"]) == ("B5", S_CLASSIFYING, S_ESCALATED, "E1")


# ---- c3: khởi động hai lần ------------------------------------------------------------------------------------------------------


async def test_c3_start_twice_second_does_nothing() -> None:
    """c3: cha chạy lại `parent_wait` (đánh thức sớm → `start_missing` lần 2) → con đã có thread không chạy gì: 1 dòng `turns`
    submit, 1 `child_started`; `child_submit` của cha 1 dòng/con; mỗi con 1 lượt submit."""
    f = make_flow(classify(adobe_item(), grant_item()))
    await f.submit(TWO_APPROVALS)
    assert (await f.waiting("T1")) == "parent_wait"  # D-77: hai con chờ duyệt, vòng 1 đã báo → cha chờ con
    before = {cid: f.h.audit.events(cid) for cid in ("T1-1", "T1-2")}
    turns_before = {cid: len(f.h.turns.of(cid)) for cid in ("T1-1", "T1-2")}
    await wake_parent(f.h.runner, "T1")
    for cid in ("T1-1", "T1-2"):
        assert submits(f, cid) == 1
        assert len(f.h.audit.of(cid, "child_started")) == 1
        assert f.h.audit.events(cid) == before[cid]  # lần 2 không chạy gì ở con
        assert len(f.h.turns.of(cid)) == turns_before[cid]
    assert f.h.effects.count("T1", "child_submit") == 2


# ---- c4: recover/run_new ticket con chưa có thread ----------------------------------------------------------------------------


@pytest.mark.parametrize("how", ["recover", "run_new"])
async def test_c4_recover_child_without_thread_closes_turn(how: str) -> None:
    """c4 (P4): `recover`/`run_new` gặp ticket CON (dòng `tickets` có `parent_ticket_id`) chưa có thread → đóng lượt, trả None, không
    chạy B1 (khởi động là việc của cha — một đường code)."""
    h = GraphHarness()
    now = h.clock.now()
    h.tickets.register("P", now, is_parent=True)
    h.tickets.register("P-1", now, parent_ticket_id="P", redacted_request="đặt lại mật khẩu")
    await h.turns.start(turn_id="tc1", ticket_id="P-1", session_id="s1", event_type="submit", at=now)
    h.clock.advance(timedelta(minutes=3))
    result = await (h.runner.recover("P-1", "tc1") if how == "recover" else h.runner.run_new("P-1", "tc1"))
    assert result is None
    assert h.turns.rows["tc1"]["ended_at"] is not None
    assert h.audit.events("P-1") == []  # không B1, không gì cả
    assert (await h.runner.snapshot("P-1")).values == {}  # không dựng state đầu `S_NEW` cho con


# ---- k1: chết sau child_create con 2, trước checkpoint cha ------------------------------------------------------------------------


async def test_k1_crash_after_child_create_before_parent_checkpoint() -> None:
    """k1 (D-18, M-T20b-3): process chết ngay TRƯỚC dòng audit `split_into_2_children` (sau `child_create` của cả 2 con, trước
    checkpoint cha) → recover: đúng 2 dòng `tickets` con, `child_create` 2 dòng, mỗi con chạy 1 lần."""
    f = make_flow([classify(reset_item(), adobe_item()), classify(reset_item(), adobe_item())])
    f.h.audit.crash_once.add("split_into_2_children")
    with pytest.raises(Crash):
        await f.submit(TC34)
    [turn] = open_turns(f, "T1")
    f.h.restart()
    await f.h.runner.recover("T1", turn)
    assert f.h.tickets.created_children == ["T1-1", "T1-2"]
    assert f.h.effects.count("T1", "child_create") == 2
    for cid in ("T1-1", "T1-2"):
        assert submits(f, cid) == 1
        assert len(f.h.audit.of(cid, "child_started")) == 1
    assert len(f.h.audit.of("T1", "split_into_2_children")) == 1


# ---- k2: chết giữa lượt lồng của con 1 -------------------------------------------------------------------------------------------


async def test_k2_crash_inside_nested_child_run_then_parent_recovers() -> None:
    """k2: chết giữa lượt lồng của con 1 (dòng audit B6 `diagnosed` đầu tiên — sau `start`, trước `child_submit`) → chạy lại cha:
    con 1 KHÔNG chạy lại từ đầu (thread đã có state: vẫn 1 lượt submit, 1 `child_started`); con 2 vẫn khởi động."""
    f = make_flow([classify(reset_item(), adobe_item()), classify(reset_item(), adobe_item())])
    f.h.audit.crash_once.add("diagnosed")
    with pytest.raises(Crash):
        await f.submit(TC34)
    assert (await f.values("T1-1")) != {}  # seed đã ghi trước khi chạy (P3)
    assert f.h.audit.of("T1-2", "child_started") == []
    [turn] = open_turns(f, "T1")
    f.h.restart()
    await f.h.runner.recover("T1", turn)
    assert submits(f, "T1-1") == 1
    assert len(f.h.audit.of("T1-1", "child_started")) == 1
    assert len(f.h.audit.of("T1-2", "child_started")) == 1 and submits(f, "T1-2") == 1
