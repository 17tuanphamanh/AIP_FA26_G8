"""Bộ hợp đồng AuthStore trên Postgres 16 thật (role app_rw) — cùng bộ test với bản in-memory.
Chạy trên database riêng: test ghi `mfa_enrolled`/`mfa_reset` (append-only, không xoá được)."""

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from app.audit.security_events import SecurityEventWriter
from app.auth.store import SqlAuthStore
from app.core.clock import FakeClock
from sqlalchemy.ext.asyncio import create_async_engine
from tests.fakes.auth import EPOCH
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.unit.auth_store_contract import AuthStoreContract, StoreEnv


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


class TestSqlAuthStore(AuthStoreContract):
    @pytest_asyncio.fixture
    async def env(self, db: PgUrls) -> AsyncIterator[StoreEnv]:
        engine = create_async_engine(db.role("app_rw"))
        clock = FakeClock(EPOCH)
        try:
            yield StoreEnv(SqlAuthStore(engine), SecurityEventWriter(engine, clock), clock)
        finally:
            await engine.dispose()
