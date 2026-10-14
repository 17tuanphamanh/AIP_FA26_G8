"""T24 bảng 7.5 — test-first: `executor/plans.py` (phase5 7.1 P2, P7; bảng 7.2) — ca p1–p5.

- p1: `check_plans` với 4 intent bật + PLAN thật → không ném; PLAN đúng bảng 7.2.
- p2: PLAN thiếu `grant_permission` / `undo` lệch `undo_tool` / metadata `reversibility: none` mà có bước `undo` / hành động `reversible`
  không bước nào hoàn tác được / PLAN rỗng cho hành động ghi / PLAN không rỗng cho hành động chỉ đọc → `RuntimeError`.
- p3: `plan_for` install: `license_paid=False` → (install); `True` / THIẾU → (assign, install) — thiếu fact coi như có phí.
- p4: `step_args` 6 hành động — `user_id` luôn `requested_for`; extend không gửi mức quyền.
- p5: `undo_args` 4 tool hoàn tác (restore lấy `previous_expires_at` của kết quả bước).
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from app.domain.action import ActionMeta
from app.executor.plans import (
    PLAN,
    READ_ONLY_ACTIONS,
    Step,
    check_plans,
    plan_for,
    step_args,
    undo_args,
)
from app.settings import get_action_metadata
from app.tools.models import (
    ExtendPermissionResult,
    InstallResult,
    LockIn,
    PermissionEntry,
    ResetPasswordResult,
    RestoreExpiryIn,
)
from app.tools.specs import REGISTRY
from tests.unit._t24 import action

FOUR = ["vpn", "account", "software", "access"]
NEW_ACTIONS = ("reset_password", "unlock_account", "install_software", "view_permissions", "grant_permission",
               "extend_permission")  # fmt: skip


def _plans(**over: tuple[Step, ...]) -> dict[str, tuple[Step, ...]]:
    return {**{k: tuple(v) for k, v in PLAN.items()}, **over}


def _without(missing: str) -> dict[str, tuple[Step, ...]]:
    return {k: tuple(v) for k, v in PLAN.items() if k != missing}


def _meta(**over: tuple[str, ActionMeta]) -> dict[str, dict[str, ActionMeta]]:
    """Bản sao metadata thật; `over[action_type] = (intent, meta)` thay một dòng."""
    meta = {intent: dict(actions) for intent, actions in get_action_metadata().root.items()}
    for action_type, (intent, m) in over.items():
        meta[intent][action_type] = m
    return meta


def _none_meta(intent: str, action_type: str) -> ActionMeta:
    base = get_action_metadata().root[intent][action_type]
    return base.model_copy(update={"reversible": False, "reversibility": "none"})


# ---- p1 ---------------------------------------------------------------------------------------------------------------------


def test_p1_check_plans_four_intents_real_plan_passes() -> None:
    """p1: PLAN thật + `action_metadata.yaml` thật + 4 intent bật → không ném (kể cả `plans=PLAN` tường minh và `["vpn"]`)."""
    check_plans(get_action_metadata().root, FOUR)
    check_plans(get_action_metadata().root, FOUR, plans=PLAN)
    check_plans(get_action_metadata().root, ["vpn"])


def test_p1_plan_is_table_7_2() -> None:
    """p1 / bảng 7.2: PLAN 6 hành động mới + 3 VPN như cũ."""
    assert tuple(PLAN["reset_password"]) == (Step("reset_password", undo="lock_account"),)
    assert tuple(PLAN["unlock_account"]) == (Step("unlock_account", undo="lock_account"),)
    assert tuple(PLAN["install_software"]) == (
        Step("assign_paid_license", undo=None, when="paid_license"), Step("install_software", undo="uninstall_software"),
    )  # fmt: skip
    assert tuple(PLAN["view_permissions"]) == ()
    assert tuple(PLAN["grant_permission"]) == (Step("grant_permission", undo="revoke_permission"),)
    assert tuple(PLAN["extend_permission"]) == (Step("extend_permission", undo="restore_permission_expiry"),)
    assert tuple(PLAN["renew_vpn_cert"]) == (Step("renew_vpn_cert", undo="revoke_vpn_cert"),)
    assert tuple(PLAN["reissue_vpn_access"]) == (Step("reissue_vpn_access", undo="revoke_vpn_cert"),)
    assert tuple(PLAN["check_vpn_status"]) == ()


def test_p1_read_only_actions() -> None:
    """P2: hành động không ghi (PLAN rỗng) chỉ được là `check_vpn_status`, `view_permissions`."""
    assert frozenset({"check_vpn_status", "view_permissions"}) == READ_ONLY_ACTIONS


def test_p1_every_metadata_action_has_plan() -> None:
    declared = {t for metas in get_action_metadata().root.values() for t in metas}
    assert set(NEW_ACTIONS) <= declared <= set(PLAN)


# ---- p2 ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("missing", NEW_ACTIONS)
def test_p2_plan_missing_action_refuses(missing: str) -> None:
    """p2: PLAN thiếu một hành động của intent bật (vd `grant_permission`) → RuntimeError nêu tên."""
    with pytest.raises(RuntimeError, match=missing):
        check_plans(get_action_metadata().root, FOUR, plans=_without(missing))


@pytest.mark.parametrize(
    ("over", "match"),
    [
        pytest.param({"grant_permission": (Step("grant_permission", undo="lock_account"),)}, "grant_permission",
                     id="grant-undo-lech"),
        pytest.param({"extend_permission": (Step("extend_permission", undo="revoke_permission"),)}, "extend_permission",
                     id="extend-undo-lech"),
        pytest.param({"reset_password": (Step("reset_password", undo=None),)}, "reset_password", id="reset-undo-thieu"),
        pytest.param({"install_software": (Step("assign_paid_license", undo="uninstall_software", when="paid_license"),
                                           Step("install_software", undo="uninstall_software"))},
                     "install_software|assign_paid_license", id="assign-co-undo-trai-spec"),
        pytest.param({"grant_permission": (Step("check_current_permissions"),)}, "grant_permission|check_current_permissions",
                     id="tool-doc"),
    ],
)  # fmt: skip
def test_p2_step_undo_must_equal_spec_undo_tool(over: dict[str, tuple[Step, ...]], match: str) -> None:
    """p2: bước `undo` khác `undo_tool` của ToolSpec / bước là tool đọc → RuntimeError nêu hành động / tool lệch (không phải lỗi
    khác của PLAN)."""
    with pytest.raises(RuntimeError, match=match):
        check_plans(get_action_metadata().root, FOUR, plans=_plans(**over))


@pytest.mark.parametrize(
    ("intent", "action_type"),
    [("access", "grant_permission"), ("software", "install_software"), ("account", "reset_password")],
)
def test_p2_reversibility_none_with_undo_step_refuses(intent: str, action_type: str) -> None:
    """p2 (M-T24-8): metadata `reversibility: none` (reversible False) mà PLAN có bước `undo` → RuntimeError."""
    meta = _meta(**{action_type: (intent, _none_meta(intent, action_type))})
    assert any(s.undo is not None for s in PLAN[action_type])
    with pytest.raises(RuntimeError, match=action_type):
        check_plans(meta, FOUR, plans=PLAN)


def test_p2_reversibility_none_without_undo_ok() -> None:
    """Đối chứng p2: `reversibility: none` + PLAN chỉ gồm bước không hoàn tác được → không ném."""
    meta = _meta(install_software=("software", _none_meta("software", "install_software")))
    plans = _plans(install_software=(Step("assign_paid_license", undo=None, when="paid_license"),))
    check_plans(meta, FOUR, plans=plans)


def test_p2_reversible_without_any_undo_step_refuses() -> None:
    """p2: hành động `reversible` có PLAN không rỗng mà KHÔNG bước nào hoàn tác được → RuntimeError."""
    assert get_action_metadata().root["software"]["install_software"].reversible
    plans = _plans(install_software=(Step("assign_paid_license"),))
    with pytest.raises(RuntimeError, match="install_software"):
        check_plans(get_action_metadata().root, FOUR, plans=plans)


def test_p2_reversible_with_one_undo_step_among_many_ok() -> None:
    """Đối chứng p2 (luật NỚI ở 7.0): `reversible` chỉ cần ÍT NHẤT MỘT bước hoàn tác được — bước license `undo=None` đứng cạnh
    bước có `undo` không làm từ chối khởi động (PLAN thật của install)."""
    assert REGISTRY["assign_paid_license"].reversible == "none"
    check_plans(get_action_metadata().root, ["software"], plans=PLAN)


@pytest.mark.parametrize("write_action", ["grant_permission", "reset_password", "install_software", "renew_vpn_cert"])
def test_p2_empty_plan_for_write_action_refuses(write_action: str) -> None:
    """p2: PLAN rỗng cho hành động ghi (ngoài `check_vpn_status`/`view_permissions`) → RuntimeError."""
    with pytest.raises(RuntimeError, match=write_action):
        check_plans(get_action_metadata().root, FOUR, plans=_plans(**{write_action: ()}))


def test_p2_non_empty_plan_for_read_only_action_refuses() -> None:
    """p2: hành động chỉ đọc (`view_permissions`) có bước ghi → RuntimeError (bước đó tự nó hợp lệ: undo khớp spec)."""
    plans = _plans(view_permissions=(Step("grant_permission", undo="revoke_permission"),))
    with pytest.raises(RuntimeError, match="view_permissions"):
        check_plans(get_action_metadata().root, FOUR, plans=plans)


# ---- p3 ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("facts", "tools"),
    [
        pytest.param({"license_paid": False}, ("install_software",), id="mien-phi"),
        pytest.param({"license_paid": True}, ("assign_paid_license", "install_software"), id="co-phi"),
        pytest.param({}, ("assign_paid_license", "install_software"), id="thieu-fact-coi-nhu-co-phi"),
        pytest.param({"in_catalog": True}, ("assign_paid_license", "install_software"), id="thieu-fact-co-fact-khac"),
    ],
)
def test_p3_plan_for_install_license_step(facts: dict[str, Any], tools: tuple[str, ...]) -> None:
    """p3 (M-T24-2, M-T24-3): bước license `when="paid_license"` giữ khi `facts.get("license_paid") is not False`."""
    steps = plan_for(action("install_software", facts=facts))
    assert tuple(s.tool for s in steps) == tools


def test_p3_plan_for_injected_plans_and_unknown_type() -> None:
    """`plan_for(action, plans)` đọc PLAN tiêm; hành động lạ → KeyError (bug → E9)."""
    custom = {"grant_permission": (Step("grant_permission", undo="revoke_permission"),
                                   Step("extend_permission", undo="restore_permission_expiry"))}  # fmt: skip
    assert tuple(s.tool for s in plan_for(action("grant_permission"), custom)) == ("grant_permission", "extend_permission")
    assert plan_for(action("view_permissions")) == ()
    with pytest.raises(KeyError):
        plan_for(action("grant_permission").model_copy(update={"type": "format_disk"}))


def test_p3_plan_for_non_install_unchanged() -> None:
    assert tuple(s.tool for s in plan_for(action("reset_password"))) == ("reset_password",)
    assert tuple(s.tool for s in plan_for(action("extend_permission"))) == ("extend_permission",)


# ---- p4 ---------------------------------------------------------------------------------------------------------------------


def test_p4_reset_unlock_user_is_requested_for_not_sender() -> None:
    """p4 (M-T24-4): account `target_user=nv005`, người gửi nv001 → Action `requested_for="nv005"` → `user_id="nv005"`."""
    a = action("reset_password", rf="nv005", params={"account_type": "ad"})
    assert step_args("reset_password", a) == {"user_id": "nv005", "account_type": "ad"}
    b = action("unlock_account", rf="nv005", params={"account_type": "email"})
    assert step_args("unlock_account", b) == {"user_id": "nv005", "account_type": "email"}


def test_p4_install_steps() -> None:
    a = action("install_software", rf="nv001", params={"device_id": "LAP-0342", "software_name": "adobe-acrobat-pro"},
               facts={"license_paid": True})  # fmt: skip
    assert step_args("assign_paid_license", a) == {"user_id": "nv001", "software_name": "adobe-acrobat-pro"}
    assert step_args("install_software", a) == {"device_id": "LAP-0342", "software_name": "adobe-acrobat-pro"}


def test_p4_assign_license_user_is_requested_for() -> None:
    a = action("install_software", rf="nv007", params={"device_id": "LAP-0342", "software_name": "adobe-acrobat-pro"})
    assert step_args("assign_paid_license", a)["user_id"] == "nv007"


def test_p4_grant_args() -> None:
    a = action("grant_permission", rf="nv005", params={"resource_path": "finance/public-reports", "permission_level": "write",
                                                       "duration_days": 45})  # fmt: skip
    assert step_args("grant_permission", a) == {"user_id": "nv005", "resource_path": "finance/public-reports",
                                                "level": "write", "duration_days": 45}  # fmt: skip


def test_p4_extend_args_no_permission_level() -> None:
    """p4 (M-T24-5): extend KHÔNG có khoá mức quyền (`level`/`permission_level`) — kể cả khi `params` lỡ mang `permission_level`."""
    a = action("extend_permission", rf="nv005", params={"resource_path": "finance/Q3", "duration_days": 30})
    args = step_args("extend_permission", a)
    assert args == {"user_id": "nv005", "resource_path": "finance/Q3", "duration_days": 30}
    leaky = action("extend_permission", rf="nv005",
                   params={"resource_path": "finance/Q3", "duration_days": 30, "permission_level": "full"})  # fmt: skip
    leaked = step_args("extend_permission", leaky)
    assert "level" not in leaked and "permission_level" not in leaked


def test_p4_vpn_unchanged() -> None:
    a = action("renew_vpn_cert")
    assert step_args("renew_vpn_cert", a) == {"user_id": "nv001", "device_id": "LAP-0342"}


# ---- p5 ---------------------------------------------------------------------------------------------------------------------

AT = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)


def test_p5_lock_account_undo_args() -> None:
    a = action("reset_password", rf="nv005", params={"account_type": "email"})
    result = ResetPasswordResult(user_id="nv005", account_type="email", delivered_via="email", must_change_at_next_login=True)
    args = undo_args("lock_account", a, result)
    assert args == {"user_id": "nv005", "account_type": "email", "reason": "admin"}
    LockIn.model_validate(args)


def test_p5_uninstall_undo_args() -> None:
    a = action("install_software", params={"device_id": "LAP-0342", "software_name": "zoom"})
    result = InstallResult(device_id="LAP-0342", name="zoom", version="6.1.0", installed_at=AT)
    assert undo_args("uninstall_software", a, result) == {"device_id": "LAP-0342", "software_name": "zoom"}


def test_p5_revoke_permission_undo_args() -> None:
    a = action("grant_permission", rf="nv005")
    result = PermissionEntry(path="finance/public-reports", level="read", granted_at=AT, expires_at=None, status="active")
    assert undo_args("revoke_permission", a, result) == {"user_id": "nv005", "resource_path": "finance/public-reports"}


@pytest.mark.parametrize("previous", [datetime(2026, 10, 4, 3, 0, tzinfo=UTC), None], ids=["co-han-cu", "vinh-vien-cu"])
def test_p5_restore_expiry_uses_previous_expires_at(previous: datetime | None) -> None:
    """p5: `restore_permission_expiry(user_id, resource_path, expires_at=result.previous_expires_at)` — None (vĩnh viễn cũ) giữ None."""
    a = action("extend_permission", rf="nv005")
    result = ExtendPermissionResult(path="finance/Q3", level="read", granted_at=AT, expires_at=AT, status="active",
                                    previous_expires_at=previous)  # fmt: skip
    args = undo_args("restore_permission_expiry", a, result)
    assert set(args) == {"user_id", "resource_path", "expires_at"}
    assert RestoreExpiryIn.model_validate(args) == RestoreExpiryIn(user_id="nv005", resource_path="finance/Q3",
                                                                   expires_at=previous)  # fmt: skip
