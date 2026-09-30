"""`goto(..., audit_columns=…)` và `effects.peek` — Phase 4 chặng 4b DỪNG 2 (PLAN-4b S11). Viết TỪ ĐẶC TẢ, trước code: phase4 mục
5.1 P9 (`peek`), P10 (`audit_columns` + `_POINT_COLUMNS`), 5.3 b9.

- b9: khoá ngoài `_POINT_COLUMNS` = {approver_id, deadline, conflict_detected, response_time_seconds} → `ValueError` TRƯỚC khi ghi
  dòng audit (0 dòng).
- P10: khoá hợp lệ → vào CỘT audit cùng tên, KHÔNG vào state trả về; `intended_action` (key sẵn có) → cột `intended_action` là dict JSON.
- P9: `effects.peek(state, kind, *, step, sub="")` cùng khoá với `effects.once`; chưa làm → None; đã `once` → `result_ref`; không ghi
  dòng mới, không gọi hàm.
"""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import app.graph.goto as goto_module
import pytest
from app.core.clock import FakeClock
from app.core.hashing import hash_action
from app.domain.states import S_ASSESSING, S_PENDING_APPROVAL, S_REJECTED
from app.graph import effects
from app.graph.context import RunContext, bind_run
from app.graph.fakes import FAKE_ACTION
from app.graph.goto import goto
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import MemoryAudit, MemoryEffects, MemorySpans

pytestmark = pytest.mark.asyncio

POINT_COLUMNS = frozenset({"approver_id", "deadline", "conflict_detected", "response_time_seconds"})  # P10
DEADLINE = datetime(2026, 9, 29, 3, 30, tzinfo=UTC)


class SpyEffects(MemoryEffects):
    """`EffectStore` giả ghi lại khoá của `peek` và `run_once` — kiểm "cùng khoá" (P9)."""

    def __init__(self) -> None:
        super().__init__()
        self.peeked: list[str] = []
        self.ran: list[str] = []

    async def peek(self, key: str) -> str | None:
        self.peeked.append(key)
        return await super().peek(key)

    async def run_once(
        self, *, key: str, ticket_id: str, kind: str, step: str, turn_id: str,
        call: Callable[[], Awaitable[Any]],
    ) -> str | None:  # fmt: skip
        self.ran.append(key)
        return await super().run_once(key=key, ticket_id=ticket_id, kind=kind, step=step, turn_id=turn_id, call=call)


@contextmanager
def run(audit: MemoryAudit | None = None, store: MemoryEffects | None = None, turn_id: str = "T1") -> Iterator[None]:
    with bind_run(RunContext(turn_id=turn_id, trace_id="0" * 32, audit=audit or MemoryAudit(),
                             effects=store or MemoryEffects(), spans=MemorySpans(), clock=FakeClock(),
                             txlog=MemoryTxLog())):  # fmt: skip
        yield


def state(status: str, **extra: Any) -> dict[str, Any]:
    return {"ticket_id": "t1", "turn_id": "T1", "status": status, **extra}


# ---- b9 + P10: audit_columns ---------------------------------------------------------------------------------------------


async def test_p10_point_columns_constant() -> None:
    """P10: hằng `goto._POINT_COLUMNS` đúng 4 cột của điểm log 5/6."""
    assert set(getattr(goto_module, "_POINT_COLUMNS", ())) == POINT_COLUMNS


@pytest.mark.parametrize(
    ("columns", "bad"),
    [
        pytest.param({"foo": 1}, "foo", id="b9-foo"),
        pytest.param({"approver_id": "l1_01", "foo": 1}, "foo", id="hop-le-lan-khoa-la"),
        pytest.param({"exit_code": "E5"}, "exit_code", id="cot-audit-that-nhung-khong-phai-diem-5-6"),
        pytest.param({"approval_result": "approved"}, "approval_result", id="state-key-khong-phai-point-column"),
    ],
)
async def test_b9_goto_unknown_audit_column_value_error_before_audit(columns: dict[str, Any], bad: str) -> None:
    """b9 (P10): `audit_columns` có khoá ngoài `_POINT_COLUMNS` → `ValueError` (nêu tên khoá) TRƯỚC khi ghi dòng audit — 0 dòng."""
    audit = MemoryAudit()
    with run(audit), pytest.raises(ValueError, match=bad):
        await goto(state(S_ASSESSING), S_PENDING_APPROVAL, next_node="approval_wait", step="B15", event="queued",
                   audit_columns=columns)  # fmt: skip
    assert audit.rows == []


