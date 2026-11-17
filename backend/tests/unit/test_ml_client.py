"""`MlClient` (thiết kế Phase 3 mục 4.5, 4.8 a9–a13 + Q-3a-2/3/12). Lời gọi đếm ở nơi nhận (transport).

`attempts` = số lần gọi LỖI (cùng nghĩa `ToolResult.attempts`, Q-3a-2): 500, 500, 200 → 2; hết lượt → 3.
"""

import ast
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.core.clock import FakeClock
from app.ml import MlClient, MlContractError
from app.ml import client as ml_client
from app.ml.client import CONNECT_TIMEOUT_S, TIMEOUT_S

pytestmark = pytest.mark.asyncio

TOKEN = "t" * 43
REPO = Path(__file__).resolve().parents[3]
EMBED_OK = {"vectors": [[1.0]], "dim": 1, "model": "BAAI/bge-m3", "truncated": [False],
            "token_counts": [3]}  # fmt: skip

type Step = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


class Scripted:
    """Transport trả lần lượt theo kịch bản (phần tử cuối lặp lại), ghi lại mọi request nhận được."""

    def __init__(self, *steps: Step) -> None:
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.steps[min(len(self.requests), len(self.steps)) - 1]
        if isinstance(step, Exception):
            raise step
        if callable(step) and not isinstance(step, httpx.Response):
            return step(request)
        return step

    @property
    def calls(self) -> int:
        return len(self.requests)


def make(transport: Scripted, clock: FakeClock | None = None) -> MlClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(transport), base_url="http://ml:8200")
    return MlClient(http, TOKEN, clock=clock or FakeClock())


def ok(body: dict[str, Any] = EMBED_OK) -> httpx.Response:
    return httpx.Response(200, json=body, headers={"X-Model-Version": "bge-m3@aaaaaaa;reranker@bbbbbbb"})


MISSING = httpx.Response(503, json={"error": "model_missing"})


async def test_a9_500_500_200_succeeds_with_two_failed_calls() -> None:
    clock = FakeClock()
    t = Scripted(httpx.Response(500), httpx.Response(500), ok())
    r = await make(t, clock).embed(["xin chào"])
    assert t.calls == 3
    assert r.attempts == 2 and r.error is None
    assert r.data is not None and r.data.vectors == [[1.0]]
    assert r.model_version == "bge-m3@aaaaaaa;reranker@bbbbbbb"
    assert clock.sleeps == [1, 2]  # backoff của call_with_retry, không vòng retry thứ hai


async def test_a10_500_forever_is_value_not_exception() -> None:
    t = Scripted(httpx.Response(500))
    r = await make(t).embed(["xin chào"])
    assert t.calls == 3
    assert r.error == "http_5xx" and r.data is None
    assert r.attempts == 3  # Q-3a-2: hết lượt = 3 lần lỗi (spec a10 ghi 2 — chờ sửa spec)


async def test_a11_model_missing_single_call_no_retry() -> None:
    t = Scripted(MISSING, ok())
    r = await make(t).classify("đặt lại mật khẩu")
    assert t.calls == 1
    assert r.attempts == 0 and r.error == "model_missing" and r.data is None


async def test_a11_model_missing_intent() -> None:
    t = Scripted(MISSING)
    r = await make(t).classify_intent("vpn lỗi")
    assert (t.calls, r.attempts, r.error) == (1, 0, "model_missing")


async def test_plain_503_is_retried_as_5xx() -> None:
    t = Scripted(httpx.Response(503, json={"status": "loading"}))
    r = await make(t).embed(["a"])
    assert (t.calls, r.error, r.attempts) == (3, "http_5xx", 3)


@pytest.mark.parametrize("code", [401, 413, 422])
async def test_a12_contract_errors_raise(code: int) -> None:
    t = Scripted(httpx.Response(code, json={"detail": "văn bản người dùng BI-MAT"}))
    with pytest.raises(MlContractError, match=f"HTTP {code}") as exc:
        await make(t).embed(["a"])
    assert t.calls == 1  # không retry
    assert "BI-MAT" not in str(exc.value)  # thông điệp không kèm body


# ---- Phase 5 (T23a, P4 — Q-5-9): /classify 422 too_many_windows = lỗi lớp 3 (giá trị) → B2 xuống L4, không E9 ------------

