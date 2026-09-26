"""Ánh xạ lỗi của graph → HTTP cho route sự kiện (P1 mục 6.1, 10; 2b-Q7).

| Lỗi | HTTP | Ghi chú |
|---|---|---|
| `LateEvent` | 409 | guard đã ghi `late_event`, trạng thái không đổi |
| `TicketBusy` | 503 + `Retry-After` | lượt khác giữ khoá quá `lock_timeout` — lỗi tạm |
| `InvalidEvent` | 422 | loại sự kiện không hợp với node chờ |
| `TicketNotFound` | 404 | |
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.graph.late_event import InvalidEvent, LateEvent, TicketNotFound
from app.graph.ports import TicketBusy


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
