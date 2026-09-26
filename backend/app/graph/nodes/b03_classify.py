"""B3–B5 — node GIẢ (Phase 2a). Intent thật: Phase 3; tách ý + ticket con: Phase 5 (D-31)."""

from typing import Any

from app.domain.exit_codes import ExitCode
from app.domain.states import S_CLASSIFYING, S_DIAGNOSING, S_ESCALATED
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b03_classify(state: Any) -> dict[str, Any]:
        outcome = deps.scenario.pick(state, "b03_classify")
        if outcome == "out_of_scope":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_out_of_scope",
                exit_code=ExitCode.E1.value, escalation_reason_detail="out_of_scope",
            )  # fmt: skip
        if outcome == "split":
            return await goto(
                state, S_CLASSIFYING, next_node="parent_wait", step="B5", event="split",
                is_parent=True, children=[],
            )  # fmt: skip
        return await goto(
            state, S_DIAGNOSING, next_node="b06_diagnose", step="B3", event="intent_classified",
            intent="vpn", intent_confidence=0.95,
        )  # fmt: skip

    return b03_classify
