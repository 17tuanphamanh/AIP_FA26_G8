"""Fixture cho test mock. Chạy riêng với backend vì cả hai đều là package `app`:
`uv run pytest mock_services/tests -o pythonpath=mock_services` (make test làm việc này).

Token dịch vụ sinh ngẫu nhiên mỗi phiên test — không đọc `.env`.
"""

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.main import create_app
from app.security import ServiceTokens
from fastapi.testclient import TestClient

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def tokens() -> ServiceTokens:
    return ServiceTokens(
        agent=secrets.token_urlsafe(32),
        executor=secrets.token_urlsafe(32),
        worker=secrets.token_urlsafe(32),
    )


@pytest.fixture
def client(tokens: ServiceTokens) -> Iterator[TestClient]:
    with TestClient(create_app(tokens=tokens, now=lambda: NOW)) as c:
        yield c


@pytest.fixture
def agent(tokens: ServiceTokens) -> dict[str, str]:
    return {"X-Service-Token": tokens.agent}


@pytest.fixture
def executor(tokens: ServiceTokens) -> dict[str, str]:
    return {"X-Service-Token": tokens.executor}


@pytest.fixture
def worker(tokens: ServiceTokens) -> dict[str, str]:
    return {"X-Service-Token": tokens.worker}
