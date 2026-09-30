"""M9 A0 — có DSN monitor thì truy vấn M9 chạy dưới role app_monitor, pool chính vẫn là app_rw."""

import pytest
from app.db.session import create_engines
from app.monitor.db import monitor_engine
from app.settings import Settings
from sqlalchemy import text
from tests.integration.pg import PgUrls


@pytest.mark.asyncio
async def test_monitor_engine_connects_as_app_monitor(migrated: PgUrls) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=migrated.role("app_rw"),
        monitor_database_url=migrated.role("app_monitor"),
    )
    engines = create_engines(settings)
    try:
        async with monitor_engine(engines).connect() as conn:
            assert (await conn.execute(text("SELECT current_user"))).scalar() == "app_monitor"
        async with engines.main.connect() as conn:
            assert (await conn.execute(text("SELECT current_user"))).scalar() == "app_rw"
    finally:
        await engines.dispose()
