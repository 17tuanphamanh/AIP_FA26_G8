"""Route ticket (P10 "Phải có"; B01 mục 2, B02 mục 2, B19 mục 2; 2b-3).

`POST /api/tickets` → 202: privacy guard (D-07) → `tickets.create` (ticket + lượt `submit` + sự kiện
`privacy_secret_redacted` nếu có, MỘT transaction, `created_at` từ Clock của app) → `runner.run_new` chạy nền.

Privacy guard (3e, phase3 mục 8.3): guard lỗi → 503 `{"error":"privacy_guard_unavailable"}`, không INSERT, không
`start_event`. Body 202 có `notices` (thông báo đã che bí mật/PII). Tin nhắn sau có bí mật → `privacy_secret_redacted`
ghi TRƯỚC `start_event` (lỗi ghi → 503).

`POST /api/tickets/{id}/messages` | `/confirm` → 202, thứ tự kiểm CHỐT (2b-3 a, b):
  413 (middleware) → quyền (`require`) → không có / không đọc được → 404 (giống hệt nhau) → không phải
  chủ → 403 → ticket con → 409 → body sai → 422 → guard → `start_event` (409 sự kiện muộn / 503 bận).
  Bị từ chối ở 403/404: chỉ ghi `permission_denied` (404 id giả: không ghi gì), không gọi guard,
  không ghi `turns`/`late_event`.

`GET /api/tickets/{id}` → `TicketView`: đã có `final_state` thì `status` lấy từ `tickets`, còn mở thì từ
checkpoint; `waiting_for` CHỈ từ checkpoint; đọc checkpoint lỗi → 503 (không đoán).

`POST /api/tickets/{id}/override` → 201 (Phase 4 4d P1–P4, TC23; PLAN-4d 2.1): người có `decision:override` ghi lại "đáng lẽ quyết
khác" cho ticket ĐÃ kết thúc — KHÔNG đổi kết quả ticket (một dòng `audit_logs` `step="OVERRIDE"` qua `desk.approvals.record_override`;
không đụng `tickets`, checkpoint, lượt, `start_event`, executor). Thứ tự: 413 → quyền → đăng nhập lại ≤ 10 phút (`recent_login`, 403
`reauth_required`) → 404 (không có / không đọc được) → người gửi tự ghi đè 403 + `permission_denied` → còn mở 409 `ticket_open` → body
422 (`other` thiếu note → `fields: ["note"]`) → trùng quyết định gốc (server suy từ audit, P3) 422 `same_as_original` → guard trên
`note` (503; có bí mật → `privacy_secret_redacted`) → `other` mà note rỗng SAU khi che 422 → ghi; người này đã ghi đè → 409
`already_overridden` (khoá idempotency theo ticket + người, quyết bằng INSERT).
"""

import json
import logging
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from langgraph.types import StateSnapshot
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.desk import (
    SECRET_EVENT,
    Desk,
    get_desk,
    parse_body,
    record_redacted,
    redact,
    redact_reply_items,
)
from app.api.errors import InvalidRequest, error_fields
from app.auth.authz import can_override, can_read_ticket
from app.auth.deps import deny, require
from app.auth.models import Principal
from app.core.ids import new_ticket_id, new_turn_id
from app.db.tickets import NewTicket, TicketRow
from app.domain.children import children_progress
from app.domain.messages import child_title
from app.domain.override import (
    Decision,
    OverrideReason,
    OverrideRecord,
    original_decision,
)
from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_NEW
from app.graph.late_event import InvalidReply, Validate, start_event

log = logging.getLogger(__name__)
router = APIRouter()

TEXT_MAX = 4000
NOTE_MAX = 1000
CHILD_MESSAGE = "Vui lòng trả lời trong hội thoại chung"  # P1 mục 6.1, D-31
_CHILD_INDEX = re.compile(r"[0-9]{1,2}")  # khoá `items` của `/reply` = id con `<cha>-<i>`: phần sau `<cha>-` CHỈ là số (T20b, soát lượt 4)
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


class ReplyAnswer(BaseModel):
    """Một ý `needs=answer` của `/reply` (T20b P11, 5.2.6)."""

    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=TEXT_MAX)


class ReplyConfirm(BaseModel):
    """Một ý `needs=confirm` của `/reply` — "Đã ổn" / "Chưa ổn" + ghi chú."""

    model_config = ConfigDict(extra="forbid")
    confirmed: bool
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class ReplyIn(BaseModel):
    """`{items: {[child_id]: {answer} | {confirmed, note?}}}` — `extra="forbid"` mọi tầng (5.2.6)."""

    model_config = ConfigDict(extra="forbid")
    items: dict[str, ReplyAnswer | ReplyConfirm] = Field(min_length=1)


