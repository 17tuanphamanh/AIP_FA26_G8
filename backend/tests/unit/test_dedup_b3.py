"""M1 — B3 báo trùng yêu cầu (sau khi nhận intent của ticket lá).

Graph `nodes="real"` như `test_b03_classify.py`. Ticket "cũ" được gieo thẳng vào bản giả (`MemoryTickets` + dòng audit B3 — nơi
`intent` của ticket CÒN MỞ nằm, vì `tickets.intent` chỉ được ghi ở B20). Bản giả trả TẬP CHA (mọi ticket) để mọi điều kiện lọc phải
do `domain.dedup.pick_duplicate` đảm nhiệm — mutation ở hàm đó đỏ ở đây. Đếm tin ở NƠI NHẬN (`RecordingNotifier`).
Cổng: KHÔNG dừng luồng, KHÔNG đổi `exit_code`; M5 không thấy gì (`test_dedup_isolation_ast.py`).
"""

from datetime import timedelta
from typing import Any

import pytest
from app.domain.context import RequesterContext
from app.domain.final import FinalSummary
from app.domain.states import S_CLASSIFYING, S_DIAGNOSING
from app.graph.builder import wrap_node
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b03_classify
from app.settings import get_dedup
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.unit.test_b03_classify import SESSION_NV001, TEXT, _env, item, out

pytestmark = pytest.mark.asyncio

NOTICE = "Bạn đang có một yêu cầu VPN đang xử lý (mã {tid}). Yêu cầu này vẫn được tiếp nhận."
OK = out(item("vpn", 0.9))


def seed(h: GraphHarness, tid: str, *, requester: str = "nv001", intent: str | None = "vpn", age_h: float = 1.0,
         final: str | None = None, close_reason: str | None = "resolved_user_confirmed", is_parent: bool = False,
         parent: str | None = None) -> None:  # fmt: skip
    """Ticket có sẵn trong 'DB': dòng `tickets` (+ final_state nếu đã đóng) và dòng audit B3 mang `intent`."""
    created = h.clock.now() - timedelta(hours=age_h)
    h.tickets.register(tid, created, requester_id=requester, is_parent=is_parent, parent_ticket_id=parent)
    if intent is not None:
        h.audit.rows.append({"ticket_id": tid, "step": "B3", "event": "intent_classified", "intent": intent, "detail": {}})
    if final is not None:
        h.tickets.rows[tid]["final"] = FinalSummary(
            final_state=final, exit_code=None, block_reason=None, close_reason=close_reason, resolution_path=None,
            aggregate_status=None, auto_closed=False, intent=intent, slots=None, total_turns=1, total_duration_seconds=1,
            closed_at=h.clock.now(),
        )  # fmt: skip


def notices(h: GraphHarness, tid: str = "t1") -> list[str]:
    return [text for t, text, _ in h.notifier.sent if t == tid and "đang xử lý (mã" in text]


def point1(h: GraphHarness, tid: str = "t1") -> dict[str, Any]:
    [row] = [r for r in h.audit.rows if r["ticket_id"] == tid and r["step"] == "B3" and r["event"] == "intent_classified"]
    return row  # type: ignore[no-any-return]


async def run(h: GraphHarness, tid: str = "t1", **kw: Any) -> dict[str, Any]:
    return (await h.submit_as(tid, SESSION_NV001, text=TEXT, **kw)).values  # type: ignore[no-any-return]


# ---- cùng người + cùng intent + còn mở + trong cửa sổ → đúng 1 tin + audit ---------------------------------------------------


async def test_duplicate_sends_one_fixed_notice_and_audits_duplicate_of() -> None:
    h, _ = _env([OK])
    seed(h, "old")
    v = await run(h)
    assert notices(h) == [NOTICE.format(tid="old")]
    assert point1(h)["detail"]["duplicate_of"] == "old"
    assert (point1(h)["from_status"], point1(h)["to_status"]) == (S_CLASSIFYING, S_DIAGNOSING)
    assert ("B6", "diagnosed") in h.audit.events("t1")  # luồng đi tiếp B3 → B6
    assert [m["text"] for m in v["conversation"] if m.get("kind") == "duplicate"] == [NOTICE.format(tid="old")]


async def test_flow_is_identical_with_and_without_duplicate() -> None:
    """KHÔNG dừng luồng, KHÔNG đổi exit_code: cùng kịch bản LLM, chạy có / không ticket trùng → cùng chuỗi bước, cùng trạng thái cuối."""
    dup, _ = _env([OK])
    seed(dup, "old")
    v_dup = await run(dup)
    base, _ = _env([OK])
    v_base = await run(base)
    assert dup.audit.events("t1") == base.audit.events("t1")
    assert (v_dup["status"], v_dup.get("exit_code"), v_dup.get("escalation_reason_detail")) == (
        v_base["status"], v_base.get("exit_code"), v_base.get("escalation_reason_detail"),
    )  # fmt: skip
    assert v_dup["intent"] == v_base["intent"] and v_dup["slots"] == v_base["slots"]


async def test_notice_goes_through_effects_once_with_notify_user_kind() -> None:
    h, _ = _env([OK])
    seed(h, "old")
    await run(h)
    rows = [r for r in h.effects.rows.values() if r["ticket_id"] == "t1" and r["kind"] == "notify_user" and r["step"] == "B3"]
    assert len(rows) == 1


