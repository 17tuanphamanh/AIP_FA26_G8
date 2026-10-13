"""T20b — luồng đầu-cuối trên harness (phase5 5.2.7 kiểu tc34/tc35/tc32/tc36/tc12r, 5.2.11 DỪNG 1). Viết TỪ ĐẶC TẢ trước code.

Runner thật + `InMemorySaver` + ScriptedLLM (gateway thật) + store giả: 2+ thread cha/con thật. Kỳ vọng chép từ bảng 5.2.7; "số tin
assistant của cha = số lượt người dùng" (D-31) đếm ở `conversation` CHA. Executor của harness (`CountingExecutor`) đếm lời gọi ghi
theo ticket. Phần API/`children_progress` của 5.2.7 thuộc DỪNG 2 (`test_t20b_api.py`).

Đối chứng (xanh sẵn, `test_control_*`): từng ý chạy MỘT MÌNH như ticket thường đi đúng chuỗi node thật trên harness của `_t20b` — để
ca nhiều ý đỏ/xanh vì T20b chứ không vì fixture.
"""

from typing import Any

import pytest
from app.domain.states import (
    S_CLARIFYING,
    S_CONFIRMING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
    S_REJECTED,
    S_RESOLVED,
)
from tests.unit._t20b import (
    ADOBE,
    EXTEND,
    PRINTER,
    RESET,
    TC32,
    TC34,
    TC35,
    Flow,
    adobe_item,
    classify,
    extend_item,
    make_flow,
    oos_item,
    reset_item,
)

pytestmark = pytest.mark.asyncio

CHO_DUNG2: frozenset[str] = frozenset()  # mọi ca thuộc DỪNG 1 — không xfail (phần DỪNG 2 của 5.2.7 ở test_t20b_api.py)


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.originalname in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError), reason="T20b DỪNG 2"))


def digests(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in msgs if m.get("kind") == "digest"]


async def reply(f: Flow, items: dict[str, dict[str, Any]]) -> None:
    r = await f.deliver("T1", S_CONFIRMING, {"kind": "reply", "items": items})
    assert r.status is not None


def assert_parent_closed(f: Flow, final_state: str, aggregate: str) -> None:
    final = f.h.tickets.final("T1")
    assert final is not None, f.h.audit.events("T1")
    assert (final.final_state, final.aggregate_status, final.exit_code, final.close_reason, final.resolution_path) == (
        final_state, aggregate, None, None, None)  # fmt: skip
    assert f.h.escalations.of("T1") == []


async def test_tc34_two_children_one_needs_approval_all_resolved() -> None:
    """tc34: con 1 R01 → reset 1 lần → `confirm_wait`; con 2 R14 → phiếu → 0 tin tới cha trước khi duyệt → duyệt → install →
    dừng; cha 1 digest 2 khối `result` → reply cả hai "Đã ổn" → 2 con `resolved_user_confirmed` → tin tổng kết → `S_RESOLVED`/
    `ALL_RESOLVED`, `close_reason`/`exit_code` NULL; số tin assistant cha = số lượt người dùng (2)."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    assert f.h.executor.calls["T1-1"] == 1 and f.h.executor.calls["T1-2"] == 0
    assert await f.assistant_msgs() == []  # 0 tin trước khi duyệt
    await f.deliver("T1-2", S_PENDING_APPROVAL, f.decision("T1-2"))
    [d1] = digests(await f.assistant_msgs())
    assert [i["kind"] for i in d1["items"]] == ["result", "result"]
    await reply(f, {"T1-1": {"confirmed": True}, "T1-2": {"confirmed": True}})
    for cid in ("T1-1", "T1-2"):
        v = await f.values(cid)
        assert (v["status"], v["close_reason"]) == (S_RESOLVED, "resolved_user_confirmed")
        assert f.h.executor.calls[cid] == 1
    assert_parent_closed(f, S_RESOLVED, "ALL_RESOLVED")
    msgs = await f.assistant_msgs()
    assert len(msgs) == 2  # = lượt người dùng: gửi câu + một lần trả lời
    assert msgs[-1]["text"] == "Cả 2 yêu cầu đã hoàn tất." and msgs[-1]["items"] == []
    assert (await f.waiting("T1")) is None


async def test_tc35_question_then_second_round_all_resolved() -> None:
    """tc35: digest vòng 1 `result` + `question` → reply {ý 1 confirmed, ý 2 answer "30"} → con 2 B11 → R10 AUTO → extend 1 lần →
    dừng → digest vòng 2 (`result` ý 2) → reply {ý 2 confirmed} → `ALL_RESOLVED`; số tin assistant cha = 3 = số lượt người dùng.
    Q-T20b-3 = A: hạn `clarify` vòng 1 bị thay bởi hạn `confirm` vòng 2 (chỉ hạn vòng 2 còn chưa bắn)."""
    f = make_flow(classify(reset_item(), extend_item()), extract={"duration": "30"})
    await f.submit(TC35)
    [d1] = digests(await f.assistant_msgs())
    assert [i["kind"] for i in d1["items"]] == ["result", "question"]
    await reply(f, {"T1-1": {"confirmed": True}, "T1-2": {"answer": "30"}})
    assert f.h.executor.calls["T1-2"] == 1
    v = await f.values("T1")
    assert (await f.waiting("T1"), v["parent_round"], v["awaiting"]) == ("parent_reply_wait", 2, {"T1-2": "confirm"})
    d2 = digests(await f.assistant_msgs())[-1]
    assert (d2["round"], [(i["child_id"], i["kind"]) for i in d2["items"]]) == (2, [("T1-2", "result")])
    assert [w["kind"] for w in f.h.deadlines.waits if w["ticket_id"] == "T1" and w["fired_at"] is None] == ["confirm"]
    await reply(f, {"T1-2": {"confirmed": True}})
    assert_parent_closed(f, S_RESOLVED, "ALL_RESOLVED")
    assert len(await f.assistant_msgs()) == 3


async def test_tc36_unresolved_one_confirmed_other_partially_escalated() -> None:
    """tc36: như tc34 nhưng trả lời {ý 1 "Chưa ổn" + ghi chú, ý 2 "Đã ổn"} → con 1 E8, con 2 `resolved_user_confirmed`; cha
    `S_RESOLVED`/`PARTIALLY_ESCALATED`, `close_reason` NULL; 1 dòng `escalations` (con 1), 0 cho cha."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    await f.deliver("T1-2", S_PENDING_APPROVAL, f.decision("T1-2"))
    await reply(f, {"T1-1": {"confirmed": False, "note": "vẫn chưa đăng nhập được"}, "T1-2": {"confirmed": True}})
    c1, c2 = await f.values("T1-1"), await f.values("T1-2")
    assert (c1["status"], c1["exit_code"]) == (S_ESCALATED, "E8")
    assert (c2["status"], c2["close_reason"]) == (S_RESOLVED, "resolved_user_confirmed")
    assert_parent_closed(f, S_RESOLVED, "PARTIALLY_ESCALATED")
    assert len(f.h.escalations.of("T1-1")) == 1
    msgs = await f.assistant_msgs()
    assert len(msgs) == 2
    assert msgs[-1]["text"].splitlines()[-1] == "Đã xong 1/2 yêu cầu; phần còn lại đã chuyển kỹ thuật viên."


