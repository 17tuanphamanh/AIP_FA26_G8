"""Dựng registry GHI (token `svc_executor`) + `VpnExecutor` — CHỈ `main.py` (API process) gọi (P7, D-03). Worker không import
module này (hợp đồng import-linter 3 cấm `app.worker`/`app.graph`… import adapter ghi, kể cả gián tiếp).

Registry ghi RIÊNG (không dùng chung với registry đọc svc_agent): breaker riêng, chỉ handler tool ghi VPN (Phase 3).
"""

import httpx

from app.core.clock import Clock
from app.settings import Settings
from app.tools.adapters import vpn_write
from app.tools.adapters.http import ServiceHttp
from app.tools.registry import ToolRegistry
from app.tools.wiring import breaker_board


def build_write_registry(
    settings: Settings, clock: Clock, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[ToolRegistry, ServiceHttp]:
    """Trả registry + client (để đóng khi tắt app). Thiếu `SVC_EXECUTOR_TOKEN` → lỗi rõ ràng (không bao giờ dùng token khác)."""
    if settings.svc_executor_token is None:
        raise RuntimeError("SVC_EXECUTOR_TOKEN chưa cấu hình — không dựng được registry ghi (D-03)")
    http = ServiceHttp(settings.mock_url, settings.svc_executor_token, transport)
    registry = ToolRegistry(vpn_write.write_handlers(http), breakers=breaker_board(settings, clock), clock=clock)
    return registry, http
