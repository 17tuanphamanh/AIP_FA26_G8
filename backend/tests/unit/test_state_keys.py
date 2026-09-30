"""Q-A 2b-2: key node trả về phải thuộc `TicketState` — LangGraph 1.2 bỏ IM LẶNG key lạ (mất dữ liệu mà
không ai biết, ví dụ `resolution_path` trong mã giả B10/B17). goto() và boundary chặn thành lỗi → E9."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.domain.states import S_ESCALATED, S_NEW, S_SCREENING
from app.domain.ticket_state import STATE_KEYS, UnknownStateKey, check_state_keys
from app.graph.boundary import with_error_boundary
from app.graph.context import RunContext, bind_run
from app.graph.goto import goto
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import MemoryAudit, MemoryEffects, MemorySpans


@contextmanager
def run(audit: MemoryAudit) -> Iterator[RunContext]:
    ctx = RunContext(turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(),
                     spans=MemorySpans(), clock=FakeClock(), txlog=MemoryTxLog())  # fmt: skip
    with bind_run(ctx):
        yield ctx


def test_state_keys_used_by_b20_exist_and_resolution_path_does_not() -> None:
    assert {"need_type", "approval_result", "is_parent", "aggregate_status"} <= STATE_KEYS
    assert "resolution_path" not in STATE_KEYS  # B20 suy ra, node không đặt (Q-A)
    check_state_keys(["status", "next", "need_type"])
    with pytest.raises(UnknownStateKey, match="resolution_path"):
        check_state_keys(["status", "resolution_path"])


@pytest.mark.asyncio
async def test_goto_rejects_unknown_key_before_writing_audit() -> None:
    audit = MemoryAudit()
    with run(audit), pytest.raises(UnknownStateKey, match="resolution_path"):
        await goto({"ticket_id": "t1", "status": S_NEW}, S_SCREENING, next_node="b02_screen",
                   step="B1", event="x", resolution_path="auto")  # fmt: skip
    assert audit.rows == []


@pytest.mark.asyncio
async def test_node_returning_unknown_key_goes_e9() -> None:
    async def sloppy(state: Any) -> dict[str, Any]:
        return {"status": S_SCREENING, "next": "b02_screen", "resolutionpath": "auto"}  # gõ sai

    audit = MemoryAudit()
    with run(audit):
        update = await with_error_boundary("b01_identity", sloppy)(
            {"ticket_id": "t1", "status": S_NEW})
    assert (update["status"], update["exit_code"]) == (S_ESCALATED, "E9")
    [row] = audit.rows
    assert "UnknownStateKey" in row["detail"]["exception"]
