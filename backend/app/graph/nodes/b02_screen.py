"""B2 — node GIẢ (Phase 2a). Sàng lọc injection thật: Phase 5 (B02)."""

from typing import Any

from app.domain.exit_codes import BlockReason, CloseReason, ExitCode
from app.domain.states import S_BLOCKED, S_CLASSIFYING, S_ESCALATED
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b02_screen(state: Any) -> dict[str, Any]:
        outcome = deps.scenario.pick(state, "b02_screen")
        if outcome == "injection":
            return await goto(
                state, S_BLOCKED, next_node="b20_audit", step="B2", event="injection_detected",
                exit_code=ExitCode.E0.value, block_reason=BlockReason.INJECTION_DETECTED.value,
                close_reason=CloseReason.BLOCKED_INJECTION_DETECTED.value,
            )  # fmt: skip
        if outcome == "guard_error":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B2", event="guard_unavailable",
                exit_code=ExitCode.E2.value,
            )  # fmt: skip
        return await goto(state, S_CLASSIFYING, next_node="b03_classify", step="B2", event="screened")

    return b02_screen
