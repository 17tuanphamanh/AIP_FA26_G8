"""Hàng đợi L2 + đóng ca (P9 mục 7; B20 mục 4.1, 4.3, 5.1; P10 §3.4) — quyền `escalation:handle` (L1, L2 — P6 §5.3, NGU-CANH 2.2;
nhân viên, manager → 403).

`GET /api/escalations/queue?status=open|closed&limit=&after=` → `{items, next_cursor}` (P4 tuần 8):
- Thứ tự `priority, created_at, escalation_id` (`escalations.priority` từ seed `exit_code_priority`), chỉ ticket lá hoặc cha lỗi (D-30, T20b).
- `status` mặc định `open`; giá trị khác → 422. `limit` 1–100 (mặc định 50). Không trần tổng số dòng: duyệt hết bằng `next_cursor`.
- `after`/`next_cursor` là chuỗi MỜ: base64url (không `=`) của JSON `{v, s, p, t, i}` = phiên bản, `status`, vị trí keyset (priority,
  created_at, escalation_id) của dòng cuối trang trước. Sai dạng / khác `status` của query → 422 `fields: ["query.after"]`. Không ký: chỉ
  mang vị trí, sửa tay không mở thêm quyền hay dữ liệu. Keyset (không offset) → dòng bị đóng giữa hai trang không làm trùng/sót dòng khác.
- Ca đã đóng kèm `closed_at`, `close_result`, `closed_by`, `close_note` (bản ĐÃ che); ca mở → null.

`POST /api/escalations/{id}/close` thân `{close_result, note}` → 200 `EscalationCloseOut`. Thứ tự kiểm: 401 → 403 (`require`) → 422 thân
(`parse_body`, `fields` không tiền tố như mọi thân tự kiểm) → 404 `not_found` (id không có / hỏng) → 409 `already_closed` → 403 +
`permission_denied` khi người đóng là CHÍNH người gửi ticket (Q5a soát 12/11 — `authz.can_close_escalation`) → 422
`fields: ["close_result"]` (`completed` cho ca deny / E5 / E6 — `authz.can_close_escalation`) → privacy guard trên `note` (lỗi → 503;
bản che chỉ khoảng trắng hoặc > 1000 ký tự → 422 `fields: ["note"]`, KHÔNG cắt — cắt ngang có thể vỡ mặt nạ) → `close` MỘT transaction
(`db/escalations.SqlEscalationStore.close`); thua lần đóng đồng thời → 409.
D-99 (17/11/2026, Tuấn Anh chốt phần 1–5; luật thuần ở `domain/escalation_flow.py`):
- Hàng đợi nhận `tier=2|3` (mặc định 2). Đọc: người có `escalation:handle` HOẶC `escalation:handle:l3` (Trưởng IT). Mỗi dòng thêm người nhận,
  cấp, thông tin chuyển cấp, lời nhắn người dùng, `due_at` + `overdue` (hạn theo mức ưu tiên, theo đồng hồ server).
- `POST /api/escalations/{id}/claim` (không thân) → 200: nhận ca. 404 → 409 `already_closed` → 403 (sai cấp / chính người gửi) → 409
  `already_claimed` (người khác đã nhận) | `tier_changed` (ca vừa đổi cấp). Bấm lại khi chính mình đã nhận → 200, không đổi gì.
- `POST /api/escalations/{id}/raise` thân `{target: it_manager|vendor, note}` → 200: chuyển cấp 3. Chỉ từ cấp 2, người làm có
  `escalation:handle`, không phải người gửi; ca đã có người khác nhận → 409 `already_claimed`; đã ở cấp 3 → 409 `already_raised`. Ghi chú
  qua privacy guard như `note` của `/close`.
- `/close` thêm `user_message` (tuỳ chọn, 1–500 ký tự): che + qua `OutputGuard` (vi phạm → 422 `fields: ["user_message"]`). Ca cấp 3 chỉ
  Trưởng IT đóng; ca người khác đang nhận → 409 `already_claimed`.
- `reopened_as_new` làm phương án (A): SAU khi đóng ca, tạo ticket mới cùng người gửi + cùng nội dung đã che, chạy lại từ đầu, ghi
  `escalations.new_ticket_id`. Tạo lỗi → ca vẫn đóng, `new_ticket_id` null, log tên lớp lỗi (không chặn việc đóng ca).
"""

