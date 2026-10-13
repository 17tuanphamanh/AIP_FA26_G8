"""T20a — `build_action` 4 intent, `PARAMS_BY_ACTION`, `normalize_software_name`, `requested_for_of` (phase5 5.1.1 P6–P8,
bảng 5.1.3 + bất biến (a)–(d), 5.1.6 a1–a13; PLAN-T20a TQ-6, TQ-7, TQ-10).

Viết TỪ ĐẶC TẢ, trước code. Kỳ vọng `target`/`requested_for`/`params` chép từ bảng 5.1.3; thuộc tính tĩnh (scope, reversible…) chép
từ bảng 4.2 — không đọc lại từ hằng trong code. `PARAMS_BY_ACTION` kiểm ĐỘC LẬP với bảng 5.1.3 (bảng `BANG_5_1_3` dưới đây viết từ
đặc tả). `metadata` = `get_action_metadata().of(intent)` (như B11). Thiếu slot bắt buộc / intent lạ → `ValueError` (E9 ở B11).
"""

import re
from datetime import UTC, datetime
from typing import Any

import pytest
from app.domain.action import (
    PARAMS_BY_ACTION,
    Action,
    FactValue,
    build_action,
    normalize_software_name,
    requested_for_of,
)
from app.domain.context import RequesterContext
from app.settings import get_action_metadata, get_slots

FREE_TEXT = frozenset({"reason", "justification", "version", "error_code"})  # bất biến (d)
SOFTWARE_PARAM = re.compile(r"^[a-z0-9][a-z0-9.+#-]{0,63}$")  # P8

# Bảng 5.1.3 — action_type → {khoá params: (kiểu, bắt buộc)}. Chép từ đặc tả.
BANG_5_1_3: dict[str, dict[str, tuple[type, bool]]] = {
    "renew_vpn_cert": {"device_id": (str, True)},
    "reissue_vpn_access": {"device_id": (str, True)},
    "check_vpn_status": {"device_id": (str, True)},
    "reset_password": {"account_type": (str, True)},
    "unlock_account": {"account_type": (str, True)},
    "install_software": {"device_id": (str, True), "software_name": (str, True)},
    "view_permissions": {"resource_path": (str, False)},
    "grant_permission": {"resource_path": (str, True), "permission_level": (str, True), "duration_days": (int, True)},
    "extend_permission": {"resource_path": (str, True), "duration_days": (int, True)},
}

# Bảng 4.2 — (reversible, reversibility, data_sensitivity, scope, privilege_level).
META_4_2: dict[str, tuple[bool, str, str, str, str]] = {
    "reset_password": (True, "partial", "medium", "single_account", "standard_user"),
    "unlock_account": (True, "full", "low", "single_account", "standard_user"),
    "install_software": (True, "partial", "low", "single_device", "standard_user"),
    "view_permissions": (True, "full", "low", "single_account", "standard_user"),
    "grant_permission": (True, "full", "medium", "single_account", "standard_user"),
    "extend_permission": (True, "full", "medium", "single_account", "standard_user"),
}

INTENT_OF = {
    "renew_vpn_cert": "vpn", "reissue_vpn_access": "vpn", "check_vpn_status": "vpn",
    "reset_password": "account", "unlock_account": "account", "install_software": "software",
    "view_permissions": "access", "grant_permission": "access", "extend_permission": "access",
}  # fmt: skip


def _req(user_id: str = "nv001") -> RequesterContext:
    return RequesterContext(
        user_id=user_id, role="employee", department="Finance", manager_id="fin_head", employment_status="active",
        tenure_days=980, is_privileged_account=False, captured_at=datetime(2026, 9, 29, 3, 0, tzinfo=UTC),
    )  # fmt: skip


def _build(intent: str, slots: dict[str, str], facts: dict[str, FactValue] | None = None,
           requester: str = "nv001") -> Action:  # fmt: skip
    return build_action(intent, slots, dict(facts or {}), _req(requester), get_action_metadata().of(intent))


def _static(a: Action) -> tuple[bool, str, str, str, str]:
    return (a.reversible, a.reversibility, a.data_sensitivity, a.scope, a.privilege_level)


# ---- a1–a6: 6 hành động mới (bảng 5.1.3) ------------------------------------------------------------------------------------

