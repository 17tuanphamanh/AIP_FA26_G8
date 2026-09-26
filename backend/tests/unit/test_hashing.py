"""hash_action: JSON sắp khóa, UTF-8, SHA-256 — ổn định khi đổi thứ tự khóa [Chốt cổng 1]."""

import hashlib
from typing import Any

from app.core.hashing import hash_action
from app.domain.action import Action

ACTION: dict[str, Any] = {
    "type": "grant_permission",
    "target": "folder:finance/Q3",
    "requested_for": "nv001",
    "scope": "single_account",
    "privilege_level": "standard_user",
    "reversible": True,
    "reversibility": "full",
    "data_sensitivity": "high",
    "params": {"permission_level": "read", "duration_days": 30},
    "facts": {"resource_sensitivity": "high", "target_is_self": True},
}


def test_key_order_does_not_change_hash() -> None:
    reordered = {k: ACTION[k] for k in reversed(list(ACTION))}
    reordered["params"] = {"duration_days": 30, "permission_level": "read"}
    reordered["facts"] = {"target_is_self": True, "resource_sensitivity": "high"}
    assert hash_action(reordered) == hash_action(ACTION)


def test_model_and_equivalent_dict_hash_equal() -> None:
    assert hash_action(Action(**ACTION)) == hash_action(ACTION)


def test_model_field_order_does_not_matter() -> None:
    a = Action(**ACTION)
    b = Action(**{k: ACTION[k] for k in reversed(list(ACTION))})
    assert hash_action(a) == hash_action(b)


def test_any_value_change_changes_hash() -> None:
    base = hash_action(ACTION)
    assert hash_action({**ACTION, "target": "folder:finance/Q4"}) != base
    assert hash_action({**ACTION, "params": {**ACTION["params"], "duration_days": 31}}) != base
    assert hash_action({**ACTION, "facts": {**ACTION["facts"], "target_is_self": False}}) != base


def test_format_is_sorted_compact_utf8_sha256() -> None:
    # Chuỗi chuẩn viết tay: khóa sắp xếp, không khoảng trắng, giữ nguyên tiếng Việt (UTF-8).
    data = {"b": "Phòng Tài chính", "a": 1, "c": {"y": True, "x": None}}
    canonical = '{"a":1,"b":"Phòng Tài chính","c":{"x":null,"y":true}}'
    assert hash_action(data) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_hash_is_hex_sha256() -> None:
    h = hash_action(ACTION)
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
