"""Ghi đè quyết định (Phase 4 chặng 4d — phase4 7.1 P1–P4, TC23; PLAN-4d mục 2.1). THUẦN: không I/O.

Người có `decision:override` ghi lại "đáng lẽ quyết khác" cho một ticket ĐÃ kết thúc — dữ liệu cho RQ (độ đúng của quyết định
escalate) và M9 `override_count`. Ghi đè KHÔNG đổi kết quả ticket: một dòng `audit_logs` `step="OVERRIDE"`, không đụng `tickets`,
checkpoint, lượt, executor.

- `original_decision` do SERVER suy từ audit (P3, PLAN-4d TQ-3): dòng `B13/B14 risk_decided` mới nhất → `detail.route`
  (`AUTO`/`HITL`/`ESCALATE_L2` → `L2`); dòng đó thiếu `detail.route` (node giả gate2) → cột `policy_decision`; không có
  `risk_decided` mà có `B10 deflected_info_only` → `ANSWER`; còn lại → `L2`.
- `override_key` = sha256("override:" + ticket_id + ":" + overrider_id) — mỗi người ghi đè một ticket tối đa MỘT lần (P4).
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

type Decision = Literal["AUTO", "HITL", "L2", "ANSWER"]
type OverrideReason = Literal[
    "too_risky_for_auto", "approval_unnecessary", "should_not_escalate", "wrong_answer", "policy_gap", "other",
]  # fmt: skip

OVERRIDE_STEP: Final = "OVERRIDE"
OVERRIDE_EVENT: Final = "override_recorded"
# `RiskDecision.route` (b12_assess `_ROUTE`) → quyết định ghi đè; route lạ → "L2" (còn lại → L2, P3)
_BY_ROUTE: Final[Mapping[str, Decision]] = {"AUTO": "AUTO", "HITL": "HITL", "ESCALATE_L2": "L2"}
# Node giả B12 (gate2) không ghi `detail.route` — suy từ cột `policy_decision` (TQ-3)
_BY_POLICY: Final[Mapping[str, Decision]] = {"allow": "AUTO", "approval_required": "HITL"}


@dataclass(frozen=True)
class DecisionTrail:
    """Phần audit của ticket mà P3 cần: dòng `risk_decided` MỚI NHẤT (`detail.route`, cột `policy_decision`) + có dòng B10
    `deflected_info_only` hay không."""

    risk_route: str | None
    risk_policy_decision: str | None
    has_risk_decided: bool
    deflected: bool


def original_decision(trail: DecisionTrail) -> Decision:
    if trail.has_risk_decided:
        if trail.risk_route is not None:
            return _BY_ROUTE.get(trail.risk_route, "L2")
        return _BY_POLICY.get(trail.risk_policy_decision or "", "L2")
    return "ANSWER" if trail.deflected else "L2"


def override_key(ticket_id: str, overrider_id: str) -> str:
    return hashlib.sha256(("override:" + ticket_id + ":" + overrider_id).encode()).hexdigest()


@dataclass(frozen=True)
class OverrideRecord:
    ticket_id: str
    overrider_id: str
    original_decision: Decision
    override_decision: Decision
    reason_code: OverrideReason
    note: str | None  # ĐÃ qua privacy guard L1 (route)
    created_at: datetime

    def audit_row(self) -> dict[str, Any]:
        """Dòng `audit_logs` (P4): `step="OVERRIDE"`, `event="override_recorded"`, `from_status`/`to_status` None, 3 cột ghi đè,
        `note`, `detail={reason_code}`, `idempotency_key = override_key(...)`, `created_at`."""
        return {
            "ticket_id": self.ticket_id, "created_at": self.created_at, "step": OVERRIDE_STEP, "event": OVERRIDE_EVENT,
            "from_status": None, "to_status": None, "original_decision": self.original_decision,
            "override_decision": self.override_decision, "overrider_id": self.overrider_id, "note": self.note,
            "detail": {"reason_code": self.reason_code}, "idempotency_key": override_key(self.ticket_id, self.overrider_id),
        }  # fmt: skip
