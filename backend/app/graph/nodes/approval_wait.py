"""Node chờ `S_PENDING_APPROVAL` + quyết định B16 — node CHUNG cho node giả lẫn node thật (Phase 4 4c, PLAN-4c TQ-1; khuôn
`confirm_wait` 3g). KHÔNG side effect nào trước `interrupt()` — resume chạy lại node từ đầu.

Hết hạn → E6, KHÔNG BAO GIỜ tự thực thi (bất biến 5; chuyển cấm 2 chặn mọi ca `approval_result != "approved"`).

Quyết định được ghi vào phiếu Ở ĐÂY (B15-B16 mục 5: `approvals.close` có điều kiện `status='pending'`, đặt `decided_at` ở cả 3
nhánh), không ở route duyệt: người duyệt (`approver_id`), lý do (`note`, `reason_code`), vai trò (`decided_as`) đến từ sự kiện mà
route dựng từ token + body (2b-3, 4c P4).

Sau `interrupt()`, thứ tự cố định (phase4 6.1 P1, P2):
1. Che L1 ghi chú bằng `redact_text` THUẦN (route đã che — node không tin đầu vào, khuôn `clarify_wait` Q-3g-4, TQ-2). Từ đây CHỈ
   bản đã che được ghi vào phiếu, cột `audit_logs.note`, tin nhắn (Q-4c-1).
2. `close` (trả 0/1 → `close_applied`) → đọc lại phiếu (`created_at`, `first_viewed_at`).
3. Từ chối: output guard trên ghi chú (vi phạm → bỏ câu "Ghi chú…", `note_suppressed=true`) → tin THEO MẪU (`domain.messages`,
   không LLM) qua `effects.once("notify_user", step="B16")` → `conversation` một tin `rejection` (D-31: một tin; B20 không gửi thêm
   vì nhánh này không có `exit_code`).
4. Điểm log 6 (cả 3 nhánh): cột `approval_result` (khoá state), `note` (chỉ từ chối) + `response_time_seconds` qua `audit_columns`
   (= `ev.at − phiếu.created_at`; timeout NULL); `detail` chỉ số/enum/bool: `view_duration`, `decided_without_view`, `decided_as`,
   `reason_code`, `close_applied` (+ `note_suppressed`). Nguồn (TQ-5): quyết định → sự kiện (route chụp dưới khoá lúc bấm); timeout →
   `first_viewed_at` của phiếu.
5. **Duyệt mà kế hoạch đã đổi (Phase 4 4d Q-4d-3, TC26):** SAU `close` (phiếu vẫn `approved` — đúng quyết định của người duyệt), TRƯỚC
   `goto(S_EXECUTING)`: `hash_action(intended_action)` phải bằng `state.action_plan_hash` (lớp state — đúng phép so của cấm F3) rồi bằng
   `approvals.action_plan_hash` (lớp phiếu — cái người duyệt đã xem, 4c P6). Lệch → E5 `action_plan_changed_since_approval` ở B16, dòng
   audit mang đủ điểm log 6 + `hash_source`, `hash_old`, `hash_new`, `action_plan_hash_matched=False`; B16 không gửi tin (B20 gửi mẫu
   E5). Thiếu hành động = bug → không so, để cấm F3 chặn → E9 như cũ. Cấm F3 và hai lớp của B17 giữ làm lớp sau.
"""

from datetime import datetime
from typing import Any

from langgraph.types import interrupt

from app.approval.store import ApprovalRow
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.exit_codes import CloseReason, ExitCode
from app.domain.messages import rejection_msg, rejection_text, target_phrase
from app.domain.states import S_ESCALATED, S_EXECUTING, S_REJECTED
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def _point6(ev: dict[str, Any], kind: str, a: ApprovalRow | None, applied: int) -> dict[str, Any]:
    if kind == "timeout":
        return {"view_duration": None, "decided_without_view": a is None or a.first_viewed_at is None,
                "decided_as": None, "reason_code": None, "close_applied": applied}  # fmt: skip
    view = ev.get("view_duration")
    return {"view_duration": view, "decided_without_view": view is None, "decided_as": ev.get("decided_as"),
            "reason_code": ev.get("reason_code"), "close_applied": applied}  # fmt: skip


