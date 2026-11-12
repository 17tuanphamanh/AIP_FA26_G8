"""T20a — slot theo hành động + chống LLM bịa đích + fact mới (phase5 5.1.1 P1, P4, P5; 4.2 `value_rules`; 5.1.6 p1, p5, p6, h1).

Viết TỪ ĐẶC TẢ, trước code. `config/slots.yaml` theo P4: access `required: [action]`, optional `[resource_path, permission_level,
duration, target_user, justification]`, `value_rules.target_user` như account, `required_by_action` cho grant/extend; software thêm
`action` vào optional; `duration` `^[1-9][0-9]{0,2}$` (duyệt DỪNG 1: `[0-9]`, không `\\d`); p7 `resource_path` chặn "."/"..".
P5: `TOKEN_IN_TEXT` ⊇ {device_id, error_code, target_user, resource_path}; `PHRASE_IN_TEXT` = {reason, software_name}.
"""

from pathlib import Path

import pytest
import yaml
from app.domain.facts import FACT_TYPES, FACT_VALUE_SETS, check_facts
from app.domain.slots import (
    MUST_APPEAR_IN_TEXT,
    PHRASE_IN_TEXT,
    TOKEN_IN_TEXT,
    IntentSlots,
    sanitize_slots,
)
from app.settings import load_slots
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[3]
SLOTS = load_slots(REPO / "config" / "slots.yaml")  # đọc thẳng file repo (không cache get_slots)


# ---- p1: schema IntentSlots.required_by_action ---------------------------------------------------------------------------


def _intent(**over: object) -> IntentSlots:
    base: dict[str, object] = {
        "required": ("action",), "optional": ("resource_path", "duration", "justification"),
        "action_types": ("view_permissions", "grant_permission", "extend_permission"),
    }  # fmt: skip
    return IntentSlots.model_validate({**base, **over})


def test_p1_valid_required_by_action_accepted() -> None:
    spec = _intent(required_by_action={"grant_permission": ("resource_path", "duration"), "extend_permission": ("duration",)})
    assert spec.required_by_action == {"grant_permission": ("resource_path", "duration"), "extend_permission": ("duration",)}


def test_p1_default_required_by_action_empty() -> None:
    assert _intent().required_by_action == {}


@pytest.mark.parametrize(
    "rba",
    [
        pytest.param({"delete_folder": ("resource_path",)}, id="p1-khoa-ngoai-action_types"),
        pytest.param({"grant_permission": ("permission_level",)}, id="p1-gia-tri-ngoai-optional-khong-khai-bao"),
        pytest.param({"grant_permission": ("action",)}, id="p1-gia-tri-la-slot-required-khong-thuoc-optional"),
        pytest.param({"grant_permission": ("resource_path", "device_registered")}, id="p1-gia-tri-ten-fact"),
    ],
)
def test_p1_bad_required_by_action_is_schema_error(rba: dict[str, tuple[str, ...]]) -> None:
    """p1 (P4): khoá ∉ `action_types` hoặc giá trị ⊄ `optional` → lỗi schema (ValidationError) → không khởi động."""
    with pytest.raises(ValidationError):
        _intent(required_by_action=rba)


def test_p1_bad_slots_yaml_refuses_to_load(tmp_path: Path) -> None:
    """p1 "không khởi động": `slots.yaml` có `required_by_action` sai → `load_slots` ném (ValidationError là ValueError)."""
    raw = yaml.safe_load((REPO / "config" / "slots.yaml").read_text(encoding="utf-8"))
    raw["intents"]["access"]["required_by_action"] = {"delete_folder": ["resource_path"]}
    bad = tmp_path / "slots.yaml"
    bad.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError):
        load_slots(bad)


# ---- P4: nội dung config/slots.yaml -----------------------------------------------------------------------------------------


def test_p4_access_slots_by_action() -> None:
    """P4: access `required: [action]`; optional đủ 5 slot; `required_by_action` grant/extend (view không cần gì thêm)."""
    acc = SLOTS.intents["access"]
    assert acc.required == ("action",)
    assert acc.optional == ("resource_path", "permission_level", "duration", "target_user", "justification")
    assert acc.required_by_action == {
        "grant_permission": ("resource_path", "permission_level", "duration"),
        "extend_permission": ("resource_path", "duration"),
    }  # fmt: skip
    assert "view_permissions" not in acc.required_by_action
    assert acc.value_rules["target_user"].pattern == SLOTS.intents["account"].value_rules["target_user"].pattern


