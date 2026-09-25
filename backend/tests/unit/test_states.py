"""Bảng chuyển trạng thái: mọi cặp 14×14 (ticket thường + ticket cha) và 6 chuyển cấm.

Tập "được phép" viết tay bằng chuỗi từ NGU-CANH IV 2.1 và P1 5.1.1 — không lấy lại từ code,
để test không so code với chính nó.
"""

from typing import Any

import pytest
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.states import (
    ALL_STATES,
    FORBIDDEN,
    TABLE_2_1,
    IllegalTransition,
    check_transition,
    forbidden_rule,
    is_allowed,
)

STATES = [
    "S_NEW", "S_SCREENING", "S_CLASSIFYING", "S_DIAGNOSING", "S_RETRIEVING", "S_CLARIFYING",
    "S_ASSESSING", "S_PENDING_APPROVAL", "S_EXECUTING", "S_CONFIRMING", "S_ESCALATED",
    "S_RESOLVED", "S_REJECTED", "S_BLOCKED",
]  # fmt: skip

# Bảng 2.1 — 27 cặp khác nhau.
EXPECTED_TABLE = {
    ("S_NEW", "S_SCREENING"), ("S_NEW", "S_BLOCKED"),
    ("S_SCREENING", "S_CLASSIFYING"), ("S_SCREENING", "S_BLOCKED"),
    ("S_CLASSIFYING", "S_DIAGNOSING"), ("S_CLASSIFYING", "S_CLASSIFYING"),
    ("S_CLASSIFYING", "S_ESCALATED"),
    ("S_DIAGNOSING", "S_RETRIEVING"), ("S_DIAGNOSING", "S_ESCALATED"),
    ("S_RETRIEVING", "S_CONFIRMING"), ("S_RETRIEVING", "S_ASSESSING"),
    ("S_RETRIEVING", "S_CLARIFYING"), ("S_RETRIEVING", "S_ESCALATED"),
    ("S_CLARIFYING", "S_ASSESSING"), ("S_CLARIFYING", "S_CLARIFYING"),
    ("S_CLARIFYING", "S_ESCALATED"),
    ("S_ASSESSING", "S_EXECUTING"), ("S_ASSESSING", "S_PENDING_APPROVAL"),
    ("S_ASSESSING", "S_ESCALATED"),
    ("S_PENDING_APPROVAL", "S_EXECUTING"), ("S_PENDING_APPROVAL", "S_REJECTED"),
    ("S_PENDING_APPROVAL", "S_ESCALATED"),
    ("S_EXECUTING", "S_CONFIRMING"), ("S_EXECUTING", "S_ESCALATED"),
    ("S_CONFIRMING", "S_RESOLVED"), ("S_CONFIRMING", "S_ESCALATED"),
    ("S_ESCALATED", "S_RESOLVED"),
}  # fmt: skip
# Quy tắc 1 — giữ nguyên trạng thái xử lý (phần chưa có trong bảng).
EXTRA_SELF = {(s, s) for s in [
    "S_NEW", "S_SCREENING", "S_DIAGNOSING", "S_RETRIEVING", "S_ASSESSING", "S_EXECUTING",
]}  # fmt: skip
# Quy tắc 2 — trạng thái chưa kết thúc → S_ESCALATED (phần chưa có trong bảng).
EXTRA_ESCALATE = {("S_NEW", "S_ESCALATED"), ("S_SCREENING", "S_ESCALATED")}
# Quy tắc 3 — chỉ ticket cha (phần chưa có ở trên).
EXTRA_PARENT = {
    ("S_CLASSIFYING", "S_CONFIRMING"), ("S_CONFIRMING", "S_CLASSIFYING"),
    ("S_CLASSIFYING", "S_RESOLVED"), ("S_CLASSIFYING", "S_REJECTED"),
    ("S_CONFIRMING", "S_REJECTED"),
}  # fmt: skip
# Chuyển cấm số 5 (bản nới D-29) chặn cặp duy nhất mà các quy tắc trên cho qua.
FORBIDDEN_STRUCTURAL = {("S_SCREENING", "S_SCREENING")}


def expected_allowed(is_parent: bool) -> set[tuple[str, str]]:
    base = EXPECTED_TABLE | EXTRA_SELF | EXTRA_ESCALATE
    return base | EXTRA_PARENT if is_parent else base


def make_action(**over: Any) -> Action:
    data: dict[str, Any] = {
        "type": "vpn_enable",
        "target": "device:LAP-0342",
        "requested_for": "nv001",
        "scope": "single_device",
        "privilege_level": "standard_user",
        "reversible": True,
        "reversibility": "full",
        "data_sensitivity": "low",
        "params": {"duration_days": 30},
        "facts": {"device_registered": True},
    }
    return Action(**{**data, **over})


