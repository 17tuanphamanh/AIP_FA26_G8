"""Route ticket (P10 "Phải có"; B01 mục 2, B02 mục 2, B19 mục 2; 2b-3).

`POST /api/tickets` → 202: privacy guard (D-07) → `tickets.create` (ticket + lượt `submit`, MỘT
transaction, `created_at` từ Clock của app) → `runner.run_new` chạy nền.

`POST /api/tickets/{id}/messages` | `/confirm` → 202, thứ tự kiểm CHỐT (2b-3 a, b):
  413 (middleware) → quyền (`require`) → không có / không đọc được → 404 (giống hệt nhau) → không phải
  chủ → 403 → ticket con → 409 → body sai → 422 → guard → `start_event` (409 sự kiện muộn / 503 bận).
  Bị từ chối ở 403/404: chỉ ghi `permission_denied` (404 id giả: không ghi gì), không gọi guard,
  không ghi `turns`/`late_event`.

`GET /api/tickets/{id}` → `TicketView`: đã có `final_state` thì `status` lấy từ `tickets`, còn mở thì từ
checkpoint; `waiting_for` CHỈ từ checkpoint; đọc checkpoint lỗi → 503 (không đoán).
"""

import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.desk import Desk, get_desk, parse_body
from app.auth.authz import can_read_ticket
from app.auth.deps import deny, require
from app.auth.models import Principal
from app.core.ids import new_ticket_id, new_turn_id
from app.db.tickets import NewTicket, TicketRow
from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_NEW
from app.graph.late_event import start_event

log = logging.getLogger(__name__)
router = APIRouter()

TEXT_MAX = 4000
NOTE_MAX = 1000
CHILD_MESSAGE = "Vui lòng trả lời trong hội thoại chung"  # P1 mục 6.1, D-31
NOT_FOUND = "not_found"

type WaitingFor = Literal["clarify", "approval", "confirm", "reply"]
WAITING_FOR: dict[str, WaitingFor] = {
    "clarify_wait": "clarify", "approval_wait": "approval", "confirm_wait": "confirm",
    "parent_reply_wait": "reply",
}  # fmt: skip


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=TEXT_MAX)


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=TEXT_MAX)


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class Accepted(BaseModel):
    ticket_id: str
    status: str


class TicketView(BaseModel):
    """Đúng tập trường trả cho người dùng — không lộ state nội bộ khác của checkpoint."""

    ticket_id: str
    status: str
    waiting_for: WaitingFor | None
    conversation: list[dict[str, Any]]
    exit_code: str | None
    close_reason: str | None
    final_state: str | None
    created_at: datetime
    closed_at: datetime | None


def _accepted(ticket_id: str, status: str) -> JSONResponse:
    return JSONResponse(Accepted(ticket_id=ticket_id, status=status).model_dump(), status_code=202)


async def _readable(request: Request, p: Principal, desk: Desk, ticket_id: str) -> TicketRow:
    """Không có, hoặc có mà không được đọc → CÙNG một 404 (không lộ ticket tồn tại — D-02, TC30)."""
    row = await desk.tickets.get(ticket_id)
    if row is None:
        raise HTTPException(404, NOT_FOUND)
    if not can_read_ticket(p, row):
        await deny(request, p, "ticket:read:any", ticket_id=ticket_id)
        raise HTTPException(404, NOT_FOUND)
    return row


async def _owned_leaf(
    request: Request, p: Principal, desk: Desk, ticket_id: str, perm: str
) -> TicketRow:
    row = await _readable(request, p, desk, ticket_id)
    if row.requester_id != p.user_id:  # đọc được (l1, l2…) nhưng không phải chủ ticket
        await deny(request, p, perm, ticket_id=ticket_id, reason="not_owner")
        raise HTTPException(403, "forbidden")
    if row.parent_ticket_id is not None:
        raise HTTPException(409, CHILD_MESSAGE)
    return row


@router.post("/api/tickets", status_code=202)
async def create_ticket(
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:create"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    body = await parse_body(request, TicketIn)
    redacted = await desk.guard.redact(body.text)
    user = await desk.users.get_user(p.user_id)
    ticket_id, turn_id = new_ticket_id(), new_turn_id()
    await desk.tickets.create(
        NewTicket(
            ticket_id=ticket_id, requester_id=p.user_id, requester_role=p.role,
            requester_dept=user.department if user else None, session_id=p.session_id,
            redacted_request=redacted.text, created_at=desk.clock.now(),
        ),
        turn_id=turn_id,
    )  # fmt: skip
    desk.background.spawn(desk.runner.run_new(ticket_id, turn_id), name=f"submit:{ticket_id}")
    return _accepted(ticket_id, S_NEW)


@router.get("/api/tickets/{ticket_id}", response_model=TicketView)
async def read_ticket(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:read:own"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> TicketView:
    row = await _readable(request, p, desk, ticket_id)
    try:
        snap = await desk.runner.snapshot(ticket_id)
    except Exception:
        log.exception("đọc checkpoint của ticket %s lỗi", ticket_id)
        raise HTTPException(503, "checkpoint_unavailable") from None
    values = snap.values or {}
    return TicketView(
        ticket_id=ticket_id,
        status=row.final_state or values.get("status") or S_NEW,
        waiting_for=WAITING_FOR.get(snap.next[0]) if snap.next else None,
        conversation=list(values.get("conversation") or []),
        exit_code=row.exit_code, close_reason=row.close_reason, final_state=row.final_state,
        created_at=row.created_at, closed_at=row.closed_at,
    )  # fmt: skip


@router.post("/api/tickets/{ticket_id}/messages", status_code=202)
async def post_message(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:message"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    await _owned_leaf(request, p, desk, ticket_id, "ticket:message")
    body = await parse_body(request, MessageIn)
    redacted = await desk.guard.redact(body.text)
    await start_event(
        desk.runner, ticket_id, S_CLARIFYING, {"kind": "user_reply", "text": redacted.text},
        spawn=desk.background.spawn, session_id=p.session_id,
    )  # fmt: skip
    return _accepted(ticket_id, S_CLARIFYING)


@router.post("/api/tickets/{ticket_id}/confirm", status_code=202)
async def confirm(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:confirm"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    await _owned_leaf(request, p, desk, ticket_id, "ticket:confirm")
    body = await parse_body(request, ConfirmIn)
    note = (await desk.guard.redact(body.note)).text if body.note else None
    event = {"kind": "confirmed" if body.confirmed else "unresolved", "note": note}
    await start_event(
        desk.runner, ticket_id, S_CONFIRMING, event, spawn=desk.background.spawn,
        session_id=p.session_id,
    )  # fmt: skip
    return _accepted(ticket_id, S_CONFIRMING)
