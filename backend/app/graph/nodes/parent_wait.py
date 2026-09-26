"""Vòng của ticket cha — `parent_wait` + `parent_reply_wait` (node GIẢ, Phase 2a; P1 mục 8.2).

Cơ chế thật (ticket con, `child_notices`, `compose_digest`, `aggregate_children`) làm cùng B05 ở
Phase 5 (D-31). Ở đây giữ đúng hình dạng: sau `interrupt()` phải `goto` quay lại chính node để đối
soát lại (đánh thức sớm là bình thường); tin tổng hợp + hạn qua `effects.once`.
"""

from datetime import timedelta
from typing import Any

from langgraph.types import interrupt

from app.domain.states import S_CLASSIFYING, S_CONFIRMING, S_RESOLVED
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def parent_wait(state: Any) -> dict[str, Any]:
        outcome = deps.scenario.pick(state, "parent_wait")
        if outcome == "wait":
            interrupt({"wait": "children"})
            return await goto(
                state, S_CLASSIFYING, next_node="parent_wait", step="B5", event="parent_woken",
            )  # fmt: skip
        rnd = int(state.get("parent_round", 0) or 0) + 1
        run = current_run()
        await effects.once(
            state, "notify_user", deps.notifier.notify_user, state["ticket_id"],
            f"Tin tổng hợp vòng {rnd} (giả)", "none", step="B5", sub=f"round:{rnd}",
        )  # fmt: skip
        if outcome == "done":
            return await goto(
                state, S_RESOLVED, next_node="b20_audit", step="B5", event="children_aggregated",
                aggregate_status="ALL_RESOLVED", parent_round=rnd,
            )  # fmt: skip
        deadline = run.clock.now() + timedelta(hours=deps.constants.CLARIFY_TIMEOUT_HOURS)
        await effects.once(
            state, "deadline_set", deps.deadlines.set, state["ticket_id"], "clarify",
            deadline, run.turn_id, step="B5", sub=f"round:{rnd}",
        )  # fmt: skip
        return await goto(
            state, S_CONFIRMING, next_node="parent_reply_wait", step="B5", event="digest_sent",
            parent_round=rnd, awaiting={},
        )  # fmt: skip

    return parent_wait
