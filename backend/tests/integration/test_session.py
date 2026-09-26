"""Pool chính + lock pool riêng (D-19): khóa ticket giữ trên lock pool không chặn pool chính."""

import pytest
from app.db.session import create_engines, ping
from app.settings import Settings
from sqlalchemy import text
from tests.integration.pg import PgUrls


@pytest.mark.asyncio
async def test_lock_pool_is_separate_and_has_lock_timeout(migrated: PgUrls) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=migrated.role("app_rw"),
        lock_pool_size=2,
        ticket_lock_timeout=1.5,
    )
    engines = create_engines(settings)
    try:
        assert engines.main is not engines.lock
        assert engines.lock.pool.size() == 2  # type: ignore[attr-defined]
        async with engines.lock.connect() as lock_conn:
            assert (await lock_conn.execute(text("SHOW lock_timeout"))).scalar() == "1500ms"
            assert (await lock_conn.execute(text("SELECT pg_try_advisory_lock(424242)"))).scalar()
            async with engines.main.connect() as main_conn:
                # cùng ticket, session khác → không lấy được khóa; pool chính vẫn chạy bình thường
                held = await main_conn.execute(text("SELECT pg_try_advisory_lock(424242)"))
                assert held.scalar() is False
                await ping(engines.main)
            await lock_conn.execute(text("SELECT pg_advisory_unlock(424242)"))
    finally:
        await engines.dispose()
