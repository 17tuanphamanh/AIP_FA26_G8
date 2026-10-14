"""`parent_wait` — vòng của ticket cha ở `S_CLASSIFYING` (node THẬT, Phase 5 T20b P7 — mã giả phase5 5.2.4; P1 §8.2; D-17, D-30, D-31).
Bản giả (gate2, `FAKE_SCENARIO`): `graph/nodes/fake/parent_wait.py`.

Mỗi lần chạy: khởi động con chưa có thread (`current_run().children.start_missing`, P4) → đối soát con từ DB (`tickets.children_view`
— D-17, không đọc checkpoint con) → chưa đủ con dừng: `interrupt` rồi `goto` QUAY LẠI chính node (đánh thức sớm là bình thường) → đủ:
vòng `parent_round + 1` (chạy lại cùng lượt SAU khi tin vòng này đã gửi — `peek` thấy — thì `children_view(delivered_round=n)` dựng
lại ĐÚNG notice của vòng đó, `effects.once` không gửi/đánh dấu lại), MỘT tin `digest` (`compose_digest`, thuần) qua `effects.once("notify_user", tickets.deliver_round, …,
sub=f"round:{n}")` — notice vừa gom được đánh dấu `delivered_round` CÙNG transaction → mọi con đã kết thúc: `aggregate_children` →
`b20_audit` (cha: không `exit_code`, `close_reason` NULL, không `escalations` — D-30); còn ý chờ người dùng: hạn `clarify` (có câu hỏi,
24 h) hoặc `confirm` (48 h) qua `effects.once("deadline_set", sub=f"round:{n}")` → `S_CONFIRMING` → `parent_reply_wait`.
"""

from datetime import timedelta
from typing import Any

from langgraph.types import interrupt

from app.domain.children import aggregate_children, needs_of, stopped
from app.domain.messages import compose_digest
from app.domain.states import (
    S_CLASSIFYING,
    S_CONFIRMING,
    S_ESCALATED,
    S_REJECTED,
    S_RESOLVED,
)
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import audit_key, goto
from app.graph.tracing import NodeFn

NOT_STARTED = "children_not_started"  # audit B5: con chưa khởi động được ở lần chạy này (`detail.busy`, `detail.failed`)


def make(deps: NodeDeps) -> NodeFn:
    async def parent_wait(state: Any) -> dict[str, Any]:
        run = current_run()
        if run.children is None:
            raise RuntimeError("RunContext không có ChildOps — parent_wait chỉ chạy qua Runner")
        recorded = await deps.tickets.started_children(state["ticket_id"])  # Q-T20b-11: dòng `child_submit` mọi lượt
        started = await run.children.start_missing(state, recorded=recorded)  # P4 — idempotent, TRƯỚC đối soát
        if started.busy or started.failed:  # Q-T20b-6 / soát S10 B-ii: ghi TRƯỚC mọi nhánh (kể cả interrupt) — thấy được
            loop_seq = int(state.get("reasoning_loops") or 0)
            await run.audit.record({
                "ticket_id": state["ticket_id"], "turn_id": run.turn_id, "loop_seq": loop_seq,
                "idempotency_key": audit_key(state["ticket_id"], "B5", NOT_STARTED, run.turn_id, loop_seq),
                "step": "B5", "event": NOT_STARTED, "from_status": state["status"], "to_status": state["status"],
                "created_at": run.clock.now(), "detail": {"busy": list(started.busy), "failed": list(started.failed)},
            })  # fmt: skip
        rnd = int(state.get("parent_round") or 0) + 1
        sent = await effects.peek(state, "notify_user", step="B5", sub=f"round:{rnd}") is not None  # chạy lại SAU khi đã gửi vòng này
        view = await deps.tickets.children_view(
            state["ticket_id"], state["children"], delivered_round=rnd if sent else None
        )  # D-17: DB — đã gửi thì dựng lại ĐÚNG notice của vòng đó (không gom notice mới tới sau)
        if not all(stopped(c) for c in view):
            interrupt({"wait": "children"})
            # resume: interrupt() TRẢ VỀ giá trị đánh thức → quay lại CHÍNH node để đối soát với dữ liệu mới (P1 §8.2)
            return await goto(state, S_CLASSIFYING, next_node="parent_wait", step="B5", event="parent_woken")
        digest = compose_digest(view, state.get("child_seeds") or {}, round_no=rnd)  # thuần, theo mẫu (P9)
        await effects.once(
            state, "notify_user", deps.tickets.deliver_round, state["ticket_id"], rnd, digest.notice_ids,
            run.clock.now(), step="B5", sub=f"round:{rnd}",
        )  # fmt: skip
        if all(c.final_state is not None for c in view):
            final, agg = aggregate_children(view)  # P10 — D-30: không exit_code, không close_reason
            done: dict[str, Any] = {"aggregate_status": agg, "parent_round": rnd, "conversation": [digest.msg]}
            if final == S_RESOLVED:
                return await goto(state, S_RESOLVED, next_node="b20_audit", step="B5", event="children_aggregated", **done)
            if final == S_REJECTED:
                return await goto(state, S_REJECTED, next_node="b20_audit", step="B5", event="children_aggregated", **done)
            return await goto(state, S_ESCALATED, next_node="b20_audit", step="B5", event="children_aggregated", **done)
        awaiting = {c.child_id: needs_of(c) for c in view if c.final_state is None}
        kind = "clarify" if "answer" in awaiting.values() else "confirm"
        hours = deps.constants.CLARIFY_TIMEOUT_HOURS if kind == "clarify" else deps.constants.CONFIRM_TIMEOUT_HOURS
        await effects.once(
            state, "deadline_set", deps.deadlines.set, state["ticket_id"], kind, run.clock.now() + timedelta(hours=hours),
            run.turn_id, step="B5", sub=f"round:{rnd}",
        )  # fmt: skip
        return await goto(
            state, S_CONFIRMING, next_node="parent_reply_wait", step="B5", event="digest_sent", parent_round=rnd,
            awaiting=awaiting, conversation=[digest.msg],
        )  # fmt: skip

    return parent_wait
