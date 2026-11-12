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
`reopened_as_new` (Điểm lệch BE — lệch B20 cổng 7, nợ sau bảo vệ): làm (B) — ghi `close_result`, `new_ticket_id` LUÔN null, KHÔNG tạo
ticket. Chỗ cắm (A): móc `reopen` (`db/escalations.ReopenHook`, chạy TRONG transaction đóng ca) — route CHƯA truyền; thân 200 đã có
`new_ticket_id` nên thêm (A) không đổi hợp đồng API.
"""

import base64
import binascii
import json
import re
from datetime import datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.alerts import ErrorDetail
from app.api.desk import Desk, get_desk, parse_body, record_redacted, redact
from app.api.errors import InvalidRequest
from app.auth.authz import can_close_escalation
from app.auth.deps import deny, require
from app.auth.models import Principal
from app.db.escalations import (
    ClosedEscalation,
    CloseRequest,
    EscalationHead,
    QueueItem,
    QueueKey,
    QueueStatus,
    ReopenHook,
)
from app.domain.escalation_close import CloseResult, close_reason_for

router = APIRouter()

QUEUE_LIMIT_DEFAULT = 50
QUEUE_LIMIT_MAX = 100  # mỗi trang; tổng số dòng không trần (duyệt bằng `next_cursor`)
NOTE_MAX = 1000  # = CHECK `escalations.close_note` (migration 0013)
NOT_FOUND = "not_found"
ALREADY_CLOSED = "already_closed"
CURSOR_VERSION = 1
_CURSOR_MAX = 512
_CURSOR_CHARS = re.compile(r"[A-Za-z0-9_-]+")
_CURSOR_KEYS = frozenset({"v", "s", "p", "t", "i"})
_PK = re.compile(r"[0-9]{1,18}")  # như `approval/store._approval_pk`: không nhận "²", không vượt BIGINT


class EscalationQueue(Protocol):
    async def list_page(self, status: QueueStatus, limit: int, after: QueueKey | None) -> list[QueueItem]: ...

    async def get(self, escalation_id: int) -> EscalationHead | None: ...

    async def close(self, req: CloseRequest, *, reopen: ReopenHook | None = None) -> ClosedEscalation | None: ...


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


class EscalationQueuePage(BaseModel):
    items: list[EscalationQueueItem]
    next_cursor: str | None


class EscalationCloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    close_result: CloseResult
    note: str = Field(min_length=1, max_length=NOTE_MAX)

    @field_validator("note")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("note chỉ có khoảng trắng")
        return v


class EscalationCloseOut(BaseModel):
    escalation_id: int
    ticket_id: str
    close_result: CloseResult
    close_reason: str | None
    closed_at: datetime
    closed_by: str
    close_note: str
    new_ticket_id: str | None  # (B): luôn null; (A) sau này: ticket mới của `reopened_as_new`


ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}, 404: {"model": ErrorDetail}, 409: {"model": ErrorDetail},
    503: {"model": ErrorDetail},
}  # fmt: skip


# ---- cursor -------------------------------------------------------------------------------------------------------------------------


def encode_cursor(status: QueueStatus, item: QueueItem) -> str:
    raw = {"v": CURSOR_VERSION, "s": status, "p": item.priority, "t": item.created_at.isoformat(), "i": item.escalation_id}
    return base64.urlsafe_b64encode(json.dumps(raw, separators=(",", ":")).encode()).rstrip(b"=").decode()


def _int(value: Any, lo: int, hi: int) -> int | None:
    return value if type(value) is int and lo <= value <= hi else None  # `type(...) is int` loại bool


def decode_cursor(value: str, status: QueueStatus) -> QueueKey:
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


# ---- route --------------------------------------------------------------------------------------------------------------------------


@router.get("/api/escalations/queue", response_model=EscalationQueuePage, responses=ERRORS)
async def escalation_queue(
    _: Annotated[Principal, Depends(require("escalation:handle"))],
    queue: Annotated[EscalationQueue, Depends(get_queue)],
    status: Annotated[QueueStatus, Query()] = "open",
    limit: Annotated[int, Query(ge=1, le=QUEUE_LIMIT_MAX)] = QUEUE_LIMIT_DEFAULT,
    after: Annotated[str | None, Query()] = None,
) -> EscalationQueuePage:
    key = decode_cursor(after, status) if after is not None else None
    rows = await queue.list_page(status, limit + 1, key)
    page = rows[:limit]
    return EscalationQueuePage(
        items=[EscalationQueueItem.model_validate(r, from_attributes=True) for r in page],
        next_cursor=encode_cursor(status, page[-1]) if len(rows) > limit else None,
    )


@router.post("/api/escalations/{escalation_id}/close", response_model=EscalationCloseOut, responses=ERRORS)
async def close_escalation(
    escalation_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("escalation:handle"))],
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
    verdict = can_close_escalation(p, head, body.close_result, requester_id=ticket.requester_id if ticket else None)
    if verdict == "forbidden":  # thiếu quyền (`require` đã chặn) hoặc chính người gửi ticket (Q5a) — luật một chỗ (authz)
        await deny(request, p, "escalation:handle", escalation_id=head.escalation_id)
        raise HTTPException(403, "forbidden")
    if verdict == "unprocessable":
        raise InvalidRequest(["close_result"])
    redacted = await redact(desk, request, body.note)
    if not redacted.text.strip() or len(redacted.text) > NOTE_MAX:  # KHÔNG cắt bản che
        raise InvalidRequest(["note"])
    await record_redacted(desk, request, p, head.ticket_id, redacted)
    req = CloseRequest(
        escalation_id=head.escalation_id, close_result=body.close_result, closed_by=p.user_id, close_note=redacted.text,
        close_reason=close_reason_for(body.close_result, is_deny_case=head.is_deny_case), at=desk.clock.now(),
    )  # fmt: skip
    closed = await queue.close(req, reopen=None)  # (B) gói tuần 8 — (A): truyền móc tạo ticket mới ở ĐÂY
    if closed is None:  # thua lần đóng đồng thời
        raise HTTPException(409, ALREADY_CLOSED)
    return EscalationCloseOut.model_validate(closed, from_attributes=True)
