"""T20a — bộ tool chẩn đoán + `device_facts` dùng chung (phase5 5.1.1 P2, P3; 5.1.2; 5.1.6 t1; PLAN-T20a TQ-3, TQ-4).

- t1: `TOOLS` mỗi module == `TOOL_MAP[intent]` == bảng P2 (kiểm độc lập với code); `validate_specs` qua; `DIAGNOSERS` đúng 3 intent
  mới (vpn KHÔNG có — TQ-3); `infer = infer_<intent>`.
- TQ-4: `vpn.device_facts(devices, *, requester_id, device_id)` = phần máy của `infer_vpn` (hàm thuần, model tool thật).
- Tự kiểm bản giả `tests/fakes/seed_tools.SeedTools` (qua registry THẬT — output model validate được) để test infer_* không đỏ vì bản
  giả sai: đối chiếu từng giá trị với `mock_services/seed.json` (đọc độc lập ở đây).
"""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from app.settings import get_slots
from app.tools import models as m
from app.tools.diagnosis import DIAGNOSERS, access, account, software, vpn
from app.tools.specs import SPECS, TOOL_MAP, validate_specs
from tests.unit._t20a import NOW, Env

SEED = json.loads((Path(__file__).resolve().parents[3] / "mock_services" / "seed.json").read_text(encoding="utf-8"))
asyncio = pytest.mark.asyncio

# Bảng P2 (5.1.1) — chép từ đặc tả, không từ code.
TOOL_MAP_P2 = {
    "account": ("check_account_status", "check_lockout_history", "check_privilege_level"),
    "vpn": ("check_device_registered", "check_vpn_cert_expiry", "check_last_connection"),
    "software": ("check_catalog_entry", "check_license_available", "check_installed_list", "check_device_registered"),
    "access": ("check_current_permissions", "check_resource_sensitivity", "check_manager_chain", "check_account_status"),
}


# ---- t1 -----------------------------------------------------------------------------------------------------------------


def test_t1_tool_map_matches_p2() -> None:
    """t1 / P2 (D-46): `TOOL_MAP` đúng bảng P2 (account, vpn không đổi; software + check_device_registered; access +
    check_account_status)."""
    assert {k: tuple(v) for k, v in TOOL_MAP.items()} == TOOL_MAP_P2


@pytest.mark.parametrize(("intent", "module"), [("account", account), ("software", software), ("access", access)])
def test_t1_module_tools_equal_tool_map(intent: str, module: Any) -> None:
    """t1 (P3): `TOOLS` của module == `TOOL_MAP[intent]`; `infer` là `infer_<intent>`."""
    assert tuple(module.TOOLS) == tuple(TOOL_MAP[intent]) == TOOL_MAP_P2[intent]
    assert module.infer is getattr(module, f"infer_{intent}")


def test_t1_validate_specs_passes() -> None:
    """t1: `validate_specs` (luật kiểm không đổi) qua với `TOOL_MAP` mới."""
    registry = validate_specs(SPECS, get_slots().tool_arg_slots, TOOL_MAP)
    for names in TOOL_MAP.values():
        for name in names:
            assert registry[name].kind == "read" and "B6" in registry[name].allowed_steps


def test_t1_diagnosers_three_new_intents_without_vpn() -> None:
    """TQ-3: `DIAGNOSERS` ở `app.tools.diagnosis` = {account, software, access} — vpn giữ dòng code cũ, không nằm trong bảng."""
    assert dict(DIAGNOSERS) == {"account": account, "software": software, "access": access}
    assert "vpn" not in DIAGNOSERS
    for module in DIAGNOSERS.values():
        for attr in ("TOOLS", "calls", "target_calls", "infer"):
            assert hasattr(module, attr), (module.__name__, attr)


