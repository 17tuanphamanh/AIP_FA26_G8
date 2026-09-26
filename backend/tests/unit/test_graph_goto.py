"""goto() — P1 mục 5.1, 5.1.1, mục 11 dòng 1–2: bảng chuyển, 6 chuyển cấm (FORBIDDEN thắng
is_allowed), cấm 4 đầy đủ (audit trong cùng transaction), khoá idempotent D-14 v1.2."""

import itertools
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.core.hashing import hash_action
from app.domain.states import (
    ALL_STATES,
    S_ASSESSING,
    S_CLARIFYING,
    S_DIAGNOSING,
    S_ESCALATED,
    S_EXECUTING,
    S_PENDING_APPROVAL,
    S_RESOLVED,
    S_RETRIEVING,
    S_SCREENING,
    IllegalTransition,
    check_transition,
)
from app.graph.context import RunContext, bind_run
from app.graph.fakes import FAKE_ACTION, fake_risk
from app.graph.goto import audit_key, goto
from tests.fakes.graph import MemoryAudit, MemoryEffects, MemorySpans


@contextmanager
def run(audit: MemoryAudit, turn_id: str = "T1", rediag: bool = False) -> Iterator[RunContext]:
    ctx = RunContext(
        turn_id=turn_id, trace_id="0" * 32, audit=audit, effects=MemoryEffects(),
        spans=MemorySpans(), clock=FakeClock(), rediagnose_on_new_slot=rediag,
    )  # fmt: skip
    with bind_run(ctx):
        yield ctx


def state(status: str, **extra: Any) -> dict[str, Any]:
    return {"ticket_id": "t1", "turn_id": "T1", "status": status, **extra}


def _domain_allows(st: dict[str, Any], frm: str, to: str) -> bool:
    try:
        check_transition(st, frm, to, step="Bx", event="e")
    except IllegalTransition:
        return False
    return True


@pytest.mark.asyncio
@pytest.mark.parametrize("is_parent", [False, True])
async def test_goto_matches_transition_table_for_every_pair(is_parent: bool) -> None:
    """Mọi cặp (14×14): goto qua ⇔ bảng chuyển cho qua; bị chặn thì KHÔNG có dòng audit."""
    for frm, to in itertools.product(sorted(ALL_STATES), repeat=2):
        audit = MemoryAudit()
        st = state(frm, is_parent=is_parent)
        with run(audit):
            if _domain_allows(st, frm, to):
                out = await goto(st, to, next_node="n", step="Bx", event="e")
                assert out["status"] == to and out["next"] == "n"
                assert [(r["from_status"], r["to_status"]) for r in audit.rows] == [(frm, to)]
            else:
                with pytest.raises(IllegalTransition):
                    await goto(st, to, next_node="n", step="Bx", event="e")
                assert audit.rows == [], (frm, to)


APPROVED_HASH = hash_action(FAKE_ACTION)

FORBIDDEN_CASES = {
    "F1_rule_bypass": (state(S_ASSESSING, risk=fake_risk("HITL")), S_EXECUTING, {}),
    "F2_no_approval": (
        state(S_PENDING_APPROVAL, intended_action=FAKE_ACTION, action_plan_hash=APPROVED_HASH),
        S_EXECUTING, {"approval_result": "timeout"},
    ),
    "F3_plan_hash_mismatch": (
        state(S_PENDING_APPROVAL, intended_action=FAKE_ACTION, action_plan_hash="0" * 64),
        S_EXECUTING, {"approval_result": "approved"},
    ),
    "F5_screening_bypass": (state(S_SCREENING), S_DIAGNOSING, {}),
    "F6_reexecute_denied": (
        state(S_ESCALATED, exit_code="E5", intended_action=FAKE_ACTION,
              action_plan_hash=APPROVED_HASH),
        S_EXECUTING, {},
    ),
}  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.parametrize("rule_id", sorted(FORBIDDEN_CASES))
async def test_forbidden_transitions_blocked_without_audit(rule_id: str) -> None:
    st, to, fields = FORBIDDEN_CASES[rule_id]
    audit = MemoryAudit()
    with run(audit), pytest.raises(IllegalTransition) as err:
        await goto(st, to, next_node="n", step="Bx", event="e", **fields)
    assert audit.rows == []
    if rule_id != "F6_reexecute_denied":  # F6: cặp này cũng không có trong bảng
        assert err.value.rule_id == rule_id


