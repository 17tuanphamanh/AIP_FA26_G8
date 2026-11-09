"""T20a — `tools/diagnosis/software` (phase5 5.1.2 bảng software, 5.1.6 s1–s7; P8; PLAN-T20a TQ-2, TQ-4).

Viết TỪ ĐẶC TẢ, trước code. `rf` luôn là người gửi (P6); tên tra cứu = `normalize_software_name(slot)` (P8, đúng thuật toán mock);
`check_catalog_entry`/`check_license_available` chỉ khi có tên; `check_installed_list` chỉ khi có máy; `check_device_registered` luôn
gọi (không có máy → không có khoá `device_id`). Phần máy = `vpn.device_facts` (như `infer_vpn`): không nêu máy → `device_count`,
`has_registered_device`, đúng 1 máy → suy slot `device_id`; có máy → `device_registered`, `device_owner_is_requester`.

Seed: nv001 đúng 1 máy LAP-0342 (đăng ký); nv002 hai máy (LAP-0417 đăng ký, PC-0977 chưa); catalog zoom (free, không cần admin),
autocad (paid, cần admin); "photoshop" không có trong catalog (mock trả 404).
"""

from typing import Any

import pytest
from app.tools.diagnosis import software
from tests.unit._t20a import Env

ME = "nv001"
asyncio = pytest.mark.asyncio


async def _run(requester: str, slots: dict[str, str]) -> tuple[Any, ...]:
    env = Env()
    calls, diag, inferred, facts = await env.diagnose(software, requester, slots)
    return env, calls, diag, inferred, facts


# ---- lời gọi --------------------------------------------------------------------------------------------------------------


def test_calls_name_and_device_full_set_in_tools_order() -> None:
    """5.1.2 software: có tên + máy → đủ 4 tool, thứ tự `TOOLS`; tên đã chuẩn hoá (P8)."""
    assert software.calls(ME, {"software_name": "Zoom", "device_id": "LAP-0342"}) == [
        ("check_catalog_entry", {"software_name": "zoom"}),
        ("check_license_available", {"software_name": "zoom"}),
        ("check_installed_list", {"device_id": "LAP-0342"}),
        ("check_device_registered", {"user_id": ME, "device_id": "LAP-0342"}),
    ]  # fmt: skip


def test_calls_name_normalized_like_mock() -> None:
    """P8: "Adobe Acrobat Pro" → "adobe-acrobat-pro" (cùng `software.normalize` của mock)."""
    calls = dict(software.calls(ME, {"software_name": "  Adobe Acrobat  Pro "}))
    assert calls["check_catalog_entry"] == {"software_name": "adobe-acrobat-pro"}
    assert calls["check_license_available"] == {"software_name": "adobe-acrobat-pro"}


def test_s7_calls_without_name_only_device_registered() -> None:
    """s7: chưa có tên → không gọi catalog/license; vẫn gọi `check_device_registered` (không máy → không khoá device_id)."""
    assert software.calls(ME, {}) == [("check_device_registered", {"user_id": ME})]


def test_calls_name_without_device() -> None:
    """Có tên, chưa có máy → không gọi `check_installed_list`; `check_device_registered` theo người gửi."""
    assert software.calls(ME, {"software_name": "zoom"}) == [
        ("check_catalog_entry", {"software_name": "zoom"}),
        ("check_license_available", {"software_name": "zoom"}),
        ("check_device_registered", {"user_id": ME}),
    ]  # fmt: skip


def test_calls_rf_always_requester_even_with_target_user() -> None:
    """P6: software luôn người gửi — slot lạ `target_user` (không khai báo cho software) không đổi người tra."""
    for _, args in software.calls(ME, {"software_name": "zoom", "target_user": "nv005"}):
        assert args.get("user_id", ME) == ME


def test_target_calls_same_rule_on_final_slots() -> None:
    """TQ-3: `target_calls` (B11) cùng quy tắc với `calls` trên slot cuối."""
    for slots in ({"software_name": "Zoom", "device_id": "LAP-0342"}, {"software_name": "zoom"}, {}):
        assert software.target_calls(ME, slots) == software.calls(ME, slots)


# ---- s1–s7 ----------------------------------------------------------------------------------------------------------------


