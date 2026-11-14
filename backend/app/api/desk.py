"""Phụ thuộc chung của route ticket và route duyệt (2b-3), dựng trong lifespan của `create_app`.

Runtime (checkpoint, runner) mở lỗi → `app.state.desk = None` → các route này trả 503, còn
`/api/health` vẫn chạy và báo `"runtime": "down"`.

Privacy guard (3e, phase3 mục 8.3): `redact` bọc `desk.guard.redact` — exception BẤT KỲ → log CHỈ mẫu route + tên lớp
lỗi (không body, không traceback) → `PrivacyGuardUnavailable` (503). `record_redacted` ghi `privacy_secret_redacted`
cho tin nhắn sau (messages/confirm/quyết định duyệt) TRƯỚC `start_event`; lỗi ghi → 503, không `start_event`. Tạo
ticket thì sự kiện đi cùng transaction `tickets.create` (không qua đây).

`redact_reply_items` (Phase 5 T20b, Q-T20b-8 = A): che TỪNG ý của `/reply` qua `redact`, trả `items` CHỈ gồm chữ đã che (`answer`,
`note`), `confirmed` (bool) và None — test AST N1 tin hàm này như tin `redact` (import thẳng từ module này, không bí danh).
"""

import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError

from app.api.background import BackgroundRuns
from app.api.errors import InvalidRequest, PrivacyGuardUnavailable, error_fields
from app.auth.models import Principal, UserRecord
from app.auth.ports import SecurityEventSink
from app.core.clock import Clock
from app.db.hours_mode import HoursMode, HoursModeState
from app.db.m5_strategy import StrategyChange
from app.graph.ports import ApprovalRepo, TicketRepo
from app.graph.runner import Runner
from app.guard.privacy import PrivacyGuard, RedactionResult

log = logging.getLogger(__name__)
SECRET_EVENT = "privacy_secret_redacted"


class UserDirectory(Protocol):
    """`AuthStore.get_user` — phòng ban của người gửi, người quản lý của người duyệt."""

    async def get_user(self, user_id: str) -> UserRecord | None: ...


class RateGate(Protocol):
    """429 theo tài khoản (Phase 5 gói 2b, D-54 a — `api/ratelimit.py`): `None` = cho qua; số = `Retry-After` (giây). Bản SQL:
    `db/rate_limits.SqlRateGate`; bản giả: `tests/fakes/rate.py`."""

    async def tickets(self, user_id: str, now: datetime, route: str) -> int | None: ...

    async def messages(self, user_id: str, now: datetime, route: str) -> int | None: ...


class StrategyStore(Protocol):
    """Chiến lược M5 lúc vận hành (D-67) — bản SQL: `db/m5_strategy.SqlStrategyStore`; bản giả: `tests/fakes/strategy.py`."""

    async def current(self) -> StrategyChange | None: ...

    async def history(self, limit: int) -> tuple[list[StrategyChange], bool]: ...

    async def append(self, strategy: str, *, changed_by: str, reason: str, at: datetime) -> StrategyChange: ...


class HoursModeStore(Protocol):
    """D-97: giả lập giờ hành chính — bản SQL: `db/hours_mode.SqlHoursModeStore`; bản giả: `tests/fakes/hours_mode.py`."""

    async def current(self) -> HoursModeState: ...

    async def set_mode(self, mode: HoursMode, *, changed_by: str, at: datetime) -> HoursModeState: ...


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
    rate: RateGate  # Phase 5 gói 2b: bộ đếm 429 (ticket mới; tin nhắn `/messages` `/reply` `/confirm`)
    strategy: StrategyStore  # D-67: chiến lược M5 lúc vận hành (chụp lên ticket mới; route `/api/admin/strategy`)
    hours: HoursModeStore | None = None  # D-97: giả lập giờ hành chính (route `/api/hours-mode`, `/api/admin/hours-mode`)


def retry_after(lock_timeout: float) -> int:
    return max(1, math.ceil(lock_timeout))


def get_desk(request: Request) -> Desk:
    desk: Desk | None = getattr(request.app.state, "desk", None)
    if desk is None:
        raise HTTPException(503, "runtime_unavailable")
    return desk


def load_json_body(raw: bytes) -> Any:
    """JSON của body → dữ liệu, hoặc `InvalidRequest([])` (422) khi: JSON hỏng; lồng quá sâu (`RecursionError` của bộ đọc JSON — kiểm
    thử 12/11: `[[[…]]]` 20 000 tầng, 40 KB < giới hạn body, từng ra 500); có ký tự NUL trong chuỗi hoặc khoá (Postgres không nhận
    0x00 — từng ra 500 khi ghi). Duyệt KHÔNG đệ quy (ngăn xếp) nên không vấp lại giới hạn đệ quy."""
    try:
        data: Any = json.loads(raw) if raw else None
    except (ValueError, RecursionError):
        raise InvalidRequest([]) from None
    stack: list[Any] = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            if "\x00" in node:
                raise InvalidRequest([])
        elif isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return data


async def parse_body[M: BaseModel](request: Request, model: type[M]) -> M:
    """Đọc + kiểm body TRONG handler (không để FastAPI kiểm trước dependency): thứ tự kiểm của
    2b-3 là quyền → 404/403/409 → body 422. JSON hỏng / lồng quá sâu / có NUL cũng là 422 (`load_json_body`). Lỗi CHỈ mang vị
    trí trường (`api/errors.invalid_request`) — không `input` (có thể chứa mật khẩu, phase3 mục 8.3)."""
    data = load_json_body(await request.body())
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


REPLY_ANSWER_KEYS = frozenset({"answer"})
REPLY_CONFIRM_KEYS = frozenset({"confirmed", "note"})


@dataclass(frozen=True)
class RedactedReply:
    """`/reply` sau privacy guard: `items[child_id]` = `{"answer": <đã che>}` hoặc `{"confirmed": bool, "note": <đã che> | None}`;
    `result` gộp mọi ý (`secrets_found` cộng dồn, `notices` không lặp, `text` rỗng) — ghi MỘT `privacy_secret_redacted`."""

    items: dict[str, dict[str, Any]]
    result: RedactionResult


async def redact_reply_items(desk: Desk, request: Request, items: Mapping[str, BaseModel]) -> RedactedReply:
    """Fail-closed: ý có trường khác `{answer}` / `{confirmed, note?}`, hoặc `confirmed` không phải bool → `ValueError` (route đã kiểm
    hình dạng bằng `extra="forbid"`; đây là lớp thứ hai để kết quả CHỈ có chữ đã qua `redact`)."""
    out: dict[str, dict[str, Any]] = {}
    secrets = 0
    notices: list[str] = []
    for cid, item in items.items():
        raw = item.model_dump()
        done: RedactionResult | None
        if raw.keys() == REPLY_ANSWER_KEYS and isinstance(raw["answer"], str):
            done = await redact(desk, request, raw["answer"])
            out[cid] = {"answer": done.text}
        elif raw.keys() <= REPLY_CONFIRM_KEYS and isinstance(raw.get("confirmed"), bool) \
                and isinstance(raw.get("note"), str | None):  # fmt: skip
            note = raw.get("note")
            done = await redact(desk, request, note) if note else None
            out[cid] = {"confirmed": raw["confirmed"], "note": done.text if done is not None else None}
        else:
            raise ValueError("ý của /reply có trường lạ")  # không nêu tên trường (khoá có thể là chữ người dùng)
        if done is not None:
            secrets += done.secrets_found
            notices += [n for n in done.notices if n not in notices]
    return RedactedReply(out, RedactionResult(text="", secrets_found=secrets, pii_map_id=None, notices=notices))