TOO_MANY = {"error": "too_many_windows", "windows": 49, "max_windows": 48}


async def test_t23a_classify_too_many_windows_is_value() -> None:
    t = Scripted(httpx.Response(422, json=TOO_MANY), ok())
    r = await make(t).classify("văn bản rất dài")
    assert (t.calls, r.error, r.attempts, r.data) == (1, "too_many_windows", 0, None)  # không retry


@pytest.mark.parametrize(("endpoint", "response"), [
    ("classify", httpx.Response(422, json={"detail": "văn bản người dùng BI-MAT"})),  # 422 kiểm body của FastAPI
    ("classify", httpx.Response(422, json={"error": "khac"})),
    ("classify", httpx.Response(422, text="khong-phai-json")),
    ("embed", httpx.Response(422, json=TOO_MANY)),  # chỉ /classify có trần cửa sổ
    ("classify_intent", httpx.Response(422, json=TOO_MANY)),
])  # fmt: skip
async def test_t23a_other_422_still_contract_error(endpoint: str, response: httpx.Response) -> None:
    t = Scripted(response)
    client = make(t)
    call = client.embed(["a"]) if endpoint == "embed" else getattr(client, endpoint)("a")
    with pytest.raises(MlContractError, match="HTTP 422") as exc:
        await call
    assert t.calls == 1
    assert "BI-MAT" not in str(exc.value)


async def test_404_is_contract_error_not_empty() -> None:
    t = Scripted(httpx.Response(404))
    with pytest.raises(MlContractError, match="404"):
        await make(t).embed(["a"])


async def test_response_wrong_schema_raises() -> None:
    t = Scripted(ok({"vectors": "khong-phai-list"}))
    with pytest.raises(MlContractError, match="schema"):
        await make(t).embed(["a"])


@pytest.mark.parametrize(
    ("exc", "kind"),
    [(httpx.ReadTimeout("x"), "timeout"), (httpx.ConnectError("x"), "connect"),
     (httpx.RemoteProtocolError("Server disconnected"), "connect"), (httpx.ReadError("reset"), "connect")],
)  # fmt: skip
async def test_infra_errors_retried_then_returned(exc: Exception, kind: str) -> None:
    t = Scripted(exc)
    r = await make(t).embed(["a"])
    assert (t.calls, r.error, r.attempts, r.data) == (3, kind, 3, None)


async def test_transport_error_then_success() -> None:
    t = Scripted(httpx.RemoteProtocolError("OOMKilled"), ok())
    r = await make(t).embed(["a"])
    assert (t.calls, r.error, r.attempts) == (2, None, 1)


async def test_429_counts_as_5xx() -> None:
    r = await make(Scripted(httpx.Response(429))).embed(["a"])
    assert r.error == "http_5xx"


async def test_sends_token_and_json() -> None:
    t = Scripted(ok())
    await make(t).embed(["tiếng Việt"])
    req = t.requests[0]
    assert req.headers["X-Service-Token"] == TOKEN
    assert req.url.path == "/embed"
    assert json.loads(req.content) == {"texts": ["tiếng Việt"]}


# ---- chia lô (a13, Q-3a-12) ---------------------------------------------------------------------------


