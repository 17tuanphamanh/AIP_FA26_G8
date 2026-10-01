"""Repository `approvals` (P7 2.6, B15-B16 mục 5) — 2b-Q3.

- `create`: B15 gọi QUA `effects.once("approval_create")` → ghi trong CÙNG transaction với dòng
  `side_effects` (`current_tx()`); process chết giữa chừng thì cả hai cùng mất hoặc cùng còn (D-18). Phase 4 4b P8: người dự
  phòng + xung đột là tham số keyword BẮT BUỘC (TQ-9 — node quên truyền là lỗi kiểu, không lặng lẽ thành None/False).
- `close`: B16 ghi kết quả — `UPDATE … WHERE status='pending'` nên chạy lại (resume, recover) không đổi
  gì (B15-B16 mục 5 "idempotent tự nhiên"). Route duyệt KHÔNG ghi quyết định, chỉ B16 ghi. Trả số dòng đổi (0/1) — B16 ghi
  `close_applied` vào điểm log 6 (4c P2, TQ-4). `decided_at` đặt ở MỌI nhánh đóng (approved/rejected/timeout — M9 luật 7).
- `lock_row`: route duyệt đọc phiếu `FOR UPDATE` trong transaction NGẮN (chỉ đọc + kiểm) rồi nhả,
  trước khi giao sự kiện cho graph (khoá ticket riêng, D-19).
- Bấm muộn (TC27, quyết định 2b-3 Q2): KHÔNG đổi `status` — phiếu `pending` quá hạn phải giữ `pending`
  để worker còn bắn timeout (E6); chỉ ghi audit `late_event` (`graph.late_event.record_late`).
- `notify_approver`: Phase 4 vẫn CHỈ log (hộp thư = `GET /api/approvals?mine=1`; bảng thông báo ở Phase 7 — Q-4-E). `kind` (4c P3,
  TQ-8): `new` (B15, mặc định — `result_ref` giữ `log:{id}`), `reminder_1`/`reminder_2` (worker nhắc 50 %/80 %). `log_approver_notice` là
  MỘT định nghĩa cho cả B15 (qua phương thức này) lẫn worker nhắc (`WorkerJobs`, Q-4c-2 = A — `worker.py` không truyền `SqlApprovals`).
- `get_status` (3h): B17 kiểm "đã duyệt" = state + bảng + hash (phase3 11.4 bước 1, P8).
- 4c DỪNG 2 (P5, P6 — route hộp thư/xem phiếu; `main.py` dựng `Desk` với chính lớp này nên truy vấn mới nằm ở đây): `inbox` (phiếu
  tôi được giao + dự phòng SAU nhắc 2, nối `tickets` lấy người gửi + dòng audit B15 `queued` cùng `action_plan_hash` lấy
  `intended_action` — không đọc checkpoint), `mark_viewed` (`first_viewed_at` chỉ lần đầu, chỉ khi `pending`), `procedure_title`
  (tiêu đề tài liệu quy trình ở bản KB hiện hành).
"""

import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import Table, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import Approval
from app.db.runtime import current_tx

log = logging.getLogger(__name__)

_APPROVALS: Table = Approval.__table__  # type: ignore[assignment]

type NoticeKind = Literal["new", "reminder_1", "reminder_2"]

# 4c P5: vai trò lọc Ở SQL (trước LIMIT); hành động của phiếu = dòng audit B15 `queued` CÙNG ticket + `action_plan_hash` (mới nhất) —
# không đọc checkpoint từng phiếu (5.7 #5). Xung đột lợi ích lọc ở route (`authz.approval_role`).
_INBOX_SQL = """
SELECT a.approval_id, a.ticket_id, a.status, a.created_at, a.deadline, a.reminder_1_at, a.reminder_2_at,
       a.approver_id, a.backup_approver_id, t.requester_id, q.intended_action
FROM approvals a
JOIN tickets t ON t.ticket_id = a.ticket_id
LEFT JOIN LATERAL (
    SELECT l.intended_action FROM audit_logs l
    WHERE l.ticket_id = a.ticket_id AND l.step = 'B15' AND l.event = 'queued' AND l.action_plan_hash = a.action_plan_hash
    ORDER BY l.created_at DESC, l.log_id DESC LIMIT 1
) q ON true
WHERE (a.approver_id = :me OR (a.backup_approver_id = :me AND a.reminder_2_at IS NOT NULL)) {status}
ORDER BY a.created_at DESC, a.approval_id DESC
LIMIT :limit
"""
_INBOX = text(_INBOX_SQL.format(status=""))
_INBOX_BY_STATUS = text(_INBOX_SQL.format(status="AND a.status = :status"))
# 4c P6: ghi lần xem ĐẦU, chỉ khi phiếu còn chờ.
_MARK_VIEWED = text(
    "UPDATE approvals SET first_viewed_at = :now WHERE approval_id = :id AND first_viewed_at IS NULL AND status = 'pending' "
    "RETURNING approval_id"
)
# 4c P6: tài liệu ở bản KB HIỆN HÀNH (`kb_documents.kb_version` chỉ có ở tài liệu bật — Q-3b-2).
_PROCEDURE_TITLE = text(
    "SELECT d.title FROM kb_documents d JOIN kb_versions v ON v.kb_version = d.kb_version "
    "WHERE v.is_current AND d.doc_id = :doc ORDER BY d.version DESC LIMIT 1"
)


