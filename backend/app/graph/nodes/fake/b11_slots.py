"""B11 — node GIẢ (Phase 2a), dùng khi `FAKE_SCENARIO` đặt (`builder.fake_nodes`, 3-Q32 cách A). Bản thật:
`graph/nodes/b11_slots.py` (Phase 3 chặng 3g).

Câu hỏi + hạn 24 giờ nằm ở `b11_slots` (node đứng trước), qua `effects.once`; `clarify_wait` KHÔNG có
side effect trước `interrupt()` — resume chạy lại node chờ từ đầu (D-08).
"""

from datetime import timedelta
from typing import Any

from app.domain.exit_codes import ExitCode
from app.domain.states import S_ASSESSING, S_CLARIFYING, S_ESCALATED
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import FAKE_ACTION, NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b11_slots(state: Any) -> dict[str, Any]:
        outcome = deps.scenario.pick(state, "b11_slots")
        if outcome == "missing":
            turns = int(state.get("clarification_turns", 0) or 0)
            if turns >= deps.constants.MAX_CLARIFICATION_TURNS:
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B11",
                    event="max_clarification_reached", exit_code=ExitCode.E4.value,
                )  # fmt: skip
            run = current_run()
            await effects.once(
                state, "notify_user", deps.notifier.notify_user, state["ticket_id"],
                "Câu hỏi bổ sung (giả)", "answer", step="B11",
            )  # fmt: skip
            deadline = run.clock.now() + timedelta(hours=deps.constants.CLARIFY_TIMEOUT_HOURS)
            await effects.once(
                state, "deadline_set", deps.deadlines.set, state["ticket_id"], "clarify",
                deadline, run.turn_id, step="B11",
            )  # fmt: skip
            return await goto(
                state, S_CLARIFYING, next_node="clarify_wait", step="B11", event="asked",
                clarification_turns=turns + 1,
            )  # fmt: skip
        return await goto(
            state, S_ASSESSING, next_node="b12_assess", step="B11", event="action_built",
            intended_action=FAKE_ACTION,
        )  # fmt: skip

    return b11_slots
