"""GET /api/health — 200 khi mọi phụ thuộc lõi sống, 503 kèm danh sách phụ thuộc lỗi (P9 mục 7).

Phụ thuộc lõi: DB, Qdrant, mock (P5), ml-service (3a, 3-Q9 — chết/đang nạp model → 503). LLM thêm khi có
(P9 mục 5).
Route công khai trong mạng nội bộ, không cần permission (FR-T1-1).

`runtime`: `up` | `down` — runtime graph (checkpoint + runner) có mở được lúc khởi động không (2b-3).
Chỉ để báo; không đổi mã 200/503 (runtime down thì route ticket tự trả 503).

`kb` (3c, Q-3c-5): CHỈ báo — không bao giờ đổi mã 200/503 (mã do `checks`, có `qdrant`, quyết như cũ). Kết quả
`app.state.kb_probe` cache 10 giây trong process (đồng hồ monotonic tiêm qua `app.state.kb_monotonic`, mặc định
`time.monotonic`, test tiêm giả); lỗi/timeout → `status="unknown"`, `collection=None`, cũng cache 10 giây. `api`
không import `rag`/qdrant-client — alias cố định `"kb_current"` (khớp `rag.ingest.config.ALIAS`, kiểm bằng test).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

type HealthCheck = Callable[[], Awaitable[None]]
type KbProbe = Callable[[], Awaitable[str | None]]

router = APIRouter()
log = logging.getLogger(__name__)

KB_ALIAS = "kb_current"
KB_CACHE_SECONDS = 10.0


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


async def _kb_status(request: Request) -> dict[str, str | None]:
    state = request.app.state
    now = state.kb_monotonic()
    cached = getattr(state, "_kb_cache", None)
    if cached is not None and now - cached[0] < KB_CACHE_SECONDS:
        return cached[1]  # type: ignore[no-any-return]
    try:
        collection = await asyncio.wait_for(state.kb_probe(), state.health_timeout)
        body: dict[str, str | None] = {
            "alias": KB_ALIAS, "collection": collection, "status": "ready" if collection else "missing",
        }  # fmt: skip
    except Exception as exc:  # noqa: BLE001 — biên health: lỗi bất kỳ → "unknown", không làm hỏng /api/health
        # Chỉ tên lớp lỗi: thông điệp httpx có URL, body Qdrant có thể dài — không cần để chẩn đoán.
        log.warning("kb probe lỗi: %s", type(exc).__name__)
        body = {"alias": KB_ALIAS, "collection": None, "status": "unknown"}
    state._kb_cache = (now, body)
    return body


@router.get("/api/health")
async def health(request: Request) -> JSONResponse:
    results = await run_checks(request.app.state.health_checks, request.app.state.health_timeout)
    failed = sorted(name for name, status in results.items() if status != "ok")
    body = {
        "status": "ok" if not failed else "degraded", "checks": results, "failed": failed,
        "runtime": getattr(request.app.state, "runtime_status", "down"),
        "kb": await _kb_status(request),
    }  # fmt: skip
    return JSONResponse(body, status_code=200 if not failed else 503)
