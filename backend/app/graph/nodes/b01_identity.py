"""B1 — node GIẢ (Phase 2a). B1 thật (RequesterContext.from_ad, TC24/TC25) làm ở chặng 2b."""

from typing import Any

from app.domain.exit_codes import BlockReason, CloseReason, ExitCode
from app.domain.states import S_BLOCKED, S_ESCALATED, S_SCREENING
from app.graph.context import current_run
from app.graph.fakes import NodeDeps, fake_requester
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b01_identity(state: Any) -> dict[str, Any]:
        outcome = deps.scenario.pick(state, "b01_identity")
        if outcome == "session_invalid":
            return await goto(
                state, S_BLOCKED, next_node="b20_audit", step="B1", event="session_invalid",
                block_reason=BlockReason.INVALID_CREDENTIALS.value,
                close_reason=CloseReason.BLOCKED_INVALID_CREDENTIALS.value,
            )  # fmt: skip
        if outcome == "locked":
            return await goto(
                state, S_BLOCKED, next_node="b20_audit", step="B1", event="repeated_auth_failure",
                block_reason=BlockReason.REPEATED_AUTH_FAILURE.value,
                close_reason=CloseReason.BLOCKED_REPEATED_AUTH_FAILURE.value,
            )  # fmt: skip
        if outcome == "ad_error":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B1", event="identity_unverifiable",
                exit_code=ExitCode.E2.value,
                escalation_note="Không xác minh được danh tính: AD lỗi sau retry",
            )  # fmt: skip
        ctx = fake_requester("fake-user", current_run().clock.now())
        return await goto(
            state, S_SCREENING, next_node="b02_screen", step="B1", event="identity_established",
            requester_context=ctx,
        )  # fmt: skip

    return b01_identity
