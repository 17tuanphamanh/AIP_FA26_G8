"""Truy vấn của job hạn giữ (M2 bn-a; P7 mục 4 [Chốt 17.2]) — chạy bằng role `app_rw` (ĐP chốt Q1: KHÔNG `app_migrate`, lệch P7 mục 4 —
owner tắt được trigger append-only, `app_rw` thì không; `app_rw` có CRUD trên bảng checkpoint từ 0003).

- `expired_threads(cutoff, limit)`: ticket CÒN checkpoint, ĐÃ kết thúc (`final_state IS NOT NULL`), `closed_at < cutoff` (chặt — đúng mốc
  thì còn), không escalation đang mở (L2 còn cần hội thoại), không lượt mở, có cha thì cha cũng đã kết thúc trước mốc, là cha thì mọi con
  đã kết thúc. Cũ nhất trước, tối đa `limit`. Checkpoint xoá bằng API của saver (`adelete_thread`) ở `graph/retention.py` — KHÔNG ở đây.
- `purge_ticket_rows(ticket_id)`: `side_effects` của ticket + `child_notices` có `parent_ticket_id` = ticket (P7 mục 4: cùng vòng đời
  hội thoại, theo ticket CHA). Một transaction.
- `sessions`: `expires_at < cutoff` VÀ không dòng `tickets`/`turns` nào trỏ tới (FK — ĐP chốt Q2; không sửa `tickets`).
- `wait_deadlines`: `fired_at < cutoff` (mọi chỗ đọc chỉ lấy `fired_at IS NULL`).
- `record_run`: ĐÚNG 1 dòng `security_events` loại `retention_run` (ĐP chốt Q5) — loại này vào CHECK ở migration 0015; TỚI LÚC ĐÓ (cờ chờ:
  `retention_run` chưa có trong `SECURITY_EVENT_TYPES`) ghi 1 dòng log INFO cùng số đếm. `detail` chỉ số đếm + `dry_run`.
KHÔNG câu lệnh nào chạm `audit_logs`, `security_events` ngoài INSERT, `tickets`, `transaction_log`.
"""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import SECURITY_EVENT_TYPES
from app.db.security_events import insert_event

log = logging.getLogger(__name__)

RETENTION_EVENT = "retention_run"

_EXPIRED_THREADS = text(
    "SELECT t.ticket_id FROM tickets t "
    "WHERE t.final_state IS NOT NULL AND t.closed_at < :cutoff "
    "AND EXISTS (SELECT 1 FROM checkpoints c WHERE c.thread_id = t.ticket_id) "
    "AND NOT EXISTS (SELECT 1 FROM escalations e WHERE e.ticket_id = t.ticket_id AND e.closed_at IS NULL) "
    "AND NOT EXISTS (SELECT 1 FROM turns u WHERE u.ticket_id = t.ticket_id AND u.ended_at IS NULL) "
    "AND (t.parent_ticket_id IS NULL OR EXISTS (SELECT 1 FROM tickets p WHERE p.ticket_id = t.parent_ticket_id "
    "     AND p.final_state IS NOT NULL AND p.closed_at < :cutoff)) "
    "AND NOT EXISTS (SELECT 1 FROM tickets k WHERE k.parent_ticket_id = t.ticket_id AND k.final_state IS NULL) "
    "ORDER BY t.closed_at, t.ticket_id LIMIT :limit"
)
_SESSIONS_WHERE = (
    "FROM sessions s WHERE s.expires_at < :cutoff "
    "AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.session_id = s.session_id) "
    "AND NOT EXISTS (SELECT 1 FROM turns u WHERE u.session_id = s.session_id)"
)
_COUNT_SESSIONS = text(f"SELECT count(*) {_SESSIONS_WHERE}")
_DELETE_SESSIONS = text(f"DELETE FROM sessions WHERE session_id IN (SELECT s.session_id {_SESSIONS_WHERE})")
_WAITS_WHERE = "FROM wait_deadlines WHERE fired_at IS NOT NULL AND fired_at < :cutoff"
_COUNT_WAITS = text(f"SELECT count(*) {_WAITS_WHERE}")
_DELETE_WAITS = text(f"DELETE {_WAITS_WHERE}")


class SqlRetentionStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def expired_threads(self, cutoff: datetime, limit: int) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(_EXPIRED_THREADS, {"cutoff": cutoff, "limit": limit})
            return [str(r[0]) for r in rows]

    async def purge_ticket_rows(self, ticket_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(text("DELETE FROM side_effects WHERE ticket_id = :t"), {"t": ticket_id})
            await conn.execute(text("DELETE FROM child_notices WHERE parent_ticket_id = :t"), {"t": ticket_id})

    async def count_expired_sessions(self, cutoff: datetime) -> int:
        return await self._count(_COUNT_SESSIONS, cutoff)

    async def delete_expired_sessions(self, cutoff: datetime) -> int:
        return await self._delete(_DELETE_SESSIONS, cutoff)

    async def count_fired_waits(self, cutoff: datetime) -> int:
        return await self._count(_COUNT_WAITS, cutoff)

    async def delete_fired_waits(self, cutoff: datetime) -> int:
        return await self._delete(_DELETE_WAITS, cutoff)

    async def record_run(self, detail: Mapping[str, Any], *, at: datetime) -> None:
        if RETENTION_EVENT not in SECURITY_EVENT_TYPES:  # cờ chờ migration 0015 (CHECK chưa nhận loại này)
            log.info("retention_run (chưa ghi security_events — chờ 0015): %s",
                     " ".join(f"{k}={v}" for k, v in sorted(detail.items())))  # fmt: skip
            return
        async with self._engine.begin() as conn:
            await insert_event(conn, RETENTION_EVENT, occurred_at=at, detail=dict(detail))

    async def _count(self, sql: Any, cutoff: datetime) -> int:
        async with self._engine.connect() as conn:
            return int((await conn.execute(sql, {"cutoff": cutoff})).scalar_one())

    async def _delete(self, sql: Any, cutoff: datetime) -> int:
        async with self._engine.begin() as conn:
            return int((await conn.execute(sql, {"cutoff": cutoff})).rowcount or 0)