def test_p4_software_accepts_action_slot_and_duration_rule() -> None:
    """P4: software thêm `action` vào optional (action_hint `install_software` không bị bỏ `unknown_key`); duration
    `^[1-9][0-9]{0,2}$`; account, vpn không đổi."""
    sw = SLOTS.intents["software"]
    assert "action" in sw.optional and sw.required == ("software_name", "device_id")
    # Duyệt DỪNG 1 (MẪU B mục 5): `[0-9]` thay `\d` — `\d` của Python khớp chữ số Unicode ("9٠" → int 90). Giữ ý ghim mẫu.
    assert SLOTS.intents["access"].value_rules["duration"].pattern == r"^[1-9][0-9]{0,2}$"
    assert (SLOTS.intents["account"].required, SLOTS.intents["account"].optional) == (
        ("account_type", "action"), ("reason", "target_user"))
    assert (SLOTS.intents["vpn"].required, SLOTS.intents["vpn"].optional) == (("device_id", "action"),
                                                                              ("reason", "error_code"))
    clean, dropped = sanitize_slots(sw, {"action": "install_software", "software_name": "Zoom"}, text="cài Zoom giúp em")
    assert clean == {"action": "install_software", "software_name": "Zoom"} and dropped == {}


# ---- p5: chống LLM bịa đích (P5) ---------------------------------------------------------------------------------------------


def test_p5_code_constants() -> None:
    """P5: hằng CODE — `TOKEN_IN_TEXT` ⊇ {device_id, error_code, target_user, resource_path}; `PHRASE_IN_TEXT` = {reason,
    software_name}; slot chuẩn hoá (account_type, permission_level, duration, action) KHÔNG phải có trong câu."""
    assert {"device_id", "error_code", "target_user", "resource_path"} <= TOKEN_IN_TEXT
    assert PHRASE_IN_TEXT == {"reason", "software_name"}
    assert not ({"account_type", "permission_level", "duration", "action"} & MUST_APPEAR_IN_TEXT)


@pytest.mark.parametrize(
    ("intent", "raw", "text", "dropped"),
    [
        pytest.param("access", {"target_user": "nv005"}, "cấp quyền đọc finance/Q3 cho đồng nghiệp",
                     {"target_user": "slot_not_in_text"}, id="p5-target_user-bia-access"),
        pytest.param("account", {"target_user": "nv001"}, "đặt lại mật khẩu cho bạn cùng phòng",
                     {"target_user": "slot_not_in_text"}, id="p5-target_user-bia-account"),
        pytest.param("access", {"resource_path": "finance/public-reports"}, "cho em xem thư mục báo cáo",
                     {"resource_path": "slot_not_in_text"}, id="p5-resource_path-bia"),
        pytest.param("access", {"resource_path": "finance/Q3"}, "quyền thư mục finance/Q34",
                     {"resource_path": "slot_not_in_text"}, id="p5-resource_path-bien-token"),
        pytest.param("software", {"software_name": "Zoom"}, "cài giúp em phần mềm họp trực tuyến",
                     {"software_name": "slot_not_in_text"}, id="p5-software_name-bia"),
    ],
)
def test_p5_target_slots_not_in_text_dropped(intent: str, raw: dict[str, str], text: str, dropped: dict[str, str]) -> None:
    """p5: `target_user`/`resource_path` không có trong câu → `slot_not_in_text`; `software_name` không có (casefold) → bỏ."""
    clean, got = sanitize_slots(SLOTS.intents[intent], raw, text=text)
    assert clean == {} and got == dropped