@pytest.mark.parametrize(
    ("module", "requester", "slots"),
    [
        (account, "nv001", {"account_type": "email", "target_user": "nv005"}),
        (software, "nv001", {"software_name": "Zoom", "device_id": "LAP-0342"}),
        (software, "nv001", {}),
        (access, "nv001", {"action": "extend_permission", "resource_path": "finance/Q3", "duration": "30"}),
        (access, "nv001", {"action": "view_permissions"}),
    ],
)
def test_t1_calls_only_tools_of_intent_in_order(module: Any, requester: str, slots: dict[str, str]) -> None:
    """P3: `calls` chỉ gồm tool trong `TOOLS`, không trùng, đúng thứ tự `TOOLS`; tham số qua được input model của registry."""
    tools = [t for t, _ in module.calls(requester, slots)]
    assert tools and len(tools) == len(set(tools))
    assert tools == [t for t in module.TOOLS if t in tools]
    from app.tools.specs import REGISTRY

    for tool, args in module.calls(requester, slots):
        REGISTRY[tool].input_model.model_validate(args)  # extra=forbid — khoá thừa là lỗi hợp đồng


# ---- TQ-4: device_facts (phần máy của infer_vpn) ----------------------------------------------------------------------------


def _dev(device_id: str, owner: str, registered: bool = True) -> m.Device:
    return m.Device(device_id=device_id, owner_id=owner, kind="laptop", os="Windows 11", registered=registered,
                    registered_at=NOW - timedelta(days=10) if registered else None)  # fmt: skip


def test_device_facts_no_device_one_machine_infers() -> None:
    """TQ-4 (như infer_vpn): không nêu máy, đúng 1 máy → device_count, has_registered_device, suy slot device_id + fact máy."""
    slots, facts = vpn.device_facts([_dev("LAP-0342", "nv001")], requester_id="nv001", device_id=None)
    assert slots == {"device_id": "LAP-0342"}
    assert facts == {"device_count": 1, "has_registered_device": True, "device_registered": True,
                     "device_owner_is_requester": True}  # fmt: skip


def test_device_facts_no_device_two_machines_not_inferred() -> None:
    slots, facts = vpn.device_facts([_dev("LAP-0417", "nv002"), _dev("PC-0977", "nv002", registered=False)],
                                    requester_id="nv002", device_id=None)  # fmt: skip
    assert slots == {} and facts == {"device_count": 2, "has_registered_device": True}


def test_device_facts_zero_devices() -> None:
    slots, facts = vpn.device_facts([], requester_id="nv007", device_id=None)
    assert slots == {} and facts == {"device_count": 0, "has_registered_device": False}


def test_device_facts_named_device_other_owner() -> None:
    """Có nêu máy → chỉ device_registered, device_owner_is_requester (máy người khác → False)."""
    slots, facts = vpn.device_facts([_dev("LAP-0417", "nv002")], requester_id="nv001", device_id="LAP-0417")
    assert slots == {} and facts == {"device_registered": True, "device_owner_is_requester": False}


def test_device_facts_named_device_missing_is_false() -> None:
    slots, facts = vpn.device_facts([], requester_id="nv001", device_id="LAP-9999")
    assert slots == {} and facts == {"device_registered": False, "device_owner_is_requester": False}


# ---- tự kiểm bản giả SeedTools (đối chiếu seed.json đọc độc lập) ------------------------------------------------------------


def _seed_user(user_id: str) -> dict[str, Any]:
    return next(u for u in SEED["users"] if u["user_id"] == user_id)


@asyncio
async def test_fake_account_status_matches_seed_and_mock_defaults() -> None:
    env = Env()
    [r] = await env.run_calls([("check_account_status", {"user_id": "nv007", "account_type": "email"})])
    assert isinstance(r.data, m.AccountStatus)
    seed = _seed_user("nv007")
    assert (r.data.department, r.data.employment_status, r.data.is_service_account) == (
        seed["department"], seed["employment_status"], seed["is_service_account"])
    assert (r.data.account.locked, r.data.account.lock_reason) == (True, "bad_password")
    [r] = await env.run_calls([("check_account_status", {"user_id": "nv001"})])  # mặc định ad, seed `{}` → mặc định mock
    assert isinstance(r.data, m.AccountStatus)
    assert (r.data.account.account_type, r.data.account.enabled, r.data.account.locked) == ("ad", True, False)
    [r] = await env.run_calls([("check_account_status", {"user_id": "nv005", "account_type": "erp"})])
    assert r.data is None and r.empty and r.error is None  # 404: không có tài khoản erp
    [r] = await env.run_calls([("check_account_status", {"user_id": "nv-la"})])
    assert r.data is None and r.empty


