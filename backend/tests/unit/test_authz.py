"""Tầng 3 (P6 mục 5.3) — hàm thuần `can_*`, 3 xung đột lợi ích [Chốt B15], `scope_tool_target` (D-16)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from app.auth.authz import (
    ApprovalParties,
    approval_conflict,
    can_close_escalation,
    can_decide_approval,
    can_override,
    can_read_audit,
    can_read_ticket,
    scope_tool_target,
)
from app.auth.models import Principal
from app.auth.permissions import permissions_of
from app.domain.action import Action
from app.domain.context import RequesterContext

NOW = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)


def _p(user_id: str, role: str) -> Principal:
    return Principal(user_id, role, "s", 0, permissions_of(role))  # type: ignore[arg-type]


@dataclass(frozen=True)
class T:
    requester_id: str


@dataclass(frozen=True)
class A:
    approver_id: str
    status: str = "pending"
    deadline: datetime = NOW + timedelta(minutes=30)
    backup_approver_id: str | None = None  # 4c P4: `ApprovalLike` thêm 2 trường (cách dựng — kỳ vọng không đổi)
    reminder_2_at: datetime | None = None


@dataclass(frozen=True)
class E:
    is_deny_case: bool
    exit_code: str = "E1"


def _for(user_id: str) -> Action:
    """Hành động mà người hưởng lợi (`requested_for`) là `user_id` — thay `action_targets` cũ (Phase 4 4b TQ-4: `ApprovalParties`
    mang `approver_chain` + `action`, xung đột tính bằng `domain.approval.conflict_type`; kỳ vọng không đổi)."""
    return Action(
        type="renew_vpn_cert", target="device:LAP-0342", requested_for=user_id, scope="single_device",
        privilege_level="standard_user", reversible=True, reversibility="full", data_sensitivity="low", params={}, facts={},
    )  # fmt: skip


NO_CONFLICT = ApprovalParties(requester_id="nv001", approver_chain=("it_mgr01",), action=_for("nv001"))


def test_can_read_ticket() -> None:
    assert can_read_ticket(_p("nv001", "employee"), T("nv001"))
    assert not can_read_ticket(_p("nv001", "employee"), T("nv002"))
    for role in ("l1", "manager", "l2"):
        assert can_read_ticket(_p("x", role), T("nv002"))


def test_can_decide_approval_happy_path() -> None:
    assert can_decide_approval(_p("l1_01", "l1"), A("l1_01"), NO_CONFLICT, now=NOW)


@pytest.mark.parametrize(
    ("principal", "approval", "now"),
    [
        (_p("l1_02", "l1"), A("l1_01"), NOW),  # không phải người được giao
        (_p("l2_01", "l2"), A("l2_01"), NOW),  # L2 không có approval:decide
        (_p("l1_01", "l1"), A("l1_01", status="approved"), NOW),  # đã quyết
        (_p("l1_01", "l1"), A("l1_01"), NOW + timedelta(minutes=30)),  # hết hạn (now == deadline)
    ],
)
def test_can_decide_approval_denied(principal: Principal, approval: A, now: datetime) -> None:
    assert not can_decide_approval(principal, approval, NO_CONFLICT, now=now)


def test_three_conflicts_of_interest() -> None:
    assert approval_conflict("l1_01", ApprovalParties("l1_01", (), None)) == "self"
    assert approval_conflict("l1_01", ApprovalParties("boss", ("boss",), None)) == "boss_of_approver"
    assert approval_conflict("l1_01", ApprovalParties("nv001", (), _for("l1_01"))) == "targets_approver"
    assert approval_conflict("l1_01", NO_CONFLICT) is None
    for parties in (
        ApprovalParties("l1_01", (), None),
        ApprovalParties("boss", ("boss",), None),
        ApprovalParties("nv001", (), _for("l1_01")),
    ):
        assert not can_decide_approval(_p("l1_01", "l1"), A("l1_01"), parties, now=NOW)


def test_can_override_not_own_request() -> None:
    assert can_override(_p("l1_01", "l1"), T("nv001"))
    assert not can_override(_p("l1_01", "l1"), T("l1_01"))
    assert not can_override(_p("l2_01", "l2"), T("nv001"))
    assert not can_override(_p("nv001", "employee"), T("nv002"))


def test_can_close_escalation() -> None:
    assert can_close_escalation(_p("l2_01", "l2"), E(False), "completed") == "allow"
    assert can_close_escalation(_p("l2_01", "l2"), E(True), "completed") == "unprocessable"
    assert can_close_escalation(_p("l2_01", "l2"), E(True), "confirmed_denial") == "allow"
    assert can_close_escalation(_p("it_mgr01", "manager"), E(False), "completed") == "forbidden"
    # P4 tuần 8: L1 cũng đóng được (escalation:handle — P6 §5.3); `completed` cho E5/E6 → 422 kể cả khi `is_deny_case` sai (B20:303)
    assert can_close_escalation(_p("l1_01", "l1"), E(False), "completed") == "allow"
    assert can_close_escalation(_p("nv001", "employee"), E(False), "confirmed_denial") == "forbidden"
    for code in ("E5", "E6"):
        assert can_close_escalation(_p("l2_01", "l2"), E(False, code), "completed") == "unprocessable"
        assert can_close_escalation(_p("l2_01", "l2"), E(False, code), "confirmed_denial") == "allow"
        assert can_close_escalation(_p("l2_01", "l2"), E(False, code), "reopened_as_new") == "allow"


def test_can_read_audit() -> None:
    assert can_read_audit(_p("it_mgr01", "manager"), approver_id=None)
    assert can_read_audit(_p("l1_01", "l1"), approver_id="l1_01")
    assert not can_read_audit(_p("l1_01", "l1"), approver_id="l1_02")
    assert not can_read_audit(_p("l1_01", "l1"), approver_id=None)
    assert not can_read_audit(_p("l2_01", "l2"), approver_id="l2_01")


def test_scope_tool_target() -> None:
    ctx = RequesterContext.model_validate(
        {"user_id": "nv001", "role": "employee", "department": "finance", "manager_id": None,
         "employment_status": "active", "tenure_days": 10, "is_privileged_account": False,
         "captured_at": NOW}
    )  # fmt: skip
    assert scope_tool_target(ctx, None).target_is_other is False
    assert scope_tool_target(ctx, "nv001").user_id == "nv001"
    other = scope_tool_target(ctx, "nv002")
    assert (other.user_id, other.target_is_other) == ("nv002", True)
