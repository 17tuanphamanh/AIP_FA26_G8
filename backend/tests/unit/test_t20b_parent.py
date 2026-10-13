"""T20b — `parent_wait` THẬT (phase5 P7, mã giả 5.2.4, 5.2.5; 5.2.8 p1–p4, p6; D-17, D-30, D-31; Q-T20b-3 = A). Viết TỪ ĐẶC TẢ
trước code (không mở `graph/nodes/parent_wait.py`, `graph/children.py`).

Graph THẬT trên harness `_t20b` (2 thread cha/con thật). Kịch bản theo bảng 5.2.7: TC34 (con 1 R01 → `confirm_wait`, con 2 R14 → chờ
duyệt), TC35 (con 1 → `confirm_wait`, con 2 thiếu `duration` → `clarify_wait`), "tất cả kết thúc ngay" (con 1 người khác → E5, con 2 ngoài
phạm vi → E1). Đếm tin ở `conversation` của CHA (`role == "assistant"`). Mọi ca thuộc DỪNG 1 — không xfail (p5 ở `test_t20b_digest.py`).
"""

from typing import Any

import pytest
from app.domain.states import S_CLASSIFYING, S_CONFIRMING, S_ESCALATED
from app.graph.late_event import wake_parent
from tests.fakes.graph import Crash
from tests.unit._t20b import (
    ADOBE,
    PRINTER,
    RESET,
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

CHO_DUNG2: frozenset[str] = frozenset()  # mọi ca thuộc DỪNG 1 — không xfail


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.originalname in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError), reason="T20b DỪNG 2"))


def digests(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in msgs if m.get("kind") == "digest"]


def unfired(f: Flow, ticket_id: str) -> list[str]:
    return [w["kind"] for w in f.h.deadlines.waits if w["ticket_id"] == ticket_id and w["fired_at"] is None]


