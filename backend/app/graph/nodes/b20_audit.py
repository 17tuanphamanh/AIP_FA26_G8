"""B20 — node GIẢ (Phase 2a): chỉ kết thúc thread. B20 thật (điểm log 8, `finalize_once`,
`escalations` + ghi chú bàn giao 4 phần, thông báo theo mã E) làm ở chặng 2b."""

from typing import Any

from langgraph.graph import END

from app.graph.fakes import NodeDeps
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b20_audit(state: Any) -> dict[str, Any]:
        deps.scenario.pick(state, "b20_audit")
        await deps.scenario.hook(state, "b20")
        return {"next": END}

    return b20_audit
