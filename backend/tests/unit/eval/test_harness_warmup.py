"""G2 mốc 3 — làm nóng rerank (`app.eval.warmup`, chạy TRONG container backend): `/embed` 1 câu + `/rerank` đủ lô
`min(rag_rerank_k, 32)` đoạn (`RERANK_MAX_PASSAGES`, ml_service/app/schemas.py:10), chữ TỔNG HỢP cố định, header `X-Service-Token`.
"""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from app.eval.stack import Clock
from app.eval.warmup import PASSAGE_MAX, main, make_client, warm
from pydantic import SecretStr
from tests.unit.eval.fake_stack import FakeApi, FakeClock


def ticking(fake: FakeClock, step: float = 0.05) -> Clock:
    """Mỗi lần đọc đồng hồ tiến `step` giây — để thời lượng vòng khác 0."""
    def mono() -> float:
        fake.now += step
        return fake.now
    return Clock(monotonic=mono, sleep=fake.sleep)


@pytest.mark.parametrize(("k", "expected"), [(20, 20), (32, 32), (50, 32), (1, 1)])
def test_warmup_payload(k: int, expected: int) -> None:
    posts: list[tuple[str, dict[str, Any]]] = []
    result = warm(lambda path, body: posts.append((path, body)), k, 3, ticking(FakeClock()))
    assert [p for p, _ in posts] == ["/embed", "/rerank"] * 3
    for path, body in posts:
        if path == "/rerank":
            assert set(body) == {"query", "passages"} and len(body["passages"]) == expected
            assert all(isinstance(x, str) and x for x in body["passages"])
        else:
            assert set(body) == {"texts"} and len(body["texts"]) == 1
    assert result["rounds"] == 3 and result["first_ms"] > 0 and result["last_ms"] > 0
    assert PASSAGE_MAX == 32


@pytest.mark.parametrize("rounds", [0, -1])
def test_warmup_rounds_positive(rounds: int) -> None:
    with pytest.raises(ValueError):
        warm(lambda path, body: None, 20, rounds, ticking(FakeClock()))


def test_warmup_client_headers() -> None:
    api = FakeApi()
    api.on("POST", "/rerank", lambda r: httpx.Response(200, json={"seen": r.headers.get("X-Service-Token")}))
    with make_client("http://ml-service:8200", "tok", transport=httpx.MockTransport(api.handle)) as c:
        assert c.post("/rerank", json={}).json() == {"seen": "tok"}


@dataclass
class FakeSettings:
    ml_service_url: str = "http://ml-service:8200"
    ml_service_token: SecretStr | None = field(default_factory=lambda: SecretStr("tok"))
    rag_rerank_k: int = 20


def test_warmup_main_prints_json() -> None:
    api = FakeApi()
    api.fallback = lambda r: httpx.Response(200, json={})
    out: list[str] = []
    assert main(["--rounds", "2"], settings_factory=FakeSettings, transport=httpx.MockTransport(api.handle), out=out.append) == 0
    [line] = out
    data = json.loads(line)
    assert set(data) == {"rounds", "first_ms", "last_ms"} and data["rounds"] == 2
    assert [p for _, p, _ in api.calls] == ["/embed", "/rerank"] * 2


@pytest.mark.parametrize("status", [401, 503])
def test_warmup_main_http_error_exit2(status: int) -> None:
    api = FakeApi()
    api.fallback = lambda r: httpx.Response(status, text="SENTINEL_BODY")
    out: list[str] = []
    assert main(["--rounds", "1"], settings_factory=FakeSettings, transport=httpx.MockTransport(api.handle), out=out.append) == 2
    assert "SENTINEL" not in "\n".join(out)


def test_warmup_main_no_token_exit2() -> None:
    out: list[str] = []
    code = main(["--rounds", "1"], settings_factory=lambda: FakeSettings(ml_service_token=None), out=out.append)
    assert code == 2 and "ML_SERVICE_TOKEN" in "\n".join(out)
