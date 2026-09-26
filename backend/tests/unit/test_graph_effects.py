"""effects.once — P1 mục 5.3 (D-18): side effect đúng một lần khi node chạy lại."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.graph import effects
from app.graph.context import RunContext, bind_run
from tests.fakes.graph import MemoryAudit, MemoryEffects, MemorySpans

STATE = {"ticket_id": "t1", "turn_id": "T1", "status": "S_ASSESSING"}


@contextmanager
def run(store: MemoryEffects, turn_id: str = "T1") -> Iterator[None]:
    with bind_run(RunContext(turn_id=turn_id, trace_id="0" * 32, audit=MemoryAudit(),
                             effects=store, spans=MemorySpans(), clock=FakeClock())):  # fmt: skip
        yield


class Counter:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def create(self, *args: Any) -> int:
        self.calls.append(args)
        return 100 + len(self.calls)


@pytest.mark.asyncio
async def test_rerun_returns_old_ref_without_calling_again() -> None:
    store, fn = MemoryEffects(), Counter()
    with run(store):
        first = await effects.once(STATE, "approval_create", fn.create, "t1", step="B15")
        again = await effects.once(STATE, "approval_create", fn.create, "t1", step="B15")
    assert first == again == "101"
    assert len(fn.calls) == 1


@pytest.mark.asyncio
async def test_sub_loop_and_turn_make_distinct_effects() -> None:
    store, fn = MemoryEffects(), Counter()
    with run(store):
        await effects.once(STATE, "notify_user", fn.create, step="B5", sub="round:1")
        await effects.once(STATE, "notify_user", fn.create, step="B5", sub="round:2")
        await effects.once({**STATE, "reasoning_loops": 1}, "notify_user", fn.create, step="B5",
                           sub="round:1")  # fmt: skip
    with run(store, turn_id="T2"):
        await effects.once(STATE, "notify_user", fn.create, step="B5", sub="round:1")
    assert len(fn.calls) == 4


@pytest.mark.asyncio
async def test_failed_effect_is_not_recorded_and_can_retry() -> None:
    store = MemoryEffects()
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("gửi lỗi")
        return "ok"

    with run(store):
        with pytest.raises(RuntimeError):
            await effects.once(STATE, "notify_user", flaky, step="B18")
        assert await effects.once(STATE, "notify_user", flaky, step="B18") == "ok"
    assert calls == 2


@pytest.mark.asyncio
async def test_sync_function_and_unknown_kind() -> None:
    store = MemoryEffects()
    with run(store):
        assert await effects.once(STATE, "deadline_set", lambda: "x", step="B11") == "x"
        with pytest.raises(ValueError, match="kind lạ"):
            await effects.once(STATE, "send_email", lambda: None, step="B11")
