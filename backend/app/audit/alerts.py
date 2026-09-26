"""Writer `alerts` của M7 (P9 mục 6: "ngoại lệ ghi duy nhất … qua `audit/alerts_writer`").

`raise_once`: `INSERT … ON CONFLICT (rule_id, subject, window_start) DO NOTHING` — hai nơi sinh cùng
một cảnh báo (auth lúc khoá, B1 khi gặp người đang bị khoá) vẫn ra đúng một dòng; chạy lại cũng vậy.
Khớp `auth.ports.AlertSink` và `graph.ports.AlertSink` theo cấu trúc.
"""

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.security_events import check_detail
from app.core.clock import Clock
from app.db.models import Alert
from app.domain.alerts import SUBJECT_MAX, AlertDraft

_TABLE: Table = Alert.__table__  # type: ignore[assignment]
_KEY = ("rule_id", "subject", "window_start")


def check_alert(draft: AlertDraft) -> None:
    """Dùng chung cho writer thật và bản giả test."""
    if not draft.rule_id:
        raise ValueError("alerts: thiếu rule_id")
    if len(draft.subject) > SUBJECT_MAX:
        raise ValueError(f"alerts.subject dài quá {SUBJECT_MAX} ký tự")
    if draft.window_start.tzinfo is None:
        raise ValueError("alerts.window_start phải có múi giờ")
    check_detail("alerts", draft.detail)


class AlertWriter:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    async def raise_once(self, draft: AlertDraft) -> bool:
        """True = vừa tạo dòng mới; False = cảnh báo này đã có (cùng khoá)."""
        check_alert(draft)
        async with self._engine.begin() as conn:
            row = await conn.execute(
                pg_insert(_TABLE)
                .values(
                    rule_id=draft.rule_id,
                    subject=draft.subject,
                    window_start=draft.window_start,
                    severity=draft.severity,
                    value=draft.value,
                    detail=dict(draft.detail),
                    created_at=self._clock.now(),
                )
                .on_conflict_do_nothing(index_elements=list(_KEY))
                .returning(_TABLE.c.alert_id)
            )
            return row.first() is not None
