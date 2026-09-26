"""`BackgroundRuns.drain` (2b-3): task ĐÃ xong nhưng `done_callback` (bỏ task khỏi tập) chưa chạy →
`drain` vẫn phải trả về. Python 3.12 `gather` trên toàn future đã xong trả kết quả NGAY, không nhường
vòng lặp — vòng `while self._tasks: await gather(...)` quay mãi, callback không bao giờ được chạy.

Vòng quay không nhường nên `asyncio.wait_for` không cắt được: chạy trong thread daemon riêng (vòng lặp
riêng) và `join` có hạn — hỏng thì test ĐỎ sau 2 giây thay vì treo cả bộ test.
"""

import asyncio
import threading

from app.api.background import BackgroundRuns

JOIN_SECONDS = 2.0


def test_drain_returns_when_done_callback_pending() -> None:
    outcome: list[object] = []

    async def scenario() -> None:
        # eager: task chạy xong NGAY trong create_task; done_callback chỉ được xếp lịch (call_soon)
        asyncio.get_running_loop().set_task_factory(asyncio.eager_task_factory)
        runs = BackgroundRuns()

        async def instant() -> None:
            return None

        task = runs.spawn(instant(), name="instant")
        assert task.done() and len(runs) == 1  # đúng trạng thái cần thử: xong mà chưa bị bỏ khỏi tập
        await runs.drain()
        assert len(runs) == 0

    def target() -> None:
        try:
            asyncio.run(scenario())
            outcome.append("ok")
        except BaseException as exc:  # noqa: BLE001 — chuyển lỗi về thread test
            outcome.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(JOIN_SECONDS)
    assert not thread.is_alive(), f"drain treo quá {JOIN_SECONDS} giây (quay vô hạn)"
    assert outcome == ["ok"], outcome
