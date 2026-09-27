"""a1 (token), a2 (413 chunked), a8 (log không có văn bản) — thiết kế 3a mục 4.8."""

import logging
from collections.abc import Iterator

import pytest
from app.limits import MAX_BODY_BYTES
from app.main import create_app
from app.settings import MlSettings
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.conftest import FakeLoader

BODIES = {
    "/embed": {"texts": ["xin chào"]},
    "/rerank": {"query": "vpn", "passages": ["vpn lỗi"]},
    "/count_tokens": {"texts": ["xin chào"]},
    "/classify": {"text": "xin chào"},
    "/classify_intent": {"text": "xin chào"},
}
OK = {"/embed": 200, "/rerank": 200, "/count_tokens": 200, "/classify": 503, "/classify_intent": 503}


@pytest.mark.parametrize("path", sorted(BODIES))
def test_missing_token_401(client: TestClient, path: str) -> None:
    r = client.post(path, json=BODIES[path])
    assert r.status_code == 401


@pytest.mark.parametrize("path", sorted(BODIES))
def test_wrong_token_401(client: TestClient, path: str, token: str) -> None:
    r = client.post(path, json=BODIES[path], headers={"X-Service-Token": token[:-1] + "x"})
    assert r.status_code == 401


@pytest.mark.parametrize("path", sorted(BODIES))
def test_right_token_passes(client: TestClient, path: str, auth: dict[str, str]) -> None:
    assert client.post(path, json=BODIES[path], headers=auth).status_code == OK[path]


def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_token_required_and_long(token: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ML_SERVICE_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        MlSettings()  # type: ignore[call-arg]  # không mặc định (3-Q21)
    with pytest.raises(ValidationError):
        MlSettings(ml_service_token="ngan-qua")
    assert MlSettings(ml_service_token=token).ml_max_concurrency == 1  # quyết định 3a


def _chunks(total: int) -> Iterator[bytes]:
    yield b'{"texts": ["'
    sent = 0
    while sent < total:
        yield b"a" * 4096
        sent += 4096
    yield b'"]}'


def test_chunked_body_over_limit_413_handler_not_run(
    client: TestClient, loader: FakeLoader, auth: dict[str, str]
) -> None:
    before = len(loader.embedder.calls)  # warm-up lúc khởi động đã gọi 1 lần
    r = client.post("/embed", content=_chunks(300 * 1024), headers=auth)
    assert r.status_code == 413
    assert len(loader.embedder.calls) == before


def test_413_before_token(client: TestClient) -> None:
    r = client.post("/embed", content=_chunks(MAX_BODY_BYTES + 1))
    assert r.status_code == 413


def test_body_at_limit_passes_limit(client: TestClient, auth: dict[str, str]) -> None:
    text = "a" * (MAX_BODY_BYTES - len('{"texts":[""]}'))
    body = f'{{"texts":["{text}"]}}'.encode()
    assert len(body) == MAX_BODY_BYTES
    r = client.post("/embed", content=body, headers={**auth, "Content-Type": "application/json"})
    assert r.status_code == 200


def test_logs_never_contain_text(
    settings: MlSettings, loader: FakeLoader, auth: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    canary = "CANARY-mat-khau-7f3a"
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app(settings, loader=loader)) as c:
        assert c.post("/embed", json={"texts": [f"mật khẩu {canary}"]}, headers=auth).status_code == 200
        c.post("/rerank", json={"query": canary, "passages": [canary]}, headers=auth)
        c.post("/count_tokens", json={"texts": [canary]}, headers=auth)
        c.post("/classify", json={"text": canary}, headers=auth)
        bad = c.post("/embed", json={"texts": [canary], "extra": canary}, headers=auth)
    assert "embed items=1" in caplog.text  # đối chứng: log có ghi
    assert canary not in caplog.text
    assert bad.status_code == 422 and canary not in bad.text  # 422 không vọng lại đầu vào
