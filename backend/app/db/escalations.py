"""Repository `escalations` — hàng đợi L2 (B20 mục 4, 8; P9 mục 7 `GET /api/escalations/queue`).

- `create`: gọi QUA `effects.once("escalation_create")` (D-18) → dùng transaction của dòng
  `side_effects` (`current_tx()`), nên chạy lại B20 không tạo dòng thứ hai. `priority` lấy bằng
  `INSERT … SELECT rank FROM exit_code_priority` — bảng seed là nguồn duy nhất (B20 5.1), không có
  hằng ưu tiên thứ hai trong code.
- `list_open`: chưa đóng (`closed_at IS NULL`), ticket lá (`is_parent = false`, D-30) HOẶC ticket cha có `exit_code` (cha lỗi E2/E9 —
  Phase 5 T20b Q-T20b-5 (ii): L2 phải THẤY cha lỗi; view/chỉ số M9 không đổi), sắp theo
  `priority, created_at, escalation_id`.
- P4 tuần 8 (B20 mục 4.3): `list_page` — hàng đợi `open` | `closed` phân trang keyset theo ĐÚNG thứ tự sắp trên (`after` = vị trí dòng
  cuối trang trước; không trần tổng số dòng); `get` — đầu ca (để route kiểm 404/409/422 TRƯỚC khi che ghi chú); `close` — MỘT
  transaction: `UPDATE escalations … WHERE closed_at IS NULL` (hai lần đóng đồng thời: một thắng, một nhận None → 409), `new_ticket_id`
  (móc `reopen` — phương án (A) cắm ĐÚNG chỗ này; gói tuần 8 chưa truyền móc = (B)), `tickets.close_reason` (B20 5.1: chỉ khi
  `close_reason IS NULL AND final_state = 'S_ESCALATED'`, không khớp → bỏ qua + log.info), dòng audit `B20`/`escalation_closed`
  (điểm log 8 bổ sung, B20:253) với `detail` ĐÚNG 4 khoá — không nguyên văn ghi chú.
"""

import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, Table, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.audit.writer import check_audit_row
from app.db.models import AuditLog, Escalation, ExitCodePriority, Ticket
from app.db.runtime import current_tx
from app.domain.escalation_close import CloseResult
from app.domain.states import S_ESCALATED

log = logging.getLogger(__name__)

_ESC: Table = Escalation.__table__  # type: ignore[assignment]
_PRIO: Table = ExitCodePriority.__table__  # type: ignore[assignment]
_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]
_AUDIT: Table = AuditLog.__table__  # type: ignore[assignment]

type QueueStatus = Literal["open", "closed"]
CLOSE_STEP = "B20"
CLOSE_EVENT = "escalation_closed"  # điểm log 8 bổ sung "đóng bởi L2" (B20:253) — KHÁC ("B20", "closed") mà audit/check đếm cho điểm 8


class UnknownExitCode(LookupError):
    """`exit_code_priority` không có mã này — seed thiếu (lỗi cấu hình DB)."""


@dataclass(frozen=True)
class QueueItem:
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
    closed_at: datetime | None = None
    close_result: str | None = None
    closed_by: str | None = None
    close_note: str | None = None


@dataclass(frozen=True)
class QueueKey:
    """Vị trí keyset trong thứ tự `priority, created_at, escalation_id` (cursor của route mã hoá đúng 3 giá trị này)."""

    priority: int
    created_at: datetime
    escalation_id: int


@dataclass(frozen=True)
class EscalationHead:
    escalation_id: int
    ticket_id: str
    exit_code: str
    is_deny_case: bool
    closed_at: datetime | None


@dataclass(frozen=True)
class CloseRequest:
    escalation_id: int
    close_result: CloseResult
    closed_by: str
    close_note: str  # ĐÃ qua privacy guard (route), 1–1000 ký tự (CHECK 0013)
    close_reason: str  # `domain.escalation_close.close_reason_for`
    at: datetime


@dataclass(frozen=True)
class ClosedEscalation:
    escalation_id: int
    ticket_id: str
    close_result: str
    close_reason: str | None  # giá trị THẬT của `tickets.close_reason` sau transaction (bỏ qua cập nhật → giá trị đang có)
    closed_at: datetime
    closed_by: str
    close_note: str
    new_ticket_id: str | None


