"""Bộ hợp đồng AuthStore trên bản in-memory (bản SQL: integration/test_auth_store_sql.py)."""

import pytest
from app.core.clock import FakeClock
from tests.fakes.auth import EPOCH, InMemoryAuthStore, RecordingSink
from tests.unit.auth_store_contract import AuthStoreContract, StoreEnv


class TestInMemoryAuthStore(AuthStoreContract):
    @pytest.fixture
    def env(self) -> StoreEnv:
        clock = FakeClock(EPOCH)
        sink = RecordingSink(clock)
        return StoreEnv(InMemoryAuthStore(sink), sink, clock)