@pytest.mark.parametrize(
    ("intent", "raw", "text"),
    [
        pytest.param("access", {"target_user": "nv004", "resource_path": "engineering/specs"},
                     "Cấp quyền đọc engineering/specs cho NV004 trong 30 ngày", id="p5-token-casefold-giu"),
        pytest.param("software", {"software_name": "zoom"}, "Cài ZOOM giúp em", id="p5-software_name-casefold-giu"),
        pytest.param("software", {"software_name": "Adobe Acrobat Pro"}, "cài adobe   acrobat PRO cho máy LAP-0342",
                     id="p5-software_name-gop-khoang-trang-giu"),
        pytest.param("access", {"permission_level": "read"}, "cho mình quyền đọc thư mục đó", id="p5-permission_level-read-giu"),
        pytest.param("access", {"duration": "14"}, "gia hạn thêm 2 tuần", id="p5-duration-chuan-hoa-giu"),
        pytest.param("account", {"account_type": "ad"}, "không đăng nhập được máy tính", id="p5-account_type-chuan-hoa-giu"),
    ],
)
def test_p5_slots_kept(intent: str, raw: dict[str, str], text: str) -> None:
    """p5: slot đích có trong câu (token biên + casefold; phrase casefold + gộp khoảng trắng) → giữ; slot chuẩn hoá
    (`permission_level=read` khi câu viết "quyền đọc", `duration`, `account_type`) → GIỮ dù không có nguyên chữ."""
    clean, dropped = sanitize_slots(SLOTS.intents[intent], raw, text=text)
    assert clean == raw and dropped == {}


# ---- p6: duration -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "00", "030", "1000", "-1", "3.5", "ba mươi"])
def test_p6_duration_bad_value(value: str) -> None:
    """p6 (P4): `duration="0"` (và số 0 đầu / > 3 chữ số / không phải số) → `bad_value` (mẫu `^[1-9][0-9]{0,2}$`)."""
    clean, dropped = sanitize_slots(SLOTS.intents["access"], {"duration": value}, text=f"gia hạn {value} ngày")
    assert clean == {} and dropped == {"duration": "bad_value"}


@pytest.mark.parametrize("value", ["1", "30", "90", "999"])
def test_p6_duration_ok(value: str) -> None:
    clean, _ = sanitize_slots(SLOTS.intents["access"], {"duration": value}, text=f"gia hạn {value} ngày")  # V6: cần dấu vết
    assert clean == {"duration": value}


@pytest.mark.parametrize("value", ["9\u0660", "\u0663\u0660", "\uff13\uff10", "3\u0966"])
def test_p6_duration_unicode_digits_bad_value(value: str) -> None:
    """Duyệt DỪNG 1 (gia cố security-reviewer): chữ số Unicode (Ả Rập, toàn khổ, Devanagari) → `bad_value` — `int("9٠") == 90`
    nên `\\d` sẽ cho qua một số ngày người dùng không thấy được."""
    assert int(value) > 0  # chính là ca nguy hiểm: Python đổi được sang số
    clean, dropped = sanitize_slots(SLOTS.intents["access"], {"duration": value}, text=f"gia hạn {value} ngày")
    assert clean == {} and dropped == {"duration": "bad_value"}


# ---- p7: resource_path chặn đoạn "." / ".." (duyệt DỪNG 1) -----------------------------------------------------------------------


@pytest.mark.parametrize("value", ["finance/..", "a/./b", "finance/../hr", "finance/.", "..", "./finance", "a/b/.."])
def test_p7_resource_path_dot_segments_bad_value(value: str) -> None:
    """p7: đoạn đường dẫn "." hoặc ".." → `bad_value` (không bao giờ tới tool/`params.resource_path`)."""
    clean, dropped = sanitize_slots(SLOTS.intents["access"], {"resource_path": value}, text=f"quyền thư mục {value}")
    assert clean == {} and dropped == {"resource_path": "bad_value"}


@pytest.mark.parametrize("value", ["finance/Q3", "finance/public-reports", "engineering/specs", "a/b.c", "a/..b",
                                   "finance/Q3/2026.v1"])  # fmt: skip
def test_p7_resource_path_ok(value: str) -> None:
    """p7: đường dẫn hợp lệ vẫn qua — "finance/Q3" (seed) và tên có dấu chấm không phải đoạn "."/".."."""
    clean, dropped = sanitize_slots(SLOTS.intents["access"], {"resource_path": value}, text=f"quyền thư mục {value}")
    assert clean == {"resource_path": value} and dropped == {}


# ---- h1 (phần fact mới — P1) ----------------------------------------------------------------------------------------------------


def test_h1_existing_permission_level_fact() -> None:
    """P1: `existing_permission_level` str ∈ {read, write, full}; ngoài tập / sai kiểu → FactKeyViolation."""
    assert FACT_TYPES["existing_permission_level"] is str
    assert FACT_VALUE_SETS["existing_permission_level"] == {"read", "write", "full"}
    for level in ("read", "write", "full"):
        check_facts({"existing_permission_level": level})
    with pytest.raises(AssertionError):  # FactKeyViolation là AssertionError
        check_facts({"existing_permission_level": "admin"})
