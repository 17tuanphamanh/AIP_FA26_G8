"""Fixture e2e dùng chung: mock thật cho cả module, reset seed trước mỗi test."""

from collections.abc import Iterator

import httpx
import pytest
from tests.e2e.mock_server import MockServer, run_mock


@pytest.fixture(scope="module")
def mock_server() -> Iterator[MockServer]:
    with run_mock() as server:
        yield server


@pytest.fixture
def reset(mock_server: MockServer) -> None:
    httpx.post(f"{mock_server.url}/_admin/reset", timeout=5).raise_for_status()
