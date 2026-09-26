"""Task nền của API (P1 bảng 3 "API trả 202 ngay [Chốt 14.3]"; 2b-3 chốt (h)).

- Giữ THAM CHIẾU mọi task (asyncio chỉ giữ tham chiếu yếu — task không ai giữ có thể bị gom rác giữa
  chừng).
- `done_callback`: exception của task được log kèm traceback, không bao giờ mất im lặng.
- Task bị huỷ (kể cả trước khi kịp chạy dòng nào) → gọi `on_cancel` — dùng để nhả khoá ticket đã giao
  cho task (`graph.late_event.start_event`).
- Tắt app: chờ tối đa N giây cho lượt đang chạy, rồi huỷ phần còn lại — lượt dở còn mở trong `turns`,
  worker phục hồi (P1 mục 7).
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

log = logging.getLogger(__name__)

type OnCancel = Callable[[], Coroutine[Any, Any, None]]


class BackgroundRuns:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def __len__(self) -> int:
        return len(self._tasks)

    def spawn(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str,
        on_cancel: OnCancel | None = None,
    ) -> asyncio.Task[Any]:
        task = asyncio.get_running_loop().create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._done(t, on_cancel))
        return task

    def _done(self, task: asyncio.Task[Any], on_cancel: OnCancel | None) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            log.warning("task nền %s bị huỷ — lượt dở (nếu có) để worker phục hồi", task.get_name())
            if on_cancel is not None:
                self.spawn(on_cancel(), name=f"{task.get_name()}:on_cancel")
            return
        exc = task.exception()
        if exc is not None:
            log.error("task nền %s lỗi: %s", task.get_name(), exc, exc_info=exc)

    async def drain(self) -> None:
        """Chờ tới khi không còn task (kể cả task sinh thêm trong lúc chờ) — dùng trong test."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
            # `gather` trên task ĐÃ xong có thể trả về mà không nhường vòng lặp → `_done` (bỏ task
            # khỏi tập) chưa kịp chạy → quay vô hạn. Nhường một nhịp.
            await asyncio.sleep(0)

    async def shutdown(self, timeout: float) -> None:
        if not self._tasks:
            return
        _, pending = await asyncio.wait(list(self._tasks), timeout=timeout)
        for task in pending:
            task.cancel()
        await self.drain()
