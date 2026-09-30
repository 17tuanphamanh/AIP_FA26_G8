"""B6–B7 — node GIẢ (Phase 2a), giữ cho `FAKE_SCENARIO`/`make gate2` (3-Q32 cách A). Bản thật: `graph/nodes/b06_diagnose.py`
(Phase 3 chặng 3f)."""

from typing import Any

from app.domain.exit_codes import ExitCode
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b06_diagnose(state: Any) -> dict[str, Any]:
        outcome = deps.scenario.pick(state, "b06_diagnose")
        if outcome == "tool_error":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B7", event="tool_system_error",
                exit_code=ExitCode.E2.value,
            )  # fmt: skip
        return await goto(
            state, S_RETRIEVING, next_node="b11_slots" if outcome == "rediag" else "b08_retrieve",
            step="B6", event="diagnosed", diagnostics={},
        )  # fmt: skip

    return b06_diagnose
