"""Engine async (psycopg 3): pool chính + lock pool riêng (D-19, P1 mục 7).

- Pool chính: transaction nghiệp vụ, audit (role app_rw).
- Lock pool: chỉ để giữ pg_advisory_lock CẤP SESSION theo ticket suốt một lượt, không giữ
  transaction mở khi gọi LLM. Cùng role app_rw, kích thước LOCK_POOL_SIZE, có lock_timeout.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.settings import Settings


@dataclass(frozen=True)
class Engines:
    main: AsyncEngine
    lock: AsyncEngine

    async def dispose(self) -> None:
        await self.main.dispose()
        await self.lock.dispose()


def create_engines(settings: Settings) -> Engines:
    main = create_async_engine(
        settings.database_url, pool_size=settings.db_pool_size, pool_pre_ping=True
    )
    lock_timeout_ms = int(settings.ticket_lock_timeout * 1000)
    lock = create_async_engine(
        settings.database_url,
        pool_size=settings.effective_lock_pool_size,
        max_overflow=0,  # cạn lock pool thì chờ, không mở thêm kết nối ngoài hạn mức
        pool_pre_ping=True,
        connect_args={"options": f"-c lock_timeout={lock_timeout_ms}"},
    )
    return Engines(main=main, lock=lock)


async def ping(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
