"""Việc treo 21 (3h DỪNG 3b): boundary (`graph/boundary.py`) hỏi `transaction_log` `begun` THEO TICKET trước khi hạ lỗi xuống
E2/E9 — ticket đã có `begun` không bao giờ mang mẫu E9 "xử lý thủ công" (chốt FAIL mục 7 c).

- Lỗi ở node sau B17 (B19 `confirm_wait`, lượt resume) trên ticket có `begun` ở lượt TRƯỚC → E7 `execution_interrupted` + câu
  "có thể đã gửi lệnh ghi…" (audit như nhánh cũ + `begun`); `begun` của ticket khác / không có → E9 như cũ.
- `TurnBudgetExceeded` sau `begun` → E7; không có → E2 như cũ.
- `has_begun` ném lỗi → nổi tiếp, không audit/E9, lượt không đóng; worker recover tới cạn lượt → runner `_give_up` xét `begun` → E7.
- Runner `_pending`: node chờ vừa resume mà `Exception` nổi ra (`snap.next == ()`) vẫn là "còn dở" — recover chạy lại nó,
  không đóng lượt bỏ ticket kẹt ở trạng thái chờ (lỗi có từ trước: goto E9 lỗi trong node chờ).
- Trạng thái đã kết thúc/escalate (B20): giữ nguyên — audit + ném tiếp, kể cả khi có `begun`.
- `RunContext.txlog` bắt buộc.

Lỗi ở `goto(S_CONFIRMING)` cuối B17 sau khi ghi thành công: `test_b17_execute.py::test_t21_final_goto_error_after_write_is_e7_not_e9`.
"""

from collections.abc import Mapping
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.core.turn_budget import TurnBudgetExceeded
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_RESOLVED
from app.graph.boundary import with_error_boundary
from app.graph.context import RunContext, bind_run
from app.graph.late_event import deliver_event
from app.graph.runner import RECOVER_EXHAUSTED
from app.settings import get_escalation_templates
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans

MAY_HAVE_WRITTEN = "có thể đã gửi lệnh ghi — L2 kiểm trên hệ thống đích trước khi làm tay"
STATE = {"ticket_id": "t1", "turn_id": "T2", "status": S_CONFIRMING, "reasoning_loops": 1}


def _fail_audit(audit: MemoryAudit, event: str) -> None:
    """Audit sập đúng ở dòng `event` — `goto` của node ném lỗi (các dòng khác ghi bình thường)."""
    real = audit.record

    async def record(row: Mapping[str, Any], **kw: Any) -> bool:
        if row["event"] == event:
            raise RuntimeError("audit sập")
        return await real(row, **kw)

    audit.record = record  # type: ignore[method-assign]


async def _confirming(h: GraphHarness) -> str:
    r = await h.submit("t1", b12_assess="auto")
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "confirm_wait")
    return str(r.turn_id)


def _open_turns(h: GraphHarness) -> list[str]:
    return [t for t, r in h.turns.rows.items() if r["ended_at"] is None]


def _run(audit: MemoryAudit, txlog: MemoryTxLog) -> RunContext:
    return RunContext(turn_id="T2", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
                      clock=FakeClock(), txlog=txlog)  # fmt: skip


