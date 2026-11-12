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

M9 (A4, Q-M9-7, Q-M9-B1-6, Q-M9-A4-1..9): `llm` và `monitor` — chuỗi, CHỈ báo như `kb`, không bao giờ đổi mã 200/503;
không chứa số tiền, DSN hay tên model. Probe dựng ở `main.py` (`app.state.llm_probe`, `app.state.monitor_probe`) — không
gọi LLM thật. Probe lỗi/timeout → `llm="unknown"`, `monitor="down"` (log tên lớp lỗi). CẢ response (body + mã, kể cả
503) cache 10 giây với khoá single-flight: hai lần gọi trong 10 giây — kể cả đồng thời — mỗi phụ thuộc chỉ kiểm một lần.
Đồng hồ dùng chung `app.state.kb_monotonic`.

O3 (soát 12/11): `warnings` — danh sách MÃ CỐ ĐỊNH (`WARNING_CODES`), CHỈ báo, không đổi 200/503: `llm_spend_cap_reached` (từ
`llm`), `mock_faults_active` (mock đang bơm lỗi — chỉ dev/test), `ml_models_missing` (ml-service thiếu model nhóm nhưng vẫn 200).
Probe `app.state.warnings_probe` dựng ở `main.py`; lỗi → `[]`. Chưa có `worker_heartbeat_stale` (heartbeat nằm trong container worker).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

type HealthCheck = Callable[[], Awaitable[None]]
type KbProbe = Callable[[], Awaitable[str | None]]
# ---- M9 ----
# `real:missing_pricing` không xuất hiện ở process thật: `check_llm` đã từ chối khởi động (3-Q26, Q-M9-A4-2).
type LlmStatus = Literal["scripted", "real:configured", "real:missing_pricing", "spend_cap_reached", "unknown"]
type MonitorStatus = Literal["ok", "not_configured", "wrong_role", "down"]
type LlmProbe = Callable[[], Awaitable[LlmStatus]]
type MonitorProbe = Callable[[], Awaitable[MonitorStatus]]
type WarningsProbe = Callable[[], Awaitable[list[str]]]
# O3 (soát 12/11): `warnings` — MÃ CỐ ĐỊNH, CHỈ báo (không đổi 200/503). Mã lạ từ probe bị lọc (không chữ tự do ra ngoài).
WARNING_CODES: frozenset[str] = frozenset({"llm_spend_cap_reached", "mock_faults_active", "ml_models_missing"})

router = APIRouter()
log = logging.getLogger(__name__)

KB_ALIAS = "kb_current"
KB_CACHE_SECONDS = 10.0
HEALTH_CACHE_SECONDS = 10.0  # M9 (A4)


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


# ---- M9 (A4) ----
async def _probe[T](name: str, probe: Callable[[], Awaitable[T]], timeout: float, fallback: T) -> T:
    try:
        return await asyncio.wait_for(probe(), timeout)
    except Exception as exc:  # noqa: BLE001 — biên health: lỗi bất kỳ → `fallback`, không làm hỏng /api/health
        log.warning("%s probe lỗi: %s", name, type(exc).__name__)  # chỉ tên lớp, như kb
        return fallback


async def _health(request: Request) -> tuple[dict[str, object], int]:
    """(body, mã). Khoá giữ suốt lượt tính: request thứ hai đứng chờ rồi đọc cache, không kiểm lại."""
    state = request.app.state
    lock = getattr(state, "_health_lock", None)
    if lock is None:  # không có `await` giữa kiểm và gán → không hai khoá
        lock = state._health_lock = asyncio.Lock()
    async with lock:
        now = state.kb_monotonic()
        cached = getattr(state, "_health_cache", None)
        if cached is not None and now - cached[0] < HEALTH_CACHE_SECONDS:
            return cached[1], cached[2]
        timeout = state.health_timeout
        no_warnings: list[str] = []
        results, kb, llm, monitor, extra = await asyncio.gather(
            run_checks(state.health_checks, timeout),
            _kb_status(request),
            _probe("llm", state.llm_probe, timeout, "unknown"),
            _probe("monitor", state.monitor_probe, timeout, "down"),
            _probe("warnings", state.warnings_probe, timeout, no_warnings),
        )
        failed = sorted(name for name, status in results.items() if status != "ok")
        warnings = {w for w in extra if w in WARNING_CODES} | ({"llm_spend_cap_reached"} if llm == "spend_cap_reached" else set())
        body: dict[str, object] = {
            "status": "ok" if not failed else "degraded", "checks": results, "failed": failed,
            "runtime": getattr(state, "runtime_status", "down"),
            "kb": kb, "llm": llm, "monitor": monitor, "warnings": sorted(warnings),
        }  # fmt: skip
        code = 200 if not failed else 503  # chỉ `checks` quyết mã — `kb`, `llm`, `monitor`, `warnings` chỉ báo
        state._health_cache = (now, body, code)
        return body, code


@router.get("/api/health")
async def health(request: Request) -> JSONResponse:
    body, code = await _health(request)
    return JSONResponse(body, status_code=code)
