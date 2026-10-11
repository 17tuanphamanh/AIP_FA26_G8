"""Đọc bảng `alerts` cho `GET /api/alerts` (A3; chốt Q-M9-A3-2 ở #10, Q-M9-A3-1 ở #6).

- Chỉ đọc qua `AsyncConnection` của engine `app_monitor` (`alerts` thuộc `MONITOR_TABLES`). Ghi (ack) KHÔNG ở đây mà ở
  `app.audit.alerts` (M7) — `app.monitor` không import `app.audit` (`.importlinter` monitor-read-only).
- `audience` là NHÃN định tuyến, không phải quyền: lấy từ `REGISTRY[rule_id].audience` (Q-M9-B1-9), không đọc
  `alerts.detail`. `rule_id` không có trong `REGISTRY` (luật đã gỡ, hoặc cảnh báo do thành phần khác ghi) →
  `DEFAULT_AUDIENCE`, vẫn hiển thị — không được rơi mất.
- Lọc `audience` bằng SQL TRƯỚC `LIMIT` (lọc sau thì `truncated` sai và mất dòng); mỗi mệnh đề WHERE có ngoặc riêng
  (thiếu ngoặc quanh `OR` thì `status` không còn áp cho nhánh "luật lạ").
- Xếp `created_at DESC, alert_id DESC`; lấy `limit + 1` dòng → `truncated` (không cắt im lặng).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import ALERT_STATUSES
from app.monitor.rules import AUDIENCE_VALUES, REGISTRY, Audience, RuleSpec

DEFAULT_AUDIENCE: tuple[Audience, ...] = ("manager",)
_COLUMNS = (
    "alert_id, rule_id, subject, severity, value, window_start, status, detail, acked_by, acked_at, created_at"
)


@dataclass(frozen=True)
class AlertRow:
    alert_id: int
    rule_id: str
    subject: str
    severity: str
    value: float | None
    window_start: datetime
    status: str
    detail: Any  # JSONB nguyên văn — api ép về object (không phải object → {})
    acked_by: str | None
    acked_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class AlertPage:
    rows: tuple[AlertRow, ...]
    truncated: bool  # còn dòng ngoài `limit`


def audience_of(rule_id: str, registry: Mapping[str, RuleSpec] = REGISTRY) -> tuple[Audience, ...]:
    """Người nhận của luật theo `REGISTRY`; `rule_id` lạ → `DEFAULT_AUDIENCE`."""
    spec = registry.get(rule_id)
    return spec.audience if spec is not None else DEFAULT_AUDIENCE


async def list_alerts(
    conn: AsyncConnection,
    *,
    status: str | None,
    audience: str | None,
    limit: int,
    registry: Mapping[str, RuleSpec] = REGISTRY,
) -> AlertPage:
    """Cảnh báo mới nhất trước. `status`/`audience` None = không lọc. `audience` = X: luật có X trong audience; với X thuộc
    `DEFAULT_AUDIENCE` thêm mọi `rule_id` không có trong `registry`."""
    if limit < 1:
        raise ValueError("limit phải ≥ 1")
    if status is not None and status not in ALERT_STATUSES:
        raise ValueError(f"status lạ: {status!r}")
    if audience is not None and audience not in AUDIENCE_VALUES:
        raise ValueError(f"audience lạ: {audience!r}")
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit + 1}
    if status is not None:
        where.append("(status = :status)")
        params["status"] = status
    if audience is not None:
        params["ids"] = [rule_id for rule_id, spec in registry.items() if audience in spec.audience]
        if audience in DEFAULT_AUDIENCE:
            where.append("(rule_id = ANY(CAST(:ids AS text[])) OR rule_id <> ALL(CAST(:known AS text[])))")
            params["known"] = list(registry)
        else:
            where.append("(rule_id = ANY(CAST(:ids AS text[])))")
    sql = f"SELECT {_COLUMNS} FROM alerts"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, alert_id DESC LIMIT :limit"
    rows = (await conn.execute(text(sql), params)).all()
    page = [AlertRow(*row) for row in rows[:limit]]
    return AlertPage(rows=tuple(page), truncated=len(rows) > limit)