async def log_approver_notice(approval_id: str, approver_id: str, kind: NoticeKind = "new") -> str:
    """Thông báo cho người duyệt (Phase 4: chỉ log — không chữ người dùng, chỉ id + loại). `result_ref` của `new` giữ như 2b."""
    log.info("phiếu duyệt %s → người duyệt %s (%s; thông báo trong app: Phase 7)", approval_id, approver_id, kind)
    return f"log:{approval_id}" if kind == "new" else f"log:{approval_id}:{kind}"


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
    # Phase 4 4b P8 (+ `conflict_detected`: nhánh `peek` của B15 suy `choice_reason` và ghi điểm log 5 từ phiếu cũ — 5.6 #8)
    backup_approver_id: str | None
    conflict_detected: bool
    conflict_type: str | None
    created_at: datetime
    reminder_1_at: datetime | None
    reminder_2_at: datetime | None
    decided_at: datetime | None
    action_plan_hash: str  # 4c P6: xem phiếu so `hash_action(action trong checkpoint)` với giá trị đã băm lúc tạo phiếu


@dataclass(frozen=True)
class InboxRow:
    """Một dòng hộp thư (P5): cột phiếu + người gửi (lọc xung đột ở route) + `intended_action` của dòng audit B15 `queued` (None
    khi B15 giả không ghi)."""

    approval_id: str
    ticket_id: str
    status: str
    created_at: datetime
    deadline: datetime
    reminder_1_at: datetime | None
    reminder_2_at: datetime | None
    approver_id: str
    backup_approver_id: str | None
    requester_id: str
    intended_action: dict[str, Any] | None


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


def _row(r: Any) -> ApprovalRow:
    return ApprovalRow(
        approval_id=str(r.approval_id), ticket_id=r.ticket_id, approver_id=r.approver_id,
        status=r.status, deadline=r.deadline.astimezone(UTC), decided_by=r.decided_by,
        note=r.note, first_viewed_at=_utc(r.first_viewed_at),
        backup_approver_id=r.backup_approver_id, conflict_detected=r.conflict_detected, conflict_type=r.conflict_type,
        created_at=r.created_at.astimezone(UTC), reminder_1_at=_utc(r.reminder_1_at), reminder_2_at=_utc(r.reminder_2_at),
        decided_at=_utc(r.decided_at), action_plan_hash=r.action_plan_hash,
    )  # fmt: skip


_PK = re.compile(r"[0-9]{1,18}")  # soát 4c S1c: `isdigit()` nhận "²" (int() ném → 500) và số > BIGINT; ≤ 18 chữ số < 2^63


def _approval_pk(approval_id: str) -> int | None:
    return int(approval_id) if _PK.fullmatch(approval_id) else None


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
        self,
        ticket_id: str,
        approver_id: str,
        deadline: datetime,
        action_plan_hash: str,
        *,
        backup_approver_id: str | None,
        conflict_detected: bool,
        conflict_type: str | None,
    ) -> str:
        async def run(conn: AsyncConnection) -> str:
            row = await conn.execute(
                insert(_APPROVALS)
                .values(ticket_id=ticket_id, approver_id=approver_id, deadline=deadline,
                        action_plan_hash=action_plan_hash, backup_approver_id=backup_approver_id,
                        conflict_detected=conflict_detected, conflict_type=conflict_type)
                .returning(_APPROVALS.c.approval_id)
            )  # fmt: skip
            return str(row.scalar_one())

        return await self._exec(run)

    async def notify_approver(self, approval_id: str, approver_id: str, kind: NoticeKind = "new") -> str:
        return await log_approver_notice(approval_id, approver_id, kind)

    async def close(
        self,
        approval_id: str,
        result: str,
        at: datetime,
        *,
        decided_by: str | None = None,
        note: str | None = None,
    ) -> int:
        async with self._engine.begin() as conn:
            res = await conn.execute(
                update(_APPROVALS)
                .where(_APPROVALS.c.approval_id == int(approval_id), _APPROVALS.c.status == "pending")
                .values(status=result, decided_at=at, decided_by=decided_by, note=note)
            )
        return int(res.rowcount)

    async def get(self, approval_id: str) -> ApprovalRow | None:
        pk = _approval_pk(approval_id)
        if pk is None:
            return None
        async with self._engine.connect() as conn:
            r = (await conn.execute(select(_APPROVALS).where(_APPROVALS.c.approval_id == pk))).first()
        return None if r is None else _row(r)

    async def inbox(self, user_id: str, status: str | None, limit: int) -> list[InboxRow]:
        params: dict[str, Any] = {"me": user_id, "limit": limit}
        if status is not None:
            params["status"] = status
        async with self._engine.connect() as conn:
            rows = await conn.execute(_INBOX_BY_STATUS if status is not None else _INBOX, params)
            return [InboxRow(
                approval_id=str(r.approval_id), ticket_id=r.ticket_id, status=r.status, created_at=r.created_at.astimezone(UTC),
                deadline=r.deadline.astimezone(UTC), reminder_1_at=_utc(r.reminder_1_at),
                reminder_2_at=_utc(r.reminder_2_at), approver_id=r.approver_id, backup_approver_id=r.backup_approver_id,
                requester_id=r.requester_id, intended_action=r.intended_action,
            ) for r in rows]  # fmt: skip

    async def mark_viewed(self, approval_id: str, now: datetime) -> bool:
        pk = _approval_pk(approval_id)
        if pk is None:
            return False
        async with self._engine.begin() as conn:
            row = (await conn.execute(_MARK_VIEWED, {"id": pk, "now": now})).first()
        return row is not None

    async def procedure_title(self, doc_id: str) -> str | None:
        async with self._engine.connect() as conn:
            title = (await conn.execute(_PROCEDURE_TITLE, {"doc": doc_id})).scalar()
        return None if title is None else str(title)

    async def get_status(self, approval_id: str) -> str | None:
        """B17 (3h, P8): "đã duyệt" đọc cả BẢNG, không chỉ state. Không có phiếu → None."""
        row = await self.get(approval_id)
        return None if row is None else row.status

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
