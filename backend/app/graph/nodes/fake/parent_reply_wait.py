"""Node chờ của ticket cha ở `S_CONFIRMING` (D-31) — node GIẢ, giữ cho `FAKE_SCENARIO`/`make gate2` (chuyển sang `fake/` ở Phase 5
T20b). Bản thật (chuyển câu trả lời xuống con): `graph/nodes/parent_reply_wait.py`."""

from typing import Any

from langgraph.types import interrupt

from app.domain.states import S_CLASSIFYING
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def parent_reply_wait(state: Any) -> dict[str, Any]:
        ev = interrupt({"wait": "parent_reply"})
        return await goto(
            state, S_CLASSIFYING, next_node="parent_wait", step="B5",
            event="reply_timeout" if ev["kind"] == "timeout" else "reply_dispatched",
        )  # fmt: skip

    return parent_reply_wait
