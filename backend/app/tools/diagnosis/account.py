"""Chẩn đoán account (phase5 5.1.2, T20a P3) — bộ lời gọi 3 tool đọc + `infer_account` (hàm thuần).

`rf` = người BỊ TÁC ĐỘNG (`requested_for_of`: `slots.target_user` nếu có, không thì người gửi — P6); `account_type` = slot, chưa có →
`"ad"` để tra (TQ-8). Slot chỉ là KHOÁ TRA CỨU — giá trị fact luôn từ đầu ra tool (test AST `test_facts_ast.py`). Mọi fact `target_*`
nói về `rf`.

`diag` (TQ-2): `ToolResult.data` — model đã validate; `None` = 404 (user lạ, hoặc user không có tài khoản `account_type` — mock) hoặc
không gọi. 404 → KHÔNG đặt fact của dòng đó (không bao giờ đặt giá trị "an toàn" giả).

- `check_account_status` → `target_user_status`, `target_is_service_account`, `target_disable_reason` (khác null),
  `target_account_locked`, `target_lock_reason` (chỉ khi khoá: bad_password/admin/inactivity giữ, giá trị khác → `"other"`, null → không
  đặt — TQ-9).
- `check_privilege_level` → `target_account_privilege`.
- `check_lockout_history` → chỉ `diagnostics`.

Không tự suy `action` (khác VPN): "không đăng nhập được" có thể là đặt lại hay mở khoá — để B11 hỏi.
"""

from collections.abc import Mapping
from typing import Any

from app.domain.action import requested_for_of
from app.domain.facts import FACT_KEYS, FACT_VALUE_SETS
from app.tools.models import AccountStatus, Privilege

TOOLS = ("check_account_status", "check_lockout_history", "check_privilege_level")  # = tools.specs.TOOL_MAP["account"]
LOCK_REASONS = FACT_VALUE_SETS["target_lock_reason"] - {"other"}  # 3 giá trị của mock `lock_reason`


def calls(requester_id: str, slots: Mapping[str, str]) -> list[tuple[str, dict[str, str]]]:
    """B6: cả 3 tool tra `rf` (luôn đủ tham số — `account_type` mặc định `"ad"`)."""
    rf = requested_for_of("account", slots, requester_id)
    account_type = slots.get("account_type", "ad")
    return [
        ("check_account_status", {"user_id": rf, "account_type": account_type}),
        ("check_lockout_history", {"user_id": rf}),
        ("check_privilege_level", {"user_id": rf, "account_type": account_type}),
    ]


def target_calls(requester_id: str, slots: Mapping[str, str]) -> list[tuple[str, dict[str, str]]]:
    """B11: cùng bộ lời gọi trên slot cuối (`account_type`, `target_user` có thể vừa được hỏi)."""
    return calls(requester_id, slots)


def infer_account(
    diag: Mapping[str, Any], *, requester_id: str, slots: Mapping[str, str]
) -> tuple[dict[str, str], dict[str, str | int | bool]]:
    status = diag["check_account_status"] if isinstance(diag["check_account_status"], AccountStatus) else None
    privilege = diag["check_privilege_level"] if isinstance(diag["check_privilege_level"], Privilege) else None
    facts: dict[str, str | int | bool] = {}
    if status is not None:
        facts["target_user_status"] = status.employment_status
        facts["target_is_service_account"] = status.is_service_account
        if status.disable_reason is not None:
            facts["target_disable_reason"] = status.disable_reason
        facts["target_account_locked"] = status.account.locked
        lock_reason = status.account.lock_reason
        if status.account.locked and lock_reason is not None:
            facts["target_lock_reason"] = lock_reason if lock_reason in LOCK_REASONS else "other"
    if privilege is not None:
        facts["target_account_privilege"] = privilege.level
    assert set(facts) <= FACT_KEYS  # hợp đồng nội bộ; build_action kiểm lại bằng FactKeyViolation
    return {}, facts


infer = infer_account  # giao diện chung cho B6/B11 (`DIAGNOSERS`)