# (id, intent, slots, requester, type, target, requested_for, params)
BANG_A = [
    pytest.param("account", {"action": "reset_password", "account_type": "ad"}, "nv001",
                 "reset_password", "user:nv001", "nv001", {"account_type": "ad"}, id="a1-reset_password"),
    pytest.param("account", {"action": "unlock_account", "account_type": "email"}, "nv007",
                 "unlock_account", "user:nv007", "nv007", {"account_type": "email"}, id="a2-unlock_account"),
    pytest.param("software", {"software_name": "Zoom", "device_id": "LAP-0342"}, "nv001",
                 "install_software", "device:LAP-0342", "nv001", {"device_id": "LAP-0342", "software_name": "zoom"},
                 id="a3-install_software-khong-slot-action"),
    pytest.param("software", {"action": "install_software", "software_name": "Zoom", "device_id": "LAP-0342"}, "nv001",
                 "install_software", "device:LAP-0342", "nv001", {"device_id": "LAP-0342", "software_name": "zoom"},
                 id="a3-install_software-co-slot-action"),
    pytest.param("access", {"action": "view_permissions"}, "nv001",
                 "view_permissions", "user:nv001", "nv001", {}, id="a4-view_permissions-khong-path"),
    pytest.param("access", {"action": "view_permissions", "resource_path": "finance/Q3"}, "nv001",
                 "view_permissions", "user:nv001", "nv001", {"resource_path": "finance/Q3"},
                 id="a4-view_permissions-co-path"),
    pytest.param("access", {"action": "grant_permission", "resource_path": "finance/public-reports",
                            "permission_level": "read", "duration": "30"}, "nv001",
                 "grant_permission", "folder:finance/public-reports", "nv001",
                 {"resource_path": "finance/public-reports", "permission_level": "read", "duration_days": 30},
                 id="a5-grant_permission"),
    pytest.param("access", {"action": "extend_permission", "resource_path": "finance/public-reports", "duration": "90"},
                 "nv001", "extend_permission", "folder:finance/public-reports", "nv001",
                 {"resource_path": "finance/public-reports", "duration_days": 90}, id="a6-extend_permission"),
    pytest.param("access", {"action": "extend_permission", "resource_path": "/finance/Q3/", "duration": "7"}, "nv002",
                 "extend_permission", "folder:finance/Q3", "nv002", {"resource_path": "finance/Q3", "duration_days": 7},
                 id="a6-extend-path-strip-slash-TQ7"),
]  # fmt: skip


@pytest.mark.parametrize(("intent", "slots", "requester", "kind", "target", "rf", "params"), BANG_A)
def test_a1_a6_bang_5_1_3(intent: str, slots: dict[str, str], requester: str, kind: str, target: str, rf: str,
                          params: dict[str, Any]) -> None:  # fmt: skip
    """a1–a6: đúng `type`, `target`, `requested_for`, `params` (đủ, không thêm khoá) theo bảng 5.1.3; thuộc tính tĩnh theo bảng
    4.2; `facts` chép nguyên từ đối số (không từ slot)."""
    facts: dict[str, FactValue] = {"target_user_status": "active"}
    a = _build(intent, slots, facts, requester)
    assert (a.type, a.target, a.requested_for) == (kind, target, rf)
    assert a.params == params
    assert {k: type(v) for k, v in a.params.items()} == {k: type(v) for k, v in params.items()}  # duration_days là int
    assert _static(a) == META_4_2[kind]
    assert a.facts == facts


# ---- a7: target_user -------------------------------------------------------------------------------------------------------


def test_a7_account_target_user_is_requested_for() -> None:
    """a7 (P6, M-T20a-7): account `target_user=nv005` → `requested_for=nv005`, `target="user:nv005"`."""
    a = _build("account", {"action": "reset_password", "account_type": "ad", "target_user": "nv005"})
    assert (a.requested_for, a.target, a.params) == ("nv005", "user:nv005", {"account_type": "ad"})


def test_a7_access_grant_target_user_is_requested_for() -> None:
    """a7: access grant `target_user=nv004` → `requested_for=nv004`, `target="folder:…"`."""
    a = _build("access", {"action": "grant_permission", "resource_path": "engineering/specs", "permission_level": "read",
                          "duration": "30", "target_user": "nv004"})  # fmt: skip
    assert (a.requested_for, a.target) == ("nv004", "folder:engineering/specs")
    assert "target_user" not in a.params


def test_a7_view_permissions_target_user() -> None:
    """Bảng 5.1.3: view_permissions `target = user:{rf}` — xem quyền của người khác → đích là người đó."""
    a = _build("access", {"action": "view_permissions", "target_user": "nv005"})
    assert (a.requested_for, a.target) == ("nv005", "user:nv005")


def test_requested_for_of_p6() -> None:
    """TQ-6 (P6): account/access = `target_user` nếu có, còn lại người gửi; software, vpn luôn người gửi."""
    assert requested_for_of("account", {"target_user": "nv005"}, "nv001") == "nv005"
    assert requested_for_of("access", {"target_user": "nv004"}, "nv001") == "nv004"
    assert requested_for_of("account", {}, "nv001") == "nv001"
    assert requested_for_of("access", {"resource_path": "finance/Q3"}, "nv001") == "nv001"
    assert requested_for_of("software", {"target_user": "nv005"}, "nv001") == "nv001"
    assert requested_for_of("vpn", {"target_user": "nv005"}, "nv001") == "nv001"


