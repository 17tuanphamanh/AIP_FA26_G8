"""Phụ thuộc chung của route ticket và route duyệt (2b-3), dựng trong lifespan của `create_app`.

Runtime (checkpoint, runner) mở lỗi → `app.state.desk = None` → các route này trả 503, còn
`/api/health` vẫn chạy và báo `"runtime": "down"`.

Privacy guard (3e, phase3 mục 8.3): `redact` bọc `desk.guard.redact` — exception BẤT KỲ → log CHỈ mẫu route + tên lớp
lỗi (không body, không traceback) → `PrivacyGuardUnavailable` (503). `record_redacted` ghi `privacy_secret_redacted`
cho tin nhắn sau (messages/confirm/quyết định duyệt) TRƯỚC `start_event`; lỗi ghi → 503, không `start_event`. Tạo
ticket thì sự kiện đi cùng transaction `tickets.create` (không qua đây).
"""

import json
import logging
import math
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError

from app.api.background import BackgroundRuns
from app.api.errors import InvalidRequest, PrivacyGuardUnavailable, error_fields
from app.auth.models import Principal, UserRecord
from app.auth.ports import SecurityEventSink
from app.core.clock import Clock
from app.graph.ports import ApprovalRepo, TicketRepo
from app.graph.runner import Runner
from app.guard.privacy import PrivacyGuard, RedactionResult

log = logging.getLogger(__name__)
SECRET_EVENT = "privacy_secret_redacted"


class UserDirectory(Protocol):
    """`AuthStore.get_user` — phòng ban của người gửi, người quản lý của người duyệt."""

    async def get_user(self, user_id: str) -> UserRecord | None: ...


@dataclass(frozen=True)
class Desk:
    runner: Runner
    tickets: TicketRepo
    approvals: ApprovalRepo
    guard: PrivacyGuard
    security: SecurityEventSink  # `privacy_secret_redacted` của tin nhắn sau (3e)
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
    2b-3 là quyền → 404/403/409 → body 422. JSON hỏng cũng là 422. Lỗi CHỈ mang vị trí trường
    (`api/errors.invalid_request`) — không `input` (có thể chứa mật khẩu, phase3 mục 8.3)."""
    raw = await request.body()
    try:
        data: Any = json.loads(raw) if raw else None
    except ValueError:
        raise InvalidRequest([]) from None
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise InvalidRequest(error_fields(exc.errors(include_url=False, include_input=False))) from None


def route_of(request: Request) -> str:
    """Mẫu đường dẫn (`/api/tickets/{ticket_id}/messages`) — không có id, không có query."""
    route = request.scope.get("route")
    return str(getattr(route, "path", "?"))


async def redact(desk: Desk, request: Request, text: str) -> RedactionResult:
    try:
        return await desk.guard.redact(text)
    except Exception as exc:  # noqa: BLE001 — guard lỗi bất kỳ → 503, không lưu gì (8.3); log không có body
        log.error("privacy guard lỗi: route=%s loại=%s", route_of(request), type(exc).__name__)
        raise PrivacyGuardUnavailable from None


async def record_redacted(
    desk: Desk, request: Request, p: Principal, ticket_id: str, result: RedactionResult
) -> None:
    if not result.secrets_found:
        return
    try:
        await desk.security.record(
            SECRET_EVENT, user_id=p.user_id, route=route_of(request), ticket_id=ticket_id,
            detail={"count": result.secrets_found},
        )  # fmt: skip
    except Exception as exc:  # noqa: BLE001 — ghi sự kiện lỗi → 503, không start_event (8.3)
        log.error("ghi %s lỗi: route=%s loại=%s", SECRET_EVENT, route_of(request), type(exc).__name__)
        raise PrivacyGuardUnavailable from None
