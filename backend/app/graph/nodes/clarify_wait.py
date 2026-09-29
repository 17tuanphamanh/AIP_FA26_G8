"""Node chờ `S_CLARIFYING` (B11). Không side effect trước `interrupt()`.

3e (thiết kế Phase 3 mục 8.6, 3-Q3 phương án A): câu trả lời qua `screen_reply` (L0 + L2, thuần) NGAY sau `interrupt()`,
trước mọi nhánh — khớp mẫu injection → `security_events(injection_detected)` qua `effects.once` → `S_ESCALATED` E0
`injection_in_reply` (không `S_BLOCKED`: bảng 2.1 không có chuyển đó). Tin trả lời đó KHÔNG vào `conversation`.
"""

from typing import Any

from langgraph.types import interrupt

from app.domain.exit_codes import ExitCode
from app.domain.states import S_CLARIFYING, S_DIAGNOSING, S_ESCALATED
from app.graph import effects
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.guard.screen import screen_reply


def make(deps: NodeDeps) -> NodeFn:
    async def clarify_wait(state: Any) -> dict[str, Any]:
        ev = interrupt({"wait": "clarify"})
        if (hit := screen_reply(str(ev.get("text") or ""))) is not None:
            await effects.once(
                state, "security_event", deps.security_events.record, "injection_detected",
                ticket_id=state["ticket_id"], detail={"layer": "regex_reply", "pattern_id": hit.id}, step="B11",
            )  # fmt: skip
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="injection_in_reply",
                exit_code=ExitCode.E0.value, escalation_reason_detail="injection_in_reply",
            )  # fmt: skip
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
