"""Fixture cho test mock. Chạy riêng với backend vì cả hai đều là package `app`:
`uv run pytest mock_services/tests -o pythonpath=mock_services` (make test làm việc này).

Token dịch vụ sinh ngẫu nhiên mỗi phiên test — không đọc `.env`, không đọc seed.local.json của máy.
"""

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.main import create_app
from app.security import ServiceTokens
from app.state import SEED_LOCAL_ENV
from fastapi.testclient import TestClient

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_local_seed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test không đọc seed.local.json thật của máy (có thể chứa địa chỉ thật): trỏ tới file không tồn tại; APP_ENV trống
    (cổng /portal tắt) trừ khi test tự đặt."""
    monkeypatch.setenv(SEED_LOCAL_ENV, str(tmp_path / "khong-co-seed.local.json"))
    monkeypatch.delenv("APP_ENV", raising=False)


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
