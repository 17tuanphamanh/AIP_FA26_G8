"""Cổng 1 / P5 mục 8: 404 → không lỗi, không retry; 500 liên tục → đúng 3 lần gọi, chờ 1s rồi 2s;
rỗng → []. Backoff chạy trên FakeClock nên test không chờ thật."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from app.core.clock import FakeClock
from app.settings import get_policy
from app.tools.retry import call_with_retry, retries_of
from tests.unit._http_errors import connect_error, status_error, timeout_error

pytestmark = pytest.mark.asyncio


class Scripted:
    """Lần lượt trả/ném theo kịch bản; đếm số lần bị gọi."""

    def __init__(self, *steps: Any) -> None:
        self.steps = list(steps)
        self.calls = 0

    async def __call__(self, *args: Any, **kw: Any) -> Any:
        self.calls += 1
        step = self.steps[min(self.calls, len(self.steps)) - 1]
        if isinstance(step, BaseException):
            raise step
        return step


async def test_404_is_valid_data_no_retry() -> None:
    fn, clock = Scripted(status_error(404)), FakeClock()
    assert await call_with_retry(fn, clock=clock) == (None, None, 0)
    assert fn.calls == 1 and clock.sleeps == []


async def test_500_forever_three_calls_backoff_1_then_2() -> None:
    fn, clock = Scripted(status_error(500)), FakeClock()
    data, err, attempts = await call_with_retry(fn, clock=clock)
    assert data is None and err is not None and err.startswith("HTTPStatusError")
    assert fn.calls == 3 and attempts == 3
    assert clock.sleeps == [1, 2]


async def test_empty_list_returned_as_is() -> None:
    assert await call_with_retry(Scripted([]), clock=FakeClock()) == ([], None, 0)


@pytest.mark.parametrize("make", [lambda: status_error(429), lambda: status_error(503), timeout_error,
                                  connect_error], ids=["429", "503", "timeout", "connect"])  # fmt: skip
async def test_transient_errors_retried_then_succeed(make: Callable[[], Exception]) -> None:
    fn, clock = Scripted(make(), {"ok": True}), FakeClock()
    assert await call_with_retry(fn, clock=clock) == ({"ok": True}, None, 1)
    assert fn.calls == 2 and clock.sleeps == [1]


@pytest.mark.parametrize("code", [400, 401, 403, 409, 422])
async def test_other_4xx_is_contract_error_not_retried(code: int) -> None:
    fn, clock = Scripted(status_error(code)), FakeClock()
    with pytest.raises(httpx.HTTPStatusError):
        await call_with_retry(fn, clock=clock)
    assert fn.calls == 1 and clock.sleeps == []


async def test_defaults_come_from_policy_json() -> None:
    constants = get_policy().constants
    fn, clock = Scripted(timeout_error()), FakeClock()
    _, _, attempts = await call_with_retry(fn, clock=clock)
    assert fn.calls == attempts == constants.TOOL_RETRY + 1
    assert clock.sleeps == [constants.BACKOFF_BASE_SECONDS * 2**k for k in range(constants.TOOL_RETRY)]


@pytest.mark.parametrize(
    ("attempts", "failed", "retries"),
    [(0, False, 0), (1, False, 1), (2, False, 2), (3, True, 2), (1, True, 0), (0, True, 0)],
)
async def test_retries_of_counts_retries_not_failed_attempts(attempts: int, failed: bool, retries: int) -> None:
    """Q-3c-10, Q-3f-1: `attempts` = số lần thử THẤT BẠI (hỏng hết = số lần gọi = 3) — `tool_retry_count` là số lần THỬ
    LẠI (hỏng hết = TOOL_RETRY = 2)."""
    assert retries_of(attempts, failed=failed) == retries


async def test_exhausted_call_retries_equal_tool_retry() -> None:
    fn, clock = Scripted(timeout_error()), FakeClock()
    _, err, attempts = await call_with_retry(fn, clock=clock)
    assert err is not None and retries_of(attempts, failed=True) == get_policy().constants.TOOL_RETRY