import base64
import binascii
import json
import logging
import re
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.alerts import ErrorDetail
from app.api.desk import Desk, get_desk, parse_body, record_redacted, redact
from app.api.errors import InvalidRequest
from app.api.notifications import output_guard
from app.api.strategy import snapshot_for_new_ticket
from app.auth.authz import can_act_on_escalation, can_close_escalation
from app.auth.deps import REQUIREMENT_ATTR, current_principal, deny, get_auth
from app.auth.models import Principal
from app.auth.permissions import L3_PERM
from app.core.ids import new_ticket_id, new_turn_id
from app.db.escalations import (
    ClaimOutcome,
    ClaimRequest,
    ClosedEscalation,
    CloseRequest,
    EscalationHead,
    QueueItem,
    QueueKey,
    QueueStatus,
    RaiseOutcome,
    RaiseRequest,
    ReopenHook,
)
from app.db.tickets import NewTicket
from app.domain.escalation_close import CloseResult, close_reason_for
from app.domain.escalation_flow import (
    RAISE_NOTE_MAX,
    USER_MESSAGE_MAX,
    RaiseTarget,
    due_at,
    is_overdue,
)

log = logging.getLogger(__name__)
router = APIRouter()

QUEUE_LIMIT_DEFAULT = 50
QUEUE_LIMIT_MAX = 100  # mỗi trang; tổng số dòng không trần (duyệt bằng `next_cursor`)
NOTE_MAX = 1000  # = CHECK `escalations.close_note` (migration 0013)
NOT_FOUND = "not_found"
ALREADY_CLOSED = "already_closed"
ALREADY_CLAIMED = "already_claimed"  # D-99: người khác đang giữ ca
ALREADY_RAISED = "already_raised"
TIER_CHANGED = "tier_changed"
CURSOR_VERSION = 1
_CURSOR_MAX = 512
_CURSOR_CHARS = re.compile(r"[A-Za-z0-9_-]+")
_CURSOR_KEYS = frozenset({"v", "s", "p", "t", "i"})
_PK = re.compile(r"[0-9]{1,18}")  # như `approval/store._approval_pk`: không nhận "²", không vượt BIGINT


class EscalationQueue(Protocol):
    async def list_page(self, status: QueueStatus, limit: int, after: QueueKey | None, *, tier: int = 2) -> list[QueueItem]: ...

    async def get(self, escalation_id: int) -> EscalationHead | None: ...

    async def close(self, req: CloseRequest, *, reopen: ReopenHook | None = None) -> ClosedEscalation | None: ...

    async def claim(self, req: ClaimRequest) -> ClaimOutcome: ...

    async def raise_tier(self, req: RaiseRequest) -> RaiseOutcome: ...

    async def set_new_ticket(self, escalation_id: int, new_ticket_id: str) -> None: ...


def get_queue(request: Request) -> EscalationQueue:
    queue: EscalationQueue | None = getattr(request.app.state, "escalations", None)
    if queue is None:
        raise HTTPException(503, "escalations_unavailable")
    return queue


# ---- thân (response_model — FE sinh kiểu) ---------------------------------------------------------------------------------------


class EscalationQueueItem(BaseModel):
    escalation_id: int
    ticket_id: str
    exit_code: str
    priority: int
    label: str
    reason_detail: str | None
    is_deny_case: bool
    handoff_note: dict[str, Any]
    assigned_to: str | None
    created_at: datetime
    closed_at: datetime | None
    close_result: CloseResult | None
    closed_by: str | None
    close_note: str | None
    # D-99
    assigned_at: datetime | None
    tier: Literal[2, 3]
    raised_at: datetime | None
    raised_by: str | None
    raise_target: RaiseTarget | None
    raise_note: str | None
    user_message: str | None
    new_ticket_id: str | None
    due_at: datetime
    overdue: bool


