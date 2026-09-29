"""B10 — node GIẢ (Phase 2a), dùng khi `FAKE_SCENARIO` đặt (`builder.fake_nodes`, 3-Q32 cách A). Bản thật:
`graph/nodes/b10_route.py` (Phase 3 chặng 3g).

Ca chỉ cần thông tin: gửi câu trả lời + đặt hạn 48 giờ Ở ĐÂY (node đứng trước `confirm_wait`), qua
`effects.once` — node chờ không có side effect.
"""

from datetime import timedelta
from typing import Any

from app.domain.exit_codes import ExitCode
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_RETRIEVING
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b10_route(state: Any) -> dict[str, Any]:
        outcome = deps.scenario.pick(state, "b10_route")
        if outcome == "llm_error":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="llm_unavailable",
                exit_code=ExitCode.E2.value,
            )  # fmt: skip
        if outcome == "info":
            run = current_run()
            await effects.once(
                state, "notify_user", deps.notifier.notify_user, state["ticket_id"],
                "Câu trả lời (giả)", "confirm", step="B10",
            )  # fmt: skip
            deadline = run.clock.now() + timedelta(hours=deps.constants.CONFIRM_TIMEOUT_HOURS)
            await effects.once(
                state, "deadline_set", deps.deadlines.set, state["ticket_id"], "confirm",
                deadline, run.turn_id, step="B10",
            )  # fmt: skip
            return await goto(
                state, S_CONFIRMING, next_node="confirm_wait", step="B10",
                event="deflected_info_only", need_type="info",
            )  # fmt: skip
        return await goto(
            state, S_RETRIEVING, next_node="b11_slots", step="B10", event="needs_action",
            need_type="action",
        )  # fmt: skip

    return b10_route
