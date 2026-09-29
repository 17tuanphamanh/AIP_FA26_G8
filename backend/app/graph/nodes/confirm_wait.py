"""Node chờ `S_CONFIRMING` — B19 (node GIẢ, Phase 2a; B19 thật ở Phase 3). Không side effect trước
`interrupt()`. Im lặng 48 giờ → tự đóng `resolved_auto_timeout_48h` [Chốt].

3e (thiết kế Phase 3 mục 8.6, 3-Q3 phương án A): `note` của xác nhận qua `screen_reply` (L0 + L2) NGAY sau
`interrupt()`, trước mọi nhánh (kể cả "đã xong") — khớp → `security_events(injection_detected)` qua `effects.once` →
`S_ESCALATED` E0 `injection_in_reply`.
"""

from typing import Any

from langgraph.types import interrupt

from app.domain.exit_codes import CloseReason, ExitCode
from app.domain.states import S_ESCALATED, S_RESOLVED
from app.graph import effects
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.guard.screen import screen_reply


def make(deps: NodeDeps) -> NodeFn:
    async def confirm_wait(state: Any) -> dict[str, Any]:
        ev = interrupt({"wait": "confirm"})
        if (hit := screen_reply(str(ev.get("note") or ""))) is not None:
            await effects.once(
                state, "security_event", deps.security_events.record, "injection_detected",
                ticket_id=state["ticket_id"], detail={"layer": "regex_reply", "pattern_id": hit.id}, step="B19",
            )  # fmt: skip
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B19", event="injection_in_reply",
                exit_code=ExitCode.E0.value, escalation_reason_detail="injection_in_reply",
            )  # fmt: skip
        if ev["kind"] == "timeout":
            return await goto(
                state, S_RESOLVED, next_node="b20_audit", step="B19",
                event="auto_closed_no_response_48h",
                close_reason=CloseReason.RESOLVED_AUTO_TIMEOUT_48H.value,
            )  # fmt: skip
        if ev["kind"] == "confirmed":
            return await goto(
                state, S_RESOLVED, next_node="b20_audit", step="B19", event="user_confirmed",
                close_reason=CloseReason.RESOLVED_USER_CONFIRMED.value,
            )  # fmt: skip
        return await goto(
            state, S_ESCALATED, next_node="b20_audit", step="B19", event="user_reported_unresolved",
            exit_code=ExitCode.E8.value,
        )  # fmt: skip

    return confirm_wait