class EscalationQueuePage(BaseModel):
    items: list[EscalationQueueItem]
    next_cursor: str | None


class EscalationCloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    close_result: CloseResult
    note: str = Field(min_length=1, max_length=NOTE_MAX)
    user_message: str | None = Field(default=None, min_length=1, max_length=USER_MESSAGE_MAX)  # D-99: lời nhắn cho người dùng

    @field_validator("note", "user_message")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("chỉ có khoảng trắng")
        return v


class EscalationRaiseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: RaiseTarget
    note: str = Field(min_length=1, max_length=RAISE_NOTE_MAX)

    @field_validator("note")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("note chỉ có khoảng trắng")
        return v


class EscalationClaimOut(BaseModel):
    escalation_id: int
    tier: Literal[2, 3]
    assigned_to: str


class EscalationRaiseOut(BaseModel):
    escalation_id: int
    tier: Literal[3]
    raise_target: RaiseTarget
    raised_at: datetime
    raised_by: str


class EscalationCloseOut(BaseModel):
    escalation_id: int
    ticket_id: str
    close_result: CloseResult
    close_reason: str | None
    closed_at: datetime
    closed_by: str
    close_note: str
    new_ticket_id: str | None  # D-99 (A): ticket mới của `reopened_as_new` (tạo lỗi → null, ca vẫn đóng)
    user_message: str | None = None  # D-99: bản ĐÃ che của lời nhắn cho người dùng


ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}, 404: {"model": ErrorDetail}, 409: {"model": ErrorDetail},
    503: {"model": ErrorDetail},
}  # fmt: skip


# ---- cursor -------------------------------------------------------------------------------------------------------------------------


def encode_cursor(status: str, item: QueueItem) -> str:
    raw = {"v": CURSOR_VERSION, "s": status, "p": item.priority, "t": item.created_at.isoformat(), "i": item.escalation_id}
    return base64.urlsafe_b64encode(json.dumps(raw, separators=(",", ":")).encode()).rstrip(b"=").decode()


def _int(value: Any, lo: int, hi: int) -> int | None:
    return value if type(value) is int and lo <= value <= hi else None  # `type(...) is int` loại bool


def decode_cursor(value: str, status: str) -> QueueKey:
    """Sai bất kỳ chỗ nào → 422 `query.after` (không trả lại giá trị người gửi)."""
    bad = InvalidRequest(["query.after"])
    if len(value) > _CURSOR_MAX or not _CURSOR_CHARS.fullmatch(value):
        raise bad
    try:
        data = json.loads(base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True))
        at = datetime.fromisoformat(data["t"]) if isinstance(data, dict) and isinstance(data.get("t"), str) else None
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise bad from None
    if not isinstance(data, dict) or data.keys() != _CURSOR_KEYS or _int(data["v"], CURSOR_VERSION, CURSOR_VERSION) is None or data["s"] != status:
        raise bad
    priority, escalation_id = _int(data["p"], 0, 32767), _int(data["i"], 1, 2**63 - 1)
    if priority is None or escalation_id is None or at is None or at.tzinfo is None:
        raise bad
    return QueueKey(priority=priority, created_at=at, escalation_id=escalation_id)


# ---- route ----------------------------------------------------------------------------------------------------------------------------


async def escalation_actor(
    request: Request, p: Annotated[Principal, Depends(current_principal)]
) -> Principal:
    """D-99: người xử lý ca ở BẤT KỲ cấp nào — `escalation:handle` (L1, L2) hoặc `escalation:handle:l3` (Trưởng IT). Luật theo từng cấp kiểm sau
    (`authz.can_act_on_escalation`)."""
    if not (p.has("escalation:handle") or p.has(L3_PERM)):
        await deny(request, p, "escalation:handle")
        raise HTTPException(403, "forbidden")
    return p


