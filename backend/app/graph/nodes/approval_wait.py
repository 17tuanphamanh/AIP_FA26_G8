"""Node chờ `S_PENDING_APPROVAL` + quyết định B16 (node GIẢ, Phase 2a; B16 thật ở Phase 4).

Không side effect trước `interrupt()`. Hết hạn → E6, KHÔNG BAO GIỜ tự thực thi (bất biến 5; chuyển
cấm 2 chặn mọi ca `approval_result != "approved"`).

Quyết định được ghi vào phiếu Ở ĐÂY (B15-B16 mục 5: `approvals.close` có điều kiện `status='pending'`),
không ở route duyệt: người duyệt (`approver_id`) và lý do (`note`) đến từ sự kiện mà route dựng từ
token + body (2b-3).
"""

from typing import Any

from langgraph.types import interrupt

from app.domain.exit_codes import CloseReason, ExitCode
from app.domain.states import S_ESCALATED, S_EXECUTING, S_REJECTED
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def approval_wait(state: Any) -> dict[str, Any]:
        ev = interrupt({"wait": "approval", "approval_id": state.get("approval_id")})
        kind = ev["kind"]
        if state.get("approval_id"):
            await deps.approvals.close(
                state["approval_id"], kind, current_run().clock.now(),
                decided_by=ev.get("approver_id"), note=ev.get("note"),
            )  # fmt: skip
        if kind == "approved":
            return await goto(
                state, S_EXECUTING, next_node="b17_execute", step="B16", event="approved",
                approval_result="approved",
            )  # fmt: skip
        if kind == "rejected":
            return await goto(
                state, S_REJECTED, next_node="b20_audit", step="B16", event="rejected",
                approval_result="rejected", close_reason=CloseReason.REJECTED_BY_APPROVER.value,
            )  # fmt: skip
        return await goto(
            state, S_ESCALATED, next_node="b20_audit", step="B16", event="approval_timeout",
            approval_result="timeout", exit_code=ExitCode.E6.value,
        )  # fmt: skip

    return approval_wait
