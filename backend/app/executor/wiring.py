"""Dựng registry GHI (token `svc_executor`) + `PlanExecutor` — CHỈ `main.py` (API process) gọi (P7, D-03). Worker không import
module này (hợp đồng import-linter 3 cấm `app.worker`/`app.graph`… import adapter ghi, kể cả gián tiếp).

Registry ghi RIÊNG (không dùng chung với registry đọc svc_agent): breaker riêng. Phase 5 T24 P6: handler tool ghi của ĐỦ 4 hệ thống
(AD, VPN, phần mềm, file server — 13 tool ghi trong `tools.specs.REGISTRY`, gồm tool hoàn tác).
"""

import httpx

from app.core.clock import Clock
from app.settings import Settings
from app.tools.adapters import ad_write, fileserver_write, software_write, vpn_write
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
    handlers = {
        **ad_write.write_handlers(http), **vpn_write.write_handlers(http), **software_write.write_handlers(http),
        **fileserver_write.write_handlers(http),
    }  # fmt: skip
    registry = ToolRegistry(handlers, breakers=breaker_board(settings, clock), clock=clock)
    return registry, http