# Dấu cho test quét route (deny-by-default, P6): cổng HOẶC — `escalation:handle` hoặc `escalation:handle:l3`.
setattr(escalation_actor, REQUIREMENT_ATTR, (f"escalation:handle|{L3_PERM}", None, False))


def _scope(status: QueueStatus, tier: int) -> str:
    """Giá trị `s` trong cursor: cấp 2 giữ đúng như trước D-99 (`open`/`closed`), cấp 3 thêm hậu tố — cursor không dùng chéo cấp."""
    return status if tier == 2 else f"{status}@3"


def _view(item: QueueItem, now: datetime) -> EscalationQueueItem:
    due = due_at(
        created_at=item.created_at,
        rank=item.priority,
        tier=item.tier,
        raised_at=item.raised_at,
    )
    return EscalationQueueItem.model_validate(
        {
            **item.__dict__,
            "due_at": due,
            "overdue": is_overdue(due=due, now=now, closed_at=item.closed_at),
        }
    )


@router.get(
    "/api/escalations/queue", response_model=EscalationQueuePage, responses=ERRORS
)
async def escalation_queue(
    _: Annotated[Principal, Depends(escalation_actor)],
    queue: Annotated[EscalationQueue, Depends(get_queue)],
    request: Request,
    status: Annotated[QueueStatus, Query()] = "open",
    tier: Annotated[int, Query(ge=2, le=3)] = 2,
    limit: Annotated[int, Query(ge=1, le=QUEUE_LIMIT_MAX)] = QUEUE_LIMIT_DEFAULT,
    after: Annotated[str | None, Query()] = None,
) -> EscalationQueuePage:
    scope = _scope(status, tier)
    key = decode_cursor(after, scope) if after is not None else None
    rows = await queue.list_page(status, limit + 1, key, tier=tier)
    page = rows[:limit]
    now = get_auth(request).clock.now()  # đồng hồ của dịch vụ đăng nhập — hàng đợi không cần runtime graph
    return EscalationQueuePage(
        items=[_view(r, now) for r in page],
        next_cursor=encode_cursor(scope, page[-1]) if len(rows) > limit else None,
    )


async def _head_for_action(
    request: Request,
    p: Principal,
    queue: EscalationQueue,
    desk: Desk,
    escalation_id: str,
) -> tuple[EscalationHead, str | None]:
    """Chung cho nhận ca / chuyển cấp / đóng: 404 → 409 `already_closed` → 403 (sai cấp hoặc chính người gửi) → 409 `already_claimed`."""
    head = await queue.get(int(escalation_id)) if _PK.fullmatch(escalation_id) else None
    if head is None:
        raise HTTPException(404, NOT_FOUND)
    if head.closed_at is not None:
        raise HTTPException(409, ALREADY_CLOSED)
    ticket = await desk.tickets.get(head.ticket_id)
    requester = ticket.requester_id if ticket else None
    if not can_act_on_escalation(p, tier=head.tier, requester_id=requester):
        await deny(request, p, "escalation:handle", escalation_id=head.escalation_id)
        raise HTTPException(403, "forbidden")
    if head.assigned_to is not None and head.assigned_to != p.user_id:
        raise HTTPException(409, ALREADY_CLAIMED)
    return head, requester


@router.post(
    "/api/escalations/{escalation_id}/claim",
    response_model=EscalationClaimOut,
    responses=ERRORS,
)
async def claim_escalation(
    escalation_id: str,
    request: Request,
    p: Annotated[Principal, Depends(escalation_actor)],
    queue: Annotated[EscalationQueue, Depends(get_queue)],
    desk: Annotated[Desk, Depends(get_desk)],
) -> EscalationClaimOut:
    head, _ = await _head_for_action(request, p, queue, desk, escalation_id)
    outcome = await queue.claim(
        ClaimRequest(
            escalation_id=head.escalation_id,
            user_id=p.user_id,
            tier=head.tier,
            at=desk.clock.now(),
        )
    )
    if outcome == "claimed":
        return EscalationClaimOut.model_validate({"escalation_id": head.escalation_id, "tier": head.tier, "assigned_to": p.user_id})
    raise HTTPException(*_CLAIM_ERRORS[outcome])