class OverrideIn(BaseModel):
    """4d P2: mã cố định (không chữ tự do ngoài `note`, mà `note` qua privacy guard trước khi vào audit)."""

    model_config = ConfigDict(extra="forbid")
    override_decision: Decision
    reason_code: OverrideReason
    note: str | None = Field(default=None, max_length=NOTE_MAX)  # BẮT BUỘC khi reason_code="other" (kiểm trong route)


class Accepted(BaseModel):
    ticket_id: str
    status: str
    notices: list[str] = []  # phase3 mục 8.3 — nguyên văn `RedactionResult.notices`


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
    # T20b P11 (5.2.6): ticket cha → tiến độ từng ý (chỉ từ DB + checkpoint CHA); ticket thường/con → None
    children_progress: list[dict[str, Any]] | None = None


def _accepted(ticket_id: str, status: str, notices: list[str]) -> JSONResponse:
    body = Accepted(ticket_id=ticket_id, status=status, notices=notices)
    return JSONResponse(body.model_dump(), status_code=202)


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
    redacted = await redact(desk, request, body.text)
    user = await desk.users.get_user(p.user_id)
    ticket_id, turn_id = new_ticket_id(), new_turn_id()
    await desk.tickets.create(
        NewTicket(
            ticket_id=ticket_id, requester_id=p.user_id, requester_role=p.role,
            requester_dept=user.department if user else None, session_id=p.session_id,
            redacted_request=redacted.text, created_at=desk.clock.now(),
        ),
        turn_id=turn_id,
        security_events=[(SECRET_EVENT, {"count": redacted.secrets_found})] if redacted.secrets_found else (),
    )  # fmt: skip
    desk.background.spawn(desk.runner.run_new(ticket_id, turn_id), name=f"submit:{ticket_id}")
    return _accepted(ticket_id, S_NEW, redacted.notices)


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
    progress = None
    if row.is_parent:  # T20b P11: chỉ DB (`children_progress_rows`) + checkpoint CHA (danh sách con, seed, `awaiting`)
        children = list(values.get("children") or [])
        seeds = values.get("child_seeds") or {}
        awaiting = values.get("awaiting") if snap.next == ("parent_reply_wait",) else None
        progress = children_progress(
            await desk.tickets.children_progress_rows(ticket_id, children),
            {cid: child_title(seeds.get(cid) or {}) for cid in children}, awaiting,
        )  # fmt: skip
    return TicketView(
        ticket_id=ticket_id,
        status=row.final_state or values.get("status") or S_NEW,
        waiting_for=WAITING_FOR.get(snap.next[0]) if snap.next else None,
        conversation=list(values.get("conversation") or []),
        exit_code=row.exit_code, close_reason=row.close_reason, final_state=row.final_state,
        created_at=row.created_at, closed_at=row.closed_at, children_progress=progress,
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
    redacted = await redact(desk, request, body.text)
    await record_redacted(desk, request, p, ticket_id, redacted)
    await start_event(
        desk.runner, ticket_id, S_CLARIFYING, {"kind": "user_reply", "text": redacted.text},
        spawn=desk.background.spawn, session_id=p.session_id,
    )  # fmt: skip
    return _accepted(ticket_id, S_CLARIFYING, redacted.notices)


@router.post("/api/tickets/{ticket_id}/confirm", status_code=202)
async def confirm(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:confirm"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    await _owned_leaf(request, p, desk, ticket_id, "ticket:confirm")
    body = await parse_body(request, ConfirmIn)
    redacted = await redact(desk, request, body.note) if body.note else None
    if redacted is not None:
        await record_redacted(desk, request, p, ticket_id, redacted)
    note = redacted.text if redacted is not None else None
    event = {"kind": "confirmed" if body.confirmed else "unresolved", "note": note}
    await start_event(
        desk.runner, ticket_id, S_CONFIRMING, event, spawn=desk.background.spawn,
        session_id=p.session_id,
    )  # fmt: skip
    return _accepted(ticket_id, S_CONFIRMING, redacted.notices if redacted is not None else [])


async def _reply_body(request: Request, parent_id: str) -> ReplyIn:
    """Như `parse_body` (422 chỉ vị trí trường) + chặn khoá `items` không có dạng `<cha>-<i>` TRƯỚC khi kiểm hình dạng, với vị trí CHUNG
    `body.items` — khoá dict là chữ tự do của người gửi chưa qua guard, không được dội lại trong 422 (soát DỪNG 2 mục 6). Sau bước này mọi
    vị trí trường nêu tên đều là id do hệ thống sinh (`<cha>-<số>`)."""
    raw = await request.body()
    try:
        data: Any = json.loads(raw) if raw else None
    except ValueError:
        raise InvalidRequest([]) from None
    items = data.get("items") if isinstance(data, dict) else None
    prefix = f"{parent_id}-"
    if isinstance(items, dict) and any(not (k.startswith(prefix) and _CHILD_INDEX.fullmatch(k[len(prefix):])) for k in items):
        raise InvalidRequest(["body.items"])
    try:
        return ReplyIn.model_validate(data)
    except ValidationError as exc:
        raise InvalidRequest(error_fields(exc.errors(include_url=False, include_input=False))) from None


def _items_match(items: dict[str, dict[str, Any]]) -> Validate:
    """Kiểm DƯỚI khoá cha (P11, chốt (c) — chặt): `items` ≡ ĐÚNG tập `awaiting`, mỗi ý đúng loại theo `needs` (`answer` ↔ `{answer}`,
    `confirm` ↔ `{confirmed, note?}`). Lệch → `InvalidReply` (vị trí trường, sắp theo id) — không giao gì, không `late_event`."""

    def check(snap: StateSnapshot) -> None:
        awaiting: dict[str, str] = dict(snap.values.get("awaiting") or {})
        bad = {cid for cid in items.keys() ^ awaiting.keys()}
        bad |= {cid for cid in items.keys() & awaiting.keys() if ("answer" in items[cid]) != (awaiting[cid] == "answer")}
        if bad:
            raise InvalidReply([f"body.items.{cid}" for cid in sorted(bad)])

    return check


@router.post("/api/tickets/{ticket_id}/reply", status_code=202)
async def reply(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:message"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    """T20b P11 (5.2.6): người dùng trả lời MỘT lần cho mọi ý của tin tổng hợp. Thứ tự kiểm như `/messages`: 413 → quyền → 404 → 403
    (không phải chủ) → 409 `CHILD_MESSAGE` (gọi vào ticket con) → 422 hình dạng body → privacy guard TỪNG `answer`/`note` (503 khi guard
    lỗi; bí mật → MỘT sự kiện `privacy_secret_redacted {count}` tổng) → `start_event(S_CONFIRMING, {"kind":"reply","items":…},
    wait_node="parent_reply_wait", validate=…)`: không ở `parent_reply_wait` (kể cả ticket thường) → 409 + `late_event`; `items` ≠ đúng
    `awaiting` → 422 `{error:"invalid_request", fields:["body.items.<child_id>"]}`. Tin người dùng ghép do NODE ghi (P8), không do route."""
    await _owned_leaf(request, p, desk, ticket_id, "ticket:message")
    body = await _reply_body(request, ticket_id)
    redacted = await redact_reply_items(desk, request, body.items)  # Q-T20b-8: che TỪNG answer/note — test AST N1 tin như `redact`
    await record_redacted(desk, request, p, ticket_id, redacted.result)
    try:
        await start_event(
            desk.runner, ticket_id, S_CONFIRMING, {"kind": "reply", "items": redacted.items}, spawn=desk.background.spawn,
            session_id=p.session_id, wait_node="parent_reply_wait", validate=_items_match(redacted.items),
        )  # fmt: skip
    except InvalidReply as exc:
        raise InvalidRequest(exc.fields) from None
    return _accepted(ticket_id, S_CONFIRMING, redacted.result.notices)


@router.post("/api/tickets/{ticket_id}/override", status_code=201)
async def override(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("decision:override", recent_login=True))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    row = await _readable(request, p, desk, ticket_id)
    if not can_override(p, row):  # người gửi tự ghi đè
        await deny(request, p, "decision:override", ticket_id=ticket_id, reason="self_override")
        raise HTTPException(403, "forbidden")
    if row.final_state is None:
        raise HTTPException(409, "ticket_open")
    body = await parse_body(request, OverrideIn)
    if body.reason_code == "other" and not (body.note and body.note.strip()):
        raise InvalidRequest(["note"])
    original = original_decision(await desk.approvals.decision_trail(ticket_id))
    if body.override_decision == original:
        raise HTTPException(422, "same_as_original")  # trước guard: yêu cầu chắc chắn bị từ chối thì không gửi note qua guard
    redacted = await redact(desk, request, body.note) if body.note else None
    if redacted is not None:
        await record_redacted(desk, request, p, ticket_id, redacted)
    note = redacted.text if redacted is not None and redacted.text.strip() else None
    if body.reason_code == "other" and note is None:  # chỉ ký tự vô hình → che xong rỗng (khuôn soát 4c S4b)
        raise InvalidRequest(["note"])
    rec = OverrideRecord(
        ticket_id=ticket_id, overrider_id=p.user_id, original_decision=original, override_decision=body.override_decision,
        reason_code=body.reason_code, note=note, created_at=desk.clock.now(),
    )  # fmt: skip
    if not await desk.approvals.record_override(rec):  # trùng khoá (ticket, người) — quyết bằng kết quả INSERT, không kiểm trước
        raise HTTPException(409, "already_overridden")
    return JSONResponse({
        "ticket_id": ticket_id, "original_decision": original, "override_decision": body.override_decision,
        "reason_code": body.reason_code, "notices": redacted.notices if redacted is not None else [],
    }, status_code=201)  # fmt: skip
