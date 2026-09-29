"""`call_with_retry` [Chốt workflow mục 4, P5 mục 5] — dùng chung cho tool đọc (B6) và RAG (B8).

- Timeout, mất kết nối, 429, 5xx: lỗi tạm thời → retry tối đa `TOOL_RETRY` lần, chờ
  `BACKOFF_BASE_SECONDS · 2^(k-1)` (1s rồi 2s). Hết lượt → trả chuỗi lỗi, KHÔNG raise.
- 404: không tồn tại = dữ liệu hợp lệ → `(None, None, attempt)`, không retry (E2 ≠ E3).
- 4xx khác: lỗi hợp đồng → raise ngay, không retry.

Trả `(data, error, attempt)`. `attempt` = số lần THỬ THẤT BẠI (0 khi thành công ngay; hỏng hết = `retries + 1`) —
đổi ra "số lần thử lại" cho `tool_retry_count` bằng `retries_of` (Q-3c-10, Q-3f-1).
Hạn cho cả lượt (phase3 9.0): trước mỗi lần ngủ backoff gọi `turn_budget.check_sleep` — ngủ xong không còn thời gian
gọi lại thì `TurnBudgetExceeded` ngay (timeout của từng lần thử do hàm gọi cắt bằng `cap_timeout`).
"""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.clock import Clock, SystemClock
from app.core.turn_budget import check_sleep
from app.settings import get_policy

_SYSTEM_CLOCK = SystemClock()


async def call_with_retry(
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    retries: int | None = None,
    base: float | None = None,
    clock: Clock = _SYSTEM_CLOCK,
    what: str = "call_with_retry",
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
        delay = base * 2 ** (attempt - 1)  # 1s, 2s
        check_sleep(delay, clock, what=what)  # 9.0: không ngủ vượt phần còn lại của lượt
        await clock.sleep(delay)


def retries_of(attempts: int, *, failed: bool) -> int:
    """Số lần THỬ LẠI từ `attempts` của `call_with_retry` (Q-3c-10, Q-3f-1): thành công sau k lần lỗi → k; hỏng hết
    (`attempts` = số lần gọi) → `attempts − 1`. Dùng chung cho B6 (`tool_retry_count`) và Retriever."""
    return max(0, attempts - 1) if failed else attempts
