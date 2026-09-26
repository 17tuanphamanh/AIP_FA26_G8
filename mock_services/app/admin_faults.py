"""Bơm lỗi cho test E2/E7 và demo (P5 mục 7): `/_admin/faults` bật 500/429/timeout/latency theo
tiền tố đường dẫn, có thể giới hạn số lần; `DELETE` tắt. `/_admin/reset` nạp lại seed.

`/_admin/*` không đòi token: mock chỉ nghe trong mạng Docker nội bộ (01 mục 2) — đây là cần gạt
của người chạy test, không phải API của hệ thống ngoài.
"""

import asyncio
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

router = APIRouter(prefix="/_admin")

UNFAULTABLE = ("/_admin", "/health")
DEFAULT_TIMEOUT_MS = 30_000  # lâu hơn mọi timeout tool (5 giây) → client chắc chắn timeout trước


class FaultIn(BaseModel):
    path_prefix: str = Field(pattern=r"^/")
    method: Literal["GET", "POST"] | None = None  # None = mọi method
    mode: Literal["error", "timeout", "latency"]
    status: int = Field(default=500, ge=400, le=599)  # chỉ dùng với mode=error
    delay_ms: int = Field(default=0, ge=0, le=120_000)  # latency: chờ rồi xử lý bình thường
    times: int | None = Field(default=None, ge=1)  # None = tới khi tắt

    @model_validator(mode="after")
    def _not_admin(self) -> "FaultIn":
        if self.path_prefix.startswith(UNFAULTABLE):
            raise ValueError("không bơm lỗi vào /_admin hay /health")
        return self


@dataclass
class Fault:
    fault_id: int
    spec: FaultIn
    remaining: int | None

    def view(self) -> dict[str, Any]:
        return {"fault_id": self.fault_id, **self.spec.model_dump(), "remaining": self.remaining}


class FaultTable:
    def __init__(self) -> None:
        self._faults: list[Fault] = []
        self._ids = itertools.count(1)

    def add(self, spec: FaultIn) -> Fault:
        fault = Fault(next(self._ids), spec, spec.times)
        self._faults.append(fault)
        return fault

    def clear(self) -> None:
        self._faults.clear()

    def remove(self, fault_id: int) -> bool:
        before = len(self._faults)
        self._faults = [f for f in self._faults if f.fault_id != fault_id]
        return before != len(self._faults)

    def list(self) -> list[Fault]:
        return list(self._faults)

    def take(self, method: str, path: str) -> FaultIn | None:
        """Lỗi đầu tiên khớp request; giảm lượt còn lại, hết lượt thì tự gỡ."""
        for fault in self._faults:
            spec = fault.spec
            if path.startswith(spec.path_prefix) and spec.method in (None, method):
                if fault.remaining is not None:
                    fault.remaining -= 1
                    if fault.remaining == 0:
                        self._faults.remove(fault)
                return spec
        return None


async def fault_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    table: FaultTable = request.app.state.faults
    spec = table.take(request.method, request.url.path)
    if spec is None:
        return await call_next(request)
    if spec.mode == "latency":
        await asyncio.sleep(spec.delay_ms / 1000)
        return await call_next(request)
    if spec.mode == "timeout":
        await asyncio.sleep((spec.delay_ms or DEFAULT_TIMEOUT_MS) / 1000)
        return JSONResponse({"detail": "injected_timeout"}, status_code=504)
    return JSONResponse({"detail": "injected_fault"}, status_code=spec.status)


@router.post("/faults", status_code=201)
async def add_fault(body: FaultIn, request: Request) -> dict[str, Any]:
    table: FaultTable = request.app.state.faults
    return table.add(body).view()


@router.get("/faults")
async def list_faults(request: Request) -> list[dict[str, Any]]:
    table: FaultTable = request.app.state.faults
    return [f.view() for f in table.list()]


@router.delete("/faults")
async def clear_faults(request: Request) -> dict[str, str]:
    table: FaultTable = request.app.state.faults
    table.clear()
    return {"status": "cleared"}


@router.delete("/faults/{fault_id}")
async def remove_fault(fault_id: int, request: Request) -> dict[str, str]:
    table: FaultTable = request.app.state.faults
    if not table.remove(fault_id):
        raise HTTPException(404, "not_found")
    return {"status": "removed"}


@router.post("/reset")
async def reset(request: Request) -> dict[str, Any]:
    """Đặt lại dữ liệu từ seed.json và tắt mọi lỗi đang bơm (chế độ demo, [Chốt 16.5])."""
    reload: Callable[[], dict[str, int]] = request.app.state.reload
    counts = reload()
    table: FaultTable = request.app.state.faults
    table.clear()
    return {"status": "reset", **counts}
