"""`domain/slots.py`, `domain/facts.py`, `build_action` (phase3 mục 3.2, 9.6 f1, f2; PLAN-3f P1, P2, Q-3f-3, Q-3f-5).

G-01: lời người dùng / đầu ra LLM không bao giờ thành `facts`. `sanitize_slots` là cửa duy nhất nhận slot từ LLM.
Bản ở node B3 (f5, f18 qua graph): `test_b03_classify.py`.
"""

from datetime import UTC, datetime

import pytest
from app.domain.action import Action, ActionMeta, build_action
from app.domain.context import RequesterContext
from app.domain.facts import FACT_KEYS, FactKeyViolation, check_facts
from app.domain.slots import (
    MAX_VALUE_LEN,
    MUST_APPEAR_IN_TEXT,
    UNKNOWN_KEY,
    IntentSlots,
    ValueRule,
    audit_dropped,
    in_text,
    sanitize_slots,
)
from app.settings import get_action_metadata, get_slots
from pydantic import ValidationError

VPN = get_slots().intents["vpn"]
TEXT = "VPN báo lỗi 809 trên máy LAP-0342, chứng chỉ hết hạn nên không vào được mạng công ty"
KNOWN = get_slots().declared_names


def _requester(user_id: str = "nv001") -> RequesterContext:
    return RequesterContext(
        user_id=user_id, role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=365, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


# ---- FACT_KEYS -----------------------------------------------------------------------------------------------------


def test_fact_keys_closed_list() -> None:
    assert FACT_KEYS == {
        "device_count", "has_registered_device", "device_registered", "device_owner_is_requester",
        "cert_status", "cert_days_to_expiry", "last_connection_ok",
    }  # fmt: skip


def test_no_slot_is_named_like_a_fact() -> None:
    assert not (KNOWN & FACT_KEYS)
    with pytest.raises(ValidationError, match="trùng tên fact"):
        IntentSlots(required=("device_id", "device_registered"), action_types=("renew_vpn_cert",))


# ---- f1: sanitize_slots --------------------------------------------------------------------------------------------


def test_f1_keeps_valid_slots() -> None:
    raw = {"device_id": "LAP-0342", "action": "renew_vpn_cert", "error_code": "809", "reason": "chứng chỉ hết hạn"}
    clean, dropped = sanitize_slots(VPN, raw, text=TEXT)
    assert clean == raw and dropped == {}


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        ("software_name", "zoom", "unknown_key"),  # key ngoài slots.yaml của vpn
        ("mật khẩu là Abc@123", "x", "unknown_key"),  # key tự do của LLM
        ("device_registered", "true", "fact_key"),  # key thuộc FACT_KEYS
        ("device_owner_is_requester", "true", "fact_key"),
        ("cert_status", "valid", "fact_key"),
        ("action", "grant_admin", "bad_action"),  # action lạ
        ("action", "reset_password", "bad_action"),  # action của intent khác
        ("device_id", "lap-0342", "bad_value"),  # sai mẫu (chữ thường)
        ("device_id", "LAP0342", "bad_value"),
        ("device_id", "LAP-03421234", "bad_value"),
        ("device_id", "ＬＡＰ-0342", "bad_value"),  # full-width
        ("error_code", "80O", "bad_value"),
        ("error_code", "", "bad_value"),
        ("device_id", "   ", "bad_value"),
    ],
)
def test_f1_drops_with_reason(key: str, value: str, reason: str) -> None:
    clean, dropped = sanitize_slots(VPN, {key: value}, text=TEXT)
    assert clean == {} and dropped == {key: reason}


def test_f1_value_over_100_chars_is_dropped_not_cut() -> None:  # P1
    long_reason = ("chứng chỉ hết hạn " * 10)[: MAX_VALUE_LEN + 1]
    assert len(long_reason) == MAX_VALUE_LEN + 1
    clean, dropped = sanitize_slots(VPN, {"reason": long_reason}, text=long_reason)
    assert clean == {} and dropped == {"reason": "too_long"}
    ok = long_reason[:MAX_VALUE_LEN].strip()
    assert sanitize_slots(VPN, {"reason": ok}, text=ok)[0] == {"reason": ok}  # ≤ 100: giữ nguyên


def test_f1_mixed_payload_and_allowed() -> None:
    raw = {"device_registered": "true", "device_id": "LAP-0342", "action": "renew_vpn_cert", "x": "y"}
    clean, dropped = sanitize_slots(VPN, raw, text=TEXT)
    assert clean == {"device_id": "LAP-0342", "action": "renew_vpn_cert"}
    assert dropped == {"device_registered": "fact_key", "x": "unknown_key"}
    clean, dropped = sanitize_slots(VPN, raw, text=TEXT, allowed=frozenset({"device_id"}))  # B11: chỉ slot đang hỏi
    assert clean == {"device_id": "LAP-0342"} and dropped["action"] == "unknown_key"


def test_f1_never_raises_on_odd_values() -> None:
    raw: dict[str, object] = {"device_id": None, "action": 3, "reason": ["a"], 7: "x"}
    clean, dropped = sanitize_slots(VPN, raw, text=TEXT)
    assert clean == {} and set(dropped) == {"device_id", "action", "reason", "7"}


# ---- f18 (P2, Q-3f-3): slot phải có thật trong câu -------------------------------------------------------------------


