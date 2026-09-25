"""Dựng ToolRegistry chỉ có tool đọc (token svc_agent) — dùng cho graph (B1, B6, B11).

Registry có tool ghi do `executor` dựng ở Phase 3 từ `tools.adapters.*_write` + token svc_executor;
module này KHÔNG import adapter ghi (hợp đồng import-linter số 3).
"""

import httpx

from app.core.clock import Clock
from app.settings import Settings
from app.tools.adapters import ad_read, fileserver_read, software_read, vpn_read
from app.tools.adapters.http import ServiceHttp
from app.tools.breaker import BreakerBoard
from app.tools.registry import Handler, ToolRegistry


def breaker_board(settings: Settings, clock: Clock) -> BreakerBoard:
    return BreakerBoard(
        clock,
        failure_threshold=settings.breaker_failure_threshold,
        window_seconds=settings.breaker_window_seconds,
        open_seconds=settings.breaker_open_seconds,
    )


def read_handlers(http: ServiceHttp) -> dict[str, Handler]:
    return {
        **ad_read.read_handlers(http),
        **vpn_read.read_handlers(http),
        **software_read.read_handlers(http),
        **fileserver_read.read_handlers(http),
    }


def build_read_registry(
    settings: Settings,
    clock: Clock,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[ToolRegistry, ServiceHttp]:
    """Trả registry + client (để đóng khi tắt app). Thiếu SVC_AGENT_TOKEN → lỗi rõ ràng."""
    if settings.svc_agent_token is None:
        raise RuntimeError("SVC_AGENT_TOKEN chưa cấu hình — không gọi được tool đọc (P6 mục 3)")
    http = ServiceHttp(settings.mock_url, settings.svc_agent_token, transport)
    registry = ToolRegistry(read_handlers(http), breakers=breaker_board(settings, clock), clock=clock)
    return registry, http
