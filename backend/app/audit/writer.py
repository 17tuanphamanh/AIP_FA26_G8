"""Writer `audit_logs` cho runtime (M7; P1 mục 5.1, P7 2.7) — chỉ INSERT (bảng append-only ở cả
quyền `app_rw` lẫn trigger, D-05). Khớp `graph.ports.AuditSink` theo cấu trúc.

Dòng có `idempotency_key`: `INSERT … ON CONFLICT DO NOTHING`, rồi kiểm dòng tồn tại TRONG CÙNG
transaction — goto() dựa vào kết quả này cho chuyển cấm 4 (→ S_RESOLVED phải có dòng audit).

`lineage` (3g, Q-3g-3): dòng lineage của bước (B10) ghi TRONG CÙNG transaction với dòng audit — idempotent theo
(ticket_id, turn_id, step, prompt_id) (`db/lineage.insert_once`).
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Table, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.lineage import check_lineage_row, insert_once
from app.db.models import AuditLog

_TABLE: Table = AuditLog.__table__  # type: ignore[assignment]
AUDIT_COLUMNS = frozenset(c.name for c in _TABLE.columns) - {"log_id"}


def check_audit_row(row: Mapping[str, Any]) -> None:
    """Dùng chung cho writer thật và bản giả in-memory: cột lạ hoặc thiếu step/event → lỗi lập trình."""
    unknown = set(row) - AUDIT_COLUMNS
    if unknown:
        raise ValueError(f"audit_logs: cột lạ {sorted(unknown)}")
    if not row.get("ticket_id") or not row.get("step") or not row.get("event"):
        raise ValueError("audit_logs: thiếu ticket_id/step/event")


class AuditWriter:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, row: Mapping[str, Any], *, lineage: Mapping[str, Any] | None = None) -> bool:
        check_audit_row(row)
        if lineage is not None:
            check_lineage_row(lineage)  # lỗi lập trình nổ TRƯỚC khi mở transaction
        key = row.get("idempotency_key")
        async with self._engine.begin() as conn:
            if lineage is not None:
                await insert_once(conn, lineage)
            if key is None:
                await conn.execute(insert(_TABLE).values(**row))
                return True
            await conn.execute(
                pg_insert(_TABLE)
                .values(**row)
                .on_conflict_do_nothing(
                    index_elements=["idempotency_key"],
                    index_where=text("idempotency_key IS NOT NULL"),
                )
            )
            found = await conn.execute(select(_TABLE.c.log_id).where(_TABLE.c.idempotency_key == key))
            return found.first() is not None
