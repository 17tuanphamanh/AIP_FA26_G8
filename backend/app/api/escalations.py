"""Hàng đợi L2 — `GET /api/escalations/queue` (P9 mục 7; B20 mục 4.1, 5.1).

Chỉ đọc. Quyền `escalation:handle` (l1, l2 — P6 5.1; manager không có quyền này → 403). Thứ tự lấy từ
`escalations.priority` (bảng seed `exit_code_priority` là nguồn duy nhất), chỉ ticket lá (D-30), chưa
đóng. Đóng escalation (`POST /api/escalations/{id}/close`, 422 ca deny) làm ở Phase 7.
"""

from dataclasses import asdict
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth.deps import require
from app.auth.models import Principal
from app.db.escalations import QueueItem

router = APIRouter()

QUEUE_LIMIT_DEFAULT = 50
QUEUE_LIMIT_MAX = 200


class EscalationQueue(Protocol):
    async def list_open(self, limit: int) -> list[QueueItem]: ...


def get_queue(request: Request) -> EscalationQueue:
    queue: EscalationQueue | None = getattr(request.app.state, "escalations", None)
    if queue is None:
        raise HTTPException(503, "escalations_unavailable")
    return queue


@router.get("/api/escalations/queue")
async def escalation_queue(
    _: Annotated[Principal, Depends(require("escalation:handle"))],
    queue: Annotated[EscalationQueue, Depends(get_queue)],
    limit: Annotated[int, Query(ge=1, le=QUEUE_LIMIT_MAX)] = QUEUE_LIMIT_DEFAULT,
) -> list[dict[str, Any]]:
    items = await queue.list_open(limit)
    return [{**asdict(i), "created_at": i.created_at.isoformat()} for i in items]