# (A) `reopened_as_new` tạo ticket mới: gọi TRONG transaction đóng ca, trả `ticket_id` mới (→ `escalations.new_ticket_id`).
type ReopenHook = Callable[[AsyncConnection, EscalationHead, CloseRequest], Awaitable[str]]


def close_audit_row(req: CloseRequest, ticket_id: str) -> dict[str, Any]:
    """Dòng audit đóng ca: `detail` ĐÚNG {escalation_id, close_result, closed_by, note_length} — không nguyên văn ghi chú."""
    key = hashlib.sha256(f"escalation_close:{req.escalation_id}".encode()).hexdigest()
    return {
        "ticket_id": ticket_id, "created_at": req.at, "step": CLOSE_STEP, "event": CLOSE_EVENT, "idempotency_key": key,
        "detail": {"escalation_id": req.escalation_id, "close_result": req.close_result, "closed_by": req.closed_by,
                   "note_length": len(req.close_note)},
    }  # fmt: skip


_QUEUE_COLUMNS = (
    _ESC.c.escalation_id, _ESC.c.ticket_id, _ESC.c.exit_code, _ESC.c.priority, _PRIO.c.label, _ESC.c.reason_detail,
    _ESC.c.is_deny_case, _ESC.c.handoff_note, _ESC.c.assigned_to, _ESC.c.created_at,
)  # fmt: skip
_CLOSED_COLUMNS = (_ESC.c.closed_at, _ESC.c.close_result, _ESC.c.closed_by, _ESC.c.close_note)
_ORDER = (_ESC.c.priority, _ESC.c.created_at, _ESC.c.escalation_id)


def _visible() -> ColumnElement[bool]:
    return or_(_TICKETS.c.is_parent.is_(False), _TICKETS.c.exit_code.is_not(None))


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


class SqlEscalationStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(
        self,
        *,
        ticket_id: str,
        exit_code: str,
        reason_detail: str | None,
        handoff_note: Mapping[str, Any],
        is_deny_case: bool,
        created_at: datetime,
    ) -> str:
        insert_from = select(
            literal(ticket_id), literal(exit_code), _PRIO.c.rank, literal(reason_detail),
            literal(dict(handoff_note), _ESC.c.handoff_note.type), literal(is_deny_case),
            literal(created_at, _ESC.c.created_at.type),
        ).where(_PRIO.c.exit_code == exit_code)  # fmt: skip
        stmt = (
            _ESC.insert()
            .from_select(
                ["ticket_id", "exit_code", "priority", "reason_detail", "handoff_note",
                 "is_deny_case", "created_at"],
                insert_from,
            )
            .returning(_ESC.c.escalation_id)
        )

        async def run(conn: AsyncConnection) -> str:
            row = (await conn.execute(stmt)).first()
            if row is None:
                raise UnknownExitCode(exit_code)
            return str(row.escalation_id)

        conn = current_tx()
        if conn is not None:
            return await run(conn)
        async with self._engine.begin() as own:
            return await run(own)

    async def list_open(self, limit: int) -> list[QueueItem]:
        query = (
            select(
                _ESC.c.escalation_id, _ESC.c.ticket_id, _ESC.c.exit_code, _ESC.c.priority,
                _PRIO.c.label, _ESC.c.reason_detail, _ESC.c.is_deny_case, _ESC.c.handoff_note,
                _ESC.c.assigned_to, _ESC.c.created_at,
            )
            .join(_PRIO, _PRIO.c.exit_code == _ESC.c.exit_code)
            .join(_TICKETS, _TICKETS.c.ticket_id == _ESC.c.ticket_id)
            .where(_ESC.c.closed_at.is_(None), or_(_TICKETS.c.is_parent.is_(False), _TICKETS.c.exit_code.is_not(None)))
            .order_by(_ESC.c.priority, _ESC.c.created_at, _ESC.c.escalation_id)
            .limit(limit)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).all()
        return [
            QueueItem(**{**r._mapping, "created_at": r.created_at.astimezone(UTC)}) for r in rows
        ]

    async def list_page(self, status: QueueStatus, limit: int, after: QueueKey | None) -> list[QueueItem]:
        """Tối đa `limit` dòng SAU `after` theo `priority, created_at, escalation_id` (route lấy `limit + 1` để biết còn trang)."""
        closed = _ESC.c.closed_at.is_not(None) if status == "closed" else _ESC.c.closed_at.is_(None)
        query = (
            select(*_QUEUE_COLUMNS, *_CLOSED_COLUMNS)
            .join(_PRIO, _PRIO.c.exit_code == _ESC.c.exit_code)
            .join(_TICKETS, _TICKETS.c.ticket_id == _ESC.c.ticket_id)
            .where(closed, _visible())
            .order_by(*_ORDER)
            .limit(limit)
        )
        if after is not None:
            query = query.where(tuple_(*_ORDER) > tuple_(after.priority, after.created_at, after.escalation_id))
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).all()
        return [
            QueueItem(**{**r._mapping, "created_at": r.created_at.astimezone(UTC), "closed_at": _utc(r.closed_at)})
            for r in rows
        ]

    async def get(self, escalation_id: int) -> EscalationHead | None:
        query = select(
            _ESC.c.escalation_id, _ESC.c.ticket_id, _ESC.c.exit_code, _ESC.c.is_deny_case, _ESC.c.closed_at,
        ).where(_ESC.c.escalation_id == escalation_id)  # fmt: skip
        async with self._engine.connect() as conn:
            row = (await conn.execute(query)).first()
        return None if row is None else EscalationHead(**{**row._mapping, "closed_at": _utc(row.closed_at)})

    async def close(self, req: CloseRequest, *, reopen: ReopenHook | None = None) -> ClosedEscalation | None:
        """MỘT transaction. None = ca đã đóng lúc UPDATE (thua lần đóng đồng thời) → route trả 409; không ghi gì."""
        async with self._engine.begin() as conn:
            row = (await conn.execute(
                _ESC.update()
                .where(_ESC.c.escalation_id == req.escalation_id, _ESC.c.closed_at.is_(None))
                .values(closed_at=req.at, close_result=req.close_result, closed_by=req.closed_by, close_note=req.close_note)
                .returning(_ESC.c.escalation_id, _ESC.c.ticket_id, _ESC.c.exit_code, _ESC.c.is_deny_case, _ESC.c.closed_at)
            )).first()  # fmt: skip
            if row is None:
                return None
            head = EscalationHead(**{**row._mapping, "closed_at": _utc(row.closed_at)})
            new_ticket_id = None
            if reopen is not None and req.close_result == "reopened_as_new":
                new_ticket_id = await reopen(conn, head, req)
                await conn.execute(
                    _ESC.update().where(_ESC.c.escalation_id == req.escalation_id).values(new_ticket_id=new_ticket_id)
                )
            reason = (await conn.execute(
                _TICKETS.update()
                .where(_TICKETS.c.ticket_id == head.ticket_id, _TICKETS.c.close_reason.is_(None),
                       _TICKETS.c.final_state == S_ESCALATED)
                .values(close_reason=req.close_reason)
                .returning(_TICKETS.c.close_reason)
            )).scalar()  # fmt: skip
            if reason is None:
                log.info("đóng ca %s: ticket %s không ở S_ESCALATED hoặc đã có close_reason — bỏ qua cập nhật close_reason",
                         req.escalation_id, head.ticket_id)  # fmt: skip
                reason = (await conn.execute(
                    select(_TICKETS.c.close_reason).where(_TICKETS.c.ticket_id == head.ticket_id)
                )).scalar()  # fmt: skip
            audit = close_audit_row(req, head.ticket_id)
            check_audit_row(audit)
            await conn.execute(_AUDIT.insert().values(**audit))
        return ClosedEscalation(
            escalation_id=head.escalation_id, ticket_id=head.ticket_id, close_result=req.close_result, close_reason=reason,
            closed_at=req.at, closed_by=req.closed_by, close_note=req.close_note, new_ticket_id=new_ticket_id,
        )  # fmt: skip
