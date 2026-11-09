"""T22a — đủ 20 luật M5 (phase5-thiet-ke-chi-tiet.md mục 4.4 bảng luật, 4.7 bảng ca a*–f*, h1–h8; P1–P10 mục 4.1).

Viết TỪ ĐẶC TẢ, trước code (bước S2 PLAN-T22a). Kỳ vọng chép từ bảng 4.4/4.7, không suy từ code.

- Ca a*–f*: khuôn `LUAT_C5` của `test_policy_rules_vpn.py`, nhưng ctx đi QUA `build_ctx` (P5 — f10/f11 và M-T22a-8 cần thế):
  state dựng tay → `build_ctx(state, NOW, business_hours)` → `evaluate_rules(get_policy().rules, action, ctx,
  intents=action_intents())`. Cờ B6 `ctx_flags.target_is_other = False` (P5 + 4.6 bước 5 "cờ B6 = False"; ca g3 mới bật True).
- Thuộc tính tĩnh của `Action` (scope, privilege_level, reversible, …) lấy từ bảng 4.2 — không đọc `action_metadata.yaml`.
- Ca "none" ↔ `matched False`, `decision None`, `rule_id None`, `all_matched []`. `all_matched` so cả THỨ TỰ (thứ tự luật trong file).
- Người gửi theo `mock_services/seed.json`: nv001 (Finance, active), nv007 (HR, active).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast
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
from app.domain.facts import FactKeyViolation, check_facts
from app.executor.plans import check_plans
from app.risk.context import build_ctx
from app.risk.models import RuleVerdict
from app.risk.policy_engine import evaluate_rules
from app.settings import (
    Settings,
    action_intents,
    check_intent_config,
    check_policy_config,
    get_action_metadata,
    get_policy,
    get_slots,
)

REPO = Path(__file__).resolve().parents[3]
VN = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=VN)  # thứ Ba 29/09/2026 10:00 giờ VN — trong giờ hành chính

AUTO, HITL, DENY = "allow", "approval_required", "deny"

# ---- Người gửi (seed.json) -------------------------------------------------------------------------------------------

NV001 = RequesterContext(
    user_id="nv001", role="employee", department="Finance", manager_id="fin_head", employment_status="active",
    tenure_days=980, is_privileged_account=False, captured_at=NOW,
)  # fmt: skip
NV007 = RequesterContext(
    user_id="nv007", role="employee", department="HR", manager_id="hr_head", employment_status="active",
    tenure_days=1500, is_privileged_account=False, captured_at=NOW,
)  # fmt: skip

# ---- Bảng 4.2: thuộc tính tĩnh của 6 hành động mới (reversible, reversibility, data_sensitivity, scope, privilege_level) ---

META_4_2: dict[str, tuple[bool, Reversibility, Sensitivity, Scope, PrivilegeLevel]] = {
    "reset_password": (True, "partial", "medium", "single_account", "standard_user"),
    "unlock_account": (True, "full", "low", "single_account", "standard_user"),
    "install_software": (True, "partial", "low", "single_device", "standard_user"),
    "view_permissions": (True, "full", "low", "single_account", "standard_user"),
    "grant_permission": (True, "full", "medium", "single_account", "standard_user"),
    "extend_permission": (True, "full", "medium", "single_account", "standard_user"),
}

# ---- Ca gốc (an toàn) mỗi hành động — bảng 4.7 -------------------------------------------------------------------------


@dataclass(frozen=True)
class Goc:
    requester: RequesterContext
    action_type: str
    target: str
    requested_for: str
    params: dict[str, Any]
    facts: dict[str, FactValue]


GOC: dict[str, Goc] = {
    "G-RESET": Goc(NV001, "reset_password", "user:nv001", "nv001", {}, {
        "target_account_privilege": "standard_user", "target_is_service_account": False, "target_user_status": "active",
    }),
    "G-UNLOCK": Goc(NV007, "unlock_account", "user:nv007", "nv007", {}, {
        "target_account_locked": True, "target_lock_reason": "bad_password",
        "target_account_privilege": "standard_user", "target_is_service_account": False, "target_user_status": "active",
    }),
    "G-VIEW": Goc(NV001, "view_permissions", "user:nv001", "nv001", {}, {}),
    "G-GRANT": Goc(NV001, "grant_permission", "folder:finance/public-reports", "nv001",
                   {"permission_level": "read", "duration_days": 30}, {
        "resource_sensitivity": "low", "same_department": True, "has_permission_record": False,
        "target_user_status": "active",
    }),
    # T20a (phase5 5.1.6 r4, P1): thêm fact `existing_permission_level="read"` — R10 mới đòi `in [read, write]`. Giữ
    # `params.permission_level` (TQ-15: ca luật dựng tay, luật không đọc khoá này cho extend).
    "G-EXTEND": Goc(NV001, "extend_permission", "folder:finance/public-reports", "nv001",
                    {"permission_level": "read", "duration_days": 30}, {
        "has_permission_record": True, "same_department": True, "resource_sensitivity": "low",
        "target_user_status": "active", "existing_permission_level": "read",
    }),
    "G-INSTALL": Goc(NV001, "install_software", "device:LAP-0342", "nv001", {}, {
        "in_catalog": True, "license_paid": False, "requires_local_admin": False,
        "device_owner_is_requester": True, "device_registered": True,
    }),
}  # fmt: skip


@dataclass(frozen=True)
class Ca:
    goc: str
    requester: RequesterContext
    action_type: str
    target: str
    requested_for: str
    params: dict[str, Any]
    facts: dict[str, FactValue]
    decision: str | None
    rule_id: str | None
    all_matched: tuple[str, ...]
    ctx_flags: dict[str, bool] = field(default_factory=lambda: {"target_is_other": False})


def _ca(
    goc: str, *, decision: str | None = None, rule_id: str | None = None, khop: str = "",
    facts: dict[str, FactValue] | None = None, bo: tuple[str, ...] = (), params: dict[str, Any] | None = None,
    bo_params: tuple[str, ...] = (), requested_for: str | None = None, target: str | None = None,
) -> Ca:  # fmt: skip
    """Đổi đúng một thứ so với ca gốc `goc` (bảng 4.7). `khop` = all_matched mong đợi, theo thứ tự trong file."""
    g = GOC[goc]
    f = {k: v for k, v in {**g.facts, **(facts or {})}.items() if k not in bo}
    p = {k: v for k, v in {**g.params, **(params or {})}.items() if k not in bo_params}
    return Ca(
        goc=goc, requester=g.requester, action_type=g.action_type, target=target or g.target,
        requested_for=requested_for or g.requested_for, params=p, facts=f, decision=decision, rule_id=rule_id,
        all_matched=tuple(khop.split()),
    )  # fmt: skip


# fmt: off
BANG_4_7 = [
    # ---- a* — account/reset_password: R01 (allow), R03/R04/R05 (approval_required) ----
    pytest.param(_ca("G-RESET", decision=AUTO, rule_id="R01", khop="R01"), id="a1-R01-khop"),
    pytest.param(_ca("G-RESET", bo=("target_account_privilege",)), id="a2-R01-thieu-target_account_privilege"),
    pytest.param(_ca("G-RESET", bo=("target_is_service_account",)), id="a3-R01-thieu-target_is_service_account"),
    pytest.param(_ca("G-RESET", bo=("target_user_status",)), id="a4-R01-thieu-target_user_status"),
    pytest.param(_ca("G-RESET", requested_for="nv005", target="user:nv005"), id="a6-R01-nguoi-khac-nv005-ho-L2"),
    pytest.param(_ca("G-RESET", facts={"target_account_privilege": "admin"}, decision=HITL, rule_id="R04", khop="R04"),
                 id="a7-R01+R04-privilege-admin-R04"),
    pytest.param(_ca("G-RESET", facts={"target_account_privilege": "elevated"}), id="a8-R01-privilege-elevated"),
    pytest.param(_ca("G-RESET", facts={"target_is_service_account": True}, decision=HITL, rule_id="R03", khop="R03"),
                 id="a9-R03-service-true"),
    pytest.param(_ca("G-RESET", facts={"target_user_status": "terminated"}, decision=HITL, rule_id="R05", khop="R05"),
                 id="a10-R05-status-terminated"),
    pytest.param(_ca("G-RESET", facts={"target_user_status": "disabled", "target_disable_reason": "security"}),
                 id="a11-status-disabled-security-R12-chi-access"),
    pytest.param(_ca("G-RESET", facts={"target_is_service_account": True, "target_account_privilege": "admin",
                                       "target_user_status": "terminated"},
                     decision=HITL, rule_id="R03", khop="R03 R04 R05"), id="a12-R03+R04+R05-R03-dung-truoc"),
    # ---- b* — account/unlock_account: R02 (allow) ----
    pytest.param(_ca("G-UNLOCK", decision=AUTO, rule_id="R02", khop="R02"), id="b1-R02-khop"),
    pytest.param(_ca("G-UNLOCK", facts={"target_lock_reason": "admin"}), id="b2-R02-lock_reason-admin-ho-L3"),
    pytest.param(_ca("G-UNLOCK", facts={"target_lock_reason": "inactivity"}),
                 id="b2-R02-lock_reason-inactivity-ho-L3"),
    pytest.param(_ca("G-UNLOCK", bo=("target_account_locked",)), id="b3-R02-thieu-target_account_locked"),
    pytest.param(_ca("G-UNLOCK", bo=("target_lock_reason",)), id="b4-R02-thieu-target_lock_reason"),
    pytest.param(_ca("G-UNLOCK", bo=("target_account_privilege",)), id="b5-R02-thieu-target_account_privilege"),
    pytest.param(_ca("G-UNLOCK", bo=("target_is_service_account",)), id="b6-R02-thieu-target_is_service_account"),
    pytest.param(_ca("G-UNLOCK", bo=("target_user_status",)), id="b7-R02-thieu-target_user_status"),
    pytest.param(_ca("G-UNLOCK", facts={"target_account_privilege": "admin"},
                     decision=HITL, rule_id="R04", khop="R04"), id="b9-R02+R04-privilege-admin-R04"),
    # ---- c* — access/view_permissions: R06 (allow) ----
    pytest.param(_ca("G-VIEW", decision=AUTO, rule_id="R06", khop="R06"), id="c1-R06-khop"),
    pytest.param(_ca("G-VIEW", requested_for="nv005", target="user:nv005"), id="c2-R06-nguoi-khac-nv005"),
    # ---- d* — access/grant_permission: R07, R08, R09 (approval_required), R12 (deny) ----
    pytest.param(_ca("G-GRANT"), id="d1-G-GRANT-ho-L1-khong-luat"),
    pytest.param(_ca("G-GRANT", facts={"resource_sensitivity": "high"}, decision=HITL, rule_id="R07", khop="R07"),
                 id="d2-R07-sensitivity-high"),
    pytest.param(_ca("G-GRANT", params={"permission_level": "full"}, decision=HITL, rule_id="R08", khop="R08"),
                 id="d3-R08-permission_level-full"),
    pytest.param(_ca("G-GRANT", facts={"same_department": False}, decision=HITL, rule_id="R09", khop="R09"),
                 id="d4-R09-same_department-false"),
    pytest.param(_ca("G-GRANT", facts={"resource_sensitivity": "high", "same_department": False},
                     params={"permission_level": "full"}, decision=HITL, rule_id="R07", khop="R07 R08 R09"),
                 id="d5-R07+R08+R09-R07"),
    pytest.param(_ca("G-GRANT", facts={"target_user_status": "disabled", "target_disable_reason": "security"},
                     decision=DENY, rule_id="R12", khop="R12"), id="d6-R12-disabled-security-deny"),
    pytest.param(_ca("G-GRANT", facts={"target_user_status": "disabled", "target_disable_reason": "security",
                                       "resource_sensitivity": "high"},
                     decision=DENY, rule_id="R12", khop="R07 R12"), id="d7-R12+R07-chat-nhat-thang-deny"),
    pytest.param(_ca("G-GRANT", facts={"target_user_status": "disabled", "target_disable_reason": "other"}),
                 id="d8-R12-disable_reason-other"),
    pytest.param(_ca("G-GRANT", facts={"target_user_status": "disabled"}), id="d9-R12-thieu-target_disable_reason"),
    pytest.param(_ca("G-GRANT", params={"permission_level": "FULL"}), id="d10-permission_level-FULL"),
    pytest.param(_ca("G-GRANT", params={"permission_level": 1}), id="d10-permission_level-1"),
    # ---- e* — access/extend_permission: R10 (allow), R09, R12 ----
    pytest.param(_ca("G-EXTEND", decision=AUTO, rule_id="R10", khop="R10"), id="e1-R10-khop"),
    pytest.param(_ca("G-EXTEND", params={"duration_days": 180}), id="e2-R10-180-ngay-ho-L4"),
    pytest.param(_ca("G-EXTEND", params={"duration_days": 90}, decision=AUTO, rule_id="R10", khop="R10"),
                 id="e3-R10-dung-90-ngay-lte"),
    pytest.param(_ca("G-EXTEND", params={"duration_days": 91}), id="e4-R10-91-ngay"),
    pytest.param(_ca("G-EXTEND", facts={"resource_sensitivity": "high"}), id="e5-R10-sensitivity-high-R07-chi-grant"),
    pytest.param(_ca("G-EXTEND", facts={"same_department": False}, decision=HITL, rule_id="R09", khop="R09"),
                 id="e6-R09-extend-khac-phong"),
    pytest.param(_ca("G-EXTEND", bo=("has_permission_record",)), id="e7-R10-thieu-has_permission_record"),
    pytest.param(_ca("G-EXTEND", bo=("same_department",)), id="e8-R10-thieu-same_department"),
    pytest.param(_ca("G-EXTEND", bo=("resource_sensitivity",)), id="e9-R10-thieu-resource_sensitivity"),
    pytest.param(_ca("G-EXTEND", bo=("target_user_status",)), id="e10-R10-thieu-target_user_status"),
    pytest.param(_ca("G-EXTEND", bo_params=("duration_days",)), id="e11-R10-thieu-duration_days"),
    pytest.param(_ca("G-EXTEND", requested_for="nv005"), id="e12-R10-other-true-requested_for-nv005"),
    pytest.param(_ca("G-EXTEND", facts={"target_user_status": "disabled"}),
                 id="e12b-R10-disabled-thieu-target_disable_reason"),
    pytest.param(_ca("G-EXTEND", facts={"target_user_status": "disabled", "target_disable_reason": "security"},
                     decision=DENY, rule_id="R12", khop="R12"), id="e13-R12-extend-deny"),
    pytest.param(_ca("G-EXTEND", params={"duration_days": "30"}), id="e14-R10-duration_days-str-30"),
    # e15 (chốt Q-T22a-7): duration_days ngoài khoảng 1–365 / bool → coi như THIẾU (P3) → R10 không khớp; bắt M-T22a-10
    pytest.param(_ca("G-EXTEND", params={"duration_days": 0}), id="e15-R10-duration_days-0"),
    pytest.param(_ca("G-EXTEND", params={"duration_days": -1}), id="e15-R10-duration_days-am-1"),
    pytest.param(_ca("G-EXTEND", params={"duration_days": 400}), id="e15-R10-duration_days-400"),
    pytest.param(_ca("G-EXTEND", params={"duration_days": True}), id="e15-R10-duration_days-True"),
    # ---- r* — T20a P1 (phase5 5.1.6 r1–r3): R10 thêm `F.existing_permission_level in [read, write]` (M-T20a-1) ----
    pytest.param(_ca("G-EXTEND", facts={"existing_permission_level": "write"}, decision=AUTO, rule_id="R10", khop="R10"),
                 id="r1-R10-existing_permission_level-write"),
    pytest.param(_ca("G-EXTEND", facts={"existing_permission_level": "full"}),
                 id="r2-R10-existing_permission_level-full"),
    pytest.param(_ca("G-EXTEND", bo=("existing_permission_level",)), id="r3-R10-thieu-existing_permission_level"),
    # ---- f* — software/install_software: R11 (allow), R13, R14, R15 ----
    pytest.param(_ca("G-INSTALL", decision=AUTO, rule_id="R11", khop="R11"), id="f1-R11-khop"),
    pytest.param(_ca("G-INSTALL", facts={"in_catalog": False}, decision=HITL, rule_id="R13", khop="R13"),
                 id="f2-R13-in_catalog-false"),
    pytest.param(_ca("G-INSTALL", facts={"license_paid": True}, decision=HITL, rule_id="R14", khop="R14"),
                 id="f3-R14-license_paid-true"),
    pytest.param(_ca("G-INSTALL", facts={"requires_local_admin": True}, decision=HITL, rule_id="R15", khop="R15"),
                 id="f4-R15-requires_local_admin-true"),
    pytest.param(_ca("G-INSTALL", facts={"license_paid": True}, decision=HITL, rule_id="R14", khop="R14"),
                 id="f5-R11+R14-paid-R11-khong-khop"),
    pytest.param(_ca("G-INSTALL", facts={"in_catalog": False, "license_paid": True, "requires_local_admin": True},
                     decision=HITL, rule_id="R13", khop="R13 R14 R15"), id="f6-R13+R14+R15-R13"),
    pytest.param(_ca("G-INSTALL", bo=("in_catalog",)), id="f7-R11-thieu-in_catalog"),
    pytest.param(_ca("G-INSTALL", bo=("license_paid",)), id="f8-R11-thieu-license_paid"),
    pytest.param(_ca("G-INSTALL", bo=("requires_local_admin",)), id="f9-R11-thieu-requires_local_admin"),
    pytest.param(_ca("G-INSTALL", facts={"device_owner_is_requester": False}),
                 id="f10-R11-may-nguoi-khac-owner-false"),
    pytest.param(_ca("G-INSTALL", bo=("device_owner_is_requester",)),
                 id="f11-R11-thieu-device_owner_is_requester"),
]
# fmt: on


def _action(ca: Ca) -> Action:
    check_facts(ca.facts)  # tự kiểm ca test: chỉ key thuộc FACT_KEYS, đúng kiểu, đúng tập giá trị (P2)
    reversible, reversibility, data_sensitivity, scope, privilege_level = META_4_2[ca.action_type]
    return Action(
        type=ca.action_type, target=ca.target, requested_for=ca.requested_for, scope=scope,
        privilege_level=privilege_level, reversible=reversible, reversibility=reversibility,
        data_sensitivity=data_sensitivity, params=dict(ca.params), facts=dict(ca.facts),
    )  # fmt: skip


def _verdict(ca: Ca) -> RuleVerdict:
    action = _action(ca)
    state = {
        "intended_action": action.model_dump(),
        "requester_context": ca.requester.model_dump(),
        "ctx_flags": dict(ca.ctx_flags),
    }
    ctx = build_ctx(state, NOW, get_policy().business_hours)
    return evaluate_rules(get_policy().rules, action, ctx, intents=action_intents())


@pytest.mark.parametrize("ca", BANG_4_7)
def test_bang_4_7_luat_a_den_f(ca: Ca) -> None:
    """Bảng 4.7 a*–f* (kỳ vọng chép từ bảng 4.7/4.4): state → build_ctx → evaluate_rules cho đúng decision, rule_id,
    all_matched (thứ tự file). Nhiều luật khớp → chặt nhất thắng (deny > approval_required > allow); thiếu fact → sai (P1).
    d10/e14: params sai kiểu/ngoài tập không ném lỗi, bị coi như thiếu (P3)."""
    v = _verdict(ca)
    assert isinstance(v, RuleVerdict)
    got = (v.matched, v.decision, v.rule_id, list(v.all_matched))
    assert got == (bool(ca.all_matched), ca.decision, ca.rule_id, list(ca.all_matched)), v


def test_bang_4_7_du_ca_id_khong_trung() -> None:
    """Bảng 4.7: bảng tham số hoá không rỗng, id không trùng, đủ mọi họ a/b/c/d/e/f."""
    ids = [str(p.id) for p in BANG_4_7]
    assert len(ids) == len(set(ids)) >= 55
    for ho in "abcdef":
        assert any(i.startswith(ho) for i in ids), ho


# ---- h4 — test meta: mỗi luật allow có ca "thiếu từng fact" (P1) ---------------------------------------------------------

# Bảng 4.4: điều kiện F.* / P.* của từng luật allow có fact (R06 chỉ có `other` → ca c2).
ALLOW_FACTS_4_4: dict[str, tuple[str, ...]] = {
    "R01": ("target_account_privilege", "target_is_service_account", "target_user_status"),
    "R02": ("target_account_locked", "target_lock_reason", "target_account_privilege", "target_is_service_account",
            "target_user_status"),
    # T20a P1 (Q-T20a-1 d): + `existing_permission_level` (ca r3)
    "R10": ("has_permission_record", "same_department", "resource_sensitivity", "target_user_status", "duration_days",
            "existing_permission_level"),
    "R11": ("in_catalog", "license_paid", "requires_local_admin"),
}  # fmt: skip


def test_h4_moi_luat_allow_co_ca_thieu_tung_fact() -> None:
    """h4 (P1): với mỗi luật allow của bảng 4.4 có fact (R01, R02, R10, R11), file có ca `<luật>-thieu-<fact>` cho TỪNG
    fact, kỳ vọng không khớp luật đó; R06 (chỉ `other`) có ca người khác c2."""
    by_id = {str(p.id): cast(Ca, p.values[0]) for p in BANG_4_7}
    for luat, facts in ALLOW_FACTS_4_4.items():
        for fact in facts:
            hits = [i for i in by_id if f"-{luat}-thieu-{fact}" in i]
            assert hits, (luat, fact)
            for i in hits:
                assert luat not in by_id[i].all_matched, i
                assert by_id[i].decision != AUTO, i
    assert any(i.startswith("c2-R06") and not by_id[i].all_matched for i in by_id)


def test_h4_cong_5_moi_luat_r01_r15_co_ca_khop() -> None:
    """Cổng 5 (mục 1.3: "20 luật đều có ca khớp và ca suýt khớp"): R01–R15 đều có ≥ 1 ca trong bảng 4.7 mà luật đó khớp
    (R16–R20 đã có ở test_policy_rules_vpn.py `LUAT_C5`)."""
    cases = [cast(Ca, p.values[0]) for p in BANG_4_7]
    for n in range(1, 16):
        rid = f"R{n:02d}"
        assert any(rid in c.all_matched for c in cases), rid


# ---- h1 — đếm luật ---------------------------------------------------------------------------------------------------


def test_h1_dung_21_luat_r01_r21_7_12_2() -> None:
    """h1 (P8, kiểm đếm bảng 4.4 [Chốt N4]): đúng 21 id R01…R21, không trùng, thứ tự tăng dần trong file;
    7 allow / 12 approval_required / 2 deny. Đổi ở Q5 (ĐP 09/11 10:05 duyệt mở rộng N4 cho BẢN DEMO): + R21 deny phần mềm bị cấm
    (nội dung kiểm ở `test_q5_phan_mem_cam.py`); bản đo `bf94df2` vẫn 20 luật 7/12/1."""
    rules = get_policy().rules
    ids = [r.id for r in rules]
    assert ids == [f"R{n:02d}" for n in range(1, 22)]
    assert len(set(ids)) == 21
    by_type: dict[str, set[str]] = {}
    for r in rules:
        by_type.setdefault(str(r.type), set()).add(r.id)
    assert by_type.get(AUTO) == {"R01", "R02", "R06", "R10", "R11", "R16", "R20"}
    assert by_type.get(HITL) == {"R03", "R04", "R05", "R07", "R08", "R09", "R13", "R14", "R15", "R17", "R18", "R19"}
    assert by_type.get(DENY) == {"R12", "R21"}
    assert {k: len(v) for k, v in by_type.items()} == {AUTO: 7, HITL: 12, DENY: 2}


# ---- P8 — nội dung R01–R15 đúng bảng 4.4 nguyên văn ----------------------------------------------------------------------

_F, _P, _OTHER = "action.facts.", "action.params.", "ctx.target_is_other"
_ACTIVE = ["active", "probation"]


def _c(fact: str, op: str, value: object = None) -> tuple[str, str, str]:
    """Điều kiện chuẩn hoá để so: `in`/`not_in` so như tập (sắp xếp danh sách); không có `value` → chuỗi rỗng."""
    if isinstance(value, list):
        value = sorted(value, key=str)
    return (fact, op, "" if value is None else json.dumps(value, ensure_ascii=False))


BANG_4_4: dict[str, tuple[str, str, set[str], list[tuple[str, str, str]], str]] = {
    "R01": (AUTO, "account", {"reset_password"}, [
        _c(_OTHER, "is_false"), _c(_F + "target_account_privilege", "eq", "standard_user"),
        _c(_F + "target_is_service_account", "is_false"), _c(_F + "target_user_status", "in", _ACTIVE),
    ], "Đặt lại mật khẩu tài khoản thường của chính mình"),
    "R02": (AUTO, "account", {"unlock_account"}, [
        _c(_OTHER, "is_false"), _c(_F + "target_account_locked", "is_true"),
        _c(_F + "target_lock_reason", "eq", "bad_password"), _c(_F + "target_account_privilege", "eq", "standard_user"),
        _c(_F + "target_is_service_account", "is_false"), _c(_F + "target_user_status", "in", _ACTIVE),
    ], "Mở khoá tài khoản thường của chính mình bị khoá do nhập sai mật khẩu"),
    "R03": (HITL, "account", {"reset_password", "unlock_account"}, [
        _c(_F + "target_is_service_account", "is_true"),
    ], "Thao tác trên tài khoản dịch vụ cần người duyệt"),
    "R04": (HITL, "account", {"reset_password", "unlock_account"}, [
        _c(_F + "target_account_privilege", "eq", "admin"),
    ], "Thao tác trên tài khoản quản trị cần người duyệt"),
    "R05": (HITL, "account", {"reset_password", "unlock_account"}, [
        _c(_F + "target_user_status", "eq", "terminated"),
    ], "Thao tác trên tài khoản của người đã nghỉ việc cần người duyệt"),
    "R06": (AUTO, "access", {"view_permissions"}, [_c(_OTHER, "is_false")], "Xem quyền hiện có của chính mình"),
    "R07": (HITL, "access", {"grant_permission"}, [
        _c(_F + "resource_sensitivity", "eq", "high"),
    ], "Cấp quyền mới vào dữ liệu nhạy cảm cần người duyệt"),
    "R08": (HITL, "access", {"grant_permission"}, [
        _c(_P + "permission_level", "eq", "full"),
    ], "Cấp quyền quản trị (toàn quyền) thư mục cần người duyệt"),
    "R09": (HITL, "access", {"grant_permission", "extend_permission"}, [
        _c(_F + "same_department", "is_false"),
    ], "Cấp/gia hạn quyền vào tài nguyên phòng ban khác (vượt cấp quản lý) cần người duyệt"),
    "R10": (AUTO, "access", {"extend_permission"}, [
        _c(_OTHER, "is_false"), _c(_F + "has_permission_record", "is_true"), _c(_F + "same_department", "is_true"),
        _c(_F + "resource_sensitivity", "in", ["low", "medium"]), _c(_F + "target_user_status", "in", _ACTIVE),
        _c(_P + "duration_days", "lte", 90),
        _c(_F + "existing_permission_level", "in", ["read", "write"]),  # T20a P1 (Q-T20a-1 d, bảng 4.4 v0.3)
    ], "Gia hạn quyền cũ (≤ 90 ngày) vào thư mục không nhạy cảm của phòng mình"),
    "R11": (AUTO, "software", {"install_software"}, [
        _c(_OTHER, "is_false"), _c(_F + "in_catalog", "is_true"), _c(_F + "license_paid", "is_false"),
        _c(_F + "requires_local_admin", "is_false"),
    ], "Cài phần mềm miễn phí trong danh mục lên máy của mình"),
    "R12": (DENY, "access", {"grant_permission", "extend_permission"}, [
        _c(_F + "target_user_status", "eq", "disabled"), _c(_F + "target_disable_reason", "eq", "security"),
    ], "Cấm cấp quyền cho tài khoản bị vô hiệu hoá vì lý do bảo mật"),
    "R13": (HITL, "software", {"install_software"}, [
        _c(_F + "in_catalog", "is_false"),
    ], "Cài phần mềm ngoài danh mục cần người duyệt"),
    "R14": (HITL, "software", {"install_software"}, [
        _c(_F + "license_paid", "is_true"),
    ], "Cài phần mềm có phí license cần người duyệt"),
    "R15": (HITL, "software", {"install_software"}, [
        _c(_F + "requires_local_admin", "is_true"),
    ], "Cài phần mềm cần quyền quản trị máy cần người duyệt"),
}  # fmt: skip


def _raw_rules() -> dict[str, dict[str, Any]]:
    raw = json.loads((REPO / "config" / "policy.json").read_text(encoding="utf-8"))
    return {r["id"]: r for r in raw["rules"]}


def _norm_cond(c: dict[str, Any]) -> tuple[str, str, str]:
    assert "fact" in c, f"luật T22a chỉ dùng điều kiện phẳng trong `all` (bảng 4.4): {c}"
    return _c(c["fact"], c["op"], c.get("value"))


@pytest.mark.parametrize("rid", sorted(BANG_4_4))
def test_p8_luat_r01_r15_dung_bang_4_4(rid: str) -> None:
    """P8 (bảng 4.4 nguyên văn): type, intent, action, điều kiện `all` (không xét thứ tự điều kiện; `in` so như tập),
    `description` = cột "Mô tả"."""
    loai, intent, actions, conds, mo_ta = BANG_4_4[rid]
    rules = _raw_rules()
    assert rid in rules, f"policy.json chưa có {rid}"
    rule = rules[rid]
    assert (rule["type"], rule["intent"]) == (loai, intent)
    got_actions = rule["action"] if isinstance(rule["action"], list) else [rule["action"]]
    assert set(got_actions) == actions
    assert set(rule["conditions"]) == {"all"}
    assert sorted(_norm_cond(c) for c in rule["conditions"]["all"]) == sorted(conds)
    assert rule["description"] == mo_ta


# ---- h2 — hành động của luật thuộc đúng intent ---------------------------------------------------------------------------

ACTION_TYPES_4_2 = {
    "account": {"reset_password", "unlock_account"},
    "software": {"install_software"},
    "access": {"view_permissions", "grant_permission", "extend_permission"},
}


def _actions(rule: Any) -> list[str]:
    return [rule.action] if isinstance(rule.action, str) else list(rule.action)


def test_h2_hanh_dong_cua_luat_thuoc_dung_intent() -> None:
    """h2: `check_policy_config` thật xanh; mọi `action` của mỗi luật ∈ `action_types` của đúng `intent` của luật
    (slots.yaml); 3 intent mới khai báo đúng `action_types` bảng 4.2 (P6)."""
    check_policy_config(get_policy(), get_slots(), get_action_metadata())
    slots = get_slots().intents
    assert set(ACTION_TYPES_4_2) <= set(slots), f"slots.yaml chưa khai báo 3 intent mới: {sorted(slots)}"
    intents = action_intents()
    for rule in get_policy().rules:
        for a in _actions(rule):
            assert a in slots[rule.intent].action_types, (rule.id, a)
            assert intents[a] == rule.intent, (rule.id, a)
    for intent, types in ACTION_TYPES_4_2.items():
        assert set(slots[intent].action_types) == types, intent


# ---- h3 — Việc treo 19: không luật nào tham chiếu action.target (P10) ------------------------------------------------


def _facts_in(node: object) -> list[str]:
    if isinstance(node, dict):
        own = [node["fact"]] if isinstance(node.get("fact"), str) else []
        return own + [f for v in node.values() for f in _facts_in(v)]
    if isinstance(node, list):
        return [f for v in node for f in _facts_in(v)]
    return []


def test_h3_khong_dieu_kien_nao_tham_chieu_action_target() -> None:
    """h3 (P10, Việc treo 19): không điều kiện nào — kể cả trong nhóm `all`/`any` lồng — dùng fact `action.target`."""
    raw = json.loads((REPO / "config" / "policy.json").read_text(encoding="utf-8"))
    facts = [f for r in raw["rules"] for f in _facts_in(r["conditions"])]
    assert len(raw["rules"]) == 21 and facts  # Q5: + R21
    assert "action.target" not in facts


# ---- h5, h6 — khởi động với cấu hình thật, không bật intent mới -----------------------------------------------------------


def test_h5_khoi_dong_voi_cau_hinh_that() -> None:
    """h5 (P6): settings thật (`ENABLED_INTENTS=["vpn"]`) → `check_policy_config`, `check_intent_config`, `check_plans`
    không ném — 3 intent khai báo nhưng không bật thì không cần PLAN/roster."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    check_policy_config(get_policy(), get_slots(), get_action_metadata())
    check_intent_config(settings, get_slots(), get_action_metadata())
    check_plans(get_action_metadata().root, settings.enabled_intents)
    assert {"account", "software", "access"} <= set(get_slots().intents)


