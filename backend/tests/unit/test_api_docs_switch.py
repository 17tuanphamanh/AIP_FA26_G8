"""`API_DOCS` on|off: off → /docs, /redoc, /openapi.json trả 404; on (mặc định) → 200. Không phụ thuộc APP_ENV (demo chạy dev).
`app.openapi()` nội bộ (sinh hợp đồng FE — `gen:api`) và `/api/health` vẫn chạy khi off."""

from typing import Any

import pytest
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.fakes.runtime import no_runtime

DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


def _client(**over: Any) -> TestClient:
    return TestClient(create_app(_settings(**over), health_checks={}, runtime=no_runtime))


@pytest.mark.parametrize("env", [None, "dev", "test", "staging", "prod"])
@pytest.mark.parametrize("path", DOC_PATHS)
def test_off_returns_404_in_every_env(env: str | None, path: str) -> None:
    assert _client(app_env=env, api_docs="off").get(path).status_code == 404


@pytest.mark.parametrize("path", DOC_PATHS)
def test_on_returns_200(path: str) -> None:
    assert _client(api_docs="on").get(path).status_code == 200


def test_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_DOCS", raising=False)
    assert _settings().api_docs == "on"
    assert _client().get("/openapi.json").status_code == 200


def test_env_var_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_DOCS", "off")
    assert _settings().api_docs == "off"


@pytest.mark.parametrize("value", ["x", "ON", "true", "0", "Off"])
def test_unknown_value_refuses_start(value: str) -> None:
    with pytest.raises(ValidationError, match=r"API_DOCS=.* không hợp lệ — giá trị hợp lệ: on \| off"):
        _settings(api_docs=value)


def test_internal_openapi_still_works_when_off() -> None:
    spec = create_app(_settings(api_docs="off"), health_checks={}, runtime=no_runtime).openapi()
    assert "/api/health" in spec["paths"]


def test_health_still_works_when_off() -> None:
    with _client(api_docs="off") as client:
        assert client.get("/api/health").status_code == 200
