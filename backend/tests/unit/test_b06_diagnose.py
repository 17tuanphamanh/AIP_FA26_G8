"""Node B6–B7 THẬT, mức node (thiết kế Phase 3 mục 9.4, 9.6 f7–f16; PLAN-3f chốt Q-3f-1, Q-3f-7).

Tool VPN: registry THẬT trên `tests/fakes/vpn.SeedVpn` — đọc `mock_services/seed.json` (không chép tay), trả JSON như mock
thật; đếm lời gọi ở handler (nơi nhận). Cùng bộ f7–f14 chạy với mock thật: `tests/e2e/test_b06_vs_mock.py`; f17 checkpoint
Postgres: `tests/integration/test_b06_pg.py` (ở đây: round-trip serde in-memory).
"""

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.core.turn_budget import TurnDeadline, bind_turn_deadline
from app.domain.context import RequesterContext
from app.domain.facts import FACT_KEYS
from app.domain.states import S_DIAGNOSING, S_ESCALATED, S_RETRIEVING
from app.graph.builder import wrap_node
from app.graph.checkpoint import make_serde
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b06_diagnose
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.vpn import SeedVpn

pytestmark = pytest.mark.asyncio


def ctx(user_id: str) -> RequesterContext:
    return RequesterContext(
        user_id=user_id, role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=365, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def state(user_id: str, slots: dict[str, str] | None = None, **over: Any) -> dict[str, Any]:
    return {"ticket_id": "t1", "turn_id": "T1", "status": S_DIAGNOSING, "intent": "vpn", "slots": slots or {},
            "facts": {}, "requester_context": ctx(user_id), "reasoning_loops": 1, **over}  # fmt: skip


async def diagnose(st: dict[str, Any], **harness: Any) -> tuple[dict[str, Any], dict[str, Any], SeedVpn]:
    clock = harness.pop("clock", FakeClock())
    vpn = harness.pop("vpn", None) or SeedVpn(clock)
    h = GraphHarness(clock=clock, vpn=vpn, **harness)
    audit = MemoryAudit()
    run = RunContext(turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
                     clock=clock, txlog=MemoryTxLog())  # fmt: skip
    with bind_run(run):
        update = await wrap_node("b06_diagnose", b06_diagnose.make(h.deps()))(st)
    [row] = audit.rows
    return update, row, vpn


# ---- f7–f12: seed thật ---------------------------------------------------------------------------------------------------


async def test_f7_nv001_no_device_infers_lap0342_and_renew() -> None:
    update, row, vpn = await diagnose(state("nv001"))
    assert (update["status"], update["next"]) == (S_RETRIEVING, "b08_retrieve")
    assert update["slots"] == {"device_id": "LAP-0342", "action": "renew_vpn_cert"}
    f = update["facts"]
    assert (f["cert_status"], f["device_owner_is_requester"], f["device_registered"]) == ("expired", True, True)
    assert (f["device_count"], f["has_registered_device"], f["last_connection_ok"]) == (1, True, False)
    assert f["cert_days_to_expiry"] == -3 and set(f) <= FACT_KEYS
    assert update["tool_retry_count"] == 0 and update["ctx_flags"] == {"target_is_other": False}
    assert update["rediagnose"] is False and update["reasoning_loops"] == 2
    assert dict(vpn.calls) == {"check_device_registered": 1, "check_vpn_cert_expiry": 1, "check_last_connection": 1}
    d = row["detail"]
    assert (row["step"], row["event"], d["phase"], d["slots_inferred"]) == ("B6", "diagnosed", "lookup",
                                                                           ["action", "device_id"])  # fmt: skip
    assert d["tools_called"] == ["check_device_registered", "check_vpn_cert_expiry", "check_last_connection"]
    assert d["facts"] == f and d["rediagnose"] is False


async def test_f8_nv002_two_devices_no_device_id() -> None:  # M-3f-4
    update, _, _ = await diagnose(state("nv002"))
    assert "device_id" not in update["slots"] and "action" not in update["slots"]
    assert (update["facts"]["device_count"], update["facts"]["has_registered_device"]) == (2, True)
    assert "device_registered" not in update["facts"]


async def test_f9_nv007_no_device() -> None:
    update, _, _ = await diagnose(state("nv007"))
    assert update["facts"] == {"device_count": 0, "has_registered_device": False}
    assert update["slots"] == {} and update["diagnostics"]["check_device_registered"] is None  # rỗng = dữ liệu


async def test_f10_nv001_names_nv002_device_owner_false_no_action() -> None:  # M-3f-3, M-3f-9 (G-02)
    update, row, _ = await diagnose(state("nv001", {"device_id": "LAP-0417"}))
    f = update["facts"]
    assert (f["device_owner_is_requester"], f["cert_status"], f["device_registered"]) == (False, "none", True)
    assert update["slots"] == {"device_id": "LAP-0417"}  # KHÔNG tự đặt action
    assert row["detail"]["phase"] == "device" and row["detail"]["slots_inferred"] == []


async def test_f11_nv001_names_missing_device_not_registered() -> None:  # M-3f-5
    update, _, _ = await diagnose(state("nv001", {"device_id": "LAP-9999"}))
    f = update["facts"]
    assert (f["device_registered"], f["device_owner_is_requester"], f["cert_status"]) == (False, False, "none")
    assert update["diagnostics"]["check_device_registered"] is None  # 404 = dữ liệu hợp lệ, không E2
    assert update["status"] == S_RETRIEVING


async def test_f12_nv005_revoked_reissue() -> None:
    update, _, _ = await diagnose(state("nv005"))
    assert update["slots"] == {"device_id": "LAP-0610", "action": "reissue_vpn_access"}
    assert update["facts"]["cert_status"] == "revoked"


async def test_user_slots_never_overwritten() -> None:
    update, row, _ = await diagnose(state("nv001", {"action": "check_vpn_status"}))
    assert update["slots"] == {"action": "check_vpn_status", "device_id": "LAP-0342"}  # device suy thêm, action giữ
    assert row["detail"]["slots_inferred"] == ["device_id"]


# ---- f13: lỗi hệ thống → B7 E2 (không "không tồn tại") ----------------------------------------------------------------


async def test_f13_cert_500_goes_e2_tool_system_error() -> None:  # M-3f-10
    clock = FakeClock()
    vpn = SeedVpn(clock).fail("check_vpn_cert_expiry", 500)
    update, row, _ = await diagnose(state("nv001"), clock=clock, vpn=vpn)
    assert (update["status"], update["exit_code"], update["escalation_reason_detail"]) == (
        S_ESCALATED, "E2", "tool_system_error",
    )  # fmt: skip
    assert update["tool_retry_count"] == 2  # Q-3f-1: 3 lần gọi = 2 lần thử lại
    assert update["tool_errors"] == ["check_vpn_cert_expiry: HTTPStatusError"]  # không URL, không user_id
    assert vpn.calls["check_vpn_cert_expiry"] == 3  # TOOL_RETRY 2 → đúng 3 lần gọi (TC18)
    assert "facts" not in update and "diagnostics" not in update  # không kết luận gì từ dữ liệu thiếu
    assert (row["step"], row["event"]) == ("B7", "tool_system_error")
    assert "nv001" not in repr(row["detail"]) and "/vpn/" not in repr(row["detail"])


async def test_f13_404_user_is_data_not_error() -> None:
    update, _, _ = await diagnose(state("nv-ma"))  # người gửi không có ở hệ thống VPN → 404 cả 3 tool
    assert update["status"] == S_RETRIEVING and update["facts"] == {"device_count": 0, "has_registered_device": False}


async def test_retry_then_success_counts_one_retry() -> None:
    clock = FakeClock()
    vpn = SeedVpn(clock).fail("check_last_connection", 503, times=1)
    update, _, _ = await diagnose(state("nv001"), clock=clock, vpn=vpn)
    assert update["status"] == S_RETRIEVING and update["tool_retry_count"] == 1


# ---- f14: song song ---------------------------------------------------------------------------------------------------


async def test_f14_three_slow_tools_run_in_parallel() -> None:
    vpn = SeedVpn(FakeClock())
    vpn.latency_s = 0.3
    t0 = time.perf_counter()
    update, _, _ = await diagnose(state("nv001"), vpn=vpn)
    elapsed = time.perf_counter() - t0
    assert update["status"] == S_RETRIEVING and sum(vpn.calls.values()) == 3
    assert elapsed < 0.5, f"B6 mất {elapsed:.2f}s — 3 tool 0,3 s phải chạy song song"


# ---- f15, f16, hạn lượt, D-20, lỗi hợp đồng ---------------------------------------------------------------------------


async def test_f15_proactive_diagnosis_off_zero_calls() -> None:
    update, row, vpn = await diagnose(state("nv001"), enable_proactive_diagnosis=False)
    assert sum(vpn.calls.values()) == 0
    assert (update["facts"], update["next"], row["event"]) == ({}, "b08_retrieve", "diagnosis_skipped")
    assert "device_id" not in update.get("slots", {})


async def test_f16_max_loops_exceeded() -> None:
    update, row, vpn = await diagnose(state("nv001", reasoning_loops=5))
    assert (update["exit_code"], update["escalation_reason_detail"], update["reasoning_loops"]) == (
        "E2", "max_loops_exceeded", 6,
    )  # fmt: skip
    assert sum(vpn.calls.values()) == 0 and row["step"] == "B6"


async def test_turn_budget_exceeded_at_b6_zero_calls() -> None:
    clock = FakeClock()
    with bind_turn_deadline(TurnDeadline(clock.now() + timedelta(seconds=1), 2.0)):
        update, row, vpn = await diagnose(state("nv001"), clock=clock)
    assert (update["exit_code"], update["escalation_reason_detail"]) == ("E2", "turn_budget_exceeded")
    assert sum(vpn.calls.values()) == 0 and row["event"] == "turn_budget_exceeded"


async def test_q3f7_rediagnose_flag_routes_back_to_b11_and_resets() -> None:
    update, row, vpn = await diagnose(state("nv001", {"device_id": "LAP-0342"}, rediagnose=True))
    assert (update["next"], update["rediagnose"]) == ("b11_slots", False)
    assert sum(vpn.calls.values()) == 3  # 3f: luôn đủ 3 tool (chọn theo slot đổi — 3g)
    assert row["detail"]["rediagnose"] is True


async def test_unknown_intent_is_a_bug_e9() -> None:
    update, row, vpn = await diagnose(state("nv001", intent="account"))
    assert (update["exit_code"], row["event"]) == ("E9", "unhandled_exception")
    assert sum(vpn.calls.values()) == 0


# ---- diagnostics JSON + round-trip serde (f17 bản in-memory) ---------------------------------------------------------------


async def test_f17_diagnostics_json_and_facts_roundtrip_serde() -> None:
    update, _, _ = await diagnose(state("nv001"))
    diag = update["diagnostics"]
    assert set(diag) == {"check_device_registered", "check_vpn_cert_expiry", "check_last_connection"}
    json.dumps(diag)  # dict/list/str thuần — không model Pydantic trong state (PLAN-3f mục 3)
    assert diag["check_device_registered"][0]["device_id"] == "LAP-0342"
    serde = make_serde()
    payload = {k: update[k] for k in ("diagnostics", "facts", "slots", "ctx_flags", "tool_retry_count", "rediagnose")}
    assert serde.loads_typed(serde.dumps_typed(payload)) == payload