async def test_p10_audit_columns_go_to_columns_not_state() -> None:
    """P10: `audit_columns={"approver_id", "deadline", "conflict_detected"}` → ghi vào cột audit cùng tên (False vẫn là False, không
    NULL); KHÔNG xuất hiện trong state `goto` trả về."""
    audit = MemoryAudit()
    with run(audit):
        out = await goto(state(S_ASSESSING), S_PENDING_APPROVAL, next_node="approval_wait", step="B15", event="queued",
                         audit_columns={"approver_id": "l1_01", "deadline": DEADLINE, "conflict_detected": False})  # fmt: skip
    [row] = audit.rows
    assert (row["approver_id"], row["deadline"]) == ("l1_01", DEADLINE)
    assert row["conflict_detected"] is False
    assert (out["status"], out["next"]) == (S_PENDING_APPROVAL, "approval_wait")
    assert not (POINT_COLUMNS | {"audit_columns"}) & set(out), sorted(out)


async def test_p10_response_time_seconds_column_point6() -> None:
    """P10: `response_time_seconds` (điểm log 6, B16) cũng là cột hợp lệ của `audit_columns`."""
    audit = MemoryAudit()
    with run(audit):
        out = await goto(state(S_PENDING_APPROVAL), S_REJECTED, next_node="b20_audit", step="B16", event="rejected",
                         approval_result="rejected", audit_columns={"response_time_seconds": 12.5})  # fmt: skip
    [row] = audit.rows
    assert row["response_time_seconds"] == 12.5
    assert "response_time_seconds" not in out


async def test_p10_intended_action_key_fills_audit_column_as_json() -> None:
    """P10 / Q-4b-4: `intended_action` (key state sẵn có) → cột `audit_logs.intended_action` là dict JSON của Action (có `type` +
    `target`); `action_plan_hash` vào cột cùng tên."""
    audit = MemoryAudit()
    plan_hash = hash_action(FAKE_ACTION)
    with run(audit):
        await goto(state(S_ASSESSING), S_PENDING_APPROVAL, next_node="approval_wait", step="B15", event="queued",
                   intended_action=FAKE_ACTION, action_plan_hash=plan_hash)  # fmt: skip
    [row] = audit.rows
    assert isinstance(row["intended_action"], dict)
    assert (row["intended_action"]["type"], row["intended_action"]["target"]) == (FAKE_ACTION.type, FAKE_ACTION.target)
    assert row["action_plan_hash"] == plan_hash


# ---- P9: effects.peek --------------------------------------------------------------------------------------------------------


class Counter:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, *args: Any) -> str:
        self.calls += 1
        return f"a{self.calls}"


STATE = state(S_ASSESSING, reasoning_loops=1)


async def test_p9_peek_before_once_is_none_and_writes_nothing() -> None:
    store = SpyEffects()
    with run(store=store):
        assert await effects.peek(STATE, "approval_create", step="B15") is None
    assert store.rows == {} and store.ran == [] and len(store.peeked) == 1


async def test_p9_peek_after_once_returns_ref_same_key_no_call_no_row() -> None:
    """P9: sau `once` → `peek` trả ĐÚNG `result_ref`; khoá `peek` = khoá `once` (ticket, step, turn, loop_seq, kind, sub); không gọi
    hàm lần hai, không thêm dòng."""
    store, fn = SpyEffects(), Counter()
    with run(store=store):
        ref = await effects.once(STATE, "approval_create", fn.create, "t1", step="B15")
        rows = dict(store.rows)
        got = await effects.peek(STATE, "approval_create", step="B15")
    assert got == ref == "a1"
    assert store.peeked == store.ran and len(store.ran) == 1
    assert fn.calls == 1 and store.rows == rows


@pytest.mark.parametrize(
    ("kind", "step", "sub", "loops", "turn"),
    [
        pytest.param("notify_approver", "B15", "", 1, "T1", id="kind-khac"),
        pytest.param("approval_create", "B16", "", 1, "T1", id="step-khac"),
        pytest.param("approval_create", "B15", "x", 1, "T1", id="sub-khac"),
        pytest.param("approval_create", "B15", "", 2, "T1", id="loop-khac"),
        pytest.param("approval_create", "B15", "", 1, "T2", id="luot-khac"),
    ],
)
async def test_p9_peek_other_key_is_none(kind: str, step: str, sub: str, loops: int, turn: str) -> None:
    """P9: `peek` với khác một thành phần khoá (kind / step / sub / loop / lượt) → None — cùng khoá với `once`, không "đoán"."""
    store, fn = SpyEffects(), Counter()
    with run(store=store):
        await effects.once(STATE, "approval_create", fn.create, "t1", step="B15")
    with run(store=store, turn_id=turn):
        got = await effects.peek(state(S_ASSESSING, reasoning_loops=loops), kind, step=step, sub=sub)
    assert got is None
    assert fn.calls == 1 and len(store.rows) == 1
