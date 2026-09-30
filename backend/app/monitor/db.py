"""Engine chỉ-đọc của M9 (kế hoạch M9 mục 4.1, hợp đồng A0 mục 3).

Mọi truy vấn M9 chạy trên role `app_monitor`. Thiếu DSN → `MonitorUnavailable` (route: 503
`monitor_unavailable`, gắn ở `main.py`; job: bỏ qua). KHÔNG rơi về `engines.main` (app_rw) — rơi về là
mất rào chỉ-đọc mà không ai biết.
"""

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine

if TYPE_CHECKING:
    from app.db.session import Engines


class MonitorUnavailable(Exception):
    """Chưa cấu hình `MONITOR_DATABASE_URL`."""


def monitor_engine(engines: "Engines") -> AsyncEngine:
    """Engine role app_monitor. engines.monitor is None → raise MonitorUnavailable. KHÔNG rơi về engines.main."""
    if engines.monitor is None:
        raise MonitorUnavailable("MONITOR_DATABASE_URL chưa đặt")
    return engines.monitor
