"""Fixture e2e dùng chung: mock thật cho cả module, reset seed (+ bộ đếm `/_admin/calls`) trước mỗi test.

Cổng 3 (`test_gate3_vpn.py`) cần thêm Postgres + Qdrant: TÁI DÙNG fixture phiên của `tests/integration/conftest.py`
(testcontainers, script init của compose, alembic bằng app_migrate) — nhập tên vào đây để pytest thấy ở thư mục e2e; không
viết lại. Pytest đăng ký chúng thành fixture riêng của e2e → phiên `make test` có một cặp container cho integration và một
cặp cho e2e (DB e2e không lẫn dòng của test integration). `kb`: KB fixture ingest thật MỘT lần cho module.
"""

from collections.abc import Iterator

import httpx
import pytest
from tests.e2e.gate3_env import ingest_kb
from tests.e2e.mock_server import MockServer, run_mock
from tests.integration.conftest import (  # noqa: F401 — fixture phiên, tái dùng
    migrated,
    pg,
    qdrant_url,
)
from tests.integration.pg import PgUrls


@pytest.fixture(scope="module")
def mock_server() -> Iterator[MockServer]:
    with run_mock() as server:
        yield server


@pytest.fixture
def reset(mock_server: MockServer) -> None:
    httpx.post(f"{mock_server.url}/_admin/reset", timeout=5).raise_for_status()


@pytest.fixture(scope="module")
def kb(migrated: PgUrls, qdrant_url: str, tmp_path_factory: pytest.TempPathFactory) -> None:  # noqa: F811
    ingest_kb(migrated, qdrant_url, tmp_path_factory.mktemp("kb"))
