"""Engine chỉ-đọc của M9 (kế hoạch M9 mục 4.1, hợp đồng A0 mục 3).

Mọi truy vấn M9 chạy trên role `app_monitor`. Thiếu DSN → `MonitorUnavailable` (route: 503
`monitor_unavailable`, gắn ở `main.py`; job: bỏ qua). KHÔNG rơi về `engines.main` (app_rw) — rơi về là
mất rào chỉ-đọc mà không ai biết.

`read_snapshot` (A3, review PR #22): một response dashboard / danh sách cảnh báo = một giao dịch
`REPEATABLE READ, READ ONLY` → mọi số trong response cùng một snapshot (không lệch nhau khi dữ liệu đang ghi).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

if TYPE_CHECKING:
    from app.db.session import Engines

# Role DB duy nhất M9 được chạy (A4, Q-M9-B1-6): `/api/health` so `SELECT current_user` với hằng này — đặt nhầm DSN
# `app_rw` thì báo `wrong_role` thay vì để M9 chạy với quyền ghi mà không ai biết.
MONITOR_ROLE = "app_monitor"


class MonitorUnavailable(Exception):
    """Chưa cấu hình `MONITOR_DATABASE_URL`."""


def monitor_engine(engines: "Engines") -> AsyncEngine:
    """Engine role app_monitor. engines.monitor is None → raise MonitorUnavailable. KHÔNG rơi về engines.main."""
    if engines.monitor is None:
        raise MonitorUnavailable("MONITOR_DATABASE_URL chưa đặt")
    return engines.monitor


@asynccontextmanager
async def read_snapshot(engines: "Engines") -> AsyncIterator[AsyncConnection]:
    """Connection của engine monitor trong MỘT giao dịch `REPEATABLE READ, READ ONLY` (thiếu DSN → MonitorUnavailable)."""
    async with monitor_engine(engines).connect() as conn:
        await conn.execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True)
        async with conn.begin():
            yield conn