def _rerank_echo(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    scores = [float(p.removeprefix("p")) for p in body["passages"]]
    return ok({"scores": scores, "truncated": [False] * len(scores),
               "query_truncated": len(scores) == 18, "model": "reranker"})  # fmt: skip


async def test_a13_rerank_50_passages_two_batches_in_order() -> None:
    t = Scripted(_rerank_echo)
    passages = [f"p{i}" for i in range(50)]
    r = await make(t).rerank("vpn", passages)
    sizes = [len(json.loads(req.content)["passages"]) for req in t.requests]
    assert sizes == [32, 18]
    assert all(json.loads(req.content)["query"] == "vpn" for req in t.requests)
    assert r.data is not None and r.data.scores == [float(i) for i in range(50)]
    assert r.data.query_truncated is True  # một lô báo cắt → cả kết quả báo


def _embed_echo(request: httpx.Request) -> httpx.Response:
    n = len(json.loads(request.content)["texts"])
    return ok({"vectors": [[1.0]] * n, "dim": 1, "model": "BAAI/bge-m3", "truncated": [False] * n, "token_counts": [1] * n})


async def test_failed_batch_stops_and_sums_attempts() -> None:
    """D-101: đổi sang `/embed` (còn thử lại 5xx) — `/rerank` không thử lại 5xx nữa (test riêng bên dưới)."""
    t = Scripted(httpx.Response(500), _embed_echo, httpx.Response(500))
    r = await make(t).embed([f"p{i}" for i in range(70)])
    assert r.error == "http_5xx" and r.data is None
    assert r.attempts == 1 + 3  # lô 1: 1 lần lỗi rồi xong; lô 2: hết lượt
    assert t.calls == 2 + 3


# ---- D-101: rerank chờ một lần, ml-service biết giây chờ ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "kind"),
    [(httpx.ReadTimeout("chậm"), "timeout"), (httpx.Response(500), "http_5xx"), (httpx.Response(503, json={"error": "abandoned"}), "http_5xx")],
)
async def test_d101_rerank_timeout_or_5xx_not_retried(step: Step, kind: str) -> None:
    t = Scripted(step, _rerank_echo)
    r = await make(t).rerank("q", ["p1", "p2"])
    assert (r.error, r.attempts, t.calls) == (kind, 1, 1)


async def test_d101_rerank_connect_error_still_retried() -> None:
    t = Scripted(httpx.ConnectError("mất kết nối"), _rerank_echo)
    r = await make(t).rerank("q", ["p1", "p2"])
    assert r.error is None and t.calls == 2


async def test_d101_embed_timeout_still_retried() -> None:
    t = Scripted(httpx.ReadTimeout("chậm"), _embed_echo)
    r = await make(t).embed(["a"])
    assert r.error is None and t.calls == 2


async def test_d101_client_timeout_header_and_connect_cap() -> None:
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _rerank_echo(request) if request.url.path == "/rerank" else _embed_echo(request)

    client = make(Scripted(capture))
    await client.rerank("q", ["p1"])
    await client.embed(["a"])
    assert [float(r.headers["X-Client-Timeout"]) for r in seen] == [TIMEOUT_S["rerank"], TIMEOUT_S["embed"]]
    assert seen[0].extensions["timeout"]["connect"] == CONNECT_TIMEOUT_S
    assert seen[0].extensions["timeout"]["read"] == TIMEOUT_S["rerank"]


async def test_batches_split_by_bytes_too() -> None:
    big = "a" * (60 * 1024)
    t = Scripted(lambda req: ok({"counts": [1] * len(json.loads(req.content)["texts"]), "model": "m"}))
    r = await make(t).count_tokens([big] * 5)
    assert r.data is not None and len(r.data.counts) == 5
    assert all(len(req.content) <= ml_client.MAX_REQUEST_BYTES for req in t.requests)
    assert t.calls >= 2


async def test_single_text_over_byte_limit_is_contract_error() -> None:
    t = Scripted(ok())
    with pytest.raises(MlContractError, match="văn bản thứ 1 .* byte"):
        await make(t).embed(["ngắn", "b" * (ml_client.MAX_REQUEST_BYTES + 1)])
    assert t.calls == 0


async def test_empty_input_is_contract_error() -> None:
    with pytest.raises(MlContractError):
        await make(Scripted(ok())).embed([])


async def test_batch_limits_match_ml_service_schemas() -> None:
    tree = ast.parse((REPO / "ml_service/app/schemas.py").read_text(encoding="utf-8"))
    consts = {
        n.targets[0].id: ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id.isupper()
    }
    assert consts["EMBED_MAX_ITEMS"] == ml_client.EMBED_MAX_ITEMS
    assert consts["RERANK_MAX_PASSAGES"] == ml_client.RERANK_MAX_PASSAGES
    assert consts["COUNT_MAX_ITEMS"] == ml_client.COUNT_MAX_ITEMS
    limits = (REPO / "ml_service/app/limits.py").read_text(encoding="utf-8")
    assert "MAX_BODY_BYTES = 256 * 1024" in limits and ml_client.MAX_REQUEST_BYTES < 256 * 1024


async def test_span_log_has_no_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    await make(Scripted(ok())).embed(["CANARY-noi-dung-nguoi-dung"])
    assert "ml:embed items=1 batches=1 attempts=0 error=None" in caplog.text
    assert "CANARY" not in caplog.text
