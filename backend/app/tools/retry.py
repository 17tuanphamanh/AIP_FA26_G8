"""`call_with_retry` [Chốt workflow mục 4, P5 mục 5] — dùng chung cho tool đọc (B6) và RAG (B8).

- Timeout, mất kết nối, 429, 5xx: lỗi tạm thời → retry tối đa `TOOL_RETRY` lần, chờ
  `BACKOFF_BASE_SECONDS · 2^(k-1)` (1s rồi 2s). Hết lượt → trả chuỗi lỗi, KHÔNG raise.
- 404: không tồn tại = dữ liệu hợp lệ → `(None, None, attempt)`, không retry (E2 ≠ E3).
- 4xx khác: lỗi hợp đồng → raise ngay, không retry.

Trả `(data, error, attempt)`; `attempt` → `tool_retry_count` ở điểm log 2 và 3 [Chốt].
"""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.clock import Clock, SystemClock
from app.settings import get_policy

_SYSTEM_CLOCK = SystemClock()


async def call_with_retry(
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    retries: int | None = None,
    base: float | None = None,
    clock: Clock = _SYSTEM_CLOCK,
    **kw: Any,
) -> tuple[Any, str | None, int]:
    constants = get_policy().constants
    retries = constants.TOOL_RETRY if retries is None else retries
    base = constants.BACKOFF_BASE_SECONDS if base is None else base
    attempt = 0
    while True:
        err: Exception
        try:
            return await fn(*args, **kw), None, attempt
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            err = e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None, None, attempt  # không tồn tại = dữ liệu hợp lệ
            if e.response.status_code != 429 and e.response.status_code < 500:
                raise  # 4xx khác: lỗi hợp đồng, không retry
            err = e
        attempt += 1
        if attempt > retries:
            return None, f"{type(err).__name__}: {err}", attempt
        await clock.sleep(base * 2 ** (attempt - 1))  # 1s, 2s