# ---- a8, a9, a10 ------------------------------------------------------------------------------------------------------------

FULL_SLOTS: dict[str, tuple[str, dict[str, str]]] = {
    "reset_password": ("account", {"action": "reset_password", "account_type": "ad", "reason": "quên mật khẩu"}),
    "unlock_account": ("account", {"action": "unlock_account", "account_type": "email", "reason": "bị khoá"}),
    "install_software": ("software", {"software_name": "Zoom", "device_id": "LAP-0342", "version": "6.2",
                                      "justification": "họp với khách hàng"}),
    "view_permissions": ("access", {"action": "view_permissions", "justification": "kiểm tra"}),
    "grant_permission": ("access", {"action": "grant_permission", "resource_path": "finance/public-reports",
                                    "permission_level": "read", "duration": "30", "justification": "báo cáo quý"}),
    "extend_permission": ("access", {"action": "extend_permission", "resource_path": "finance/public-reports",
                                     "duration": "30", "justification": "dự án kéo dài"}),
}  # fmt: skip


@pytest.mark.parametrize("kind", sorted(FULL_SLOTS))
def test_a8_free_text_slots_never_in_params(kind: str) -> None:
    """a8 (P7, M-T20a-8): slot chữ tự do `justification`, `reason`, `version` có mặt → không vào `params` (cả 6 hành động);
    chữ đó không xuất hiện ở đâu trong Action."""
    intent, slots = FULL_SLOTS[kind]
    a = _build(intent, slots)
    assert not (set(a.params) & FREE_TEXT)
    dumped = a.model_dump_json()
    for k in ("reason", "justification", "version"):
        if k in slots:
            assert slots[k] not in dumped, k


def test_a9_extend_never_carries_permission_level() -> None:
    """a9 (P7, M-T20a-9): extend có slot `permission_level=full` → `params` KHÔNG có `permission_level` (hợp đồng `ExtendIn`)."""
    a = _build("access", {"action": "extend_permission", "resource_path": "finance/public-reports", "duration": "30",
                          "permission_level": "full"})  # fmt: skip
    assert "permission_level" not in a.params
    assert a.params == {"resource_path": "finance/public-reports", "duration_days": 30}


def test_a10_software_name_normalized() -> None:
    """a10 (P8): "Adobe Acrobat Pro" → `params.software_name == "adobe-acrobat-pro"`."""
    a = _build("software", {"software_name": "Adobe Acrobat Pro", "device_id": "LAP-0342"})
    assert a.params["software_name"] == "adobe-acrobat-pro"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Zoom", "zoom"), ("  zoom ", "zoom"), ("Adobe Acrobat Pro", "adobe-acrobat-pro"),
     ("Adobe   Acrobat\tPro", "adobe-acrobat-pro"), ("7-Zip", "7-zip"), ("Notepad++", "notepad++"), ("C#", "c#"),
     ("MS.Project 2024", "ms.project-2024")],
)  # fmt: skip
def test_p8_normalize_software_name(raw: str, expected: str) -> None:
    """P8: `"-".join(s.strip().lower().split())` (đúng `software.normalize` của mock); kết quả khớp mẫu P8."""
    got = normalize_software_name(raw)
    assert got == expected and SOFTWARE_PARAM.fullmatch(got)


@pytest.mark.parametrize("raw", ["", "   ", "-zoom", "zoom/../x", "zoom;rm", "a" * 65, "Zoom (bản mới)"])
def test_p8_normalize_software_name_bad_raises(raw: str) -> None:
    """P8: kết quả không khớp `^[a-z0-9][a-z0-9.+#-]{0,63}$` → ValueError (không dấu cách, không ký tự lệnh)."""
    with pytest.raises(ValueError):
        normalize_software_name(raw)


# ---- a11: VPN không đổi ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["renew_vpn_cert", "reissue_vpn_access", "check_vpn_status"])
def test_a11_vpn_action_unchanged(kind: str) -> None:
    """a11: VPN — `Action` giống hệt trước T20a (so với bản dựng tay; metadata VPN: low, single_device, full)."""
    facts: dict[str, FactValue] = {"device_registered": True, "device_owner_is_requester": True, "cert_status": "expired"}
    a = _build("vpn", {"action": kind, "device_id": "LAP-0342", "reason": "đi công tác", "error_code": "809"}, facts)
    assert a == Action(
        type=kind, target="device:LAP-0342", requested_for="nv001", scope="single_device",
        privilege_level="standard_user", reversible=True, reversibility="full", data_sensitivity="low",
        params={"device_id": "LAP-0342"}, facts=facts,
    )  # fmt: skip


