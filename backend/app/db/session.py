"""Engine async (psycopg 3): pool chính + lock pool riêng (D-19, P1 mục 7) + pool chỉ-đọc M9.

- Pool chính: transaction nghiệp vụ, audit (role app_rw).
- Lock pool: chỉ để giữ pg_advisory_lock CẤP SESSION theo ticket suốt một lượt, không giữ
  transaction mở khi gọi LLM. Cùng role app_rw, kích thước LOCK_POOL_SIZE, có lock_timeout.
- Monitor (M9): role app_monitor, chỉ SELECT. Thiếu MONITOR_DATABASE_URL → None; M9 lấy qua
  `monitor.db.monitor_engine`, không bao giờ rơi về pool chính.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.settings import Settings


@dataclass(frozen=True)
class Engines:
    main: AsyncEngine
    lock: AsyncEngine
    monitor: AsyncEngine | None  # M9 — None khi thiếu DSN (fail-closed)

    async def dispose(self) -> None:
        await self.main.dispose()
        await self.lock.dispose()
        if self.monitor is not None:
            await self.monitor.dispose()


def create_engines(settings: Settings) -> Engines:
    main = create_async_engine(
        settings.database_url, pool_size=settings.db_pool_size, pool_pre_ping=True, hide_parameters=True
    )
    lock_timeout_ms = int(settings.ticket_lock_timeout * 1000)
    lock = create_async_engine(
        settings.database_url,
        pool_size=settings.effective_lock_pool_size,
        max_overflow=0,  # cạn lock pool thì chờ, không mở thêm kết nối ngoài hạn mức
        pool_timeout=5,  # E13 (soát 12/11): chờ tối đa 5 s rồi `TicketBusy` → 503 + Retry-After (trước: 30 s rồi 500)
        pool_pre_ping=True,
        connect_args={"options": f"-c lock_timeout={lock_timeout_ms}"},
        hide_parameters=True,
    )
    # M9 (A4): lớp hai sau quyền của role — mọi giao dịch trên engine monitor mặc định READ ONLY, nên DSN đặt nhầm
    # sang `app_rw` vẫn không ghi được (lỗi 25006).
    monitor = (
        create_async_engine(
            settings.monitor_database_url,
            pool_pre_ping=True,
            connect_args={"options": "-c default_transaction_read_only=on"},
            hide_parameters=True,
        )
        if settings.monitor_database_url is not None
        else None
    )
    return Engines(main=main, lock=lock, monitor=monitor)


async def ping(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