@asyncio
async def test_s1_zoom_on_own_lap0342() -> None:
    """s1: "Zoom" + LAP-0342 (nv001) → in_catalog True, license_paid False, requires_local_admin False, device_registered True,
    device_owner_is_requester True."""
    _, _, _, inferred, facts = await _run(ME, {"software_name": "Zoom", "device_id": "LAP-0342"})
    assert facts == {
        "in_catalog": True, "license_paid": False, "requires_local_admin": False, "software_prohibited": False,  # Q5
        "device_registered": True, "device_owner_is_requester": True,
    }  # fmt: skip
    assert inferred == {}  # đã nêu máy → không suy gì


@asyncio
async def test_s2_autocad_paid_and_local_admin() -> None:
    """s2: "AutoCAD" → license_paid True, requires_local_admin True (vẫn trong catalog)."""
    _, _, _, _, facts = await _run(ME, {"software_name": "AutoCAD", "device_id": "LAP-0342"})
    assert (facts["in_catalog"], facts["license_paid"], facts["requires_local_admin"]) == (True, True, True)


@asyncio
async def test_s3_photoshop_404_in_catalog_false_only() -> None:
    """s3 (M-T20a-3): "Photoshop" — catalog 404 → `in_catalog=False`; KHÔNG đặt license_paid, requires_local_admin."""
    _, _, diag, _, facts = await _run(ME, {"software_name": "Photoshop", "device_id": "LAP-0342"})
    assert diag["check_catalog_entry"] is None  # 404 = dữ liệu, không lỗi
    assert facts["in_catalog"] is False
    assert "license_paid" not in facts and "requires_local_admin" not in facts


@asyncio
async def test_s4_nv001_no_device_infers_lap0342() -> None:
    """s4: nv001 không nêu máy (đúng 1 máy) → suy slot `device_id=LAP-0342` + fact máy."""
    _, _, _, inferred, facts = await _run(ME, {"software_name": "Zoom"})
    assert inferred == {"device_id": "LAP-0342"}
    assert (facts["device_count"], facts["has_registered_device"]) == (1, True)
    assert (facts["device_registered"], facts["device_owner_is_requester"]) == (True, True)
    assert facts["in_catalog"] is True


@asyncio
async def test_s5_nv002_two_devices_not_inferred() -> None:
    """s5: nv002 không nêu máy (2 máy) → không suy; `device_count=2`; không fact máy cụ thể."""
    _, _, _, inferred, facts = await _run("nv002", {"software_name": "vscode"})
    assert "device_id" not in inferred
    assert (facts["device_count"], facts["has_registered_device"]) == (2, True)
    assert "device_registered" not in facts and "device_owner_is_requester" not in facts


@asyncio
async def test_s6_other_persons_device_owner_false() -> None:
    """s6: máy PC-0977 của nv002, người gửi nv001 → `device_owner_is_requester=False` (PC-0977 chưa đăng ký → registered False)."""
    _, _, _, inferred, facts = await _run(ME, {"software_name": "Zoom", "device_id": "PC-0977"})
    assert facts["device_owner_is_requester"] is False
    assert facts["device_registered"] is False
    assert inferred == {}


@asyncio
async def test_s6_unknown_device_404_false() -> None:
    """5.1.2 "như VPN (404 → false)": máy không tồn tại → device_registered False, device_owner_is_requester False."""
    _, _, _, _, facts = await _run(ME, {"software_name": "Zoom", "device_id": "LAP-9999"})
    assert (facts["device_registered"], facts["device_owner_is_requester"]) == (False, False)


@asyncio
async def test_s7_no_name_no_catalog_facts_but_device_facts() -> None:
    """s7: tên chưa có → không gọi catalog/license (đếm ở nơi nhận); vẫn gọi `check_device_registered`; không đặt `in_catalog`
    (TQ-2: chưa gọi ≠ 404)."""
    env, _, _, inferred, facts = await _run(ME, {})
    assert env.tools.calls["check_catalog_entry"] == 0 and env.tools.calls["check_license_available"] == 0
    assert env.vpn.calls["check_device_registered"] == 1
    assert "in_catalog" not in facts and "license_paid" not in facts and "requires_local_admin" not in facts
    assert inferred == {"device_id": "LAP-0342"} and facts["device_count"] == 1
