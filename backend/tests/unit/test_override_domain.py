"""Ghi đè (TC23) — phần THUẦN của `app.domain.override` + `MemoryAudit.record_new` (bản giả). Phase 4 chặng 4d DỪNG 1, viết TỪ
ĐẶC TẢ trước thân code: phase4 mục 7.1 P3, P4; PLAN-4d mục 2.1 (hợp đồng), mục 3 (o6, o7, o8), TQ-3, TQ-4.

- o6: `original_decision(DecisionTrail)` — `risk_decided` mới nhất → `detail.route` (AUTO→AUTO, HITL→HITL, ESCALATE_L2→L2, route lạ →
  L2); thiếu route → cột `policy_decision` (allow→AUTO, approval_required→HITL, khác → L2); không `risk_decided` mà có B10
  `deflected_info_only` → ANSWER; còn lại → L2.
- o7: `override_key(t, u)` = `sha256("override:" + t + ":" + u)` hex — tính ĐỘC LẬP bằng `hashlib` trong test.
- `OverrideRecord.audit_row()`: ĐÚNG 12 khoá của hợp đồng 2.1 (không `turn_id`, `loop_seq` — TQ-4).
- o8 (bản giả): `MemoryAudit.record_new` — lần 1 True, lần 2 False, đúng 1 dòng; thiếu `idempotency_key` → `ValueError`.
"""

import dataclasses
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest
from app.domain.override import (
    OVERRIDE_EVENT,
    OVERRIDE_STEP,
    Decision,
    DecisionTrail,
    OverrideReason,
    OverrideRecord,
    original_decision,
    override_key,
)
from tests.fakes.graph import MemoryAudit

T0 = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
ROW_KEYS = frozenset({
    "ticket_id", "created_at", "step", "event", "from_status", "to_status", "original_decision", "override_decision",
    "overrider_id", "note", "detail", "idempotency_key",
})  # fmt: skip


def _sha(ticket_id: str, overrider_id: str) -> str:
    """Công thức hợp đồng 2.1, tính độc lập (không gọi code app)."""
    return hashlib.sha256(("override:" + ticket_id + ":" + overrider_id).encode()).hexdigest()


def _rec(**over: Any) -> OverrideRecord:
    base: dict[str, Any] = {
        "ticket_id": "tk-o", "overrider_id": "l1_02", "original_decision": "HITL", "override_decision": "L2",
        "reason_code": "policy_gap", "note": "đã che [BÍ_MẬT_ĐÃ_ẨN]", "created_at": T0,
    }  # fmt: skip
    base.update(over)
    return OverrideRecord(**base)


# ---- kiểu + hằng (hợp đồng 2.1) ------------------------------------------------------------------------------------------------


def test_o6_decision_and_reason_literals_from_contract() -> None:
    """P2: `override_decision ∈ {AUTO, HITL, L2, ANSWER}`; `reason_code` ∈ 6 mã cố định."""
    assert set(get_args(Decision.__value__)) == {"AUTO", "HITL", "L2", "ANSWER"}
    assert set(get_args(OverrideReason.__value__)) == {
        "too_risky_for_auto", "approval_unnecessary", "should_not_escalate", "wrong_answer", "policy_gap", "other",
    }  # fmt: skip


def test_p4_override_step_and_event_constants() -> None:
    assert (OVERRIDE_STEP, OVERRIDE_EVENT) == ("OVERRIDE", "override_recorded")


# ---- o6: original_decision ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trail", "expected"),
    [
        # risk_decided có detail.route (P3, TQ-3)
        pytest.param(DecisionTrail("AUTO", "allow", True, False), "AUTO", id="route-AUTO"),
        pytest.param(DecisionTrail("HITL", "approval_required", True, False), "HITL", id="route-HITL"),
        pytest.param(DecisionTrail("ESCALATE_L2", "deny", True, False), "L2", id="route-ESCALATE_L2-thanh-L2"),
        # route thắng cột policy_decision khi có route
        pytest.param(DecisionTrail("AUTO", "approval_required", True, False), "AUTO", id="route-thang-policy-AUTO"),
        pytest.param(DecisionTrail("HITL", "allow", True, False), "HITL", id="route-thang-policy-HITL"),
        # route lạ → L2 (TQ-3), kể cả cột policy_decision là allow
        pytest.param(DecisionTrail("SOMETHING", "allow", True, False), "L2", id="route-la-L2"),
        # thiếu detail.route (node giả B12 — A9) → cột policy_decision
        pytest.param(DecisionTrail(None, "allow", True, False), "AUTO", id="khong-route-allow"),
        pytest.param(DecisionTrail(None, "approval_required", True, False), "HITL", id="khong-route-approval_required"),
        pytest.param(DecisionTrail(None, "deny", True, False), "L2", id="khong-route-deny"),
        pytest.param(DecisionTrail(None, None, True, False), "L2", id="khong-route-khong-policy"),
        # có risk_decided thì B10 không quyết định
        pytest.param(DecisionTrail("HITL", "approval_required", True, True), "HITL", id="risk-thang-B10"),
        # không có risk_decided
        pytest.param(DecisionTrail(None, None, False, True), "ANSWER", id="chi-B10-ANSWER"),
        pytest.param(DecisionTrail(None, None, False, False), "L2", id="khong-gi-L2"),
    ],
)
def test_o6_original_decision_table(trail: DecisionTrail, expected: str) -> None:
    """o6 (P3 + TQ-3): bảng `original_decision` của hợp đồng 2.1."""
    assert original_decision(trail) == expected