@asyncio
async def test_fake_privilege_lockouts_manager_chain() -> None:
    env = Env()
    p, lo, mc = await env.run_calls([
        ("check_privilege_level", {"user_id": "svc_backup", "account_type": "ad"}),
        ("check_lockout_history", {"user_id": "nv007"}),
        ("check_manager_chain", {"user_id": "l1_01"}),
    ])  # fmt: skip
    assert isinstance(p.data, m.Privilege) and p.data.level == "admin"
    assert isinstance(lo.data, m.LockoutList) and len(lo.data.root) == 3
    assert [x.at for x in lo.data.root] == sorted((x.at for x in lo.data.root), reverse=True)
    assert isinstance(mc.data, m.ManagerChain) and [x.user_id for x in mc.data.root] == ["l1_lead", "it_mgr01"]
    [p] = await env.run_calls([("check_privilege_level", {"user_id": "nv001", "account_type": "ad"})])
    assert isinstance(p.data, m.Privilege) and p.data.level == "standard_user"


@asyncio
async def test_fake_software_tools() -> None:
    env = Env()
    cat, lic, inst = await env.run_calls([
        ("check_catalog_entry", {"software_name": "AutoCAD"}),
        ("check_license_available", {"software_name": "autocad"}),
        ("check_installed_list", {"device_id": "LAP-0342"}),
    ])  # fmt: skip
    assert isinstance(cat.data, m.CatalogEntry)
    assert (cat.data.in_catalog, cat.data.paid, cat.data.requires_local_admin) == (True, True, True)
    assert isinstance(lic.data, m.LicenseInfo) and (lic.data.total, lic.data.used, lic.data.available) == (3, 3, 0)
    assert isinstance(inst.data, m.InstalledList) and [i.name for i in inst.data.root] == ["ms-office", "zoom"]
    miss, none_dev, empty_dev = await env.run_calls([
        ("check_catalog_entry", {"software_name": "Photoshop"}),
        ("check_installed_list", {"device_id": "LAP-9999"}),
        ("check_installed_list", {"device_id": "PC-0977"}),
    ])  # fmt: skip
    assert miss.data is None and none_dev.data is None
    assert isinstance(empty_dev.data, m.InstalledList) and empty_dev.data.root == [] and empty_dev.empty
    [z] = await env.run_calls([("check_catalog_entry", {"software_name": "  Adobe Acrobat Pro "})])
    assert isinstance(z.data, m.CatalogEntry) and z.data.name == "adobe-acrobat-pro"


@asyncio
async def test_fake_file_tools() -> None:
    env = Env()
    q3, empty, unknown = await env.run_calls([
        ("check_current_permissions", {"user_id": "nv002", "resource_path": "/finance/Q3/"}),
        ("check_current_permissions", {"user_id": "nv004", "resource_path": "engineering/specs"}),
        ("check_current_permissions", {"user_id": "nv-la"}),
    ])  # fmt: skip
    assert isinstance(q3.data, m.PermissionList) and [(p.path, p.level, p.status) for p in q3.data.root] == [
        ("finance/Q3", "read", "expired")]
    assert isinstance(empty.data, m.PermissionList) and empty.data.root == [] and empty.empty
    assert unknown.data is None and unknown.empty
    [all_rows] = await env.run_calls([("check_current_permissions", {"user_id": "nv001"})])
    assert isinstance(all_rows.data, m.PermissionList)
    assert [p.path for p in all_rows.data.root] == ["finance/Q3", "finance/public-reports"]
    res, miss = await env.run_calls([
        ("check_resource_sensitivity", {"resource_path": "/engineering/specs"}),
        ("check_resource_sensitivity", {"resource_path": "finance/khong-co"}),
    ])  # fmt: skip
    assert isinstance(res.data, m.ResourceInfo)
    assert (res.data.sensitivity, res.data.owner_department) == ("medium", "Engineering")
    assert miss.data is None
    assert env.tools.calls["check_current_permissions"] == 4 and len(env.tools.seen) == 6
