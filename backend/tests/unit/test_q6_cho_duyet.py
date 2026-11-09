"""Q6 (ĐP 09/11) — ý chờ duyệt không giữ câu hỏi của ý khác. Viết TRƯỚC code (DỪNG 1). Agent chính viết (không phải test-writer).

Bằng chứng (audit ticket 0106501f…): con 1 B15 `queued` 15:12:11, con 2 B11 hỏi 15:12:21, cha chỉ gửi vòng 1 lúc 15:43:47 (con 1 E6) — người
dùng không thấy câu hỏi của con 2 suốt 31 phút. Nguyên nhân: `domain.stopped()` coi "chờ L1 duyệt" KHÔNG phải điểm dừng.

Luật mới (PLAN Q6, chờ ĐP duyệt):
- Con "đã dừng" = kết thúc, HOẶC có notice chưa gửi `needs ≠ none`, HOẶC đang chờ duyệt (phiếu `pending` + không còn lượt mở — DB, D-17).
- Một vòng gửi khi: mọi con đã dừng VÀ (có ít nhất một notice chưa gửi HOẶC mọi con đã kết thúc — vòng tổng kết không có notice, tc34).
- Sau vòng: còn ý chờ người dùng → hạn clarify/confirm → `parent_reply_wait` (như cũ, `awaiting` CHỈ gồm ý chờ người dùng); không ý nào chờ
  người dùng mà còn con chờ duyệt → quay lại `parent_wait` (S_CLASSIFYING), KHÔNG đặt hạn người dùng; mọi con kết thúc → aggregate như cũ.

Notice "chờ duyệt" là notice THẬT của B15 (Q3 M4: `effects.once("notify_user", sub="approval_pending")` → `ChildAwareNotifier`, kind `result`,
needs `none`) — không giả lập. Ý chờ duyệt dùng Adobe Acrobat Pro (R14, như tc34); ý hỏi lại dùng gia hạn quyền (như tc35).
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from app.domain.children import ChildView, Notice, round_ready, stopped
from app.domain.states import (
    S_CLASSIFYING,
    S_CONFIRMING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
    S_RESOLVED,
)
from app.graph.late_event import wake_parent
from app.graph.worker_jobs import WorkerJobs
from tests.fakes.graph import Crash
from tests.unit._t20b import (
    ADOBE,
    ADOBE_PRINTER,
    EXTEND,
    TWO_APPROVALS,
    Flow,
    adobe_item,
    classify,
    extend_item,
    grant_item,
    make_flow,
    oos_item,
)

pytestmark = pytest.mark.asyncio

APPROVE_PLUS_ASK = f"{ADOBE} với lại {EXTEND} cho mình"  # ý 1 chờ duyệt, ý 2 hỏi lại (như ca 31 phút)
PENDING_TEXT = "cần được duyệt"


def digests(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in msgs if m.get("kind") == "digest"]


def shape(d: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(i["child_id"], i["kind"], i["needs"]) for i in d["items"]]


async def reply(f: Flow, items: dict[str, dict[str, Any]]) -> None:
    r = await f.deliver("T1", S_CONFIRMING, {"kind": "reply", "items": items})
    assert r.status is not None


def parent_waits(f: Flow) -> list[str]:
    return [w["kind"] for w in f.h.deadlines.waits if w["ticket_id"] == "T1" and w["fired_at"] is None]


# ---- thuần: điều kiện dừng + điều kiện gửi vòng ------------------------------------------------------------------------------------------

_AT = datetime(2026, 11, 9, 15, 12, tzinfo=UTC)


def _n(nid: int, cid: str, needs: str = "none", kind: str = "result") -> Notice:
    return Notice(nid, cid, "B15", kind, needs, "x", _AT)  # type: ignore[arg-type]


def _v(i: int, *, final: str | None = None, pending: tuple[Notice, ...] = (), approval: bool = False) -> ChildView:
    return ChildView(f"T1-{i}", i, final, pending, awaiting_approval=approval)


async def test_stopped_counts_awaiting_approval() -> None:
    """Mutation 1 (trả `stopped()` về bản cũ) đỏ ở đây và ở ca 31 phút."""
    assert stopped(_v(1, approval=True))
    assert not stopped(_v(1))  # đang xử lý (không phiếu pending, không notice) — vẫn chưa dừng
    assert not stopped(_v(1, pending=(_n(1, "T1-1"),)))  # notice needs=none một mình KHÔNG làm con dừng (như cũ)


async def test_round_ready_needs_one_unsent_notice_unless_all_closed() -> None:
    """Mutation 2 (bỏ điều kiện "có ít nhất một notice") đỏ ở đây và ở ca chờ con."""
    asked = _v(2, pending=(_n(2, "T1-2", "answer", "question"),))
    assert round_ready([_v(1, approval=True, pending=(_n(1, "T1-1"),)), asked])
    assert round_ready([_v(1, approval=True), asked])  # notice chờ duyệt đã gửi vòng trước: không chặn câu hỏi của ý 2
    assert not round_ready([_v(1, approval=True), _v(2, approval=True)])  # mọi notice đã gửi → KHÔNG gửi vòng rỗng
    assert not round_ready([_v(1, approval=True), _v(2, final=S_RESOLVED)])
    assert round_ready([_v(1, final=S_RESOLVED), _v(2, final=S_RESOLVED)])  # vòng tổng kết (tc34): 0 notice vẫn gửi
    assert not round_ready([_v(1), asked])  # một con đang xử lý → chờ (như cũ)


# ---- luồng: ca 31 phút ------------------------------------------------------------------------------------------------------------------


async def test_q6_round_one_sent_at_once_with_pending_notice_and_question() -> None:
    """Ca audit 0106501f: vòng 1 gửi NGAY trong lượt gửi câu — có cả "chờ duyệt" của ý 1 và câu hỏi của ý 2; `awaiting` chỉ ý 2;
    hạn của cha = clarify; con 1 vẫn chờ duyệt."""
    f = make_flow(classify(adobe_item(), extend_item()), extract={"duration": "30"})
    r = await f.submit(APPROVE_PLUS_ASK)
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "parent_reply_wait"), f.h.audit.events("T1")
    assert r.values["awaiting"] == {"T1-2": "answer"}
    [d1] = digests(await f.assistant_msgs())
    assert d1["round"] == 1 and shape(d1) == [("T1-1", "result", "none"), ("T1-2", "question", "answer")]
    assert PENDING_TEXT in d1["items"][0]["text"]
    pending, = f.h.tickets.notices_of("T1-1")
    assert (pending["source_step"], pending["delivered_round"]) == ("B15", 1)  # notice THẬT của B15, đã gửi ở vòng 1
    assert parent_waits(f) == ["clarify"]
    assert (await f.waiting("T1-1")) == "approval_wait"


async def test_q6_answer_item2_then_approve_item1_new_round_without_repeat() -> None:
    """Trả lời ý 2 → ý 2 chạy tiếp, vòng 2 KHÔNG lặp "chờ duyệt" của ý 1; xác nhận ý 2 → không có gì để báo → cha CHỜ CON (không vòng
    rỗng, không hạn mới); duyệt ý 1 → vòng 3 mang kết quả ý 1 → xác nhận → `ALL_RESOLVED`. Số tin assistant cha = số lượt người dùng."""
    f = make_flow(classify(adobe_item(), extend_item()), extract={"duration": "30"})
    await f.submit(APPROVE_PLUS_ASK)
    await reply(f, {"T1-2": {"answer": "30"}})
    assert f.h.executor.calls["T1-2"] == 1 and f.h.executor.calls["T1-1"] == 0
    d2 = digests(await f.assistant_msgs())[-1]
    assert (d2["round"], shape(d2)) == (2, [("T1-2", "result", "confirm")])
    assert (await f.values("T1"))["awaiting"] == {"T1-2": "confirm"}

    await reply(f, {"T1-2": {"confirmed": True}})
    assert (await f.values("T1-2"))["status"] == S_RESOLVED
    v = await f.values("T1")
    assert (await f.waiting("T1"), v["status"], v["parent_round"]) == ("parent_wait", S_CLASSIFYING, 2)
    assert len(digests(await f.assistant_msgs())) == 2  # không vòng rỗng

    await f.deliver("T1-1", S_PENDING_APPROVAL, f.decision("T1-1"))
    d3 = digests(await f.assistant_msgs())[-1]
    assert (d3["round"], shape(d3)) == (3, [("T1-1", "result", "confirm")])
    assert (await f.values("T1"))["awaiting"] == {"T1-1": "confirm"}
    await reply(f, {"T1-1": {"confirmed": True}})
    final = f.h.tickets.final("T1")
    assert final is not None and (final.final_state, final.aggregate_status) == (S_RESOLVED, "ALL_RESOLVED")
    assert len(await f.assistant_msgs()) == 1 + len(await f.user_msgs()) == 4  # lượt người dùng = gửi câu + 3 lần trả lời


async def test_q6_approval_while_parent_waits_reply_is_carried_by_next_round() -> None:
    """[Điểm ĐP chốt Đ3] Duyệt ý 1 TRONG LÚC cha chờ người dùng trả lời ý 2: không gửi tin chen (một lượt người dùng — một tin); kết quả
    ý 1 đi cùng vòng sau lần trả lời kế tiếp. Khung tiến độ (`children_progress`) đã thấy ý 1 `closed`/`ready` ngay."""
    f = make_flow(classify(adobe_item(), extend_item()), extract={"duration": "30"})
    await f.submit(APPROVE_PLUS_ASK)
    await f.deliver("T1-1", S_PENDING_APPROVAL, f.decision("T1-1"))
    assert (await f.waiting("T1"), len(digests(await f.assistant_msgs()))) == ("parent_reply_wait", 1)
    await reply(f, {"T1-2": {"answer": "30"}})
    d2 = digests(await f.assistant_msgs())[-1]
    assert (d2["round"], shape(d2)) == (2, [("T1-1", "result", "confirm"), ("T1-2", "result", "confirm")])
    assert (await f.values("T1"))["awaiting"] == {"T1-1": "confirm", "T1-2": "confirm"}


# ---- luồng: chỉ còn con chờ duyệt → cha chờ con, không hạn người dùng -------------------------------------------------------------------


async def test_q6_e6_item1_new_round_parent_aggregates() -> None:
    """Ý 1 chờ duyệt + ý 2 E1 ngay → vòng 1 (chờ duyệt + escalation) gửi ngay, KHÔNG ý nào chờ người dùng → cha ở `parent_wait`
    (S_CLASSIFYING), 0 hạn người dùng; ý 1 hết hạn duyệt (E6) → vòng 2 → cha `S_ESCALATED`/`ALL_ESCALATED`, D-30 giữ nguyên."""
    f = make_flow(classify(adobe_item(), oos_item()))
    r = await f.submit(ADOBE_PRINTER)
    assert (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait"), f.h.audit.events("T1")
    [d1] = digests(await f.assistant_msgs())
    assert shape(d1) == [("T1-1", "result", "none"), ("T1-2", "escalation", "none")]
    assert (await f.values("T1"))["parent_round"] == 1 and parent_waits(f) == []
    assert ("B5", "digest_sent") in f.h.audit.events("T1")

    await f.deliver("T1-1", S_PENDING_APPROVAL, {"kind": "timeout"})
    assert (await f.values("T1-1"))["exit_code"] == "E6"
    d2 = digests(await f.assistant_msgs())[-1]
    assert (d2["round"], shape(d2)) == (2, [("T1-1", "escalation", "none")])
    final = f.h.tickets.final("T1")
    assert final is not None
    assert (final.final_state, final.aggregate_status, final.exit_code, final.close_reason) == (
        S_ESCALATED, "ALL_ESCALATED", None, None)  # fmt: skip
    assert f.h.escalations.of("T1") == [] and len(await f.assistant_msgs()) == 2


async def test_q6_two_items_both_pending_one_round_no_user_deadline() -> None:
    """2 ý cùng chờ duyệt → MỘT vòng báo cả hai; cha chờ con, không đặt hạn người dùng, `awaiting` rỗng; đánh thức thừa không gửi lại.
    Duyệt từng ý → mỗi kết quả một vòng mới."""
    f = make_flow(classify(adobe_item(), grant_item()))
    r = await f.submit(TWO_APPROVALS)
    assert (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait"), f.h.audit.events("T1")
    assert [await f.waiting(c) for c in ("T1-1", "T1-2")] == ["approval_wait", "approval_wait"]
    [d1] = digests(await f.assistant_msgs())
    assert shape(d1) == [("T1-1", "result", "none"), ("T1-2", "result", "none")]
    assert all(PENDING_TEXT in i["text"] for i in d1["items"])
    assert parent_waits(f) == [] and not (await f.values("T1")).get("awaiting")

    await wake_parent(f.h.runner, "T1")  # đánh thức thừa (worker / tín hiệu lặp)
    assert len(digests(await f.assistant_msgs())) == 1 and (await f.values("T1"))["parent_round"] == 1

    await f.deliver("T1-2", S_PENDING_APPROVAL, f.decision("T1-2"))
    d2 = digests(await f.assistant_msgs())[-1]
    assert d2["round"] == 2 and [i["child_id"] for i in d2["items"]] == ["T1-2"]


# ---- chạy lại / phục hồi ----------------------------------------------------------------------------------------------------------------


async def test_q6_rerun_after_round_sent_on_wait_children_branch_no_duplicate() -> None:
    """Process chết sau khi vòng 1 (nhánh chờ con) đã gửi, trước checkpoint → phục hồi dựng lại ĐÚNG vòng 1 (khoá `round:1`), không gửi
    lại, không gom notice tới sau, rồi chờ con."""
    f = make_flow([classify(adobe_item(), oos_item())] * 2)
    f.h.audit.crash_once.add("digest_sent")
    with pytest.raises(Crash):
        await f.submit(ADOBE_PRINTER)
    sent = {n["notice_id"] for n in f.h.tickets.notices if n["delivered_round"] == 1}
    assert len(sent) == 2
    [turn] = [t["turn_id"] for t in f.h.turns.of("T1") if t["ended_at"] is None]
    f.h.restart()
    r = await f.h.runner.recover("T1", turn)
    assert r is not None and (r.status, r.waiting_at) == (S_CLASSIFYING, "parent_wait")
    [d1] = digests(await f.assistant_msgs())
    assert d1["round"] == 1 and len(d1["items"]) == 2
    assert {n["notice_id"] for n in f.h.tickets.notices if n["delivered_round"] == 1} == sent
    assert f.h.effects.count("T1", "notify_user") == 1


# ---- S5: lưới an toàn `parents_to_wake` theo đúng `round_ready` ---------------------------------------------------------------------


async def test_q6_s5_safety_net_matches_round_ready() -> None:
    """S5 (D-77, NGHI-2): hai con chờ duyệt đã báo ở vòng 1 → lưới KHÔNG chọn cha (không notice mới — không đánh thức mỗi 60 s); duyệt
    con 2 mà tín hiệu đánh thức bị mất → con 1 vẫn chờ duyệt + con 2 có notice chưa gửi → lưới chọn cha, `scan_parents` đánh thức đúng 1
    lần → vòng 2 chỉ ý 2. Mutation: bỏ vế "chờ duyệt" → đỏ ở lần chọn thứ hai; bỏ vế "có notice" → đỏ ở lần đầu."""
    f = make_flow(classify(adobe_item(), grant_item()))
    await f.submit(TWO_APPROVALS)
    assert (await f.waiting("T1")) == "parent_wait"
    assert "T1" not in await f.h.deadlines.parents_to_wake(10)

    async def lost(_: str) -> None:  # tín hiệu đánh thức bị mất (process chết sau khi nhả khoá con)
        return None

    original = f.h.runner.wake_parent
    f.h.runner.wake_parent = lost  # type: ignore[method-assign,assignment]
    await f.deliver("T1-2", S_PENDING_APPROVAL, f.decision("T1-2"))
    f.h.runner.wake_parent = original  # type: ignore[method-assign]
    assert (await f.waiting("T1-1"), len(digests(await f.assistant_msgs()))) == ("approval_wait", 1)
    assert "T1" in await f.h.deadlines.parents_to_wake(10)
    report = await WorkerJobs(f.h.runner, f.h.deadlines, f.h.turns).scan_parents()
    assert report.woken == 1
    d2 = digests(await f.assistant_msgs())[-1]
    assert d2["round"] == 2 and [i["child_id"] for i in d2["items"]] == ["T1-2"]
