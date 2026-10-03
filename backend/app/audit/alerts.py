"""Writer `alerts` của M7 (P9 mục 6: "ngoại lệ ghi duy nhất … qua `audit/alerts_writer`").

`raise_once`: `INSERT … ON CONFLICT (rule_id, subject, window_start) DO NOTHING` — hai nơi sinh cùng
một cảnh báo (auth lúc khoá, B1 khi gặp người đang bị khoá) vẫn ra đúng một dòng; chạy lại cũng vậy.
Khớp `auth.ports.AlertSink` và `graph.ports.AlertSink` theo cấu trúc.

`ack` (M9 A3, chốt Q-M9-A3-2/6 ở #10): thao tác GHI duy nhất người dùng làm với cảnh báo — `POST /api/alerts/{id}/ack`
gọi, bằng engine `app_rw` (route truyền `engines.main`), không qua `app.monitor` (M9 chỉ đọc). Nguyên tử: một
`UPDATE … WHERE status = 'open'` — hai người ack cùng lúc thì giao dịch sau chờ khoá dòng, Postgres kiểm lại `WHERE`
trên bản mới (READ COMMITTED) → 0 dòng → `already_acked`; `acked_by`/`acked_at` của người đầu giữ nguyên. Không
"SELECT rồi UPDATE". 0 dòng mà dòng vẫn `open` → thử lại UPDATE đúng một lần (không trả 409 cho cảnh báo còn mở); vẫn
`open` → `RuntimeError`. Dấu vết: 3 cột `status`, `acked_by`, `acked_at` + 1 dòng log INFO `alert_acked` (`alert_id`,
`rule_id`, `user_id` nằm trong message — `JsonFormatter` bỏ `extra`; không ghi `subject`, `detail`).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Table, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.audit.security_events import check_detail
from app.core.clock import Clock
from app.db.models import Alert
from app.domain.alerts import SUBJECT_MAX, AlertDraft

_TABLE: Table = Alert.__table__  # type: ignore[assignment]
_KEY = ("rule_id", "subject", "window_start")

log = logging.getLogger(__name__)

type AckOutcome = Literal["acked", "already_acked", "not_found"]


@dataclass(frozen=True)
class AckResult:
    outcome: AckOutcome
    row: Mapping[str, Any] | None  # đủ cột của dòng `alerts` sau khi ack; chỉ có khi outcome = "acked"


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

    async def ack(self, alert_id: int, user_id: str) -> AckResult:
        """Ack cảnh báo `alert_id` cho `user_id` (lấy từ token, không từ input); `acked_at` = Clock của app."""
        now = self._clock.now()
        async with self._engine.begin() as conn:
            row = await self._try_ack(conn, alert_id, user_id, now)
            if row is None and await self._status(conn, alert_id) == "open":
                row = await self._try_ack(conn, alert_id, user_id, now)  # thử lại đúng một lần
            if row is None:
                status = await self._status(conn, alert_id)
                if status is None:
                    return AckResult("not_found", None)
                if status == "acked":
                    return AckResult("already_acked", None)
                raise RuntimeError(f"alerts {alert_id}: vẫn '{status}' sau khi thử lại ack")
        fields = {"alert_id": alert_id, "rule_id": row["rule_id"], "user_id": user_id}
        log.info("alert_acked alert_id=%s rule_id=%s user_id=%s", *fields.values(), extra=fields)
        return AckResult("acked", row)

    async def _try_ack(
        self, conn: AsyncConnection, alert_id: int, user_id: str, now: datetime
    ) -> Mapping[str, Any] | None:
        """`UPDATE … WHERE alert_id = :id AND status = 'open' RETURNING *` — dòng sau ack, hoặc None (0 dòng)."""
        result = await conn.execute(
            update(_TABLE)
            .where(_TABLE.c.alert_id == alert_id, _TABLE.c.status == "open")
            .values(status="acked", acked_by=user_id, acked_at=now)
            .returning(*_TABLE.c)
        )
        row = result.mappings().first()
        return None if row is None else dict(row)

    @staticmethod
    async def _status(conn: AsyncConnection, alert_id: int) -> str | None:
        status: str | None = (
            await conn.execute(select(_TABLE.c.status).where(_TABLE.c.alert_id == alert_id))
        ).scalar_one_or_none()
        return status
