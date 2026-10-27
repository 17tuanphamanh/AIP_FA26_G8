"""`GET /api/alerts`, `POST /api/alerts/{id}/ack` — M9 A3 (chốt Q-M9-A3-2 ở #10, Q-M9-A3-1 ở #6, duyệt plan A3).

Thứ tự kiểm như route cũ: 401 → `require("alert:read")` 403 (ghi `permission_denied`) → 422 tham số (FastAPI gom, ném SAU
dependency quyền) → GET: engine monitor (thiếu DSN → 503 `monitor_unavailable`) / POST: 404 → 409.

- GET đọc bằng engine `app_monitor` trong một giao dịch `REPEATABLE READ, READ ONLY` (`monitor.db.read_snapshot`); không bao
  giờ rơi về `engines.main`. 200 = `{"items": [AlertView], "truncated": bool}` — object, không phải mảng trần.
- `audience` là NHÃN, không phải quyền: ai có `alert:read` thấy mọi cảnh báo; `?audience=` chỉ là bộ lọc tùy chọn.
- POST ghi bằng `app_rw` qua `app.audit.alerts.AlertWriter.ack` (M7) — `app.monitor` không import `app.audit`. Không body;
  `acked_by` = người trong token. Không đụng engine monitor → thiếu DSN monitor vẫn ack được (503 chỉ áp cho GET).
- `detail` của dòng `alerts` không phải object → `{}`; `severity` để `str` (cột không có CHECK): một dòng lạ không được làm
  500 cả danh sách (= mất cảnh báo).
- `responses=` khai thân lỗi THẬT cho OpenAPI (FE sinh kiểu): 422 là `{"error","fields"}` (`api.errors`), không phải
  `HTTPValidationError` mặc định của FastAPI. `ErrorDetail`, `InvalidRequestBody`, `GET_ERRORS` khai ở `api.dashboard`
  (D13, tránh vòng import), xuất lại ở đây cho các route đang import từ module này.
- Khung giờ (D13): `from`/`to` nhận đúng như `/api/dashboard` (`window` + `resolve_window`, kiểm trong THÂN handler sau
  quyền); lọc `window_start` trong `[from, to)`. Không gửi cả hai → không lọc (KHÔNG áp mặc định 7 ngày) = như trước D13.
"""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel

from app.api.dashboard import (
    GET_ERRORS,
    ErrorDetail,
    InvalidRequestBody,
    resolve_window,
    window,
)
from app.audit.alerts import AlertWriter
from app.auth.deps import require
from app.auth.models import Principal
from app.monitor.db import read_snapshot
from app.monitor.queries.alerts import AlertRow, audience_of, list_alerts

router = APIRouter()

LIMIT_DEFAULT = 200
LIMIT_MAX = 200
ALERT_ID_MAX = 2**63 - 1  # alerts.alert_id BIGINT — lớn hơn thì 422, không để Postgres báo lỗi (500)
NOT_FOUND = "not_found"
ALREADY_ACKED = "already_acked"

type AlertStatus = Literal["open", "acked"]
type AudienceParam = Literal["manager", "dev", "ops"]  # = monitor.rules.AUDIENCE_VALUES (test ghim)


class AlertView(BaseModel):
    """Một cảnh báo — ĐÚNG 12 khoá (Q-M9-A3-2); thời gian ISO 8601 có múi giờ."""

    alert_id: int
    rule_id: str
    subject: str
    severity: str
    value: float | None
    window_start: datetime
    status: AlertStatus
    detail: dict[str, Any]
    audience: list[AudienceParam]
    acked_by: str | None
    acked_at: datetime | None
    created_at: datetime


class AlertList(BaseModel):
    items: list[AlertView]
    truncated: bool  # còn dòng ngoài `limit` (không phân trang — FE hiện băng)


ACK_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail},
    403: {"model": ErrorDetail},
    404: {"model": ErrorDetail},
    409: {"model": ErrorDetail},
    422: {"model": InvalidRequestBody},
}


def _view(row: AlertRow | dict[str, Any]) -> AlertView:
    """Dòng `alerts` (đọc qua monitor, hoặc `RETURNING` của ack) → `AlertView`; `audience` tra `REGISTRY`."""
    fields = asdict(row) if isinstance(row, AlertRow) else dict(row)
    detail = fields["detail"]
    return AlertView(
        alert_id=fields["alert_id"], rule_id=fields["rule_id"], subject=fields["subject"], severity=fields["severity"],
        value=fields["value"], window_start=fields["window_start"], status=fields["status"],
        detail=detail if isinstance(detail, dict) else {}, audience=list(audience_of(fields["rule_id"])),
        acked_by=fields["acked_by"], acked_at=fields["acked_at"], created_at=fields["created_at"],
    )  # fmt: skip


@router.get("/api/alerts", response_model=AlertList, responses=GET_ERRORS)
async def alerts(
    request: Request,
    _: Annotated[Principal, Depends(require("alert:read"))],
    raw: Annotated[tuple[datetime | None, datetime | None], Depends(window)],
    status: Annotated[AlertStatus | None, Query()] = None,
    audience: Annotated[AudienceParam | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=LIMIT_MAX)] = LIMIT_DEFAULT,
) -> AlertList:
    frm: datetime | None = None
    to: datetime | None = None
    if raw != (None, None):
        frm, to = resolve_window(*raw, now=request.app.state.m9_clock.now())
    async with read_snapshot(request.app.state.engines) as conn:
        page = await list_alerts(conn, status=status, audience=audience, limit=limit, frm=frm, to=to)
    return AlertList(items=[_view(r) for r in page.rows], truncated=page.truncated)


@router.post("/api/alerts/{alert_id}/ack", response_model=AlertView, responses=ACK_ERRORS)
async def ack(
    request: Request,
    p: Annotated[Principal, Depends(require("alert:read"))],
    alert_id: Annotated[int, Path(ge=1, le=ALERT_ID_MAX)],
) -> AlertView:
    writer = AlertWriter(request.app.state.engines.main, request.app.state.m9_clock)
    result = await writer.ack(alert_id, p.user_id)
    if result.outcome == "not_found":
        raise HTTPException(404, NOT_FOUND)
    if result.outcome == "already_acked":
        raise HTTPException(409, ALREADY_ACKED)
    assert result.row is not None
    return _view(dict(result.row))