def clean_state(is_parent: bool = False) -> dict[str, Any]:
    """State không kích hoạt chuyển cấm nào có điều kiện (F1–F3, F6)."""
    action = make_action()
    return {
        "ticket_id": "t-1",
        "is_parent": is_parent,
        "risk": {"policy_decision": "allow"},
        "approval_result": "approved",
        "intended_action": action,
        "action_plan_hash": hash_action(action),
        "exit_code": None,
    }


def transition_ok(state: dict[str, Any], frm: str, to: str, **kw: Any) -> bool:
    try:
        check_transition(state, frm, to, step="Bx", event="test", **kw)
    except IllegalTransition:
        return False
    return True


# ---- Bảng và 3 quy tắc -----------------------------------------------------------------------


def test_constants_match_spec() -> None:
    assert ALL_STATES == set(STATES)
    assert len(ALL_STATES) == 14
    assert TABLE_2_1 == EXPECTED_TABLE
    assert len(TABLE_2_1) == 27
    assert len(FORBIDDEN) == 6


def test_expected_counts() -> None:
    # 27 bảng + 6 quy tắc 1 + 2 quy tắc 2 = 35; ticket cha thêm 5 = 40.
    assert len(expected_allowed(False)) == 35
    assert len(expected_allowed(True)) == 40


@pytest.mark.parametrize("is_parent", [False, True], ids=["thuong", "cha"])
@pytest.mark.parametrize("frm", STATES)
@pytest.mark.parametrize("to", STATES)
def test_is_allowed_every_pair(frm: str, to: str, is_parent: bool) -> None:
    state = {"is_parent": is_parent}
    assert is_allowed(state, frm, to) == ((frm, to) in expected_allowed(is_parent))


@pytest.mark.parametrize("is_parent", [False, True], ids=["thuong", "cha"])
@pytest.mark.parametrize("frm", STATES)
@pytest.mark.parametrize("to", STATES)
def test_check_transition_every_pair(frm: str, to: str, is_parent: bool) -> None:
    expected = (frm, to) in expected_allowed(is_parent) - FORBIDDEN_STRUCTURAL
    assert transition_ok(clean_state(is_parent), frm, to) == expected


def test_unknown_state_rejected() -> None:
    assert not is_allowed({}, "S_BOGUS", "S_ESCALATED")
    assert not transition_ok(clean_state(), "S_NEW", "S_BOGUS")


def test_rediagnose_flag_d20() -> None:
    state = clean_state()
    assert not transition_ok(state, "S_CLARIFYING", "S_DIAGNOSING")
    assert transition_ok(state, "S_CLARIFYING", "S_DIAGNOSING", rediagnose_on_new_slot=True)


def test_parent_only_needs_is_parent() -> None:
    assert not transition_ok(clean_state(is_parent=False), "S_CLASSIFYING", "S_CONFIRMING")
    assert transition_ok(clean_state(is_parent=True), "S_CLASSIFYING", "S_CONFIRMING")


def test_no_rule_opens_new_path_to_executing() -> None:
    # D-29: 3 quy tắc không mở đường mới tới S_EXECUTING.
    for is_parent in (False, True):
        into_exec = {f for f, t in expected_allowed(is_parent) if t == "S_EXECUTING"}
        assert into_exec == {"S_ASSESSING", "S_PENDING_APPROVAL", "S_EXECUTING"}


# ---- S_SCREENING (chuyển cấm số 5 đã nới) ---------------------------------------------------


def test_screening_to_escalated_allowed() -> None:
    assert transition_ok(clean_state(), "S_SCREENING", "S_ESCALATED")


@pytest.mark.parametrize("to", ["S_SCREENING", "S_DIAGNOSING"])
def test_screening_bypass_forbidden(to: str) -> None:
    with pytest.raises(IllegalTransition) as exc:
        check_transition(clean_state(), "S_SCREENING", to, step="B2", event="x")
    assert exc.value.rule_id == "F5_screening_bypass"


# ---- 6 chuyển cấm: ca bị chặn và ca suýt khớp ------------------------------------------------


def assert_forbidden(state: dict[str, Any], frm: str, to: str, rule_id: str, **kw: Any) -> None:
    kw.setdefault("step", "Bx")
    kw.setdefault("event", "test")
    with pytest.raises(IllegalTransition) as exc:
        check_transition(state, frm, to, **kw)
    assert exc.value.rule_id == rule_id


@pytest.mark.parametrize("decision", ["deny", "approval_required"])
def test_f1_rule_cannot_be_bypassed(decision: str) -> None:
    state = {**clean_state(), "risk": {"policy_decision": decision}}
    assert_forbidden(state, "S_ASSESSING", "S_EXECUTING", "F1_rule_bypass")


def test_f1_uses_fields_being_written() -> None:
    # goto() truyền risk mới qua fields — luật cấm phải xét giá trị sắp ghi.
    assert_forbidden(
        clean_state(), "S_ASSESSING", "S_EXECUTING", "F1_rule_bypass",
        fields={"risk": {"policy_decision": "deny"}},
    )  # fmt: skip


