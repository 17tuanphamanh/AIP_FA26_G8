"""T24 bảng 7.5 — test-first: B17 (phase5 7.1 P3, P4) — ca x10 (`_write_calls` không đếm `not_reversible`) + node B17 thật với
`view_permissions` (R06 allow): tin B18 lấy dòng quyền từ `state["diagnostics"]["check_current_permissions"]` (B6), 0 lời gọi ghi.

Khuôn `test_b17_execute.Env`: node B17 thật, `PlanExecutor` thật trên registry ghi thật + hệ thống ghi giả (`_t24.FakeWrites`), AD giả
sau registry đọc thật.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.states import S_CONFIRMING, S_EXECUTING
from app.domain.ticket_state import ExecutionResult
from app.executor.plan_executor import PlanExecutor
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b17_execute
from app.graph.nodes.b17_execute import _write_calls
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, ad_user
from tests.unit._t24 import TZ, FakeWrites, action

IN_HOURS = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # thứ Ba 10:00 giờ VN

# ---- x10 ----------------------------------------------------------------------------------------------------------------------


def _result(details: list[tuple[str, str]], steps: list[str]) -> ExecutionResult:
    return ExecutionResult(success=False, steps_done=steps, failed_step="install_software", rollback_status="not_attempted",
                           rollback_details=details, action_plan_hash_matched=None, handoff_note="x")  # fmt: skip


def test_x10_write_calls_does_not_count_not_reversible() -> None:
    """x10 (M-T24-9): assign xong + install lỗi + `("assign_paid_license", "not_reversible")` → 2 lời gọi (không gọi hoàn tác)."""
    assert _write_calls(_result([("assign_paid_license", "not_reversible")], ["assign_paid_license"])) == 2


def test_x10_write_calls_counts_real_undo() -> None:
    """Đối chứng x10: thêm `("grant_permission", "undone")` (lời hoàn tác ĐÃ gửi) → +1."""
    base = _write_calls(_result([("assign_paid_license", "not_reversible")], ["grant_permission", "assign_paid_license"]))
    more = _write_calls(_result([("assign_paid_license", "not_reversible"), ("grant_permission", "undone")],
                                ["grant_permission", "assign_paid_license"]))  # fmt: skip
    assert base == 3 and more == base + 1


# ---- node B17: view_permissions ------------------------------------------------------------------------------------------------


def _requester(user: str = "nv001") -> RequesterContext:
    return RequesterContext(
        user_id=user, role="employee", department="finance", manager_id=None, employment_status="active",
        tenure_days=365, is_privileged_account=False, captured_at=IN_HOURS,
    )  # fmt: skip


DIAG_ROWS = [
    {"path": "finance/Q3", "level": "read", "granted_at": "2026-09-01T03:00:00+00:00",
     "expires_at": "2026-11-01T18:30:00+00:00", "status": "active"},
    {"path": "finance/public-reports", "level": "read", "granted_at": "2026-01-01T03:00:00+00:00", "expires_at": None,
     "status": "active"},
]  # fmt: skip


def _state(diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_EXECUTING, "intent": "access", "reasoning_loops": 1,
        "requester_context": _requester(), "intended_action": action("view_permissions"),
        "ctx_flags": {"target_is_other": False}, "redacted_request": "xem quyền của tôi",
        "slots": {"action": "view_permissions"},
    }  # fmt: skip
    if diagnostics is not None:
        state["diagnostics"] = diagnostics
    return state


class Env:
    def __init__(self) -> None:
        self.clock = FakeClock(IN_HOURS)
        self.ad = FakeAd(ad_user("nv001"))
        self.txlog = MemoryTxLog()
        self.writes = FakeWrites(self.clock, self.txlog)
        self.h = GraphHarness(clock=self.clock, ad=self.ad, txlog=self.txlog)
        self.executor: Any = PlanExecutor(self.writes.registry(), self.txlog, self.clock, tz=TZ)

    @contextmanager
    def run(self) -> Iterator[None]:
        with bind_run(RunContext(turn_id="T1", trace_id="0" * 32, audit=self.h.audit, effects=self.h.effects,
                                 spans=self.h.spans, clock=self.clock, txlog=self.txlog)):  # fmt: skip
            yield

    async def node(self, state: dict[str, Any]) -> dict[str, Any]:
        deps = self.h.deps()
        deps.executor = self.executor
        fn = b17_execute.make(deps)
        with self.run():
            out: dict[str, Any] = await fn(state)
        return out


@pytest.mark.asyncio
async def test_x5_b17_view_permissions_message_lists_rows_zero_writes() -> None:
    """P4 + x5 ở mức node: R06 allow → B17 → tin `result` liệt kê quyền (ngày hết hạn theo giờ địa phương), 0 lời gọi ghi, 0 `begun`."""
    env = Env()
    out = await env.node(_state({"check_current_permissions": DIAG_ROWS}))
    assert out.get("status") == S_CONFIRMING, env.h.audit.events("t1")
    assert env.writes.total() == 0 and env.txlog.rows == []
    [msg] = out["conversation"]
    assert msg["kind"] == "result"
    assert msg["text"] == (
        "Quyền truy cập hiện có của bạn: finance/Q3 (read, hết hạn 02/11/2026); finance/public-reports (read, không thời hạn). "
        "Bạn xem đã đủ chưa rồi xác nhận giúp mình nhé."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "diagnostics", [None, {}, {"check_current_permissions": None}], ids=["khong-diagnostics", "thieu-khoa", "404-None"]
)
async def test_x5_b17_view_permissions_missing_rows_unreadable(diagnostics: dict[str, Any] | None) -> None:
    """Thiếu dữ liệu quyền (B6 không lưu / 404) → "Mình chưa đọc được danh sách quyền…", vẫn 0 lời gọi ghi."""
    env = Env()
    out = await env.node(_state(diagnostics))
    assert out.get("status") == S_CONFIRMING, env.h.audit.events("t1")
    [msg] = out["conversation"]
    assert msg["text"].startswith("Mình chưa đọc được danh sách quyền truy cập của bạn.")
    assert env.writes.total() == 0 and env.txlog.rows == []


@pytest.mark.asyncio
async def test_x5_b17_view_permissions_empty_list_no_rows() -> None:
    env = Env()
    out = await env.node(_state({"check_current_permissions": []}))
    [msg] = out["conversation"]
    assert msg["text"] == "Quyền truy cập hiện có của bạn: chưa thấy quyền nào. Bạn xem đã đủ chưa rồi xác nhận giúp mình nhé."
