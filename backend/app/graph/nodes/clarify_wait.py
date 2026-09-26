"""Node chờ `S_CLARIFYING` (B11). Không side effect trước `interrupt()`."""

from typing import Any

from langgraph.types import interrupt

from app.domain.exit_codes import ExitCode
from app.domain.states import S_CLARIFYING, S_DIAGNOSING, S_ESCALATED
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def clarify_wait(state: Any) -> dict[str, Any]:
        ev = interrupt({"wait": "clarify"})
        if ev["kind"] == "timeout":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="clarify_timeout",
                exit_code=ExitCode.E4.value,
            )  # fmt: skip
        if ev.get("rediagnose"):  # D-20 — chỉ qua goto khi cờ REDIAGNOSE_ON_NEW_SLOT bật
            return await goto(
                state, S_DIAGNOSING, next_node="b06_diagnose", step="B11",
                event="new_slot_rediagnose",
            )  # fmt: skip
        return await goto(
            state, S_CLARIFYING, next_node="b11_slots", step="B11", event="user_replied",
            conversation=[{"role": "user", "text": str(ev.get("text", ""))}],
        )  # fmt: skip

    return clarify_wait