async def test_audit_value_is_a_ticket_id_not_free_text() -> None:
    h, _ = _env([OK])
    seed(h, "old")
    await run(h)
    detail = point1(h)["detail"]
    assert detail["duplicate_of"] == "old"
    assert "đang xử lý" not in repr(detail) and TEXT not in repr(detail)


async def test_most_recent_open_ticket_is_cited() -> None:
    h, _ = _env([OK])
    seed(h, "older", age_h=8)
    seed(h, "newer", age_h=2)
    await run(h)
    assert notices(h) == [NOTICE.format(tid="newer")]


# ---- các ca KHÔNG báo ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case", ["baseline", "other_requester", "other_intent", "outside_window", "closed", "escalated_closed_by_l2", "no_intent"]
)  # fmt: skip
async def test_no_notice_and_no_audit_key(case: str) -> None:
    h, _ = _env([OK])
    if case == "other_requester":
        seed(h, "old", requester="nv002")
    elif case == "other_intent":
        seed(h, "old", intent="account")
    elif case == "outside_window":
        seed(h, "old", age_h=25)
    elif case == "closed":
        seed(h, "old", final="S_RESOLVED")
    elif case == "escalated_closed_by_l2":
        seed(h, "old", final="S_ESCALATED", close_reason="resolved_after_escalation")
    elif case == "no_intent":
        seed(h, "old", intent=None)
    v = await run(h)
    assert notices(h) == [] and "duplicate_of" not in point1(h)["detail"]
    assert not any(m.get("kind") == "duplicate" for m in v["conversation"])
    assert ("B6", "diagnosed") in h.audit.events("t1")


async def test_ticket_escalated_and_waiting_for_a_technician_counts_as_duplicate() -> None:
    """ĐP 08/11: `S_ESCALATED` + `close_reason` NULL (L2 chưa đóng) vẫn là yêu cầu đang xử lý."""
    h, _ = _env([OK])
    seed(h, "old", final="S_ESCALATED", close_reason=None)
    await run(h)
    assert notices(h) == [NOTICE.format(tid="old")] and point1(h)["detail"]["duplicate_of"] == "old"


async def test_window_comes_from_config_not_a_constant() -> None:
    h, _ = _env([OK], dedup=get_dedup().model_copy(update={"DEDUP_WINDOW_HOURS": 2}))
    seed(h, "old", age_h=3)
    await run(h)
    assert notices(h) == []
    h2, _ = _env([OK], dedup=get_dedup().model_copy(update={"DEDUP_WINDOW_HOURS": 4}))
    seed(h2, "old", age_h=3)
    await run(h2)
    assert notices(h2) == [NOTICE.format(tid="old")]


# ---- ticket con không báo trùng với cha ----------------------------------------------------------------------------------------


async def test_child_does_not_duplicate_its_parent_or_sibling() -> None:
    h, _ = _env([OK])
    seed(h, "P", intent="vpn")  # cha còn mở (dòng giả có intent để thử đúng điều kiện loại)
    seed(h, "P-2", intent="vpn", parent="P")
    await run(h, "P-1", parent_ticket_id="P")
    assert notices(h, "P-1") == [] and "duplicate_of" not in point1(h, "P-1")["detail"]


# ---- resume: chạy lại node → vẫn 1 tin -------------------------------------------------------------------------------------------


async def test_rerun_same_turn_still_one_notice() -> None:
    h, _ = _env([OK, OK])
    seed(h, "old")
    h.tickets.register("t1", h.clock.now())
    effects = MemoryEffects()  # CÙNG kho effect = cùng lượt chạy lại (recover sau khi chết giữa gửi tin và checkpoint)
    who = RequesterContext(user_id="nv001", role="employee", department="it", manager_id=None, employment_status="active",
                           tenure_days=400, is_privileged_account=False, captured_at=h.clock.now())  # fmt: skip
    state = {"ticket_id": "t1", "turn_id": "T1", "status": S_CLASSIFYING, "redacted_request": TEXT, "reasoning_loops": 0,
             "conversation": [], "requester_context": who.model_dump(mode="json")}  # fmt: skip
    for _ in range(2):
        run_ctx = RunContext(turn_id="T1", trace_id="0" * 32, audit=MemoryAudit(), effects=effects, spans=MemorySpans(),
                             clock=h.clock, txlog=MemoryTxLog())  # fmt: skip
        with bind_run(run_ctx):
            update = await wrap_node("b03_classify", b03_classify.make(h.deps()))(state)
        assert update["status"] == S_DIAGNOSING
    assert notices(h) == [NOTICE.format(tid="old")]
    assert effects.count("t1", "notify_user") == 1


# ---- output guard ------------------------------------------------------------------------------------------------------------------


async def test_output_guard_violation_suppresses_notice_but_audit_keeps_duplicate_of() -> None:
    bad = get_dedup().model_copy(update={"template": "mật khẩu: Abcd1234xyz đang xử lý {loai} {ma}"})
    h, _ = _env([OK], dedup=bad)
    seed(h, "old")
    v = await run(h)
    assert not [text for t, text, _ in h.notifier.sent if t == "t1" and "Abcd1234xyz" in text]  # tin bị chặn, không ai nhận
    assert point1(h)["detail"]["duplicate_of"] == "old" and not any(m.get("kind") == "duplicate" for m in v["conversation"])
    assert ("B6", "diagnosed") in h.audit.events("t1")