def test_h6_khong_bat_intent_moi() -> None:
    """h6 (P6, P11 của T22a): T22a không bật intent mới. T24 P1 (Q-5-7) bật đủ 4 — giá trị ghim đổi theo."""
    assert Settings(_env_file=None).enabled_intents == ["vpn", "account", "software", "access"]  # type: ignore[call-arg]


# ---- h7 — check_facts kiểm tập giá trị (P2) ------------------------------------------------------------------------------


def test_h7_check_facts_tap_gia_tri_target_user_status() -> None:
    """h7 (P2, `FACT_VALUE_SETS`): `target_user_status="active"` hợp lệ; `"on_leave"` (ngoài tập) → FactKeyViolation."""
    check_facts({"target_user_status": "active"})
    with pytest.raises(FactKeyViolation, match="ngoài tập giá trị"):
        check_facts({"target_user_status": "on_leave"})


# ---- h8 — procedure_doc 6 hành động (bảng 4.2 [Chốt 09/10]) ---------------------------------------------------------------

PROCEDURE_DOC_4_2 = {
    ("account", "reset_password"): "KB-ACC-001",
    ("account", "unlock_account"): "KB-ACC-002",
    ("software", "install_software"): "KB-SW-001",
    ("access", "view_permissions"): "KB-ACS-005",
    ("access", "grant_permission"): "KB-ACS-001",
    ("access", "extend_permission"): "KB-ACS-003",
}


def test_h8_procedure_doc_6_hanh_dong_dung_bang_4_2() -> None:
    """h8 (bảng 4.2 [Chốt 09/10]): `procedure_doc` của 6 hành động mới đúng mã K2."""
    root = get_action_metadata().root
    assert {"account", "software", "access"} <= set(root), f"action_metadata.yaml chưa có 3 intent mới: {sorted(root)}"
    got = {(intent, a): root[intent][a].procedure_doc for intent, a in PROCEDURE_DOC_4_2}
    assert got == PROCEDURE_DOC_4_2