def test_o6_decision_trail_is_frozen_with_contract_fields() -> None:
    trail = DecisionTrail(risk_route="AUTO", risk_policy_decision="allow", has_risk_decided=True, deflected=False)
    assert [f.name for f in dataclasses.fields(trail)] == ["risk_route", "risk_policy_decision", "has_risk_decided", "deflected"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        trail.risk_route = "HITL"  # type: ignore[misc]


# ---- o7: override_key ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ticket_id", "overrider_id"),
    [("tk-1", "l1_02"), ("0b7c6f0e-3f1a-4a7e-9c55-1d2e3f4a5b6c", "it_mgr01"), ("tk-ư", "l1_01")],
)
def test_o7_override_key_is_sha256_of_contract_string(ticket_id: str, overrider_id: str) -> None:
    """o7 (P4): khoá idempotent = sha256("override:" + ticket_id + ":" + overrider_id), hex thường 64 ký tự."""
    key = override_key(ticket_id, overrider_id)
    assert key == _sha(ticket_id, overrider_id)
    assert len(key) == 64 and key == key.lower() and int(key, 16) >= 0


def test_o7_override_key_per_ticket_and_person() -> None:
    """Hai người khác nhau cùng ticket → 2 khoá (2 dòng); cùng người, ticket khác → khoá khác."""
    assert override_key("tk-1", "l1_01") != override_key("tk-1", "l1_02")
    assert override_key("tk-1", "l1_02") != override_key("tk-2", "l1_02")


# ---- OverrideRecord.audit_row -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("note", ["lý do: [BÍ_MẬT_ĐÃ_ẨN]", None], ids=["note-da-che", "note-None"])
def test_p4_audit_row_exact_keys_and_values(note: str | None) -> None:
    """Hợp đồng 2.1: dòng audit có ĐÚNG các khoá; `from/to_status` None; `detail={"reason_code": …}`; `note` giữ nguyên (đã che
    hoặc None); `idempotency_key` theo công thức (tính độc lập)."""
    row = _rec(note=note).audit_row()
    assert set(row) == ROW_KEYS, sorted(set(row) ^ ROW_KEYS)
    assert row == {
        "ticket_id": "tk-o", "created_at": T0, "step": "OVERRIDE", "event": "override_recorded", "from_status": None,
        "to_status": None, "original_decision": "HITL", "override_decision": "L2", "overrider_id": "l1_02", "note": note,
        "detail": {"reason_code": "policy_gap"}, "idempotency_key": _sha("tk-o", "l1_02"),
    }  # fmt: skip


def test_p4_audit_row_key_ignores_time_and_decision() -> None:
    """M-4d-5: khoá chỉ theo (ticket, người) — lần ghi đè thứ hai cùng người (giờ khác, quyết định khác) ra CÙNG khoá → 409."""
    first = _rec().audit_row()
    second = _rec(created_at=T0 + timedelta(minutes=5), override_decision="AUTO", reason_code="other",
                  note="đổi ý").audit_row()  # fmt: skip
    assert first["idempotency_key"] == second["idempotency_key"] == _sha("tk-o", "l1_02")
    other = _rec(overrider_id="it_mgr01").audit_row()
    assert other["idempotency_key"] == _sha("tk-o", "it_mgr01") != first["idempotency_key"]


def test_override_record_is_frozen() -> None:
    rec = _rec()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.note = "khác"  # type: ignore[misc]


# ---- o8: MemoryAudit.record_new (bản giả) -------------------------------------------------------------------------------------


def _row(key: str | None = "k" * 64, **over: Any) -> dict[str, Any]:
    """Dòng có đúng 12 khoá hợp đồng — dựng tay (không qua `audit_row`) để o8 chỉ kiểm bản giả."""
    row: dict[str, Any] = {
        "ticket_id": "tk-o8", "created_at": T0, "step": "OVERRIDE", "event": "override_recorded", "from_status": None,
        "to_status": None, "original_decision": "HITL", "override_decision": "L2", "overrider_id": "l1_02", "note": None,
        "detail": {"reason_code": "policy_gap"}, "idempotency_key": key,
    }  # fmt: skip
    row.update(over)
    if key is None:
        del row["idempotency_key"]
    return row


@pytest.mark.asyncio
async def test_o8_memory_record_new_true_then_false_one_row() -> None:
    audit = MemoryAudit()
    assert await audit.record_new(_row()) is True
    assert await audit.record_new(_row(override_decision="AUTO", created_at=T0 + timedelta(minutes=1))) is False
    assert len(audit.rows) == 1 and audit.rows[0]["override_decision"] == "L2"
    assert await audit.record_new(_row(key="m" * 64, overrider_id="l1_01")) is True
    assert len(audit.rows) == 2


@pytest.mark.asyncio
async def test_o8_memory_record_new_without_key_value_error() -> None:
    audit = MemoryAudit()
    with pytest.raises(ValueError):
        await audit.record_new(_row(key=None))
    assert audit.rows == []


@pytest.mark.asyncio
async def test_p4_audit_row_accepted_by_memory_audit() -> None:
    """Dòng do `audit_row()` dựng đi qua `check_audit_row` của bản giả (cùng hàm kiểm với writer thật) và ghi được đúng 1 lần."""
    audit = MemoryAudit()
    assert await audit.record_new(_rec().audit_row()) is True
    assert await audit.record_new(_rec(created_at=T0 + timedelta(minutes=2)).audit_row()) is False
    assert len(audit.rows) == 1