@pytest.mark.asyncio
async def test_forbidden_wins_over_table() -> None:
    """S_PENDING_APPROVAL → S_EXECUTING có trong bảng 2.1 nhưng bị cấm 2 khi chưa được duyệt."""
    st = state(S_PENDING_APPROVAL, intended_action=FAKE_ACTION, action_plan_hash=APPROVED_HASH)
    with run(MemoryAudit()):
        with pytest.raises(IllegalTransition) as err:
            await goto(st, S_EXECUTING, next_node="b17_execute", step="B16", event="x")
        assert err.value.rule_id == "F2_no_approval"
        ok = await goto(
            st, S_EXECUTING, next_node="b17_execute", step="B16", event="approved",
            approval_result="approved",
        )  # fmt: skip
    assert ok["status"] == S_EXECUTING


@pytest.mark.asyncio
async def test_forbidden_4_requires_audit_row_in_same_transaction() -> None:
    audit = MemoryAudit()
    audit.drop = True  # INSERT không để lại dòng → không có bằng chứng ghi log
    with run(audit), pytest.raises(IllegalTransition) as err:
        await goto(state("S_CONFIRMING"), S_RESOLVED, next_node="b20_audit", step="B19",
                   event="user_confirmed")  # fmt: skip
    assert err.value.rule_id == "F4_resolved_without_log"


@pytest.mark.asyncio
async def test_forbidden_4_passes_when_row_already_exists_on_rerun() -> None:
    audit = MemoryAudit()
    with run(audit):
        for _ in range(2):  # node chạy lại khi resume/recover: dòng cũ vẫn là bằng chứng
            out = await goto(state("S_CONFIRMING"), S_RESOLVED, next_node="b20_audit",
                             step="B19", event="user_confirmed")  # fmt: skip
            assert out["status"] == S_RESOLVED
    assert len(audit.rows) == 1


@pytest.mark.asyncio
async def test_idempotency_key_keeps_distinct_events_of_same_step() -> None:
    """B11/user_replied + B11/action_built cùng lượt → 2 dòng (D-14 v1.2)."""
    audit = MemoryAudit()
    with run(audit):
        await goto(state(S_CLARIFYING), S_CLARIFYING, next_node="b11_slots", step="B11",
                   event="user_replied")  # fmt: skip
        await goto(state(S_CLARIFYING), S_ASSESSING, next_node="b12_assess", step="B11",
                   event="action_built")  # fmt: skip
    assert [r["event"] for r in audit.rows] == ["user_replied", "action_built"]


@pytest.mark.asyncio
async def test_idempotency_key_dedups_rerun_and_separates_loop_and_turn() -> None:
    audit = MemoryAudit()
    st = state(S_RETRIEVING)
    for turn, loops in [("T1", 0), ("T1", 0), ("T1", 1), ("T2", 0)]:
        with run(audit, turn_id=turn):
            await goto({**st, "reasoning_loops": loops}, S_RETRIEVING, next_node="b10_route",
                       step="B8", event="retrieved")  # fmt: skip
    assert len(audit.rows) == 3
    assert audit.rows[0]["idempotency_key"] == audit_key("t1", "B8", "retrieved", "T1", 0)
    assert {r["loop_seq"] for r in audit.rows} == {0, 1}


@pytest.mark.asyncio
async def test_rediagnose_transition_needs_flag() -> None:
    for flag in (False, True):
        with run(MemoryAudit(), rediag=flag):
            call = goto(state(S_CLARIFYING), S_DIAGNOSING, next_node="b06_diagnose",
                        step="B11", event="new_slot_rediagnose")  # fmt: skip
            if flag:
                assert (await call)["status"] == S_DIAGNOSING
            else:
                with pytest.raises(IllegalTransition):
                    await call


@pytest.mark.asyncio
async def test_audit_columns_from_fields() -> None:
    audit = MemoryAudit()
    with run(audit):
        await goto(state(S_ASSESSING), S_ESCALATED, next_node="b20_audit", step="B13/B14",
                   event="risk_decided", risk=fake_risk("ESCALATE_L2"), exit_code="E5",
                   escalation_note="ghi chú", audit_detail={"extra": 1})  # fmt: skip
    row = audit.rows[0]
    assert row["policy_decision"] == "deny" and row["decided_by"] == "rule"
    assert row["exit_code"] == "E5"
    assert row["detail"] == {"escalation_note": "ghi chú", "extra": 1}


@pytest.mark.asyncio
async def test_goto_outside_runner_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="RunContext"):
        await goto(state(S_RETRIEVING), S_RETRIEVING, next_node="x", step="B8", event="e")
