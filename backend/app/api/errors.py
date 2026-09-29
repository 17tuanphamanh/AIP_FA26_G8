"""Ánh xạ lỗi → HTTP (P1 mục 6.1, 10; 2b-Q7; phase3 mục 8.3 + PLAN-3e Q-3e-2).

| Lỗi | HTTP | Ghi chú |
|---|---|---|
| `LateEvent` | 409 | guard đã ghi `late_event`, trạng thái không đổi |
| `TicketBusy` | 503 + `Retry-After` | lượt khác giữ khoá quá `lock_timeout` — lỗi tạm |
| `InvalidEvent` | 422 | loại sự kiện không hợp với node chờ (thông điệp chỉ có tên node + loại sự kiện do route đặt) |
| `TicketNotFound` | 404 | |
| `RequestValidationError`, `InvalidRequest` | 422 | `{"error":"invalid_request","fields":[…]}` — KHÔNG `input`, `ctx`, `msg` |
| `PrivacyGuardUnavailable` | 503 | `{"error":"privacy_guard_unavailable"}` — không INSERT, không `start_event` |

Chặn rò qua 422 (mục 8.3): lỗi Pydantic mặc định trả lại `input` (có thể là mật khẩu — body `/api/auth/login`, câu
chat). MỌI lỗi kiểm dữ liệu vào — body tự kiểm trong route (`desk.parse_body`) lẫn tham số FastAPI tự kiểm — đi qua
`invalid_request`: chỉ còn vị trí trường. Tên khoá THỪA do người gửi đặt (lỗi `extra_forbidden`) cũng có thể là bí mật
→ thay bằng `<extra>`.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.graph.late_event import InvalidEvent, LateEvent, TicketNotFound
from app.graph.ports import TicketBusy

EXTRA_KEY = "<extra>"
GUARD_UNAVAILABLE = {"error": "privacy_guard_unavailable"}


class InvalidRequest(Exception):
    """Body/tham số sai (422). Chỉ mang vị trí trường — không giá trị người gửi."""

    def __init__(self, fields: list[str]) -> None:
        super().__init__("invalid_request")
        self.fields = fields


class PrivacyGuardUnavailable(Exception):
    """Guard (hoặc ghi sự kiện `privacy_secret_redacted` của nó) lỗi → 503, không lưu gì (phase3 mục 8.3)."""


def error_fields(errors: Iterable[Mapping[str, Any]]) -> list[str]:
    """Vị trí trường của lỗi Pydantic, dạng `body.text`. Không đọc `input`/`ctx`/`msg`."""
    fields = []
    for e in errors:
        loc = [str(part) for part in e.get("loc", ())]
        if e.get("type") == "extra_forbidden" and loc:
            loc[-1] = EXTRA_KEY
        fields.append(".".join(loc))
    return list(dict.fromkeys(fields))


def invalid_request(fields: list[str]) -> JSONResponse:
    return JSONResponse({"error": "invalid_request", "fields": fields}, status_code=422)


def install_graph_errors(app: FastAPI, retry_after_seconds: int) -> None:
    async def late(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": LateEvent.message}, status_code=409)

    async def busy(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": "ticket_busy"}, status_code=503,
            headers={"Retry-After": str(retry_after_seconds)},
        )  # fmt: skip

    async def invalid(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    async def missing(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "not_found"}, status_code=404)

    app.add_exception_handler(LateEvent, late)
    app.add_exception_handler(TicketBusy, busy)
    app.add_exception_handler(InvalidEvent, invalid)
    app.add_exception_handler(TicketNotFound, missing)


def install_request_errors(app: FastAPI) -> None:
    async def validation(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        return invalid_request(error_fields(exc.errors()))

    async def bad_request(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, InvalidRequest)
        return invalid_request(exc.fields)

    async def guard_down(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(GUARD_UNAVAILABLE, status_code=503)

    app.add_exception_handler(RequestValidationError, validation)
    app.add_exception_handler(InvalidRequest, bad_request)
    app.add_exception_handler(PrivacyGuardUnavailable, guard_down)
