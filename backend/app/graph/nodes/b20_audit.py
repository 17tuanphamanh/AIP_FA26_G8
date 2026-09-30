"""B20 — ghi kết quả cuối, điểm log 8, escalate L2 (B20 mục 2, 5, 5.1; D-18, D-27, D-30).

Thứ tự (lệch mã giả có chủ đích — quyết định Q-C 2b-2):
1. `finalize_once` TRƯỚC: `UPDATE tickets … WHERE final_state IS NULL`, trả dòng ĐANG CÓ trong DB.
2. Điểm log 8 ghi từ CHÍNH dòng đó (khoá idempotent theo lượt). Mã giả ghi audit trước: B20 lỗi giữa
   hai bước rồi chạy lại sau vài phút thì audit giữ `total_duration` lần 1, `tickets` giữ lần sau — hai
   nguồn lệch nhau. Làm ngược lại thì audit và `tickets` luôn giống hệt.
3. Có `exit_code` (cha không bao giờ có — D-30): `effects.once("escalation_create")` (priority lấy từ
   bảng `exit_code_priority`, ghi chú bàn giao 4 phần theo mẫu) + `effects.once("notify_user")` với tin
   theo mã [Chốt 7.1]. Tin nằm trong `conversation` của checkpoint (không thêm bảng): trả về cùng lượt
   nên chạy lại cũng chỉ có một tin.

Không làm ở đây: `wake_parent` (runner gọi SAU khi nhả khoá ticket con — tránh deadlock, 2b-Q7);
cảnh báo E0/E7/E9 (M9 Phase 7, P9 luật 2, 4); hộp thư `child_notices` của ticket con (Phase 5).
Exception ở đây: boundary ghi audit rồi ném tiếp → worker chạy lại, có giới hạn (2b-Q6).
"""

from typing import Any

from langgraph.graph import END

from app.audit.final import summarize_final
from app.audit.handoff import build_handoff, is_deny_case
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import audit_key
from app.graph.tracing import NodeFn

POINT_8_EVENT = "closed"


def make(deps: NodeDeps) -> NodeFn:
    async def b20_audit(state: Any) -> dict[str, Any]:
        run = current_run()
        ticket_id = state["ticket_id"]
        now = run.clock.now()
        summary = summarize_final(
            state, created_at=await deps.tickets.created_at(ticket_id),
            total_turns=await deps.tickets.count_turns(ticket_id), now=now,
        )  # fmt: skip
        stored = await deps.tickets.finalize_once(ticket_id, summary)

        loop_seq = int(state.get("reasoning_loops", 0) or 0)
        await run.audit.record({
            "ticket_id": ticket_id, "turn_id": run.turn_id, "loop_seq": loop_seq,
            "idempotency_key": audit_key(ticket_id, "B20", POINT_8_EVENT, run.turn_id, loop_seq),
            "step": "B20", "event": POINT_8_EVENT, "from_status": state["status"],
            "to_status": state["status"], "created_at": now,
            "final_state": stored.final_state, "exit_code": stored.exit_code,
            "block_reason": stored.block_reason, "close_reason": stored.close_reason,
            "total_turns": stored.total_turns,
            "total_duration_seconds": stored.total_duration_seconds,
            "detail": {"resolution_path": stored.resolution_path,
                       "aggregate_status": stored.aggregate_status},
        })  # fmt: skip

        update: dict[str, Any] = {"next": END}
        code = state.get("exit_code")
        if code and not state.get("is_parent"):
            await effects.once(
                state, "escalation_create", deps.escalations.create, step="B20",
                ticket_id=ticket_id, exit_code=code,
                reason_detail=state.get("escalation_reason_detail"),
                handoff_note=build_handoff(
                    state, deps.templates, retrieval_threshold=deps.constants.RETRIEVAL_THRESHOLD
                ).model_dump(),  # S0-A1: tài liệu dưới ngưỡng ghi rõ "không dùng làm căn cứ"
                is_deny_case=is_deny_case(code), created_at=now,
            )  # fmt: skip
            text = deps.templates.of(code).user_message
            ref = await effects.once(
                state, "notify_user", deps.notifier.notify_user, ticket_id, text, "none", step="B20"
            )
            update["conversation"] = [
                {"role": "assistant", "kind": "escalation", "text": text, "ref": ref}
            ]
        return update

    return b20_audit