_CLAIM_ERRORS: dict[str, tuple[int, str]] = {
    "not_found": (404, NOT_FOUND), "closed": (409, ALREADY_CLOSED), "taken": (409, ALREADY_CLAIMED), "wrong_tier": (409, TIER_CHANGED),
}  # fmt: skip
_RAISE_ERRORS: dict[str, tuple[int, str]] = {
    "not_found": (404, NOT_FOUND), "closed": (409, ALREADY_CLOSED), "already_raised": (409, ALREADY_RAISED),
}  # fmt: skip


@router.post(
    "/api/escalations/{escalation_id}/raise",
    response_model=EscalationRaiseOut,
    responses=ERRORS,
)
async def raise_escalation(
    escalation_id: str,
    request: Request,
    p: Annotated[Principal, Depends(escalation_actor)],
    queue: Annotated[EscalationQueue, Depends(get_queue)],
    desk: Annotated[Desk, Depends(get_desk)],
) -> EscalationRaiseOut:
    body = await parse_body(request, EscalationRaiseIn)
    head, _ = await _head_for_action(request, p, queue, desk, escalation_id)
    if head.tier != 2:
        raise HTTPException(409, ALREADY_RAISED)
    redacted = await redact(desk, request, body.note)
    if (
        not redacted.text.strip() or len(redacted.text) > RAISE_NOTE_MAX
    ):  # KHÔNG cắt bản che
        raise InvalidRequest(["note"])
    await record_redacted(desk, request, p, head.ticket_id, redacted)
    at = desk.clock.now()
    req = RaiseRequest(
        escalation_id=head.escalation_id,
        raised_by=p.user_id,
        target=body.target,
        note=redacted.text,
        at=at,
    )
    outcome = await queue.raise_tier(req)
    if outcome != "raised":
        raise HTTPException(*_RAISE_ERRORS[outcome])
    return EscalationRaiseOut(
        escalation_id=head.escalation_id,
        tier=3,
        raise_target=body.target,
        raised_at=at,
        raised_by=p.user_id,
    )


@router.post(
    "/api/escalations/{escalation_id}/close",
    response_model=EscalationCloseOut,
    responses=ERRORS,
)
async def close_escalation(
    escalation_id: str,
    request: Request,
    p: Annotated[Principal, Depends(escalation_actor)],
    queue: Annotated[EscalationQueue, Depends(get_queue)],
    desk: Annotated[Desk, Depends(get_desk)],
) -> EscalationCloseOut:
    body = await parse_body(request, EscalationCloseIn)
    head = await queue.get(int(escalation_id)) if _PK.fullmatch(escalation_id) else None
    if head is None:
        raise HTTPException(404, NOT_FOUND)
    if head.closed_at is not None:
        raise HTTPException(409, ALREADY_CLOSED)
    ticket = await desk.tickets.get(head.ticket_id)
    verdict = can_close_escalation(
        p,
        head,
        body.close_result,
        requester_id=ticket.requester_id if ticket else None,
        tier=head.tier,
    )
    if (
        verdict == "forbidden"
    ):  # sai cấp, thiếu quyền, hoặc chính người gửi ticket (Q5a) — luật một chỗ (authz)
        await deny(request, p, "escalation:handle", escalation_id=head.escalation_id)
        raise HTTPException(403, "forbidden")
    if (
        head.assigned_to is not None and head.assigned_to != p.user_id
    ):  # D-99: ca người khác đang giữ
        raise HTTPException(409, ALREADY_CLAIMED)
    if verdict == "unprocessable":
        raise InvalidRequest(["close_result"])
    redacted = await redact(desk, request, body.note)
    if not redacted.text.strip() or len(redacted.text) > NOTE_MAX:  # KHÔNG cắt bản che
        raise InvalidRequest(["note"])
    user_message = await _user_message(request, desk, body.user_message)
    await record_redacted(desk, request, p, head.ticket_id, redacted)
    req = CloseRequest(
        escalation_id=head.escalation_id, close_result=body.close_result, closed_by=p.user_id, close_note=redacted.text,
        close_reason=close_reason_for(body.close_result, is_deny_case=head.is_deny_case), at=desk.clock.now(), tier=head.tier,
        user_message=user_message,
    )  # fmt: skip
    closed = await queue.close(
        req, reopen=None
    )  # (A) của D-99: tạo ticket mới SAU khi đóng (bên dưới), không trong transaction
    if closed is None:  # thua lần đóng đồng thời (hoặc ca vừa đổi cấp)
        raise HTTPException(409, ALREADY_CLOSED)
    out = EscalationCloseOut.model_validate(closed, from_attributes=True)
    if body.close_result == "reopened_as_new" and ticket is not None:
        new_id = await _reopen(
            request, desk, queue, head, ticket.requester_id, ticket.redacted_request, ticket.session_id
        )
        out = out.model_copy(update={"new_ticket_id": new_id})
    return out


