"""GET /api/health — 200 khi mọi phụ thuộc lõi sống, 503 kèm danh sách phụ thuộc lỗi (P9 mục 7).

Phụ thuộc lõi: DB, Qdrant, mock (P5), ml-service (3a, 3-Q9 — chết/đang nạp model → 503). LLM thêm khi có
(P9 mục 5).
Route công khai trong mạng nội bộ, không cần permission (FR-T1-1).

`runtime`: `up` | `down` — runtime graph (checkpoint + runner) có mở được lúc khởi động không (2b-3).
Chỉ để báo; không đổi mã 200/503 (runtime down thì route ticket tự trả 503).
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

type HealthCheck = Callable[[], Awaitable[None]]

router = APIRouter()


async def run_checks(checks: Mapping[str, HealthCheck], timeout: float) -> dict[str, str]:
    async def one(check: HealthCheck) -> str:
        try:
            await asyncio.wait_for(check(), timeout)
        except TimeoutError:
            return "timeout"
        # Biên health: lỗi bất kỳ của phụ thuộc (DB, httpx, OSError…) → 503 kèm tên, không 500.
        except Exception as exc:  # noqa: BLE001
            return f"error: {type(exc).__name__}"
        return "ok"

    results = await asyncio.gather(*(one(c) for c in checks.values()))
    return dict(zip(checks, results, strict=True))


@router.get("/api/health")
async def health(request: Request) -> JSONResponse:
    results = await run_checks(request.app.state.health_checks, request.app.state.health_timeout)
    failed = sorted(name for name, status in results.items() if status != "ok")
    body = {
        "status": "ok" if not failed else "degraded", "checks": results, "failed": failed,
        "runtime": getattr(request.app.state, "runtime_status", "down"),
    }  # fmt: skip
    return JSONResponse(body, status_code=200 if not failed else 503)
