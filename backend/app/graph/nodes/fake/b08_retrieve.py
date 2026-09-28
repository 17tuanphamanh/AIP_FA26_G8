"""B8–B9 — node GIẢ, dùng khi `FAKE_SCENARIO` đặt (`builder.fake_nodes`, 3-Q32 cách A). Bản thật:
`graph/nodes/b08_retrieve.py` (Phase 3 chặng 3c)."""

from typing import Any

from app.domain.exit_codes import ExitCode
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b08_retrieve(state: Any) -> dict[str, Any]:
        outcome = deps.scenario.pick(state, "b08_retrieve")
        if outcome == "rag_error":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B8", event="retrieval_error",
                exit_code=ExitCode.E2.value,
            )  # fmt: skip
        if outcome == "no_evidence":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B9", event="no_evidence",
                exit_code=ExitCode.E3.value,
            )  # fmt: skip
        return await goto(
            state, S_RETRIEVING, next_node="b10_route", step="B8", event="retrieved",
            retrieved=[], retrieval_score=0.9,
        )  # fmt: skip

    return b08_retrieve