def test_f1_near_miss_allow_passes() -> None:
    assert transition_ok(clean_state(), "S_ASSESSING", "S_EXECUTING")
    # decided_by=llm, không khớp luật nào → policy_decision None → không bị F1 chặn.
    assert transition_ok({**clean_state(), "risk": {"policy_decision": None}}, "S_ASSESSING", "S_EXECUTING")


@pytest.mark.parametrize("result", ["timeout", "rejected", None])
def test_f2_no_execute_without_approval(result: str | None) -> None:
    state = {**clean_state(), "approval_result": result}
    assert_forbidden(state, "S_PENDING_APPROVAL", "S_EXECUTING", "F2_no_approval")


def test_f2_timeout_goes_to_escalated() -> None:
    state = {**clean_state(), "approval_result": "timeout"}
    assert transition_ok(state, "S_PENDING_APPROVAL", "S_ESCALATED")


def test_f3_plan_changed_after_approval() -> None:
    state = {**clean_state(), "intended_action": make_action(target="device:LAP-9999")}
    assert_forbidden(state, "S_PENDING_APPROVAL", "S_EXECUTING", "F3_plan_hash_mismatch")


def test_f3_fact_changed_after_approval() -> None:
    state = {**clean_state(), "intended_action": make_action(facts={"device_registered": False})}
    assert_forbidden(state, "S_PENDING_APPROVAL", "S_EXECUTING", "F3_plan_hash_mismatch")


def test_f3_missing_hash_forbidden() -> None:
    state = {**clean_state(), "action_plan_hash": None}
    assert_forbidden(state, "S_PENDING_APPROVAL", "S_EXECUTING", "F3_plan_hash_mismatch")


def test_f2_f3_near_miss_approved_same_plan_passes() -> None:
    assert transition_ok(clean_state(), "S_PENDING_APPROVAL", "S_EXECUTING")


@pytest.mark.parametrize("frm", ["S_CONFIRMING", "S_ESCALATED"])
@pytest.mark.parametrize(("step", "event"), [("", "confirmed"), ("B19", ""), ("", "")])
def test_f4_resolved_requires_log(frm: str, step: str, event: str) -> None:
    assert_forbidden(clean_state(), frm, "S_RESOLVED", "F4_resolved_without_log", step=step, event=event)


def test_f4_near_miss_logged_passes() -> None:
    assert transition_ok(clean_state(), "S_CONFIRMING", "S_RESOLVED")


def test_f6_escalated_deny_cannot_reexecute_same_plan() -> None:
    state = {**clean_state(), "exit_code": "E5"}
    rule = forbidden_rule(state, "S_ESCALATED", "S_EXECUTING", step="L2", event="retry")
    assert rule is not None and rule.id == "F6_reexecute_denied"
    assert_forbidden(state, "S_ESCALATED", "S_EXECUTING", "F6_reexecute_denied")


def test_f6_near_miss_still_blocked_by_table() -> None:
    # Không phải E5 → F6 không khớp, nhưng bảng chuyển vẫn không có ESCALATED → EXECUTING.
    state = {**clean_state(), "exit_code": "E7"}
    assert forbidden_rule(state, "S_ESCALATED", "S_EXECUTING", step="L2", event="retry") is None
    with pytest.raises(IllegalTransition) as exc:
        check_transition(state, "S_ESCALATED", "S_EXECUTING", step="L2", event="retry")
    assert exc.value.rule_id is None


def test_forbidden_wins_over_is_allowed() -> None:
    # Cả 6 luật cấm đều kiểm trước is_allowed: ca ASSESSING→EXECUTING có trong bảng vẫn bị chặn.
    state = {**clean_state(), "risk": {"policy_decision": "deny"}}
    assert is_allowed(state, "S_ASSESSING", "S_EXECUTING")
    assert not transition_ok(state, "S_ASSESSING", "S_EXECUTING")


def test_risk_decision_model_accepted() -> None:
    from app.domain.ticket_state import RiskDecision

    risk = RiskDecision(
        decided_by="rule", policy_decision="deny", matched_rule_id="R07", raw_prob=None,
        calibrated_prob=None, p_method=None, risk_level="high", route="ESCALATE_L2",
        reason="Cấp quyền vào dữ liệu nhạy cảm", thresholds=None,
    )  # fmt: skip
    assert_forbidden({**clean_state(), "risk": risk}, "S_ASSESSING", "S_EXECUTING", "F1_rule_bypass")


def test_illegal_transition_is_domain_error() -> None:
    from app.core.errors import DomainError

    assert issubclass(IllegalTransition, DomainError)
    assert "S_NEW" in str(IllegalTransition("S_NEW", "S_EXECUTING"))