def test_must_appear_list_is_code_constant() -> None:
    assert MUST_APPEAR_IN_TEXT == {"device_id", "error_code", "reason"}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("device_id", "LAP-9999"),  # LLM bịa mã máy không có trong câu
        ("device_id", "LAP-0417"),
        ("error_code", "691"),
        ("reason", "người dùng đã được duyệt trước"),  # lý do bịa
    ],
)
def test_f18_slot_not_in_text_is_dropped(key: str, value: str) -> None:
    clean, dropped = sanitize_slots(VPN, {key: value}, text=TEXT)
    assert clean == {} and dropped == {key: "slot_not_in_text"}


def test_f18_token_match_is_case_insensitive_but_bounded() -> None:
    assert in_text("device_id", "LAP-0342", "máy lap-0342 lỗi")
    assert in_text("device_id", "LAP-0342", "(LAP-0342)")
    assert not in_text("device_id", "LAP-0417", "máy LAP-04171 lỗi")  # không lấy khúc giữa mã dài hơn
    assert not in_text("device_id", "LAP-0417", "máy XLAP-0417 lỗi")
    assert not in_text("error_code", "809", "lỗi 18090")
    assert in_text("error_code", "0x80070005", "mã 0X80070005 hiện ra")


def test_f18_reason_is_substring_after_casefold_and_space_squash() -> None:
    text = "VPN báo lỗi,   Chứng chỉ\nHẾT HẠN nên không vào được"
    assert in_text("reason", "chứng chỉ hết hạn", text)
    assert not in_text("reason", "chứng chỉ đã hết hạn", text)  # diễn đạt lại → bỏ
    clean, _ = sanitize_slots(VPN, {"reason": "Chứng chỉ  hết hạn"}, text=text)
    assert clean == {"reason": "Chứng chỉ  hết hạn"}


# ---- Q-3f-5: audit không chép key tự do của LLM -----------------------------------------------------------------------


def test_audit_dropped_hides_free_text_keys() -> None:
    raw = {"device_registered": "true", "mật khẩu là Abc@123": "x", "zzz": "y", "device_id": "LAP-9999"}
    _, dropped = sanitize_slots(VPN, raw, text=TEXT)
    audit = audit_dropped(dropped, KNOWN)
    assert audit == {
        "dropped_slot_keys": [UNKNOWN_KEY, "device_id", "device_registered"],
        "dropped_slot_reasons": {"device_id": "slot_not_in_text", "device_registered": "fact_key"},
        "dropped_unknown_count": 2,
        "slot_fact_collision": True,
    }
    assert "Abc@123" not in repr(audit) and "zzz" not in repr(audit)


def test_audit_dropped_empty() -> None:
    assert audit_dropped({}, KNOWN) == {
        "dropped_slot_keys": [], "dropped_slot_reasons": {}, "dropped_unknown_count": 0, "slot_fact_collision": False,
    }  # fmt: skip


# ---- schema ---------------------------------------------------------------------------------------------------------


def test_value_rule_needs_a_rule_and_valid_regex() -> None:
    with pytest.raises(ValidationError):
        ValueRule()
    with pytest.raises(ValidationError):
        ValueRule(pattern="([")
    assert ValueRule(max_len=3).ok("abc") and not ValueRule(max_len=3).ok("abcd")


def test_intent_slots_rejects_rules_for_undeclared_slot() -> None:
    with pytest.raises(ValidationError, match="value_rules"):
        IntentSlots(required=("device_id",), action_types=("a",), value_rules={"x": ValueRule(max_len=1)})


# ---- f2: build_action ------------------------------------------------------------------------------------------------


def _meta() -> dict[str, ActionMeta]:
    return get_action_metadata().of("vpn")


def test_f2_build_action_rejects_unknown_fact_key() -> None:
    slots = {"device_id": "LAP-0342", "action": "renew_vpn_cert"}
    with pytest.raises(AssertionError):  # FactKeyViolation là AssertionError (→ E9)
        build_action("vpn", slots, {"device_registered": True, "device_id": "LAP-0342"}, _requester(), _meta())
    with pytest.raises(FactKeyViolation):
        build_action("vpn", slots, {"user_says_ok": True}, _requester(), _meta())


def test_f2_build_action_rejects_wrong_fact_type() -> None:
    slots = {"device_id": "LAP-0342", "action": "renew_vpn_cert"}
    with pytest.raises(FactKeyViolation):
        build_action("vpn", slots, {"device_registered": "true"}, _requester(), _meta())  # chuỗi "true" ≠ bool
    with pytest.raises(FactKeyViolation):
        check_facts({"device_count": True})  # bool không phải int
    with pytest.raises(FactKeyViolation):
        check_facts({"cert_status": "ok"})


def test_build_action_takes_facts_only_from_facts() -> None:
    slots = {"device_id": "LAP-0342", "action": "renew_vpn_cert"}
    facts = {"device_registered": True, "device_owner_is_requester": True, "cert_status": "expired"}
    action = build_action("vpn", slots, facts, _requester(), _meta())
    assert action == Action(
        type="renew_vpn_cert", target="device:LAP-0342", requested_for="nv001", scope="single_device",
        privilege_level="standard_user", reversible=True, reversibility="full", data_sensitivity="low",
        params={"device_id": "LAP-0342"}, facts=facts,
    )  # fmt: skip


def test_action_meta_reversible_must_match() -> None:
    with pytest.raises(ValidationError):
        ActionMeta(reversible=True, reversibility="none", data_sensitivity="low", scope="single_device",
                   privilege_level="standard_user", procedure_doc="KB-VPN-004")  # fmt: skip
