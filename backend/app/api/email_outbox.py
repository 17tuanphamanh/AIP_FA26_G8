"""`GET /api/admin/email-outbox` — hàng đợi email CHỈ ĐỌC cho Trưởng BP IT (notify-email).

Quyền `audit:read:all` (chỉ manager; không thêm permission mới — [Chốt 2.2]). Thứ tự lỗi: 401 → 403 → 422 (tham số). Chỉ GET.
Mỗi dòng: thời điểm tạo/gửi, `kind`, người nhận ĐÃ CHE (`a***@miền`, NULL khi người nhận chưa có email), trạng thái, số lần thử,
tên lớp lỗi cuối. KHÔNG trả `subject`, `body`, địa chỉ đầy đủ hay `user_id` người nhận — model `extra="forbid"` không có chỗ cho
chúng. Đọc qua engine chính (bảng `email_outbox` không cấp `app_monitor`), không ghi gì.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from app.api.alerts import ErrorDetail
from app.auth.deps import require
from app.auth.models import Principal
from app.notify.email import mask_address
from app.notify.outbox import recent_outbox

router = APIRouter()

LIMIT_DEFAULT = 50
LIMIT_MAX = 200

type OutboxStatus = Literal["pending", "sent", "failed", "skipped"]

READ_ERRORS: dict[int | str, dict[str, Any]] = {401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutboxItem(_Strict):
    id: int
    created_at: datetime
    sent_at: datetime | None
    kind: str
    recipient: str | None  # dạng che
    status: str
    attempts: int
    last_error_class: str | None


class OutboxList(_Strict):
    items: list[OutboxItem]


@router.get("/api/admin/email-outbox", response_model=OutboxList, responses=READ_ERRORS)
async def email_outbox(
    request: Request,
    _: Annotated[Principal, Depends(require("audit:read:all"))],
    status: Annotated[OutboxStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=LIMIT_MAX)] = LIMIT_DEFAULT,
) -> OutboxList:
    rows = await recent_outbox(request.app.state.engines.main, limit, status)
    return OutboxList(items=[OutboxItem(
        id=r.id, created_at=r.created_at, sent_at=r.sent_at, kind=r.kind, recipient=mask_address(r.address),
        status=r.status, attempts=r.attempts, last_error_class=r.last_error_class,
    ) for r in rows])  # fmt: skip
