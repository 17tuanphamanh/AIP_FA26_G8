"""goto() — cổng đổi trạng thái duy nhất (P1 mục 5.1, 5.1.1; bất biến 3).

1. `check_transition` (domain): FORBIDDEN (6 chuyển cấm [Chốt 2.2]) kiểm TRƯỚC và luôn thắng
   `is_allowed` (bảng 2.1 + 3 quy tắc D-29).
2. Ghi `audit_logs` idempotent: khoá sha256(ticket_id|step|event|turn_id|loop_seq) (D-14 v1.2).
3. Cấm 4 đầy đủ: sang `S_RESOLVED` mà không có dòng audit (kiểm trong cùng transaction với INSERT)
   → `IllegalTransition(F4)`. Ở domain chỉ kiểm được step/event không rỗng.
4. Key trả về phải thuộc `TicketState` (`UnknownStateKey`) — kiểm TRƯỚC khi ghi audit. LangGraph bỏ im
   lặng key lạ; ví dụ mã giả B10/B17 đặt `resolution_path` (không có trong state) sẽ mất dữ liệu.
5. `lineage=` (3g, Q-3g-3): các trường prompt/model/`kb_version` của bước (B10; B12 ở 3h) — goto thêm `ticket_id`,
   `turn_id`, `step`, `created_at` rồi audit ghi dòng `lineage` TRONG CÙNG transaction với dòng audit (idempotent theo
   ticket, lượt, bước, prompt). Không đi vào state.
6. `audit_columns=` (Phase 4 4b P10): cột điểm log KHÔNG phải khoá `TicketState` (người duyệt, hạn, xung đột — B15; thời gian
   phản hồi — B16). Chỉ nhận khoá trong `_POINT_COLUMNS`; khoá khác → `ValueError` TRƯỚC khi ghi audit. Không vào state.
   Hàm chép trường state sang cột cùng tên đổi tên `audit_columns` → `_state_columns` (tránh trùng tên tham số).

Lỗi ở đây (IllegalTransition) là bug → lọt tới boundary thành E9 (P1 mục 10).
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from app.core.hashing import sha256_key
from app.domain.states import S_RESOLVED, IllegalTransition, check_transition
from app.domain.ticket_state import check_state_keys
from app.graph.context import current_run

# Trường state → cột audit_logs cùng tên (P7 2.7, B20 mục 0.3). Trường khác (ghi chú escalate…)
# vào `detail`. `risk` bung ra các cột điểm log 4.
_SAME_NAME_COLUMNS = frozenset({
    "intended_action", "exit_code", "block_reason", "close_reason", "intent",
    "approval_result", "action_plan_hash", "approver_id", "note", "kb_version",
})  # fmt: skip
# `screening`, `security_flag` (3e): audit bước B2 mang lớp quyết định — M9 tính tỉ lệ xuống L4 (B02 mục 9).
_DETAIL_FIELDS = frozenset({
    "escalation_note", "escalation_reason_detail", "aggregate_status", "screening", "security_flag",
})  # fmt: skip
_RISK_COLUMNS = (
    "decided_by", "policy_decision", "risk_level", "reason", "matched_rule_id",
    "calibrated_prob", "raw_prob", "p_method",
)  # fmt: skip
# Cột điểm log truyền thẳng qua `audit_columns=` (4b P10) — không phải trường state.
_POINT_COLUMNS = frozenset({"approver_id", "deadline", "conflict_detected", "response_time_seconds"})


def _json(value: Any) -> Any:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def audit_key(ticket_id: str, step: str, event: str, turn_id: str, loop_seq: int) -> str:
    return sha256_key(ticket_id, step, event, turn_id, loop_seq)


def _state_columns(fields: Mapping[str, Any]) -> dict[str, Any]:
    cols: dict[str, Any] = {k: _json(v) for k, v in fields.items() if k in _SAME_NAME_COLUMNS}
    risk = fields.get("risk")
    if risk is not None:
        data = _json(risk)
        cols.update({k: data.get(k) for k in _RISK_COLUMNS if data.get(k) is not None})
    return cols


async def goto(
    state: Mapping[str, Any],
    to_status: str,
    *,
    next_node: str,
    step: str,
    event: str,
    audit_detail: Mapping[str, Any] | None = None,
    lineage: Mapping[str, Any] | None = None,
    audit_columns: Mapping[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    if audit_columns is not None and (unknown := sorted(set(audit_columns) - _POINT_COLUMNS)):
        raise ValueError(f"goto: audit_columns lạ {unknown} — chỉ nhận {sorted(_POINT_COLUMNS)} (4b P10)")
    run = current_run()
    frm = state["status"]
    check_state_keys(("status", "next", *fields))
    check_transition(
        state, frm, to_status, step=step, event=event, fields=fields,
        rediagnose_on_new_slot=run.rediagnose_on_new_slot,
    )  # fmt: skip
    loop_seq = int(fields.get("reasoning_loops", state.get("reasoning_loops", 0)) or 0)
    detail = {k: fields[k] for k in _DETAIL_FIELDS if fields.get(k) is not None}
    detail.update(audit_detail or {})
    row = {
        "ticket_id": state["ticket_id"],
        "turn_id": run.turn_id,
        "loop_seq": loop_seq,
        "idempotency_key": audit_key(state["ticket_id"], step, event, run.turn_id, loop_seq),
        "step": step,
        "event": event,
        "from_status": frm,
        "to_status": to_status,
        "created_at": run.clock.now(),
        "detail": detail,
        **_state_columns(fields),
        **{k: _json(v) for k, v in (audit_columns or {}).items()},
    }
    if lineage is None:
        present = await run.audit.record(row)
    else:
        present = await run.audit.record(row, lineage={
            **lineage, "ticket_id": state["ticket_id"], "turn_id": run.turn_id, "step": step, "created_at": row["created_at"],
        })  # fmt: skip
    if to_status == S_RESOLVED and not present:
        raise IllegalTransition(frm, to_status, "F4_resolved_without_log")
    return {"status": to_status, "next": next_node, **fields}
