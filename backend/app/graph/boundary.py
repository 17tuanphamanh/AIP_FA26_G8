"""with_error_boundary — E9, lưới an toàn cho lỗi CHƯA lường trước (huong-dan 6.4, P1 mục 5.2).

- Không bắt `GraphBubbleUp` (gồm `GraphInterrupt` — cách LangGraph dừng chờ người). Bắt nhầm thì
  mọi lần chờ người thành E9.
- Exception khác → span `error` + traceback ≤ 4 KB, audit có traceback (TC29), rồi
  `goto(S_ESCALATED, b20_audit, exit_code=E9)`. Không thay try/except cụ thể trong node (E0–E8).
- Trạng thái đã kết thúc / đã escalate (chỉ xảy ra ở `b20_audit`): không còn chuyển hợp lệ nào →
  ghi audit `unhandled_exception` (khoá idempotent THEO LƯỢT) rồi **ném tiếp** (2b-Q6, B20 mục 5.1):
  lượt không đóng, worker `scan_stale_turns` chạy lại B20 — lần sau chỉ ghi phần còn thiếu. Kết thúc
  thread ở đây (bản 2a) để lại ticket không có `final_state` = bị bỏ rơi. Giới hạn số lần: runner
  (`recover_attempts`, migration 0005).
- Mọi giá trị node trả về phải có key thuộc `TicketState` (`check_state_keys`) — key lạ → E9.
- **Hết hạn cả lượt** (`core.turn_budget.TurnBudgetExceeded`, phase3 9.0, Q-3f-2): KHÔNG phải bug → E2
  `turn_budget_exceeded` (lưới chung cho node không tự bắt: B1, B8…; B2/B3/B6 bắt tường minh để giữ `security_flag`/điểm
  log). Không bao giờ cho qua, không E3, không E9.
"""

import functools
import logging
from typing import Any

from langgraph.errors import GraphBubbleUp

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.exit_codes import ExitCode
from app.domain.states import S_ESCALATED, TERMINAL
from app.domain.ticket_state import check_state_keys
from app.graph.context import current_run
from app.graph.goto import audit_key, goto
from app.graph.tracing import NodeFn, mark_error, short_traceback

log = logging.getLogger(__name__)

AUDIT_NODE = "b20_audit"


def with_error_boundary(name: str, fn: NodeFn) -> NodeFn:
    @functools.wraps(fn)
    async def wrapped(state: Any) -> dict[str, Any]:
        try:
            update = await fn(state)
            check_state_keys(update)
            return update
        except GraphBubbleUp:
            raise
        except Exception as exc:
            if isinstance(exc, TurnBudgetExceeded) and state.get("status") not in TERMINAL | {S_ESCALATED}:
                return await _turn_budget_exceeded(name, state, exc)
            log.error(
                "unhandled_exception tại %s (ticket %s): %s: %s",
                name, state.get("ticket_id"), type(exc).__name__, exc,
            )  # fmt: skip
            mark_error(exc)
            detail = {
                "exception": f"{type(exc).__name__}: {exc}"[:500],
                "traceback": short_traceback(exc),
            }
            status = state.get("status")
            if status in TERMINAL | {S_ESCALATED}:
                run = current_run()
                loop_seq = int(state.get("reasoning_loops", 0) or 0)
                key = audit_key(state["ticket_id"], name, "unhandled_exception", run.turn_id, loop_seq)
                await run.audit.record({
                    "ticket_id": state["ticket_id"], "turn_id": run.turn_id, "loop_seq": loop_seq,
                    "idempotency_key": key, "step": name, "event": "unhandled_exception",
                    "from_status": status, "to_status": status, "created_at": run.clock.now(),
                    "detail": detail,
                })  # fmt: skip
                raise  # lượt không đóng → worker chạy lại (có giới hạn) — không bỏ rơi ticket
            return await goto(
                state, S_ESCALATED, next_node=AUDIT_NODE, step=name, event="unhandled_exception",
                audit_detail=detail, exit_code=ExitCode.E9.value,
                escalation_note=f"Lỗi hệ thống không lường trước tại {name}",
            )  # fmt: skip

    wrapped.__dict__["error_boundary"] = True
    return wrapped


async def _turn_budget_exceeded(name: str, state: Any, exc: TurnBudgetExceeded) -> dict[str, Any]:
    log.warning("turn_budget_exceeded tại %s (ticket %s): %s", name, state.get("ticket_id"), exc)
    return await goto(
        state, S_ESCALATED, next_node=AUDIT_NODE, step=name, event="turn_budget_exceeded",
        audit_detail={"node": name, "exception": f"{type(exc).__name__}: {exc}"[:500]},
        exit_code=ExitCode.E2.value, escalation_reason_detail="turn_budget_exceeded",
    )  # fmt: skip