# ---- lỗi ở B19 (lượt sau lượt đã ghi) ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t21_error_in_b19_on_ticket_with_begun_is_e7_warning() -> None:
    h = GraphHarness()
    first = await _confirming(h)
    await h.txlog.begin("t1", first, "renew_vpn_cert")  # executor thật đã ghi ở lượt submit (lượt TRƯỚC)
    _fail_audit(h.audit, "user_confirmed")
    r = await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "confirmed"})
    assert r.turn_id != first
    assert (r.status, r.values["exit_code"], r.values["escalation_reason_detail"]) == (
        S_ESCALATED, "E7", "execution_interrupted")  # fmt: skip
    assert MAY_HAVE_WRITTEN in r.values["escalation_note"]
    [row] = h.audit.of("t1", "unhandled_exception")
    assert (row["step"], row["exit_code"], row["turn_id"]) == ("confirm_wait", "E7", r.turn_id)
    assert row["detail"]["begun"] is True and "RuntimeError" in row["detail"]["traceback"]  # như nhánh cũ + begun
    [esc] = h.escalations.of("t1")
    assert (esc["exit_code"], esc["reason_detail"]) == ("E7", "execution_interrupted")
    assert MAY_HAVE_WRITTEN in esc["handoff_note"]["why_escalated"]
    assert get_escalation_templates().of("E9").next_for_l2 not in str(esc["handoff_note"])
    assert r.waiting_at is None and _open_turns(h) == [] and h.tickets.final("t1") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("begun_on", [None, "t2"], ids=["no_begun", "begun_of_other_ticket"])
async def test_t21_error_in_b19_without_begun_of_this_ticket_stays_e9(begun_on: str | None) -> None:
    h = GraphHarness()
    first = await _confirming(h)
    if begun_on is not None:
        await h.txlog.begin(begun_on, first, "renew_vpn_cert")
    _fail_audit(h.audit, "user_confirmed")
    r = await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "confirmed"})
    assert (r.status, r.values["exit_code"]) == (S_ESCALATED, "E9")
    assert r.values["escalation_note"] == "Lỗi hệ thống không lường trước tại confirm_wait"
    [row] = h.audit.of("t1", "unhandled_exception")
    assert row["exit_code"] == "E9" and "begun" not in row["detail"]


# ---- hết hạn lượt sau begun ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("begun", "exit_code", "reason"), [(True, "E7", "execution_interrupted"),
                                                            (False, "E2", "turn_budget_exceeded")])  # fmt: skip
async def test_t21_turn_budget_after_begun_is_e7(begun: bool, exit_code: str, reason: str) -> None:
    audit, txlog = MemoryAudit(), MemoryTxLog()
    if begun:
        await txlog.begin("t1", "T1", "renew_vpn_cert")

    async def node(state: Any) -> dict[str, Any]:
        raise TurnBudgetExceeded("confirm_wait: còn 0.0 s")

    with bind_run(_run(audit, txlog)):
        out = await with_error_boundary("confirm_wait", node)(dict(STATE))
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, exit_code, reason)
    assert (MAY_HAVE_WRITTEN in str(out.get("escalation_note"))) is begun
    [row] = audit.of("t1", "turn_budget_exceeded")
    assert row["detail"]["node"] == "confirm_wait" and row["detail"].get("begun") is (True if begun else None)


# ---- has_begun lỗi: fail-closed --------------------------------------------------------------------------------------


class BrokenTxLog(MemoryTxLog):
    async def has_begun(self, ticket_id: str) -> bool:
        raise ConnectionError("postgres không trả lời")


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [ValueError("bug"), TurnBudgetExceeded("hết hạn")], ids=["unhandled", "turn_budget"])
async def test_t21_has_begun_error_propagates_not_e9(exc: Exception) -> None:
    audit = MemoryAudit()

    async def node(state: Any) -> dict[str, Any]:
        raise exc

    with bind_run(_run(audit, BrokenTxLog())), pytest.raises(ConnectionError) as info:
        await with_error_boundary("confirm_wait", node)(dict(STATE))
    assert info.value.__context__ is exc  # lỗi gốc còn trong chuỗi
    assert audit.rows == []  # không E9, không E2, không audit


