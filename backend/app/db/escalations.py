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
- D-99 (17/11, migration 0018): `list_page` lọc theo CẤP (`tier` 2 = L2, 3 = Trưởng IT); `claim` (nhận ca) và `raise_tier` (chuyển cấp 3) —
  mỗi lệnh MỘT `UPDATE … WHERE` có điều kiện (đua nhau: một thắng) + một dòng audit `L2`/`escalation_claimed` | `escalation_raised`
  (`detail` chỉ id, người làm, cấp, mã đích, độ dài ghi chú — không nguyên văn); `close` ghi thêm `user_message`, chỉ đóng ca ĐÚNG cấp của
  người đóng, và gán người đóng làm người nhận nếu ca chưa ai nhận. `set_new_ticket`: ghi `new_ticket_id` sau khi route tạo ticket của
  `reopened_as_new` (phương án (A) — tạo SAU khi đóng, ngoài transaction đóng ca).
"""

import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, Table, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.audit.writer import check_audit_row
from app.db.models import AuditLog, Escalation, ExitCodePriority, Ticket
from app.db.runtime import current_tx
from app.domain.escalation_close import CloseResult
from app.domain.states import S_ESCALATED

log = logging.getLogger(__name__)

_ESC: Table = Escalation.__table__  # type: ignore[assignment]
# E7 mà lệnh ghi CÓ THỂ đã tới hệ thống đích (B17 `exec_failed` / `exec_interrupted`, worker `execution_interrupted`).
WRITE_DOUBT_REASONS: tuple[str, ...] = ("exec_failed", "exec_interrupted", "execution_interrupted")
_PRIO: Table = ExitCodePriority.__table__  # type: ignore[assignment]
_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]
_AUDIT: Table = AuditLog.__table__  # type: ignore[assignment]

type QueueStatus = Literal["open", "closed"]
CLOSE_STEP = "B20"
CLOSE_EVENT = "escalation_closed"  # điểm log 8 bổ sung "đóng bởi L2" (B20:253) — KHÁC ("B20", "closed") mà audit/check đếm cho điểm 8
FLOW_STEP = "L2"  # D-99: bước của người xử lý (nhận ca, chuyển cấp) — không phải node của graph
CLAIM_EVENT = "escalation_claimed"
RAISE_EVENT = "escalation_raised"
type ClaimOutcome = Literal["claimed", "not_found", "closed", "wrong_tier", "taken"]
type RaiseOutcome = Literal["raised", "not_found", "closed", "already_raised"]


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
    # D-99 (0018)
    assigned_at: datetime | None = None
    tier: int = 2
    raised_at: datetime | None = None
    raised_by: str | None = None
    raise_target: str | None = None
    raise_note: str | None = None
    user_message: str | None = None
    new_ticket_id: str | None = None


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
    tier: int = 2  # D-99
    assigned_to: str | None = None


@dataclass(frozen=True)
class CloseRequest:
    escalation_id: int
    close_result: CloseResult
    closed_by: str
    close_note: str  # ĐÃ qua privacy guard (route), 1–1000 ký tự (CHECK 0013)
    close_reason: str  # `domain.escalation_close.close_reason_for`
    at: datetime
    tier: int = 2  # D-99: chỉ đóng nếu ca ĐANG ở cấp này (L2 không đóng ca vừa bị chuyển lên cấp 3)
    user_message: str | None = None  # D-99: lời nhắn cho người dùng — ĐÃ che + qua cổng (route), 1–500 ký tự


@dataclass(frozen=True)
class HandlingRow:
    """D-99: trạng thái xử lý của MỘT ca cho màn chat của người gửi (`GET /api/tickets/{id}` → `handling`)."""

    escalation_id: int
    ticket_id: str
    tier: int
    assigned_at: datetime | None
    raised_at: datetime | None
    raise_target: str | None
    closed_at: datetime | None
    close_result: str | None
    user_message: str | None
    new_ticket_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class ClaimRequest:
    escalation_id: int
    user_id: str
    tier: int
    at: datetime


@dataclass(frozen=True)
class RaiseRequest:
    escalation_id: int
    raised_by: str
    target: str  # `domain.escalation_flow.RAISE_TARGETS`
    note: str  # ĐÃ che, 1–1000 ký tự (CHECK 0018)
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
    user_message: str | None = None


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
_FLOW_COLUMNS = (
    _ESC.c.assigned_at, _ESC.c.tier, _ESC.c.raised_at, _ESC.c.raised_by, _ESC.c.raise_target, _ESC.c.raise_note, _ESC.c.user_message,
    _ESC.c.new_ticket_id,
)  # fmt: skip


def flow_audit_row(*, event: str, escalation_id: int, ticket_id: str, at: datetime, detail: Mapping[str, Any]) -> dict[str, Any]:
    """D-99: dòng audit nhận ca / chuyển cấp — `detail` chỉ id, người làm, cấp, mã đích, độ dài ghi chú (không nguyên văn)."""
    key = hashlib.sha256(f"{event}:{escalation_id}:{at.isoformat()}".encode()).hexdigest()
    return {
        "ticket_id": ticket_id, "created_at": at, "step": FLOW_STEP, "event": event, "idempotency_key": key,
        "detail": {"escalation_id": escalation_id, **detail},
    }  # fmt: skip
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

    async def open_write_doubt(
        self, *, requester_id: str, intent: str, since: datetime, exclude_ticket_id: str
    ) -> str | None:
        """Xem `graph.ports.EscalationStore.open_write_doubt`. `tickets.intent` có từ B20 (ticket đã kết thúc E7)."""
        query = (
            select(_ESC.c.ticket_id)
            .join(_TICKETS, _TICKETS.c.ticket_id == _ESC.c.ticket_id)
            .where(
                _ESC.c.closed_at.is_(None), _ESC.c.exit_code == "E7", _ESC.c.reason_detail.in_(WRITE_DOUBT_REASONS),
                _ESC.c.created_at >= since, _TICKETS.c.requester_id == requester_id, _TICKETS.c.intent == intent,
                _TICKETS.c.ticket_id != exclude_ticket_id,
            )
            .order_by(_ESC.c.created_at.desc())
            .limit(1)
        )  # fmt: skip
        conn = current_tx()
        if conn is not None:
            return (await conn.execute(query)).scalar_one_or_none()
        async with self._engine.connect() as own:
            return (await own.execute(query)).scalar_one_or_none()

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

    async def list_page(self, status: QueueStatus, limit: int, after: QueueKey | None, *, tier: int = 2) -> list[QueueItem]:
        """Tối đa `limit` dòng SAU `after` theo `priority, created_at, escalation_id` (route lấy `limit + 1` để biết còn trang).
        D-99: chỉ ca ĐANG ở cấp `tier` (2 = hàng đợi L2, 3 = hàng đợi Trưởng IT)."""
        closed = _ESC.c.closed_at.is_not(None) if status == "closed" else _ESC.c.closed_at.is_(None)
        query = (
            select(*_QUEUE_COLUMNS, *_CLOSED_COLUMNS, *_FLOW_COLUMNS)
            .join(_PRIO, _PRIO.c.exit_code == _ESC.c.exit_code)
            .join(_TICKETS, _TICKETS.c.ticket_id == _ESC.c.ticket_id)
            .where(closed, _visible(), _ESC.c.tier == tier)
            .order_by(*_ORDER)
            .limit(limit)
        )
        if after is not None:
            query = query.where(tuple_(*_ORDER) > tuple_(after.priority, after.created_at, after.escalation_id))
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).all()
        times = ("closed_at", "assigned_at", "raised_at")
        return [
            QueueItem(**{**r._mapping, "created_at": r.created_at.astimezone(UTC), **{k: _utc(r._mapping[k]) for k in times}})
            for r in rows
        ]

    async def get(self, escalation_id: int) -> EscalationHead | None:
        query = select(
            _ESC.c.escalation_id, _ESC.c.ticket_id, _ESC.c.exit_code, _ESC.c.is_deny_case, _ESC.c.closed_at, _ESC.c.tier,
            _ESC.c.assigned_to,
        ).where(_ESC.c.escalation_id == escalation_id)  # fmt: skip
        async with self._engine.connect() as conn:
            row = (await conn.execute(query)).first()
        return None if row is None else EscalationHead(**{**row._mapping, "closed_at": _utc(row.closed_at)})

    async def claim(self, req: ClaimRequest) -> ClaimOutcome:
        """D-99 nhận ca: MỘT `UPDATE` khi ca còn mở, đúng cấp, chưa ai nhận (bấm lại khi chính mình đã nhận → `claimed`, không audit)."""
        async with self._engine.begin() as conn:
            row = (await conn.execute(
                _ESC.update()
                .where(_ESC.c.escalation_id == req.escalation_id, _ESC.c.closed_at.is_(None), _ESC.c.tier == req.tier,
                       _ESC.c.assigned_to.is_(None))
                .values(assigned_to=req.user_id, assigned_at=req.at)
                .returning(_ESC.c.ticket_id)
            )).first()  # fmt: skip
            if row is not None:
                audit = flow_audit_row(
                    event=CLAIM_EVENT, escalation_id=req.escalation_id, ticket_id=row.ticket_id, at=req.at,
                    detail={"by": req.user_id, "tier": req.tier},
                )  # fmt: skip
                check_audit_row(audit)
                await conn.execute(_AUDIT.insert().values(**audit))
                return "claimed"
            cur = (await conn.execute(
                select(_ESC.c.closed_at, _ESC.c.tier, _ESC.c.assigned_to).where(_ESC.c.escalation_id == req.escalation_id)
            )).first()  # fmt: skip
        return _claim_miss(cur, req.user_id, req.tier)

    async def raise_tier(self, req: RaiseRequest) -> RaiseOutcome:
        """D-99 chuyển cấp 3: chỉ ca còn mở ở cấp 2; bỏ người nhận cũ (Trưởng IT nhận lại ở hàng đợi cấp 3)."""
        async with self._engine.begin() as conn:
            row = (await conn.execute(
                _ESC.update()
                .where(_ESC.c.escalation_id == req.escalation_id, _ESC.c.closed_at.is_(None), _ESC.c.tier == 2)
                .values(tier=3, raised_at=req.at, raised_by=req.raised_by, raise_target=req.target, raise_note=req.note,
                        assigned_to=None, assigned_at=None)
                .returning(_ESC.c.ticket_id)
            )).first()  # fmt: skip
            if row is not None:
                audit = flow_audit_row(
                    event=RAISE_EVENT, escalation_id=req.escalation_id, ticket_id=row.ticket_id, at=req.at,
                    detail={"by": req.raised_by, "target": req.target, "note_length": len(req.note)},
                )  # fmt: skip
                check_audit_row(audit)
                await conn.execute(_AUDIT.insert().values(**audit))
                return "raised"
            cur = (await conn.execute(
                select(_ESC.c.closed_at, _ESC.c.tier).where(_ESC.c.escalation_id == req.escalation_id)
            )).first()  # fmt: skip
        return _raise_miss(cur)

    async def handling_of(self, ticket_ids: Sequence[str]) -> list[HandlingRow]:
        """D-99: mọi ca của các ticket (ticket + con của nó), theo `created_at, escalation_id`. Chỉ đọc."""
        if not ticket_ids:
            return []
        query = (
            select(_ESC.c.escalation_id, _ESC.c.ticket_id, _ESC.c.tier, _ESC.c.assigned_at, _ESC.c.raised_at, _ESC.c.raise_target,
                   _ESC.c.closed_at, _ESC.c.close_result, _ESC.c.user_message, _ESC.c.new_ticket_id, _ESC.c.created_at)
            .where(_ESC.c.ticket_id.in_(list(ticket_ids)))
            .order_by(_ESC.c.created_at, _ESC.c.escalation_id)
        )  # fmt: skip
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).all()
        times = ("assigned_at", "raised_at", "closed_at", "created_at")
        return [HandlingRow(**{**r._mapping, **{k: _utc(r._mapping[k]) for k in times}}) for r in rows]

    async def set_new_ticket(self, escalation_id: int, new_ticket_id: str) -> None:
        """D-99 (A): ghi ticket mới của `reopened_as_new` — chỉ khi ca đã đóng bằng kết quả đó và chưa có ticket mới."""
        async with self._engine.begin() as conn:
            await conn.execute(
                _ESC.update()
                .where(_ESC.c.escalation_id == escalation_id, _ESC.c.close_result == "reopened_as_new",
                       _ESC.c.new_ticket_id.is_(None))
                .values(new_ticket_id=new_ticket_id)
            )  # fmt: skip

    async def close(self, req: CloseRequest, *, reopen: ReopenHook | None = None) -> ClosedEscalation | None:
        """MỘT transaction. None = ca đã đóng lúc UPDATE (thua lần đóng đồng thời) → route trả 409; không ghi gì."""
        async with self._engine.begin() as conn:
            row = (await conn.execute(
                _ESC.update()
                .where(_ESC.c.escalation_id == req.escalation_id, _ESC.c.closed_at.is_(None), _ESC.c.tier == req.tier)
                .values(closed_at=req.at, close_result=req.close_result, closed_by=req.closed_by, close_note=req.close_note,
                        user_message=req.user_message, assigned_to=func.coalesce(_ESC.c.assigned_to, req.closed_by),
                        assigned_at=func.coalesce(_ESC.c.assigned_at, req.at))
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
            user_message=req.user_message,
        )  # fmt: skip


def _claim_miss(cur: Any, user_id: str, tier: int) -> ClaimOutcome:
    """Lý do `claim` không ghi (đọc lại SAU lệnh UPDATE trượt). Đã do chính người này nhận → `claimed` (bấm lại không lỗi)."""
    if cur is None:
        return "not_found"
    if cur.closed_at is not None:
        return "closed"
    if cur.tier != tier:
        return "wrong_tier"
    return "claimed" if cur.assigned_to == user_id else "taken"


def _raise_miss(cur: Any) -> RaiseOutcome:
    if cur is None:
        return "not_found"
    if cur.closed_at is not None:
        return "closed"
    return "already_raised"