# ---- a12: ValueError ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intent", "slots"),
    [
        pytest.param("printer", {"action": "print_document"}, id="a12-intent-la"),
        pytest.param("account", {"action": "reset_password"}, id="a12-account-thieu-account_type"),
        pytest.param("account", {"account_type": "ad"}, id="a12-account-thieu-action"),
        pytest.param("software", {"software_name": "zoom"}, id="a12-software-thieu-device_id"),
        pytest.param("software", {"device_id": "LAP-0342"}, id="a12-software-thieu-software_name"),
        pytest.param("access", {}, id="a12-access-thieu-action"),
        pytest.param("access", {"action": "grant_permission", "resource_path": "finance/Q3", "permission_level": "read"},
                     id="a12-grant-thieu-duration"),
        pytest.param("access", {"action": "grant_permission", "resource_path": "finance/Q3", "duration": "30"},
                     id="a12-grant-thieu-permission_level"),
        pytest.param("access", {"action": "extend_permission", "duration": "30"}, id="a12-extend-thieu-resource_path"),
        pytest.param("access", {"action": "extend_permission", "resource_path": "finance/Q3"},
                     id="a12-extend-thieu-duration"),
        pytest.param("vpn", {"action": "renew_vpn_cert"}, id="a12-vpn-thieu-device_id"),
    ],
)
def test_a12_unknown_intent_or_missing_required_slot_raises(intent: str, slots: dict[str, str]) -> None:
    """a12 (P7, TQ-10): intent lạ / thiếu slot bắt buộc theo bảng 5.1.3 → ValueError (không có nhánh mặc định)."""
    with pytest.raises(ValueError):
        _build(intent, slots)


# ---- a13: bất biến (a)–(d), tham số hoá MỌI action_type của action_metadata.yaml --------------------------------------------

# Slot tối thiểu dựng được từng hành động (bảng 5.1.3) + slot chữ tự do của intent (để kiểm (d)). Thêm action_type mới vào
# `action_metadata.yaml` mà không thêm dòng ở đây → KeyError → đỏ (cùng ý "thiếu dòng PARAMS_BY_ACTION → đỏ").
SLOTS_A13: dict[str, dict[str, str]] = {
    "renew_vpn_cert": {"action": "renew_vpn_cert", "device_id": "LAP-0342", "reason": "x", "error_code": "809"},
    "reissue_vpn_access": {"action": "reissue_vpn_access", "device_id": "LAP-0342", "reason": "x"},
    "check_vpn_status": {"action": "check_vpn_status", "device_id": "LAP-0342"},
    **{k: v for k, (_, v) in FULL_SLOTS.items()},
}
DECLARED = sorted((intent, kind) for intent, metas in get_action_metadata().root.items() for kind in metas)


def test_a13_params_by_action_matches_bang_5_1_3() -> None:
    """a13 / P7: `PARAMS_BY_ACTION` đúng bảng 5.1.3 (kiểm độc lập — bảng chép từ đặc tả) và phủ mọi action_type đã khai báo."""
    got = {kind: {k: (p.type, p.required) for k, p in keys.items()} for kind, keys in PARAMS_BY_ACTION.items()}
    assert got == BANG_5_1_3
    assert {kind for _, kind in DECLARED} <= set(PARAMS_BY_ACTION)


@pytest.mark.parametrize(("intent", "kind"), DECLARED, ids=[f"a13-{k}" for _, k in DECLARED])
def test_a13_invariants(intent: str, kind: str) -> None:
    """a13 bất biến 5.1.3: (a) install_software luôn đích `device:`; (b) account + view_permissions `target == user:{rf}`;
    (c) grant/extend `target == folder:{params.resource_path}`; (d) `set(params) ⊆ PARAMS_BY_ACTION[type]`, đủ khoá bắt buộc,
    đúng kiểu chặt, không khoá chữ tự do."""
    assert INTENT_OF[kind] == intent
    assert kind in PARAMS_BY_ACTION, f"{kind}: thiếu dòng PARAMS_BY_ACTION"
    assert kind in get_slots().intents[intent].action_types
    a = _build(intent, SLOTS_A13[kind])
    assert a.type == kind
    contract = PARAMS_BY_ACTION[kind]
    if kind == "install_software":
        assert a.target.startswith("device:")  # (a) → vế chủ máy của build_ctx áp (R11 an toàn)
    if intent == "account" or kind == "view_permissions":
        assert a.target == f"user:{a.requested_for}"  # (b)
    if kind in ("grant_permission", "extend_permission"):
        assert a.target == f"folder:{a.params['resource_path']}"  # (c)
    assert set(a.params) <= set(contract)  # (d)
    assert {k for k, p in contract.items() if p.required} <= set(a.params)
    for k, v in a.params.items():
        assert type(v) is contract[k].type, (k, v)
    assert not (set(a.params) & FREE_TEXT)
