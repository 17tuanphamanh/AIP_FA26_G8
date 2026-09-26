"""Phụ thuộc của node (`NodeDeps`) + phần GIẢ của Phase 2 (P1: "khung, node giả"). Phase 3+ thay từng
node bằng node thật. Node thật từ 2b: `b01_identity` (dùng `identity`, `directory`, `alerts`, `lockout`).

`FakeScenario` chọn kết quả của mỗi node theo ticket (mặc định = đường vui dừng ở chờ duyệt), để test
đi được mọi nhánh ra của mọi node. Kết quả đặc biệt `"raise"` → node ném `ValueError` (TC29 → E9).
`hook(state, label)` cho test chèn việc vào giữa node (vd. giết process ngay sau `approval_create`).

Các port side effect (`Notifier`, `Approvals`, `DeadlineStore`) luôn được node gọi QUA `effects.once`.
"""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.ticket_state import RiskDecision
from app.graph.ports import (
    AlertSink,
    DeadlineStore,
    IdentityReads,
    ToolCaller,
    ToolResult,
)
from app.settings import PolicyConstants


class Notifier(Protocol):
    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str: ...


class Approvals(Protocol):
    async def create(
        self, ticket_id: str, approver_id: str, deadline: datetime, action_plan_hash: str
    ) -> str: ...

    async def notify_approver(self, approval_id: str, approver_id: str) -> str: ...

    async def record_result(self, approval_id: str, result: str, at: datetime) -> None:
        """Ghi kết quả vào phiếu (idempotent: chỉ đổi phiếu đang `pending`)."""
        ...


class Executor(Protocol):
    async def execute(self, ticket_id: str, action: Action | None) -> bool: ...


DEFAULT_OUTCOMES: Mapping[str, str] = {
    "b02_screen": "ok",
    "b03_classify": "single",
    "b06_diagnose": "ok",
    "b08_retrieve": "ok",
    "b10_route": "action",
    "b11_slots": "complete",
    "b12_assess": "hitl",
    "b15_prepare_approval": "ok",
    "b17_execute": "ok",
    "parent_wait": "wait",
    "b20_audit": "ok",
}

type Hook = Callable[[Mapping[str, Any]], Any]


class FakeScenario:
    def __init__(self, default: Mapping[str, str] | None = None) -> None:
        self._default = {**DEFAULT_OUTCOMES, **(default or {})}
        self._plans: dict[tuple[str, str], list[str]] = {}
        self._hooks: dict[tuple[str, str], Hook] = {}

    def plan(self, ticket_id: str, **outcomes: str | list[str]) -> "FakeScenario":
        """Kết quả cho ticket: một chuỗi, hoặc danh sách dùng lần lượt (phần tử cuối lặp lại)."""
        for node, value in outcomes.items():
            self._plans[(ticket_id, node)] = [value] if isinstance(value, str) else list(value)
        return self

    def on(self, ticket_id: str, label: str, fn: Hook) -> "FakeScenario":
        self._hooks[(ticket_id, label)] = fn
        return self

    def pick(self, state: Mapping[str, Any], node: str) -> str:
        seq = self._plans.get((state["ticket_id"], node))
        outcome = (seq.pop(0) if len(seq) > 1 else seq[0]) if seq else self._default[node]
        if outcome == "raise":
            raise ValueError(f"lỗi giả tại {node}")  # TC29: exception không lường trước
        return outcome

    async def hook(self, state: Mapping[str, Any], label: str) -> None:
        fn = self._hooks.get((state["ticket_id"], label))
        if fn is not None:
            result = fn(state)
            if inspect.isawaitable(result):
                await result


@dataclass
class NodeDeps:
    notifier: Notifier
    approvals: Approvals
    executor: Executor
    deadlines: DeadlineStore
    constants: PolicyConstants
    identity: IdentityReads  # B1: sessions + users.locked_until
    directory: ToolCaller  # B1: `ad_get_user` qua ToolRegistry (retry, breaker)
    alerts: AlertSink  # B1: cảnh báo dò mật khẩu (P9 luật 3)
    lockout: timedelta  # LOCKOUT_MINUTES — B1 suy thời điểm bắt đầu khoá từ `locked_until`
    scenario: FakeScenario = field(default_factory=FakeScenario)
    approver_id: str = "l1-fake"


def fake_requester(user_id: str, now: datetime) -> RequesterContext:
    return RequesterContext(
        user_id=user_id, role="employee", department="it", manager_id=None,
        employment_status="active", tenure_days=365, is_privileged_account=False, captured_at=now,
    )  # fmt: skip


FAKE_ACTION = Action(
    type="vpn_reset_session", target="user:fake", requested_for="fake", scope="single_account",
    privilege_level="standard_user", reversible=True, reversibility="full",
    data_sensitivity="low", params={}, facts={},
)  # fmt: skip


def fake_risk(route: str) -> RiskDecision:
    decision = {"AUTO": "allow", "HITL": "approval_required", "ESCALATE_L2": "deny"}[route]
    level = {"AUTO": "low", "HITL": "medium", "ESCALATE_L2": "high"}[route]
    return RiskDecision(
        decided_by="rule", policy_decision=decision, matched_rule_id="FAKE", raw_prob=None,  # type: ignore[arg-type]
        calibrated_prob=None, p_method=None, risk_level=level, route=route,  # type: ignore[arg-type]
        reason="node giả (Phase 2)", thresholds=None,
    )  # fmt: skip


# ---- Bản không làm gì — dùng khi dựng runtime thật ở Phase 2 (chưa có notify/approval thật) ----


class LoggingNotifier:
    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str:
        return f"noop:{ticket_id}"


class UnavailableApprovals:
    """Phase 2 chưa có M6: không ticket nào đi tới B15 qua API (chưa có route ticket)."""

    async def create(
        self, ticket_id: str, approver_id: str, deadline: datetime, action_plan_hash: str
    ) -> str:
        raise NotImplementedError("approvals chưa có trước Phase 4")

    async def notify_approver(self, approval_id: str, approver_id: str) -> str:
        raise NotImplementedError("approvals chưa có trước Phase 4")

    async def record_result(self, approval_id: str, result: str, at: datetime) -> None:
        raise NotImplementedError("approvals chưa có trước Phase 4")


class RefusingExecutor:
    """Không thực thi gì: B17 thật (credential svc_executor) làm ở Phase 3."""

    async def execute(self, ticket_id: str, action: Action | None) -> bool:
        return False



class UnconfiguredDirectory:
    """Thiếu SVC_AGENT_TOKEN: không gọi được AD — trả lỗi hệ thống (B1 → E2), không kết luận gì về
    người dùng. Dùng thay vì để runtime không khởi động được."""

    error = "not_configured: SVC_AGENT_TOKEN"

    async def call(self, name: str, args: Mapping[str, Any], *, caller_step: str) -> ToolResult:
        return ToolResult(name, None, self.error, 0, False)
