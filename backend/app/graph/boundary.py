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
- **Ticket đã có `transaction_log` `begun`** (Việc treo 21, 3h DỪNG 3b): trạng thái chưa kết thúc/escalate → hỏi
  `run.txlog.has_begun(ticket_id)` (theo TICKET, mọi lượt) TRƯỚC cả nhánh E2 lẫn E9. Có → E7 `execution_interrupted` +
  `MAY_HAVE_WRITTEN` (audit như nhánh cũ + `"begun": True`): lệnh ghi có thể đã tới đích, mẫu E9 "xử lý thủ công" / E2 khiến L2
  hiểu là "chưa làm". Vd `goto(S_CONFIRMING)` cuối B17 lỗi SAU khi ghi đã thành công, lỗi ở B19. `has_begun` ném lỗi → ném
  tiếp (KHÔNG hạ xuống E9 — fail-closed): lượt không đóng, worker recover; cạn lượt thì runner `_give_up` xét `begun`.
"""

import functools
import logging
from typing import Any

from langgraph.errors import GraphBubbleUp

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.exit_codes import ExitCode
from app.domain.states import S_ESCALATED, TERMINAL
from app.domain.ticket_state import check_state_keys
from app.executor.txlog import MAY_HAVE_WRITTEN
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
            status = state.get("status")
            open_ = status not in TERMINAL | {S_ESCALATED}
            # Việc treo 21: TRƯỚC E2 lẫn E9. `has_begun` lỗi → nổi tiếp (fail-closed), không hạ xuống E9.
            if open_ and await current_run().txlog.has_begun(state["ticket_id"]):
                return await _after_begun(name, state, exc)
            if open_ and isinstance(exc, TurnBudgetExceeded):
                return await _turn_budget_exceeded(name, state, exc)
            detail = _unhandled(name, state, exc)
            if not open_:
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


def _unhandled(name: str, state: Any, exc: Exception) -> dict[str, Any]:
    """Log + span `error` + audit detail của lỗi chưa lường trước (TC29)."""
    log.error(
        "unhandled_exception tại %s (ticket %s): %s: %s",
        name, state.get("ticket_id"), type(exc).__name__, exc,
    )  # fmt: skip
    mark_error(exc)
    return {"exception": f"{type(exc).__name__}: {exc}"[:500], "traceback": short_traceback(exc)}


def _budget(name: str, state: Any, exc: TurnBudgetExceeded) -> dict[str, Any]:
    log.warning("turn_budget_exceeded tại %s (ticket %s): %s", name, state.get("ticket_id"), exc)
    return {"node": name, "exception": f"{type(exc).__name__}: {exc}"[:500]}


async def _turn_budget_exceeded(name: str, state: Any, exc: TurnBudgetExceeded) -> dict[str, Any]:
    return await goto(
        state, S_ESCALATED, next_node=AUDIT_NODE, step=name, event="turn_budget_exceeded",
        audit_detail=_budget(name, state, exc), exit_code=ExitCode.E2.value,
        escalation_reason_detail="turn_budget_exceeded",
    )  # fmt: skip


async def _after_begun(name: str, state: Any, exc: Exception) -> dict[str, Any]:
    """Ticket đã có `begun`: cùng event + audit detail như nhánh E2/E9 sẽ ghi, thêm `"begun": True`; ra E7."""
    if isinstance(exc, TurnBudgetExceeded):
        event, detail, what = "turn_budget_exceeded", _budget(name, state, exc), "Hết hạn lượt"
    else:
        event, detail, what = "unhandled_exception", _unhandled(name, state, exc), "Lỗi hệ thống không lường trước"
    return await goto(
        state, S_ESCALATED, next_node=AUDIT_NODE, step=name, event=event, audit_detail={**detail, "begun": True},
        exit_code=ExitCode.E7.value, escalation_reason_detail="execution_interrupted",
        escalation_note=f"{what} tại {name} sau khi transaction_log đã có begun: {MAY_HAVE_WRITTEN}.",
    )  # fmt: skip
