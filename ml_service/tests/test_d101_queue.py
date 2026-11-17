"""D-101 (máy demo 17/11: 3 ticket đồng thời → cả 3 E2 `rag_system_error` sau 50 s, ~1 phút mới hồi) — hàng chờ của ml-service.

1. Request mang `X-Client-Timeout` mà tới lượt đã chờ quá số giây đó → 503 `abandoned`, KHÔNG chạy model (backend đã bỏ; trước đây
   ml-service làm nốt mọi việc bị bỏ + các lần thử lại → hàng chờ phình). Thiếu / sai header → chạy như cũ.
2. `/embed` + `/count_tokens` có hàng chờ riêng (`ML_EMBED_CONCURRENCY`) — không xếp sau một rerank đang chạy.

Rerank giả CHẶN bằng `threading.Event` (như `test_classify_queue.py`), bật SAU khi khởi động (warm-up cũng gọi rerank).
Chạy: `uv run pytest ml_service/tests -o pythonpath=ml_service`.
"""

import threading
import time
from dataclasses import dataclass, field

import httpx
import pytest
from app.main import client_timeout, create_app
from app.settings import MlSettings
from fastapi.testclient import TestClient
from starlette.requests import Request
from tests.conftest import FakeLoader, FakeReranker

WAIT_S = 5.0


@dataclass
class CountingBlockingReranker(FakeReranker):
    armed: bool = False
    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    queries: list[str] = field(default_factory=list)

    def logits(self, pairs: list[tuple[str, str]]) -> list[float]:
        if self.armed:
            self.queries.append(pairs[0][0])
            self.entered.set()
            self.release.wait(WAIT_S)
        return super().logits(pairs)


def _app(settings: MlSettings) -> tuple[FakeLoader, CountingBlockingReranker, TestClient]:
    loader = FakeLoader()
    reranker = CountingBlockingReranker()
    loader.reranker = reranker
    return loader, reranker, TestClient(create_app(settings, loader=loader))


def test_queued_past_client_timeout_is_dropped_without_running_model(settings: MlSettings, auth: dict[str, str]) -> None:
    _, reranker, client = _app(settings)
    results: dict[str, httpx.Response] = {}
    with client as c:
        reranker.armed = True

        def first() -> None:
            results["first"] = c.post("/rerank", json={"query": "q1", "passages": ["a"]}, headers=auth)

        def late() -> None:  # chờ hàng lâu hơn 0,2 s backend chịu chờ
            results["late"] = c.post("/rerank", json={"query": "q2", "passages": ["a"]}, headers={**auth, "X-Client-Timeout": "0.2"})

        t1, t2 = threading.Thread(target=first, daemon=True), threading.Thread(target=late, daemon=True)
        t1.start()
        assert reranker.entered.wait(WAIT_S), "rerank giả chưa chạy"
        t2.start()
        time.sleep(0.5)  # "late" đang chờ hàng, đã quá 0,2 s
        reranker.release.set()
        t1.join(WAIT_S)
        t2.join(WAIT_S)
    assert results["first"].status_code == 200
    assert (results["late"].status_code, results["late"].json()) == (503, {"error": "abandoned"})
    assert reranker.queries == ["q1"]  # q2 KHÔNG chạy model


def test_within_client_timeout_runs_normally(client: TestClient, auth: dict[str, str]) -> None:
    r = client.post("/rerank", json={"query": "q", "passages": ["a"]}, headers={**auth, "X-Client-Timeout": "40"})
    assert r.status_code == 200 and "X-Model-Version" in r.headers


@pytest.mark.parametrize("value", [None, "", "abc", "0", "-1", "999", "nan"])
def test_client_timeout_header_invalid_means_no_drop(value: str | None) -> None:
    headers = [] if value is None else [(b"x-client-timeout", value.encode())]
    assert client_timeout(Request({"type": "http", "headers": headers})) is None


def test_client_timeout_header_valid() -> None:
    assert client_timeout(Request({"type": "http", "headers": [(b"x-client-timeout", b"40.000")]})) == 40.0


def test_embed_not_queued_behind_running_rerank(settings: MlSettings, auth: dict[str, str]) -> None:
    _, reranker, client = _app(settings)
    results: dict[str, httpx.Response] = {}
    with client as c:
        reranker.armed = True

        def rerank() -> None:
            results["rerank"] = c.post("/rerank", json={"query": "vpn", "passages": ["vpn lỗi"]}, headers=auth)

        def embed() -> None:
            results["embed"] = c.post("/embed", json={"texts": ["vpn không vào được"]}, headers=auth)
            results["count"] = c.post("/count_tokens", json={"texts": ["vpn"]}, headers=auth)

        t_rerank, t_embed = threading.Thread(target=rerank, daemon=True), threading.Thread(target=embed, daemon=True)
        t_rerank.start()
        try:
            assert reranker.entered.wait(WAIT_S), "rerank giả chưa chạy"
            t_embed.start()
            t_embed.join(WAIT_S - 1)
            done_while_rerank_held = "count" in results and not reranker.release.is_set()
        finally:
            reranker.release.set()
            t_rerank.join(WAIT_S)
            t_embed.join(WAIT_S)
    assert done_while_rerank_held, "embed/count_tokens phải xong trong lúc rerank còn giữ hàng chờ"
    assert results["embed"].status_code == 200 and results["count"].status_code == 200 and results["rerank"].status_code == 200


def test_embed_concurrency_default_one(token: str) -> None:
    assert MlSettings(ml_service_token=token).ml_embed_concurrency == 1