async def test_tc32_out_of_scope_child_e1_immediately_partially_escalated() -> None:
    """tc32: con 2 E1 `out_of_scope` ngay (không B6); digest vòng 1: `result` (ý 1) + `escalation` (ý 2); `awaiting` chỉ ý 1 →
    reply {ý 1 confirmed} → cha `PARTIALLY_ESCALATED`."""
    f = make_flow(classify(reset_item(), oos_item()))
    r = await f.submit(TC32)
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "parent_reply_wait")
    assert r.values["awaiting"] == {"T1-1": "confirm"}
    assert not any(step == "B6" for step, _ in f.h.audit.events("T1-2"))
    [d1] = digests(await f.assistant_msgs())
    assert [(i["index"], i["kind"]) for i in d1["items"]] == [(1, "result"), (2, "escalation")]
    await reply(f, {"T1-1": {"confirmed": True}})
    assert_parent_closed(f, S_RESOLVED, "PARTIALLY_ESCALATED")
    assert len(await f.assistant_msgs()) == 2


async def test_tc12r_l1_rejects_child2_partially_rejected() -> None:
    """tc12r: L1 từ chối ý 2 → con 2 `S_REJECTED` (notice `rejection`, `needs=none`) → digest `result` + `rejection` → reply {ý 1} →
    cha `S_RESOLVED`/`PARTIALLY_REJECTED`; 0 lời gọi ghi cho ý 2."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    await f.deliver("T1-2", S_PENDING_APPROVAL, f.decision("T1-2", "rejected", note="Không đủ license"))
    assert (await f.values("T1-2"))["status"] == S_REJECTED
    [nt] = f.h.tickets.notices_of("T1-2")
    assert (nt["kind"], nt["needs"], nt["source_step"]) == ("rejection", "none", "B16")
    [d1] = digests(await f.assistant_msgs())
    assert [i["kind"] for i in d1["items"]] == ["result", "rejection"]
    await reply(f, {"T1-1": {"confirmed": True}})
    assert_parent_closed(f, S_RESOLVED, "PARTIALLY_REJECTED")
    assert f.h.executor.calls["T1-2"] == 0
    assert len(await f.assistant_msgs()) == 2


async def test_control_reset_alone_reaches_confirm_wait() -> None:
    f = make_flow(classify(reset_item()))
    r = await f.submit(RESET)
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "confirm_wait"), f.h.audit.events(f.parent)
    assert ("B6", "diagnosed") in f.h.audit.events(f.parent)  # tên sự kiện mà test k2/v1 dựa vào
    assert f.h.notifier.count(f.parent) == 1 and f.h.tickets.notices == []  # ticket thường: tin qua notifier như cũ (n1)
    assert [w["kind"] for w in f.h.deadlines.waits if w["ticket_id"] == f.parent] == ["confirm"]  # n4: ticket thường có hạn


async def test_control_adobe_alone_reaches_approval_wait() -> None:
    f = make_flow(classify(adobe_item()))
    r = await f.submit(ADOBE)
    assert (r.status, r.waiting_at) == (S_PENDING_APPROVAL, "approval_wait"), f.h.audit.events(f.parent)
    r = await f.deliver(f.parent, S_PENDING_APPROVAL, f.decision(f.parent))
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "confirm_wait"), (
        f.h.audit.events(f.parent)[-4:], r.values.get("exit_code"), r.values.get("escalation_reason_detail"),
        r.values.get("escalation_note"))


async def test_control_extend_alone_asks_then_confirm() -> None:
    f = make_flow(classify(extend_item()), extract={"duration": "30"})
    r = await f.submit(EXTEND)
    assert (r.status, r.waiting_at) == (S_CLARIFYING, "clarify_wait"), f.h.audit.events(f.parent)
    r = await f.deliver(f.parent, S_CLARIFYING, {"kind": "user_reply", "text": "30"})
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "confirm_wait"), f.h.audit.events(f.parent)


async def test_control_out_of_scope_alone_e1() -> None:
    f = make_flow(classify(oos_item()))
    r = await f.submit(PRINTER)
    v: dict[str, Any] = dict(r.values)
    assert (r.status, v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E1", "out_of_scope")
