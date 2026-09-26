"""B15 — node GIẢ (Phase 2a). Chọn người duyệt + xung đột lợi ích thật: Phase 4.

Mọi việc trước khi chờ duyệt nằm Ở ĐÂY, qua `effects.once`: tạo phiếu (hạn 30 phút ở
`approvals.deadline`), báo người duyệt. Chạy lại (process chết trước checkpoint) → đúng 1 phiếu,
1 thông báo (D-18, P1 mục 10).

Người duyệt = `deps.approver_id` (`FAKE_APPROVER_ID`, chỉ dev/test — 2b-Q3). Chưa cấu hình → ném
lỗi → E9 qua boundary (không tự chọn ai đó).
"""

from datetime import timedelta
from typing import Any

from app.core.hashing import hash_action
from app.domain.states import S_PENDING_APPROVAL
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import FAKE_ACTION, NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b15_prepare_approval(state: Any) -> dict[str, Any]:
        deps.scenario.pick(state, "b15_prepare_approval")
        approver_id = deps.approver_id
        if approver_id is None:
            raise RuntimeError("FAKE_APPROVER_ID chưa cấu hình — B15 giả không có người duyệt")
        run = current_run()
        plan_hash = hash_action(state.get("intended_action") or FAKE_ACTION)
        deadline = run.clock.now() + timedelta(minutes=deps.constants.SLA_MINUTES)
        approval_id = await effects.once(
            state, "approval_create", deps.approvals.create, state["ticket_id"],
            approver_id, deadline, plan_hash, step="B15",
        )  # fmt: skip
        await deps.scenario.hook(state, "after_approval_create")
        await effects.once(
            state, "notify_approver", deps.approvals.notify_approver, approval_id,
            approver_id, step="B15",
        )  # fmt: skip
        return await goto(
            state, S_PENDING_APPROVAL, next_node="approval_wait", step="B15", event="queued",
            audit_detail={"approver_id": approver_id, "deadline": deadline.isoformat()},
            approval_id=approval_id, action_plan_hash=plan_hash,
        )  # fmt: skip

    return b15_prepare_approval