def _response_time(ev: dict[str, Any], kind: str, a: ApprovalRow | None) -> float | None:
    at = ev.get("at")
    if kind == "timeout" or a is None or not at:
        return None
    return (datetime.fromisoformat(str(at)) - a.created_at).total_seconds()


def _plan_mismatch(state: Any, a: ApprovalRow | None) -> dict[str, Any] | None:
    """[5] Q-4d-3: lớp state trước, lớp phiếu sau (như B17); cả hai lệch → `state`. Không có phiếu → bỏ lớp phiếu (như B17)."""
    raw = state.get("intended_action")
    if raw is None:  # bug (B15 không tạo phiếu khi thiếu hành động) → cấm F3 → E9
        return None
    new, old = hash_action(raw), state.get("action_plan_hash")
    if not old or new != old:
        return {"hash_source": "state", "hash_old": old, "hash_new": new, "action_plan_hash_matched": False}
    if a is not None and a.action_plan_hash != new:
        return {"hash_source": "approval", "hash_old": a.action_plan_hash, "hash_new": new, "action_plan_hash_matched": False}
    return None


def make(deps: NodeDeps) -> NodeFn:
    async def approval_wait(state: Any) -> dict[str, Any]:
        ev = interrupt({"wait": "approval", "approval_id": state.get("approval_id")})
        kind = ev["kind"]
        raw_note = ev.get("note")  # `None` ≠ "" (soát 4c S4b: che xong rỗng vẫn là ghi chú — CHECK rejected_needs_note)
        note = deps.privacy.redact_text(str(raw_note)).text if raw_note is not None else None  # [1] TQ-2
        applied, a = 0, None
        if state.get("approval_id"):
            applied = await deps.approvals.close(
                state["approval_id"], kind, current_run().clock.now(), decided_by=ev.get("approver_id"), note=note,
            )  # fmt: skip
            a = await deps.approvals.get(state["approval_id"])
        detail = _point6(ev, kind, a, applied)
        columns: dict[str, Any] = {"response_time_seconds": _response_time(ev, kind, a)}
        if kind == "approved" and (changed := _plan_mismatch(state, a)) is not None:  # [5] Q-4d-3
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B16", event="action_plan_changed_since_approval",
                approval_result="approved", exit_code=ExitCode.E5.value,
                escalation_reason_detail="action_plan_changed_since_approval",
                audit_columns=columns, audit_detail={**detail, **changed},
            )  # fmt: skip
        if kind == "approved":
            return await goto(
                state, S_EXECUTING, next_node="b17_execute", step="B16", event="approved",
                approval_result="approved", audit_columns=columns, audit_detail=detail,
            )  # fmt: skip
        if kind == "rejected":
            return await _rejected(state, ev, note, columns, detail)
        return await goto(
            state, S_ESCALATED, next_node="b20_audit", step="B16", event="approval_timeout",
            approval_result="timeout", exit_code=ExitCode.E6.value, audit_columns=columns, audit_detail=detail,
        )  # fmt: skip

    async def _rejected(
        state: Any, ev: dict[str, Any], note: str | None, columns: dict[str, Any], detail: dict[str, Any]
    ) -> dict[str, Any]:
        raw = state.get("intended_action")
        action = None if raw is None else Action.model_validate(raw)
        shown = note if note and deps.output_guard.violation(note) is None else None  # [3] output guard; rỗng → không câu ghi chú
        who = state.get("requester_context")
        requester = RequesterContext.model_validate(who).user_id if who is not None else ""
        phrase = target_phrase(action, requester) if action else ""  # T20a P11 (TQ-16): không có hành động → câu chung
        text = rejection_text(action.type if action else "", phrase, ev.get("reason_code"), shown)
        ref = await effects.once(
            state, "notify_user", deps.notifier.notify_user, state["ticket_id"], text, "none", step="B16"
        )
        return await goto(
            state, S_REJECTED, next_node="b20_audit", step="B16", event="rejected",
            approval_result="rejected", close_reason=CloseReason.REJECTED_BY_APPROVER.value,
            conversation=[rejection_msg(text, ref)], audit_columns={**columns, "note": note},
            audit_detail={**detail, "note_suppressed": bool(note) and shown is None},
        )  # fmt: skip

    return approval_wait
