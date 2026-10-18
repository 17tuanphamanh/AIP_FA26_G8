"""Gói 1 (D-52) DỪNG 2 — `MlClient` phía backend: `classify_failed`, không thử lại timeout `/classify`, `p_malicious` ∈ [0, 1].

Viết TỪ ĐẶC TẢ, trước code: `docs/spec/claude/dac-ta-bat-2-model.md` mục 4.2 (`classify_failed` thêm vào `MlError`,
`_is_l3_error`, ánh xạ ở `_post` — không thì rơi xuống `MlContractError` → E9), 4.6 (lỗi suy luận trả `{"error":
"classify_failed"}` 500, backend KHÔNG thử lại mã này; `/classify` không thử lại khi timeout, vẫn thử lại khi mất kết nối,
5xx), 4.7 #8 (`ClassifyOut.p_malicious: Field(ge=0, le=1)`, không nhận NaN/inf → `MlContractError`), 4.7 #10
(`/classify`, `/classify_intent` cùng trả `classify_failed`); `PLAN-B2REVIEW.md` bảng 3.3 E (phần client), mục 8.

Khuôn: `test_ml_client.py` (transport `Scripted`, đếm request ở nơi nhận).
"""

import typing
from typing import Any

import httpx
import pytest
from app.core.clock import FakeClock
from app.ml import MlClient, MlContractError
from app.ml.ports import MlError

pytestmark = [pytest.mark.asyncio, pytest.mark.xfail(reason="gói 1 DỪNG 2 — chưa nối", strict=False)]

TOKEN = "t" * 43
FAILED = {"error": "classify_failed"}


class Scripted:
    """Transport trả lần lượt theo kịch bản (phần tử cuối lặp lại), ghi lại request."""

    def __init__(self, *steps: httpx.Response | Exception) -> None:
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.steps[min(len(self.requests), len(self.steps)) - 1]
        if isinstance(step, Exception):
            raise step
        return step

    @property
    def calls(self) -> int:
        return len(self.requests)


def make(t: Scripted) -> MlClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(t), base_url="http://ml:8200")
    return MlClient(http, TOKEN, clock=FakeClock())


def classify_ok(p: Any) -> httpx.Response:
    return httpx.Response(200, json={"p_malicious": p, "windows": 1, "model": "injection-clf", "version": "v3"})


async def test_ml_error_literal_has_classify_failed() -> None:
    alias = getattr(MlError, "__value__", MlError)
    assert "classify_failed" in typing.get_args(alias)


@pytest.mark.parametrize("endpoint", ["classify", "classify_intent"])
async def test_classify_failed_is_value_one_request(endpoint: str) -> None:
    t = Scripted(httpx.Response(500, json=FAILED), classify_ok(0.1))
    r = await getattr(make(t), endpoint)("văn bản")
    assert (t.calls, r.error, r.data) == (1, "classify_failed", None)  # không thử lại


async def test_plain_500_classify_still_retried() -> None:
    t = Scripted(httpx.Response(500, json={"detail": "khac"}))
    r = await make(t).classify("văn bản")
    assert (t.calls, r.error) == (3, "http_5xx")


async def test_classify_timeout_not_retried() -> None:
    t = Scripted(httpx.ReadTimeout("x"), classify_ok(0.1))
    r = await make(t).classify("văn bản")
    assert (t.calls, r.error, r.data) == (1, "timeout", None)


async def test_embed_timeout_still_retried() -> None:
    t = Scripted(httpx.ReadTimeout("x"))
    r = await make(t).embed(["a"])
    assert (t.calls, r.error) == (3, "timeout")  # đối chứng: chỉ /classify đổi quy tắc thử lại


@pytest.mark.parametrize(("step", "kind"), [
    (httpx.ConnectError("x"), "connect"),
    (httpx.Response(503, json={"status": "loading"}), "http_5xx"),  # 503 khác model_missing
    (httpx.Response(502), "http_5xx"),
])  # fmt: skip
async def test_classify_connect_and_other_5xx_retried(step: httpx.Response | Exception, kind: str) -> None:
    t = Scripted(step)
    r = await make(t).classify("văn bản")
    assert (t.calls, r.error) == (3, kind)


@pytest.mark.parametrize("p", [1.5, -0.1, float("nan"), float("inf"), float("-inf"), 1.0000001])
async def test_p_malicious_out_of_range_is_contract_error(p: float) -> None:
    t = Scripted(classify_ok(p))
    with pytest.raises(MlContractError):
        await make(t).classify("văn bản")
    assert t.calls == 1


@pytest.mark.parametrize("p", [0.0, 1.0, 0.5])
async def test_p_malicious_bounds_accepted(p: float) -> None:
    r = await make(Scripted(classify_ok(p))).classify("văn bản")
    assert r.data is not None and r.data.p_malicious == p
