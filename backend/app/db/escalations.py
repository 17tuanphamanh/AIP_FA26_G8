"""Repository `escalations` — hàng đợi L2 (B20 mục 4, 8; P9 mục 7 `GET /api/escalations/queue`).

- `create`: gọi QUA `effects.once("escalation_create")` (D-18) → dùng transaction của dòng
  `side_effects` (`current_tx()`), nên chạy lại B20 không tạo dòng thứ hai. `priority` lấy bằng
  `INSERT … SELECT rank FROM exit_code_priority` — bảng seed là nguồn duy nhất (B20 5.1), không có
  hằng ưu tiên thứ hai trong code.
- `list_open`: chưa đóng (`closed_at IS NULL`), ticket lá (`is_parent = false`, D-30) HOẶC ticket cha có `exit_code` (cha lỗi E2/E9 —
  Phase 5 T20b Q-T20b-5 (ii): L2 phải THẤY cha lỗi; view/chỉ số M9 không đổi), sắp theo
  `priority, created_at, escalation_id`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Table, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import Escalation, ExitCodePriority, Ticket
from app.db.runtime import current_tx

_ESC: Table = Escalation.__table__  # type: ignore[assignment]
_PRIO: Table = ExitCodePriority.__table__  # type: ignore[assignment]
_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]


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
