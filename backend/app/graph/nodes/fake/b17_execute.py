"""B17–B18 — node GIẢ (Phase 2a) — chỉ gate2 dùng (`FAKE_SCENARIO`, 3-Q32 cách A). Bản thật (kiểm lại luật/hash/người,
`transaction_log`, executor VPN — 3h): `graph/nodes/b17_execute.py`.

Gửi kết quả + đặt hạn 48 giờ ở đây (B18, node đứng trước `confirm_wait`), qua `effects.once`.
"""

from datetime import timedelta
from typing import Any

from app.domain.action import Action
from app.domain.exit_codes import ExitCode
from app.domain.states import S_CONFIRMING, S_ESCALATED
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import FAKE_ACTION, NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b17_execute(state: Any) -> dict[str, Any]:
        outcome = deps.scenario.pick(state, "b17_execute")
        run = current_run()
        result = await deps.executor.execute(
            state["ticket_id"], run.turn_id, Action.model_validate(state.get("intended_action") or FAKE_ACTION)
        )
        if outcome == "fail" or not result.success:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B17", event="execution_failed",
                exit_code=ExitCode.E7.value,
            )  # fmt: skip
        await effects.once(
            state, "notify_user", deps.notifier.notify_user, state["ticket_id"],
            "Đã thực hiện xong (giả)", "confirm", step="B18",
        )  # fmt: skip
        deadline = run.clock.now() + timedelta(hours=deps.constants.CONFIRM_TIMEOUT_HOURS)
        await effects.once(
            state, "deadline_set", deps.deadlines.set, state["ticket_id"], "confirm",
            deadline, run.turn_id, step="B18",
        )  # fmt: skip
        return await goto(
            state, S_CONFIRMING, next_node="confirm_wait", step="B18", event="executed_ok",
        )  # fmt: skip

    return b17_execute
