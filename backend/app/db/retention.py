"""Truy vấn của job hạn giữ (M2 bn-a; P7 mục 4 [Chốt 17.2]) — chạy bằng role `app_rw` (ĐP chốt Q1: KHÔNG `app_migrate`, lệch P7 mục 4 —
owner tắt được trigger append-only, `app_rw` thì không; `app_rw` có CRUD trên bảng checkpoint từ 0003).

- `expired_threads(cutoff, limit)`: ticket CÒN dòng ở một trong 3 bảng checkpoint, ĐÃ kết thúc (`final_state IS NOT NULL`), `closed_at <
  cutoff` (chặt — đúng mốc thì còn), không escalation đang mở / lượt mở ở BẤT KỲ ai trong họ (chính nó, cha, con — L2 còn cần ngữ cảnh), có
  cha thì cha cũng đã kết thúc trước mốc, là cha thì mọi con đã kết thúc. Cũ nhất trước, tối đa `limit`. Checkpoint xoá bằng API của saver (`adelete_thread`) ở `graph/retention.py` — KHÔNG ở đây.
- `purge_ticket_rows(ticket_id)`: `side_effects` của ticket + `child_notices` có `parent_ticket_id` = ticket (P7 mục 4: cùng vòng đời
  hội thoại, theo ticket CHA). Một transaction.
- `sessions`: `expires_at < cutoff` VÀ không dòng `tickets`/`turns` nào trỏ tới (FK — ĐP chốt Q2; không sửa `tickets`).
- `wait_deadlines`: `fired_at < cutoff` (mọi chỗ đọc chỉ lấy `fired_at IS NULL`).
- `record_run`: ĐÚNG 1 dòng `security_events` loại `retention_run` (ĐP chốt Q5) — loại này vào CHECK ở migration 0016 (dời từ 0015 — ĐP chốt 09/11, bản demo lo-0811: số 0015 thuộc lô Q12 `it_help`); TỚI LÚC ĐÓ (cờ chờ:
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

# Họ = chính ticket + cha + các con (soát M2 1b): escalation mở / lượt mở ở BẤT KỲ ai trong họ → giữ cả họ (L2 còn cần ngữ cảnh).
_FAMILY = "(x.ticket_id = t.ticket_id OR x.ticket_id = t.parent_ticket_id OR x.ticket_id IN " \
          "(SELECT k.ticket_id FROM tickets k WHERE k.parent_ticket_id = t.ticket_id))"
# Còn dòng ở BẤT KỲ bảng checkpoint nào (soát M2 2b): `adelete_thread` xoá 3 bảng bằng 3 lệnh — lỗi giữa chừng thì lượt sau chọn lại.
_HAS_CHECKPOINT = " OR ".join(
    f"EXISTS (SELECT 1 FROM {table} c WHERE c.thread_id = t.ticket_id)"
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
)
_EXPIRED_THREADS = text(
    "SELECT t.ticket_id FROM tickets t "
    "WHERE t.final_state IS NOT NULL AND t.closed_at < :cutoff "
    f"AND ({_HAS_CHECKPOINT}) "
    f"AND NOT EXISTS (SELECT 1 FROM escalations x WHERE x.closed_at IS NULL AND {_FAMILY}) "
    f"AND NOT EXISTS (SELECT 1 FROM turns x WHERE x.ended_at IS NULL AND {_FAMILY}) "
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
        if RETENTION_EVENT not in SECURITY_EVENT_TYPES:  # cờ chờ migration 0016 (CHECK chưa nhận loại này)
            log.info("retention_run (chưa ghi security_events — chờ 0016): %s",
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
