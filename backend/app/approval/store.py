"""Repository `approvals` (P7 2.6, B15-B16 mục 5) — 2b-Q3.

- `create`: B15 gọi QUA `effects.once("approval_create")` → ghi trong CÙNG transaction với dòng
  `side_effects` (`current_tx()`); process chết giữa chừng thì cả hai cùng mất hoặc cùng còn (D-18).
- `close`: B16 ghi kết quả — `UPDATE … WHERE status='pending'` nên chạy lại (resume, recover) không đổi
  gì (B15-B16 mục 5 "idempotent tự nhiên"). Route duyệt KHÔNG ghi quyết định, chỉ B16 ghi.
- `lock_row`: route duyệt đọc phiếu `FOR UPDATE` trong transaction NGẮN (chỉ đọc + kiểm) rồi nhả,
  trước khi giao sự kiện cho graph (khoá ticket riêng, D-19).
- Bấm muộn (TC27, quyết định 2b-3 Q2): KHÔNG đổi `status` — phiếu `pending` quá hạn phải giữ `pending`
  để worker còn bắn timeout (E6); chỉ ghi audit `late_event` (`graph.late_event.record_late`).
- `notify_approver`: thông báo trong app thật ở Phase 4 (bảng `notifications`); 2b chỉ log.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Table, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import Approval
from app.db.runtime import current_tx

log = logging.getLogger(__name__)

_APPROVALS: Table = Approval.__table__  # type: ignore[assignment]


@dataclass(frozen=True)
class ApprovalRow:
    approval_id: str
    ticket_id: str
    approver_id: str
    status: str
    deadline: datetime
    decided_by: str | None
    note: str | None
    first_viewed_at: datetime | None


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


def _row(r: Any) -> ApprovalRow:
    return ApprovalRow(
        approval_id=str(r.approval_id), ticket_id=r.ticket_id, approver_id=r.approver_id,
        status=r.status, deadline=r.deadline.astimezone(UTC), decided_by=r.decided_by,
        note=r.note, first_viewed_at=_utc(r.first_viewed_at),
    )  # fmt: skip


def _approval_pk(approval_id: str) -> int | None:
    return int(approval_id) if approval_id.isdigit() else None


class SqlApprovals:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def _exec[T](self, fn: Callable[[AsyncConnection], Awaitable[T]]) -> T:
        conn = current_tx()
        if conn is not None:
            return await fn(conn)
        async with self._engine.begin() as own:
            return await fn(own)

    async def create(
        self, ticket_id: str, approver_id: str, deadline: datetime, action_plan_hash: str
    ) -> str:
        async def run(conn: AsyncConnection) -> str:
            row = await conn.execute(
                insert(_APPROVALS)
                .values(ticket_id=ticket_id, approver_id=approver_id, deadline=deadline,
                        action_plan_hash=action_plan_hash)
                .returning(_APPROVALS.c.approval_id)
            )  # fmt: skip
            return str(row.scalar_one())

        return await self._exec(run)

    async def notify_approver(self, approval_id: str, approver_id: str) -> str:
        log.info("phiếu duyệt %s → người duyệt %s (thông báo trong app: Phase 4)", approval_id, approver_id)
        return f"log:{approval_id}"

    async def close(
        self,
        approval_id: str,
        result: str,
        at: datetime,
        *,
        decided_by: str | None = None,
        note: str | None = None,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_APPROVALS)
                .where(_APPROVALS.c.approval_id == int(approval_id), _APPROVALS.c.status == "pending")
                .values(status=result, decided_at=at, decided_by=decided_by, note=note)
            )

    async def get(self, approval_id: str) -> ApprovalRow | None:
        pk = _approval_pk(approval_id)
        if pk is None:
            return None
        async with self._engine.connect() as conn:
            r = (await conn.execute(select(_APPROVALS).where(_APPROVALS.c.approval_id == pk))).first()
        return None if r is None else _row(r)

    @asynccontextmanager
    async def lock_row(self, approval_id: str) -> AsyncIterator[ApprovalRow | None]:
        """Transaction ngắn giữ khoá hàng suốt khối `async with` (B15-B16 mục 5 handler)."""
        pk = _approval_pk(approval_id)
        if pk is None:
            yield None
            return
        async with self._engine.begin() as conn:
            r = (
                await conn.execute(
                    select(_APPROVALS).where(_APPROVALS.c.approval_id == pk).with_for_update()
                )
            ).first()
            yield None if r is None else _row(r)
