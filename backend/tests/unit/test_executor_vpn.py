"""`VpnExecutor` (phase3 11.4 bước 4–5; PLAN-3h S9; chốt P4, P6, Q-3h-2) — registry GHI thật (retries=0) trên hệ thống ghi
VPN giả (`tests/fakes/executor.FakeVpnWrites`, đếm ở nơi nhận) + `transaction_log` trong bộ nhớ.

- Thành công: `begun` TRƯỚC lời gọi, ghi đúng 1 lần, `outputs` (serial, ngày hết hạn theo giờ địa phương).
- `check_vpn_status` (PLAN=[]): 0 `begun`, 0 ghi.
- Ticket đã có `begun` (mọi lượt — chốt DỪNG 2, NGHI-2) → `ExecutionInterrupted`, 0 ghi (B5).
- P4: không đủ TRỌN timeout ghi → `TurnBudgetExceeded` TRƯỚC `begun` (0 dòng, 0 ghi) — M-3h-11.
- Lỗi ghi (5xx/404/409/timeout): 1 lời gọi (không retry — M-3h-6), `handoff_note` 4 phần chỉ từ mã tập đóng + định danh (P6).
- Kế hoạch nhiều bước (Phase 5 — dựng PLAN riêng): lỗi bước 2 → hoàn tác bước 1 (`undone`/`undo_failed`); không reversible →
  `not_attempted`, 0 lời gọi hoàn tác.
PG (`begun` commit ngay, thấy từ kết nối khác): `integration/test_txlog_pg.py`. Node B17: `test_b17_execute.py`.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.core.clock import FakeClock
from app.core.turn_budget import TurnBudgetExceeded, TurnDeadline, bind_turn_deadline
from app.domain.action import Action
from app.executor.errors import ExecutionInterrupted
from app.executor.plans import Step
from app.executor.vpn import VpnExecutor, error_kind
from app.graph.fakes import RefusingExecutor
from app.settings import get_action_metadata, get_policy
from tests.fakes.executor import FakeVpnWrites, MemoryTxLog, http_error

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # thứ Ba 10:00 giờ VN
RAW_DETAIL = "chi-tiet-he-thong-ngoai-KHONG-duoc-chep"


def _action(action_type: str = "renew_vpn_cert", *, reversible: bool | None = None) -> Action:
    meta = get_action_metadata().root["vpn"][action_type]
    return Action(
        type=action_type, target="device:LAP-0342", requested_for="nv001", scope=meta.scope,
        privilege_level=meta.privilege_level, reversible=meta.reversible if reversible is None else reversible,
        reversibility=meta.reversibility if reversible is None else ("full" if reversible else "none"),
        data_sensitivity=meta.data_sensitivity, params={"device_id": "LAP-0342"},
        facts={"device_registered": True, "device_owner_is_requester": True, "cert_status": "expired",
               "cert_days_to_expiry": -3},
    )  # fmt: skip


def _executor(**plans: tuple[Step, ...]) -> tuple[VpnExecutor, FakeVpnWrites, MemoryTxLog, FakeClock]:
    clock = FakeClock(NOW)
    writes, txlog = FakeVpnWrites(clock), MemoryTxLog()
    ex = VpnExecutor(writes.registry(), txlog, clock, tz=get_policy().business_hours.tz, plans=plans or None)
    return ex, writes, txlog, clock


async def test_renew_success_begun_before_single_write() -> None:
    ex, writes, txlog, _ = _executor()
    res = await ex.execute("t1", "T1", _action())
    assert res.success and res.steps_done == ["renew_vpn_cert"] and res.failed_step is None
    assert (res.rollback_status, res.rollback_details, res.handoff_note) == ("none_needed", [], None)
    assert writes.calls == {"renew_vpn_cert": 1}
    assert txlog.statuses() == [("renew_vpn_cert", "begun")]
    # 29/09/2026 03:00 UTC + 365 ngày = 29/09/2027 10:00 giờ VN
    assert res.outputs == {"serial": "VPN-NEW-0001", "expires_on": "2027-09-29"}


async def test_expires_on_is_local_date() -> None:
    ex, _, _, clock = _executor()
    clock.set(datetime(2026, 9, 29, 20, 0, tzinfo=UTC))  # 03:00 ngày 30 giờ VN
    res = await ex.execute("t1", "T1", _action())
    assert res.outputs["expires_on"] == "2027-09-30"


async def test_reissue_success() -> None:
    ex, writes, _, _ = _executor()
    res = await ex.execute("t1", "T1", _action("reissue_vpn_access"))
    assert res.success and writes.calls == {"reissue_vpn_access": 1}


async def test_check_vpn_status_no_begun_no_write() -> None:
    ex, writes, txlog, _ = _executor()
    res = await ex.execute("t1", "T1", _action("check_vpn_status"))
    assert res.success and res.steps_done == [] and res.rollback_status == "none_needed"
    assert sum(writes.calls.values()) == 0 and txlog.rows == []


async def test_begun_exists_interrupted_zero_writes() -> None:
    """B5 / h15 phần unit (M-3h-5): lần chạy trước đã `begun` cùng ticket → không ghi lại."""
    ex, writes, txlog, _ = _executor()
    await txlog.begin("t1", "T1", "renew_vpn_cert")
    with pytest.raises(ExecutionInterrupted):
        await ex.execute("t1", "T1", _action())
    assert sum(writes.calls.values()) == 0
    assert txlog.statuses() == [("renew_vpn_cert", "begun")]


async def test_begun_of_other_turn_also_blocks() -> None:
    """Chốt DỪNG 2 (NGHI-2): `begun` ở lượt KHÁC của cùng ticket cũng chặn (trước 3h-DỪNG 2 test này khẳng định điều ngược
    lại — đổi theo chốt, chặt hơn). Mỗi ticket tới B17 tối đa một lần."""
    ex, writes, txlog, _ = _executor()
    await txlog.begin("t1", "T0", "renew_vpn_cert")
    with pytest.raises(ExecutionInterrupted):
        await ex.execute("t1", "T1", _action())
    assert sum(writes.calls.values()) == 0


async def test_begun_blocks_even_empty_plan() -> None:
    """Soát lại DỪNG 2 NGHI-a: kiểm `begun` đứng TRƯỚC kế hoạch rỗng — lớp thứ hai áp cho mọi hành động."""
    ex, writes, txlog, _ = _executor()
    await txlog.begin("t1", "T0", "renew_vpn_cert")
    with pytest.raises(ExecutionInterrupted):
        await ex.execute("t1", "T1", _action("check_vpn_status"))
    assert sum(writes.calls.values()) == 0


async def test_begun_of_other_ticket_does_not_block() -> None:
    ex, writes, txlog, _ = _executor()
    await txlog.begin("t0", "T1", "renew_vpn_cert")
    assert (await ex.execute("t1", "T1", _action())).success
    assert writes.calls == {"renew_vpn_cert": 1}


@pytest.mark.parametrize("left_s", [0.5, 4.9], ids=["con-0.5s", "con-4.9s"])
async def test_p4_not_enough_budget_before_begun(left_s: float) -> None:
    """P4 (M-3h-11): còn ít hơn TRỌN timeout ghi (5 s) → `TurnBudgetExceeded` TRƯỚC `begun`: 0 dòng, 0 lời gọi ghi."""
    ex, writes, txlog, clock = _executor()
    with bind_turn_deadline(TurnDeadline(clock.now() + timedelta(seconds=left_s + 2), 2.0)), pytest.raises(TurnBudgetExceeded):
        await ex.execute("t1", "T1", _action())
    assert txlog.rows == [] and sum(writes.calls.values()) == 0


async def test_p4_exactly_enough_budget_writes() -> None:
    ex, writes, _, clock = _executor()
    with bind_turn_deadline(TurnDeadline(clock.now() + timedelta(seconds=5 + 2), 2.0)):
        assert (await ex.execute("t1", "T1", _action())).success
    assert writes.calls == {"renew_vpn_cert": 1}


@pytest.mark.parametrize(
    ("fault", "kind"),
    [
        (lambda: http_error(500, RAW_DETAIL), "http_5xx"),
        (lambda: http_error(409, "device_not_registered"), "http_409"),
        (lambda: http_error(404, RAW_DETAIL), "http_404"),
        (lambda: httpx.ReadTimeout(RAW_DETAIL), "timeout"),
        (lambda: httpx.ConnectError(RAW_DETAIL), "connect_error"),
    ],
    ids=["500", "409", "404", "timeout", "connect"],
)
async def test_write_error_single_call_handoff_four_parts(fault, kind: str) -> None:  # type: ignore[no-untyped-def]
    """M-3h-6: lỗi ghi → đúng 1 lời gọi (không retry). P6: ghi chú bàn giao 4 phần, không chép chữ của hệ thống ngoài."""
    ex, writes, txlog, _ = _executor()
    writes.faults["renew_vpn_cert"] = fault
    res = await ex.execute("t1", "T1", _action())
    assert not res.success and res.failed_step == "renew_vpn_cert" and res.steps_done == []
    assert res.rollback_status == "none_needed" and res.rollback_details == []
    assert writes.calls == {"renew_vpn_cert": 1}  # không retry, không hoàn tác (chưa bước nào xong)
    assert txlog.statuses() == [("renew_vpn_cert", "begun")]
    note = res.handoff_note or ""
    for part in ("Đã làm:", "Lỗi ở bước:", "Hoàn tác:", "L2 cần làm tay:"):
        assert part in note
    assert f"renew_vpn_cert ({kind})" in note and "LAP-0342" in note and "nv001" in note
    assert RAW_DETAIL not in note and "device_not_registered" not in note and "http://" not in note
    assert res.outputs == {}


def _two_steps() -> tuple[Step, ...]:
    return (Step("renew_vpn_cert", undo="revoke_vpn_cert"), Step("reissue_vpn_access", undo="revoke_vpn_cert"))


async def test_multi_step_failure_undoes_done_steps() -> None:
    ex, writes, txlog, _ = _executor(renew_vpn_cert=_two_steps())
    writes.faults["reissue_vpn_access"] = lambda: http_error(500)
    res = await ex.execute("t1", "T1", _action())
    assert (res.success, res.steps_done, res.failed_step) == (False, ["renew_vpn_cert"], "reissue_vpn_access")
    assert (res.rollback_status, res.rollback_details) == ("undone", [("renew_vpn_cert", "undone")])
    assert writes.calls == {"renew_vpn_cert": 1, "reissue_vpn_access": 1, "revoke_vpn_cert": 1}
    assert txlog.statuses() == [("renew_vpn_cert", "begun"), ("reissue_vpn_access", "begun"), ("renew_vpn_cert", "undone")]
    assert "KHÔNG được khôi phục" in (res.handoff_note or "")


async def test_multi_step_undo_failure_recorded() -> None:
    ex, writes, txlog, _ = _executor(renew_vpn_cert=_two_steps())
    writes.faults["reissue_vpn_access"] = lambda: http_error(500)
    writes.faults["revoke_vpn_cert"] = lambda: http_error(503, RAW_DETAIL)
    res = await ex.execute("t1", "T1", _action())
    assert (res.rollback_status, res.rollback_details) == ("undo_failed", [("renew_vpn_cert", "UNDO_FAILED: http_5xx")])
    assert txlog.rows[-1] == {"ticket_id": "t1", "turn_id": "T1", "step_name": "renew_vpn_cert", "status": "undo_failed",
                              "detail": "UNDO_FAILED: http_5xx"}  # fmt: skip
    assert RAW_DETAIL not in (res.handoff_note or "")


async def test_not_reversible_is_not_attempted() -> None:
    """[Chốt sửa vòng 2]: hành động không hoàn tác được → không gọi undo (`not_attempted`)."""
    ex, writes, _, _ = _executor(renew_vpn_cert=_two_steps())
    writes.faults["reissue_vpn_access"] = lambda: http_error(500)
    res = await ex.execute("t1", "T1", _action(reversible=False))
    assert res.rollback_status == "not_attempted" and writes.calls["revoke_vpn_cert"] == 0


async def test_unknown_action_type_is_bug() -> None:
    ex, _, _, _ = _executor()
    bad = _action().model_copy(update={"type": "format_disk"})
    with pytest.raises(KeyError):
        await ex.execute("t1", "T1", bad)


@pytest.mark.parametrize(
    ("err", "kind"),
    [
        ("circuit_open", "circuit_open"), ("TimeoutException: x", "timeout"), ("ReadTimeout: x", "timeout"),
        ("ConnectTimeout: x", "timeout"), ("ConnectError: x", "connect_error"),
        ("HTTPStatusError: 404 not_found", "http_404"), ("HTTPStatusError: 409 device_not_registered", "http_409"),
        ("HTTPStatusError: 429 slow", "http_429"), ("HTTPStatusError: 502 bad", "http_5xx"), ("lạ gì đó", "other"),
    ],
)
async def test_error_kind_closed_set(err: str, kind: str) -> None:
    assert error_kind(err) == kind


async def test_s12_budget_runs_out_mid_plan_undoes_instead_of_e2() -> None:
    """Soát S12 NGHI-6a (kế hoạch nhiều bước — Phase 5): bước 1 đã ghi rồi hết hạn lượt trước bước 2 → KHÔNG thoát kiểu E2
    (mất dấu phần đã ghi) mà là kết quả lỗi có handoff; hoàn tác cũng không đủ trọn timeout → `undo_failed`, không gửi."""
    ex, writes, txlog, clock = _executor(renew_vpn_cert=_two_steps())
    writes.slow["renew_vpn_cert"] = timedelta(seconds=7)  # dùng được 11 s ≥ 10 s của cả kế hoạch; sau bước 1 còn 4 s < 5 s
    with bind_turn_deadline(TurnDeadline(clock.now() + timedelta(seconds=11 + 2), 2.0)):
        res = await ex.execute("t1", "T1", _action())
    assert (res.success, res.steps_done, res.failed_step) == (False, ["renew_vpn_cert"], "reissue_vpn_access")
    assert res.rollback_details == [("renew_vpn_cert", "UNDO_FAILED: turn_budget_exceeded")]
    assert writes.calls == {"renew_vpn_cert": 1}  # bước 2 và hoàn tác KHÔNG được gửi
    assert txlog.statuses() == [("renew_vpn_cert", "begun"), ("reissue_vpn_access", "begun"),
                                ("renew_vpn_cert", "undo_failed")]  # fmt: skip
    assert "reissue_vpn_access (turn_budget_exceeded)" in (res.handoff_note or "")


async def test_s12_handoff_device_id_regex() -> None:
    """Soát S12 NGHI-5: `device_id` trong ghi chú bàn giao qua regex (máy do B6 suy từ hệ thống ngoài cũng vậy)."""
    ex, writes, _, _ = _executor()
    writes.faults["renew_vpn_cert"] = lambda: http_error(500)
    bad = _action().model_copy(update={"params": {"device_id": "LAP-0342; <b>rm -rf</b>"}})
    note = (await ex.execute("t1", "T1", bad)).handoff_note or ""
    assert "rm -rf" not in note and "cho máy —" in note


async def test_s12_refusing_executor_reads_txlog() -> None:
    """Soát S12 NGHI-3: worker chạy tới B17 (checkpoint `durability="async"` chưa lưu) mà API đã `begun` → E7
    `exec_interrupted`, không phải "chưa bước nào… làm tay"."""
    txlog = MemoryTxLog()
    ex = RefusingExecutor(txlog)
    assert not (await ex.execute("t1", "T1", _action())).success
    await txlog.begin("t1", "T0", "renew_vpn_cert")  # lượt khác của cùng ticket cũng chặn (NGHI-2)
    with pytest.raises(ExecutionInterrupted):
        await ex.execute("t1", "T1", _action())


async def test_s12_check_plans_requires_result_template(monkeypatch: pytest.MonkeyPatch) -> None:
    """Soát S12 NGHI-6c: hành động có PLAN nhưng không có mẫu tin B18 → không khởi động (thay vì ghi xong rồi E9)."""
    from app.executor import plans as plans_module

    monkeypatch.setattr(plans_module, "RESULT_ACTIONS", frozenset({"renew_vpn_cert", "reissue_vpn_access"}))
    with pytest.raises(RuntimeError, match="check_vpn_status"):
        plans_module.check_plans(get_action_metadata().root, ["vpn"])