@pytest.mark.asyncio
async def test_t21_has_begun_error_keeps_turn_open_then_recover_exhausted_is_e7() -> None:
    """(c) trọn đường: `has_begun` lỗi → lượt không đóng, không escalation; worker recover (lỗi lặp lại) tới cạn lượt → runner
    `_give_up` xét `begun` (lúc này DB đã trả lời) → E7 `execution_interrupted`, không E9 `recover_exhausted`."""
    h = GraphHarness()
    first = await _confirming(h)
    await h.txlog.begin("t1", first, "renew_vpn_cert")
    _fail_audit(h.audit, "user_confirmed")
    real, down = h.txlog.has_begun, [True]

    async def has_begun(ticket_id: str) -> bool:
        if down[0]:
            raise ConnectionError("postgres không trả lời")
        return await real(ticket_id)

    h.txlog.has_begun = has_begun  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "confirmed"})
    [open_turn] = _open_turns(h)
    assert h.audit.of("t1", "unhandled_exception") == [] and h.escalations.of("t1") == []
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await h.runner.recover("t1", open_turn)
    down[0] = False
    r = await h.runner.recover("t1", open_turn)  # lần thứ 4: cạn lượt
    assert r is not None
    assert (r.values["exit_code"], r.values["escalation_reason_detail"]) == ("E7", "execution_interrupted")
    assert MAY_HAVE_WRITTEN in r.values["escalation_note"]
    [row] = h.audit.of("t1", RECOVER_EXHAUSTED)
    assert row["detail"]["begun"] is True and row["detail"]["node"] == "confirm_wait"
    assert _open_turns(h) == [] and h.audit.of("t1", "unhandled_exception") == []


@pytest.mark.asyncio
async def test_t21_recover_reruns_resumed_wait_node_that_raised() -> None:
    """Đối chứng không có `begun`: goto của B19 lẫn goto E9 của boundary cùng lỗi (audit sập) → lỗi nổi ra khỏi node chờ vừa
    resume → `snap.next == ()`. Recover phải chạy lại B19 với đúng giá trị resume (→ S_RESOLVED), không coi là "đã kết thúc"."""
    h = GraphHarness()
    await _confirming(h)
    real = h.audit.record

    async def record(row: Mapping[str, Any], **kw: Any) -> bool:
        if row["event"] in ("user_confirmed", "unhandled_exception"):
            raise RuntimeError("audit sập")
        return await real(row, **kw)

    h.audit.record = record  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="audit sập"):
        await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "confirmed"})
    snap = await h.runner.snapshot("t1")
    assert snap.next == () and [t.name for t in snap.tasks] == ["confirm_wait"]  # điều kiện của lỗi cũ
    [open_turn] = _open_turns(h)
    h.audit.record = real  # type: ignore[method-assign]
    r = await h.restart().recover("t1", open_turn)
    assert r is not None and (r.status, r.values["close_reason"]) == (S_RESOLVED, "resolved_user_confirmed")
    assert _open_turns(h) == [] and h.tickets.final("t1") is not None


# ---- (d) nhánh đã kết thúc giữ nguyên; (a) txlog bắt buộc ------------------------------------------------------------


@pytest.mark.asyncio
async def test_t21_terminal_status_still_records_and_reraises_even_with_begun() -> None:
    h = GraphHarness()
    await h.txlog.begin("t1", "T0", "renew_vpn_cert")
    h.tickets.fail = RuntimeError("lỗi giả tại b20")
    with pytest.raises(RuntimeError, match="lỗi giả tại b20"):
        await h.submit("t1", b12_assess="deny")
    [row] = h.audit.of("t1", "unhandled_exception")
    assert row["step"] == "b20_audit" and "begun" not in row["detail"]
    snap = await h.runner.snapshot("t1")
    assert (snap.values["exit_code"], snap.next) == ("E5", ("b20_audit",))
    assert len(_open_turns(h)) == 1


def test_t21_run_context_requires_txlog() -> None:
    with pytest.raises(TypeError, match="txlog"):
        RunContext(turn_id="T1", trace_id="0" * 32, audit=MemoryAudit(), effects=MemoryEffects(),  # type: ignore[call-arg]
                   spans=MemorySpans(), clock=FakeClock())  # fmt: skip
