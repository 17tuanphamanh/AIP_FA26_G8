"""T22a P5 (G5-1) — `build_ctx` tính `target_is_other` theo LOẠI ĐÍCH (phase5-thiet-ke-chi-tiet.md mục 4.1 P5, bảng 4.7 g1–g5).

Viết TỪ ĐẶC TẢ, trước code. P5: `device_target = action.target.startswith("device:")`;
`target_is_other = (cờ B6 is not False) ∨ (requested_for ≠ requester.user_id) ∨ (device_target ∧ facts.device_owner_is_requester
is not True)`. Đích không phải máy (`user:`, `folder:`) không xét fact chủ máy; VPN (mọi đích `device:`) không đổi so với 3h.

State dựng tay như checkpoint (dict qua `model_dump()`); cờ B6 mặc định `False` (P5: chỉ `False` tường minh mới không bật).
Thuộc tính tĩnh của hành động mới theo bảng 4.2; VPN theo `action_metadata.yaml` (đã có từ Phase 3).
"""

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app.domain.action import (
    Action,
    FactValue,
    PrivilegeLevel,
    Reversibility,
    Scope,
    Sensitivity,
)
from app.domain.context import RequesterContext
from app.risk.context import build_ctx
from app.settings import get_action_metadata, get_policy

VN = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=VN)  # thứ Ba 29/09/2026 10:00 giờ VN

NV001 = RequesterContext(
    user_id="nv001", role="employee", department="Finance", manager_id="fin_head", employment_status="active",
    tenure_days=980, is_privileged_account=False, captured_at=NOW,
)  # fmt: skip

# Bảng 4.2 (reversible, reversibility, data_sensitivity, scope, privilege_level) — chỉ 2 hành động dùng ở đây.
META_4_2: dict[str, tuple[bool, Reversibility, Sensitivity, Scope, PrivilegeLevel]] = {
    "reset_password": (True, "partial", "medium", "single_account", "standard_user"),
    "view_permissions": (True, "full", "low", "single_account", "standard_user"),
}
F_RESET: dict[str, FactValue] = {
    "target_account_privilege": "standard_user", "target_is_service_account": False, "target_user_status": "active",
}  # fmt: skip


def _action_moi(action_type: str, target: str, requested_for: str, facts: dict[str, FactValue]) -> Action:
    reversible, reversibility, data_sensitivity, scope, privilege_level = META_4_2[action_type]
    return Action(
        type=action_type, target=target, requested_for=requested_for, scope=scope, privilege_level=privilege_level,
        reversible=reversible, reversibility=reversibility, data_sensitivity=data_sensitivity, params={},
        facts=dict(facts),
    )  # fmt: skip


def _action_vpn(action_type: str, device_id: str, facts: dict[str, FactValue]) -> Action:
    m = get_action_metadata().of("vpn")[action_type]
    return Action(
        type=action_type, target=f"device:{device_id}", requested_for="nv001", scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": device_id}, facts=dict(facts),
    )  # fmt: skip


@dataclass(frozen=True)
class CaCtx:
    action: Action
    mong_doi: bool
    ctx_flags: dict[str, bool] = field(default_factory=lambda: {"target_is_other": False})


# fmt: off
BANG_G = [
    pytest.param(CaCtx(_action_moi("reset_password", "user:nv001", "nv001", F_RESET), False),
                 id="g1-account-tu-lam-khong-fact-may-False"),
    pytest.param(CaCtx(_action_moi("reset_password", "user:nv005", "nv005", F_RESET), True),
                 id="g2-account-requested_for-nv005-True"),
    pytest.param(CaCtx(_action_moi("reset_password", "user:nv001", "nv001", F_RESET), True,
                       ctx_flags={"target_is_other": True}),
                 id="g3-co-B6-target_is_other-True"),
    pytest.param(CaCtx(_action_vpn("renew_vpn_cert", "LAP-0342", {}), True),
                 id="g4-vpn-device-thieu-fact-chu-may-True"),
    pytest.param(CaCtx(_action_moi("view_permissions", "user:nv001", "nv001", {}), False),
                 id="g5-access-tu-xem-False"),
]
# fmt: on


@pytest.mark.parametrize("ca", BANG_G)
def test_g_build_ctx_target_is_other_theo_dich(ca: CaCtx) -> None:
    """Bảng 4.7 g1–g5 (P5): vế chủ máy chỉ áp cho đích `device:`; `requested_for` khác người gửi hoặc cờ B6 bật → True;
    VPN thiếu fact chủ máy vẫn True như 3h (bắt M-T22a-8 ở g1/g5, M-T22a-9 ở g4)."""
    state = {
        "intended_action": ca.action.model_dump(),
        "requester_context": NV001.model_dump(),
        "ctx_flags": dict(ca.ctx_flags),
    }
    ctx = build_ctx(state, NOW, get_policy().business_hours)
    assert ctx.target_is_other is ca.mong_doi
    assert ctx.requester.user_id == "nv001"
    assert dict(ctx.facts) == dict(ca.action.facts)  # gốc M-3h-8 giữ nguyên: facts = action.facts


def test_g_bang_du_5_dong() -> None:
    """Bảng 4.7: đủ g1–g5, id không trùng."""
    ids = [str(p.id) for p in BANG_G]
    assert len(ids) == len(set(ids)) == 5
    for g in ("g1-", "g2-", "g3-", "g4-", "g5-"):
        assert any(i.startswith(g) for i in ids), g
