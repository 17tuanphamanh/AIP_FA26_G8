"""Phụ thuộc chung của route ticket và route duyệt (2b-3), dựng trong lifespan của `create_app`.

Runtime (checkpoint, runner) mở lỗi → `app.state.desk = None` → các route này trả 503, còn
`/api/health` vẫn chạy và báo `"runtime": "down"`.
"""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError

from app.api.background import BackgroundRuns
from app.auth.models import UserRecord
from app.core.clock import Clock
from app.graph.ports import ApprovalRepo, TicketRepo
from app.graph.runner import Runner
from app.guard.privacy import PrivacyGuard


class UserDirectory(Protocol):
    """`AuthStore.get_user` — phòng ban của người gửi, người quản lý của người duyệt."""

    async def get_user(self, user_id: str) -> UserRecord | None: ...


@dataclass(frozen=True)
class Desk:
    runner: Runner
    tickets: TicketRepo
    approvals: ApprovalRepo
    guard: PrivacyGuard
    users: UserDirectory
    clock: Clock
    background: BackgroundRuns
    retry_after_seconds: int  # TicketBusy → 503 + Retry-After (= ceil(TICKET_LOCK_TIMEOUT))


def retry_after(lock_timeout: float) -> int:
    return max(1, math.ceil(lock_timeout))


def get_desk(request: Request) -> Desk:
    desk: Desk | None = getattr(request.app.state, "desk", None)
    if desk is None:
        raise HTTPException(503, "runtime_unavailable")
    return desk


async def parse_body[M: BaseModel](request: Request, model: type[M]) -> M:
    """Đọc + kiểm body TRONG handler (không để FastAPI kiểm trước dependency): thứ tự kiểm của
    2b-3 là quyền → 404/403/409 → body 422. JSON hỏng cũng là 422."""
    raw = await request.body()
    try:
        data: Any = json.loads(raw) if raw else None
        return model.model_validate(data)
    except (ValueError, ValidationError) as exc:
        errors: Any = exc.errors(include_url=False) if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(422, _jsonable(errors)) from None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)