async def _user_message(request: Request, desk: Desk, text: str | None) -> str | None:
    """D-99: lời nhắn cho người dùng — che như ghi chú, rồi qua cổng tin trả lời (bí mật, canary, chép prompt) → vi phạm 422."""
    if text is None:
        return None
    redacted = await redact(desk, request, text)
    clean = redacted.text.strip()
    if (
        not clean
        or len(clean) > USER_MESSAGE_MAX
        or output_guard(request).violation(clean) is not None
    ):
        raise InvalidRequest(["user_message"])
    return clean


async def _reopen(
    request: Request,
    desk: Desk,
    queue: EscalationQueue,
    head: EscalationHead,
    requester_id: str,
    text: str,
    session_id: str | None,
) -> str | None:
    """D-99 (A): ticket mới cùng người gửi + cùng nội dung ĐÃ che, chạy lại từ đầu. Lỗi → None (ca đã đóng; log tên lớp lỗi).

    D-100 (máy demo 17/11): B1 đòi phiên CÒN SỐNG của người gửi — ticket mới mang phiên của ticket gốc (họ token: làm mới token vẫn
    tính). Phiên đã hết hạn / đăng xuất → KHÔNG tạo ticket (trước đây: ticket mới bị B1 chặn `session_invalid`, người gửi không nhận
    tin nào) → None: thông báo quay về câu "đề nghị bạn gửi một yêu cầu mới" kèm lời nhắn của IT."""
    if session_id is None or desk.identity is None or await desk.identity.active_session(session_id, desk.clock.now()) is None:
        log.info("reopen ca %s: phiên của người gửi không còn — không tạo ticket mới", head.escalation_id)
        return None
    try:
        user = await desk.users.get_user(requester_id)
        strategy, source = await snapshot_for_new_ticket(request, desk)
        ticket_id, turn_id = new_ticket_id(), new_turn_id()
        await desk.tickets.create(
            NewTicket(
                ticket_id=ticket_id, requester_id=requester_id, requester_role=user.role if user else "employee",
                requester_dept=user.department if user else None, session_id=session_id, redacted_request=text,
                created_at=desk.clock.now(), strategy=strategy, source=source,
            ),
            turn_id=turn_id,
        )  # fmt: skip
        await queue.set_new_ticket(head.escalation_id, ticket_id)
    except Exception as exc:  # noqa: BLE001 — ca đã đóng; không tạo được ticket mới thì báo null, không 500
        log.warning(
            "reopen ca %s: không tạo được ticket mới (%s)",
            head.escalation_id,
            type(exc).__name__,
        )
        return None
    desk.background.spawn(
        desk.runner.run_new(ticket_id, turn_id, follows_ticket_id=None, prior_hint=None, raw_screen_hit=None),
        name=f"reopen:{ticket_id}",
    )  # fmt: skip
    return ticket_id