async def tc34_all_stopped() -> Flow:
    """TC34 tới khi duyệt con 2 (lượt thường của con → after_turn → đánh thức cha → digest vòng 1)."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    await f.deliver("T1-2", "S_PENDING_APPROVAL", f.decision("T1-2"))
    return f


# ---- p1 ------------------------------------------------------------------------------------------------------------------------


async def test_p1_one_child_stopped_other_in_approval_wait_parent_waits_zero_messages() -> None:
    """p1 (M-T20b-4, M-T20b-12): con 1 dừng (`confirm_wait`, notice chưa gửi), con 2 `approval_wait` → cha `interrupt` ở
    `parent_wait`, 0 tin; đánh thức sớm → `goto` quay lại CHÍNH node (`parent_woken`), vẫn 0 tin, notice vẫn chưa gửi."""
    f = make_flow(classify(reset_item(), adobe_item()))
    r = await f.submit(TC34)
    assert (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait")
    assert (await f.waiting("T1-2")) == "approval_wait"
    assert await f.assistant_msgs() == []
    assert f.h.effects.count("T1", "notify_user") == 0
    r2 = await wake_parent(f.h.runner, "T1")
    assert r2 is not None and (r2.status, r2.waiting_at) == (S_CLASSIFYING, "parent_wait")
    [woken] = f.h.audit.of("T1", "parent_woken")
    assert (woken["step"], woken["from_status"], woken["to_status"]) == ("B5", S_CLASSIFYING, S_CLASSIFYING)
    assert await f.assistant_msgs() == []
    [nt] = f.h.tickets.notices_of("T1-1")
    assert nt["delivered_at"] is None and nt["delivered_round"] is None


# ---- p2 ------------------------------------------------------------------------------------------------------------------------


async def test_p2_all_stopped_confirm_only_one_digest_round1() -> None:
    """p2 (M-T20b-7): mọi con dừng (chỉ cần xác nhận) → đúng 1 tin `digest` vòng 1 (2 khối `result`); notice vừa gom có
    `delivered_round=1` + `delivered_at`; hạn `confirm` của cha; `awaiting` đúng; `digest_sent` `CLASSIFYING → CONFIRMING`."""
    f = await tc34_all_stopped()
    assert (await f.waiting("T1")) == "parent_reply_wait"
    v = await f.values("T1")
    assert (v["status"], v["parent_round"]) == (S_CONFIRMING, 1)
    assert v["awaiting"] == {"T1-1": "confirm", "T1-2": "confirm"}
    [d] = digests(await f.assistant_msgs())
    assert len(await f.assistant_msgs()) == 1
    assert (d["round"], [i["child_id"] for i in d["items"]], [i["kind"] for i in d["items"]]) == (
        1, ["T1-1", "T1-2"], ["result", "result"])  # fmt: skip
    assert [i["needs"] for i in d["items"]] == ["confirm", "confirm"]
    for cid in ("T1-1", "T1-2"):
        [nt] = f.h.tickets.notices_of(cid)
        assert nt["delivered_round"] == 1 and nt["delivered_at"] is not None
    assert unfired(f, "T1") == ["confirm"]
    assert f.h.effects.count("T1", "notify_user") == 1 and f.h.effects.count("T1", "deadline_set") == 1
    [sent] = f.h.audit.of("T1", "digest_sent")
    assert (sent["step"], sent["from_status"], sent["to_status"]) == ("B5", S_CLASSIFYING, S_CONFIRMING)


async def test_p2_question_round_sets_clarify_deadline() -> None:
    """p2: có câu hỏi (notice `needs=answer`) → hạn `clarify` của cha; `awaiting={con 1: confirm, con 2: answer}`; khối `result` +
    `question`. Cả hai con dừng ngay trong lượt submit → digest ngay (không cần đánh thức)."""
    f = make_flow(classify(reset_item(), extend_item()), extract={"duration": "30"})
    r = await f.submit(TC35)
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "parent_reply_wait")
    assert r.values["awaiting"] == {"T1-1": "confirm", "T1-2": "answer"}
    [d] = digests(await f.assistant_msgs())
    assert [i["kind"] for i in d["items"]] == ["result", "question"]
    assert [i["needs"] for i in d["items"]] == ["confirm", "answer"]
    assert unfired(f, "T1") == ["clarify"]
    assert [w for w in f.h.deadlines.waits if w["ticket_id"] in ("T1-1", "T1-2")] == []  # n4: con không đặt hạn


# ---- p3 ------------------------------------------------------------------------------------------------------------------------


async def test_p3_rerun_after_sent_no_resend_no_remark() -> None:
    """p3 (M-T20b-7): process chết SAU khi đã gửi (dòng audit `digest_sent` chưa ghi, checkpoint chưa có) → chạy lại `parent_wait`
    cùng lượt: không gửi lại (1 `notify_user`), không đánh dấu lại (notice vẫn vòng 1, `delivered_at` không đổi), không quá 1 tin."""
    f = make_flow([classify(reset_item(), extend_item())] * 2, extract={"duration": "30"})
    f.h.audit.crash_once.add("digest_sent")
    with pytest.raises(Crash):
        await f.submit(TC35)
    marks = {n["notice_id"]: (n["delivered_round"], n["delivered_at"]) for n in f.h.tickets.notices}
    assert marks and all(rnd == 1 for rnd, _ in marks.values())
    [turn] = [t["turn_id"] for t in f.h.turns.of("T1") if t["ended_at"] is None]
    f.h.restart()
    await f.h.runner.recover("T1", turn)
    assert f.h.effects.count("T1", "notify_user") == 1
    assert {n["notice_id"]: (n["delivered_round"], n["delivered_at"]) for n in f.h.tickets.notices} == marks
    assert len(digests(await f.assistant_msgs())) <= 1


# ---- p4 + p6: mọi con kết thúc trước khi cha tới parent_wait --------------------------------------------------------------------


async def test_p4_p6_all_children_end_before_parent_wait_closes_now() -> None:
    """p4 (D-17, TC32 nhanh): mọi con kết thúc ngay khi khởi động (con 1 nhắm người khác → E5, con 2 ngoài phạm vi → E1) → cha đóng
    ngay `S_ESCALATED`/`ALL_ESCALATED`, đúng 1 tin (2 khối `escalation` + câu tổng kết), không cần đánh thức.
    p6 (D-30, M-T20b-9): cha `close_reason`/`exit_code` NULL, 0 `escalations` của cha, `resolution_path` NULL, hàng đợi L2 không có cha."""
    reset_other = f"{RESET} cho Nguyễn Văn A"
    i1 = item("account", reset_other, action="reset_password", slots={"account_type": "ad", "target_user": "Nguyễn Văn A"})
    f = make_flow(classify(i1, oos_item()))
    r = await f.submit(f"{reset_other}, tiện {PRINTER}")
    assert (r.status, r.waiting_at) == (S_ESCALATED, None), f.h.audit.events("T1")
    assert [t["event_type"] for t in f.h.turns.of("T1")] == ["submit"]  # không lượt đánh thức nào
    v = await f.values("T1")
    assert (v["aggregate_status"], v.get("exit_code"), v.get("close_reason")) == ("ALL_ESCALATED", None, None)
    msgs = await f.assistant_msgs()
    [d] = digests(msgs)
    assert len(msgs) == 1
    assert [i["kind"] for i in d["items"]] == ["escalation", "escalation"]
    assert d["text"].splitlines()[-1] == "Các yêu cầu đã được chuyển kỹ thuật viên."
    [agg] = f.h.audit.of("T1", "children_aggregated")
    assert (agg["step"], agg["to_status"]) == ("B5", S_ESCALATED)
    final = f.h.tickets.final("T1")
    assert final is not None
    assert (final.final_state, final.aggregate_status, final.exit_code, final.close_reason, final.resolution_path) == (
        S_ESCALATED, "ALL_ESCALATED", None, None, None)  # fmt: skip
    assert f.h.escalations.of("T1") == []
    assert len(f.h.escalations.of("T1-1")) == 1 and len(f.h.escalations.of("T1-2")) == 1
    queue = [q.ticket_id for q in await f.h.escalations.list_open(50)]
    assert "T1" not in queue and {"T1-1", "T1-2"} <= set(queue)


async def test_p_parent_digest_only_after_all_stopped_no_child_message_reaches_user() -> None:
    """D-31 (bảng 5.2.7 tc34): trước khi duyệt con 2 → 0 tin tới người dùng (cha 0 tin assistant; con không gửi qua notifier);
    chỉ khối của span (không lấy câu khác) — tiêu đề theo nhãn."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    assert await f.assistant_msgs() == [] and f.h.notifier.sent == []
    await f.deliver("T1-2", "S_PENDING_APPROVAL", f.decision("T1-2"))
    [d] = digests(await f.assistant_msgs())
    assert ADOBE not in d["text"] and RESET not in d["text"]  # thân = body notice + nhãn, không chép span
