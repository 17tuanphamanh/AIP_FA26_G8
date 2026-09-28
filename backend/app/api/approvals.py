"""`POST /api/approvals/{id}/decision` — đúng handler B15-B16 mục 5 (2b-Q3, 2b-3 chốt e, f).

Thứ tự:
1. 413 (middleware) → `require("approval:decide")` (L2, employee → 403).
2. Transaction NGẮN `lock_row` (`FOR UPDATE`, chỉ đọc + kiểm):
   - không có phiếu → 404;
   - `may_decide_as` sai (không phải người được giao, xung đột lợi ích) → 403 + `permission_denied`;
   - phiếu không còn `pending` → `already_decided`; `clock.now() >= deadline` (Clock của APP, bằng hạn
     là muộn) → `expired` → `record_late` + 409 (TC27).
3. Body: `rejected` thiếu `note` → 422.
4. Privacy guard trên `note` (3e, phase3 mục 8.3): lỗi → 503, có bí mật → `privacy_secret_redacted` trước
   `start_event`; body 202 thêm `notices` (PLAN-3e Q-3e-6).
5. `start_event(S_PENDING_APPROVAL)` → 202. Route KHÔNG ghi quyết định: B16 ghi (`approvals.close` có
   điều kiện) khi graph chạy — trước đó phiếu vẫn `pending`. `approver_id` chỉ lấy từ token.

Bấm muộn KHÔNG đổi `approvals.status` (quyết định 2b-3 Q2 — lệch câu "phiếu `late_ignored`" của B15
mục 10): phiếu `pending` quá hạn phải còn `pending` để worker bắn timeout (E6); đổi đi thì ticket kẹt
ở `S_PENDING_APPROVAL` mãi mãi. Dấu vết bấm muộn nằm ở audit `late_event` (`reason`, `approval_id`,
`clicked_by`).

`view_started_at` tuỳ chọn, chỉ ghi log; `view_duration` tính phía server từ `first_viewed_at` (route xem
phiếu ở Phase 4 mới ghi cột này → 2b luôn None). Lệch B15 mục 4 (`DecisionIn` bắt buộc) — ghi PROGRESS.
"""

import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.desk import Desk, get_desk, parse_body, record_redacted, redact
from app.auth.authz import ApprovalParties, may_decide_as
from app.auth.deps import deny, require
from app.auth.models import Principal
from app.domain.states import S_PENDING_APPROVAL
from app.graph.late_event import record_late, start_event

log = logging.getLogger(__name__)
router = APIRouter()

NOTE_MAX = 1000
type LateReason = Literal["expired", "already_decided"]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    reason_code: str | None = Field(default=None, max_length=64)
    view_started_at: datetime | None = None  # tuỳ chọn; chỉ log


def _action_targets(values: dict[str, Any]) -> list[str]:
    action = values.get("intended_action")
    if action is None:
        return []
    return [str(t) for t in (getattr(action, "target", None), getattr(action, "requested_for", None)) if t]


@router.post("/api/approvals/{approval_id}/decision", status_code=202)
async def decide(
    approval_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("approval:decide"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    now = desk.clock.now()
    late: LateReason | None = None
    async with desk.approvals.lock_row(approval_id) as a:
        if a is None:
            raise HTTPException(404, "not_found")
        ticket = await desk.tickets.get(a.ticket_id)
        me = await desk.users.get_user(p.user_id)
        snap = await desk.runner.snapshot(a.ticket_id)
        parties = ApprovalParties(
            requester_id=ticket.requester_id if ticket else "",
            approver_manager_id=me.manager_id if me else None,
            action_targets=_action_targets(dict(snap.values or {})),
        )  # fmt: skip
        if not may_decide_as(p, a, parties):
            await deny(request, p, "approval:decide", approval_id=approval_id)
            raise HTTPException(403, "forbidden")
        if a.status != "pending":
            late = "already_decided"
        elif now >= a.deadline:
            late = "expired"
        ticket_id, actual = a.ticket_id, (snap.values or {}).get("status")
        first_viewed_at = a.first_viewed_at
    if late is not None:
        await record_late(
            desk.runner, ticket_id, expected_status=S_PENDING_APPROVAL, actual_status=actual,
            event_kind="decision", source="user",
            extra={"approval_id": approval_id, "clicked_by": p.user_id, "reason": late},
        )  # fmt: skip
        raise HTTPException(409, "Yêu cầu đã chuyển sang bước khác")

    body = await parse_body(request, DecisionIn)
    if body.decision == "rejected" and not (body.note and body.note.strip()):
        raise HTTPException(422, "rejected_requires_note")  # [Chốt cổng 4]
    redacted = await redact(desk, request, body.note) if body.note else None
    if redacted is not None:
        await record_redacted(desk, request, p, ticket_id, redacted)
    note = redacted.text if redacted is not None else None
    if body.view_started_at is not None:
        log.info("phiếu %s: client báo bắt đầu xem lúc %s (chỉ log)", approval_id, body.view_started_at)
    event = {
        "kind": body.decision, "note": note, "approver_id": p.user_id, "at": now.isoformat(),
        "reason_code": body.reason_code,
        "view_duration": (now - first_viewed_at).total_seconds() if first_viewed_at else None,
    }  # fmt: skip
    await start_event(
        desk.runner, ticket_id, S_PENDING_APPROVAL, event, spawn=desk.background.spawn,
        session_id=p.session_id,
        # ticket đã rời chờ duyệt (lượt duyệt khác vừa chạy xong) — vẫn đúng MỘT dòng late_event
        late_extra={"approval_id": approval_id, "clicked_by": p.user_id, "reason": "already_decided"},
    )  # fmt: skip
    notices = redacted.notices if redacted is not None else []
    return JSONResponse({"approval_id": approval_id, "ticket_id": ticket_id,
                         "status": "accepted", "notices": notices}, status_code=202)  # fmt: skip
