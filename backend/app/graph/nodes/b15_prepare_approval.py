"""B15 — node THẬT (Phase 4 chặng 4b; phase4 3.1, 5.1 P2–P13, 5.2, 5.6). Gate2 (`FAKE_SCENARIO`) dùng bản giả
`graph/nodes/fake/b15_prepare_approval.py`.

Thứ tự (lời giao DỪNG 2, C5):
1. Chốt phòng thủ P6 — đích `device:` mà `facts.device_owner_is_requester` không phải True → E5 `approval_target_unverified`,
   TRƯỚC mọi lời gọi AD (G4-16: luật sai cũng không mở được phiếu cho máy của người khác).
2. `effects.peek("approval_create")` có (chạy lại — TC33, P9) → nhánh phiếu cũ: `approvals.get` → `once("notify_approver",
   a.approver_id)` → `goto` theo phiếu cũ. KHÔNG chọn người, KHÔNG tra AD, KHÔNG ensure (AD lỗi lúc chạy lại không làm mồ côi
   phiếu `pending`; người duyệt đổi trạng thái giữa hai lần chạy không làm báo nhầm người).
3. Thiếu khoá HMAC (`approver_users.available` False) → E2 `approver_sync_unavailable` (Q-4b-5), 0 phiếu.
4. Hook `before_approver_lookup` (test bơm lỗi AD đúng lúc này — B1 cũng tra AD) → `choose_approver` (3.1) trên lời tra CÓ CACHE
   (mỗi người một lời gọi `ad_get_user` bước `B15_APPROVER`, kể cả chuỗi quản lý mà `ensure` đi lại): lỗi hệ thống →
   E2 `approver_lookup_error`; hết hạn lượt → E2 `turn_budget_exceeded`; `Refuse` → E5 `no_valid_approver` + `rejected_candidates`.
5. `ensure` người duyệt + dự phòng (dòng `users` cho FK — Q-4-N; không tạo phiên). 6. `once("approval_create")`.
7. Hook `after_approval_create` (TC33 giết process tại đây). 8. `approvals.get`. 9. `once("notify_approver", a.approver_id)`.
10. `goto(S_PENDING_APPROVAL, …)` — điểm log 5 (P10): cột `approver_id`, `deadline`, `conflict_detected` (`audit_columns`),
    `action_plan_hash`, `intended_action` (hộp thư 4c đọc cột này); `detail` chỉ id/enum/số.

Mọi nhánh E: `goto(S_ESCALATED, next_node="b20_audit", step="B15", event=<reason>, …)`, `escalation_reason_detail` là hằng.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from app.core.hashing import hash_action
from app.core.turn_budget import TurnBudgetExceeded
from app.domain.action import Action
from app.domain.approval import (
    ApproverLookupError,
    Choice,
    Lookup,
    Refuse,
    Rejected,
    Roster,
    action_has_device_target,
    choose_approver,
    memo_lookup,
)
from app.domain.context import RequesterContext
from app.domain.exit_codes import ExitCode
from app.domain.states import S_ESCALATED, S_PENDING_APPROVAL
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.ports import ApprovalRow
from app.graph.tracing import NodeFn
from app.tools.models import AdUser
from app.tools.specs import APPROVER_STEP


def _rejected(rejected: Sequence[Rejected]) -> list[dict[str, str]]:
    return [{"user_id": r.user_id, "reason": r.reason} for r in rejected]


def _point5(a: ApprovalRow, choice: Choice[AdUser] | None, roster: Roster, sla_minutes: int) -> dict[str, Any]:
    """`detail` điểm log 5 (P10) — lấy từ PHIẾU (cả nhánh thường lẫn nhánh `peek`). Nhánh `peek` (TQ-7 sửa): `choice_reason` suy
    tất định từ phiếu cũ, `rejected_candidates=None` (không có nguồn — không bịa), `recovered=True`."""
    if choice is not None:
        reason, rejected, recovered = choice.reason, _rejected(choice.rejected), False
    else:
        reason = "conflict" if a.conflict_detected else ("no_valid_l1" if a.approver_id == roster.head else "normal")
        rejected, recovered = None, True
    return {
        "backup_approver_id": a.backup_approver_id, "conflict_type": a.conflict_type, "choice_reason": reason,
        "rejected_candidates": rejected, "sla_minutes": sla_minutes, "recovered": recovered,
    }  # fmt: skip


def make(deps: NodeDeps) -> NodeFn:
    async def ad_lookup(user_id: str) -> AdUser | None:
        """`ad_get_user` qua registry (retry, breaker, hạn lượt — điểm gọi DUY NHẤT của node, `test_turn_budget.NODE_CALL_SITES`):
        404/rỗng → None (không hợp lệ, không phải lỗi); lỗi hệ thống → `ApproverLookupError` (chuỗi lỗi KHÔNG vào audit); hết
        hạn lượt → `TurnBudgetExceeded` lan ra; lỗi hợp đồng → E9."""
        result = await deps.directory.call("ad_get_user", {"user_id": user_id}, caller_step=APPROVER_STEP)
        if result.error is not None:
            raise ApproverLookupError(user_id)
        return None if result.empty or result.data is None else result.data

    async def queued(
        state: Any, action: Action, roster: Roster, approval_id: str, choice: Choice[AdUser] | None
    ) -> dict[str, Any]:
        a = await deps.approvals.get(approval_id)
        if a is None:  # vừa tạo (hoặc `peek` thấy) mà không đọc lại được = bug → E9
            raise RuntimeError(f"B15: phiếu {approval_id} không đọc lại được")
        await effects.once(
            state, "notify_approver", deps.approvals.notify_approver, approval_id, a.approver_id, step="B15",
        )  # fmt: skip
        return await goto(
            state, S_PENDING_APPROVAL, next_node="approval_wait", step="B15", event="queued",
            approval_id=approval_id, action_plan_hash=hash_action(action), intended_action=action,
            audit_columns={"approver_id": a.approver_id, "deadline": a.deadline, "conflict_detected": a.conflict_detected},
            audit_detail=_point5(a, choice, roster, deps.approval_sla_minutes),
        )  # fmt: skip

    async def b15_prepare_approval(state: Any) -> dict[str, Any]:
        run = current_run()
        action = Action.model_validate(state["intended_action"])  # thiếu = bug → E9
        requester = RequesterContext.model_validate(state["requester_context"])
        if action_has_device_target(action) and action.facts.get("device_owner_is_requester") is not True:  # [1] P6
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B15", event="approval_target_unverified",
                audit_detail={"stage": "target_guard"}, exit_code=ExitCode.E5.value,
                escalation_reason_detail="approval_target_unverified",
            )  # fmt: skip
        roster = deps.approvers[state["intent"]]  # thiếu = cấu hình lệch mà open_approvers bỏ sót → KeyError → E9
        existing = await effects.peek(state, "approval_create", step="B15")  # [2] P9
        if existing is not None:
            return await queued(state, action, roster, existing, None)
        if not deps.approver_users.available:  # [3] Q-4b-5 — trước mọi lời tra và mọi ensure
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B15", event="approver_sync_unavailable",
                audit_detail={"stage": "sync_unavailable"}, exit_code=ExitCode.E2.value,
                escalation_reason_detail="approver_sync_unavailable",
            )  # fmt: skip
        await deps.scenario.hook(state, "before_approver_lookup")
        lookup: Lookup[AdUser] = memo_lookup(ad_lookup)  # [4] mỗi người một lời gọi — cả `choose_approver` lẫn `ensure`
        try:
            choice = await choose_approver(roster, requester.user_id, action, lookup)
            if not isinstance(choice, Refuse):
                now = run.clock.now()
                for ad_user in choice.to_sync:  # [5] FK approver/backup — TRƯỚC `once`
                    await deps.approver_users.ensure(ad_user, lookup, now=now)
        except ApproverLookupError:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B15", event="approver_lookup_error",
                audit_detail={"stage": "lookup"}, exit_code=ExitCode.E2.value,
                escalation_reason_detail="approver_lookup_error",
            )  # fmt: skip
        except TurnBudgetExceeded:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B15", event="turn_budget_exceeded",
                audit_detail={"stage": "turn_budget"}, exit_code=ExitCode.E2.value,
                escalation_reason_detail="turn_budget_exceeded",
            )  # fmt: skip
        if isinstance(choice, Refuse):
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B15", event="no_valid_approver",
                audit_detail={"stage": "choose", "rejected_candidates": _rejected(choice.rejected)},
                exit_code=ExitCode.E5.value, escalation_reason_detail="no_valid_approver",
            )  # fmt: skip
        deadline = run.clock.now() + timedelta(minutes=deps.approval_sla_minutes)  # P12: SLA hiệu lực (wiring tính)
        approval_id = await effects.once(
            state, "approval_create", deps.approvals.create, state["ticket_id"], choice.approver.user_id, deadline,
            hash_action(action), step="B15", backup_approver_id=choice.backup.user_id if choice.backup else None,
            conflict_detected=choice.conflict_detected, conflict_type=choice.conflict_type,
        )  # fmt: skip
        if approval_id is None:
            raise RuntimeError("B15: approvals.create không trả approval_id")  # bug → E9
        await deps.scenario.hook(state, "after_approval_create")  # [7] TC33: giết process tại đây
        return await queued(state, action, roster, approval_id, choice)

    return b15_prepare_approval
