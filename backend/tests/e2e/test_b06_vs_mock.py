"""f7–f14 (thiết kế Phase 3 mục 9.6; PLAN-3f S5) — node B6 THẬT trên mock hệ thống ngoài THẬT (uvicorn, `seed.json`):
registry tool đọc thật → HTTP thật → mock. Seed khác bảng mong đợi → test đỏ (không sửa seed/test cho khớp — báo Q).
Backoff chạy trên FakeClock; HTTP thật. Bản đơn vị (VPN giả đọc cùng seed): `tests/unit/test_b06_diagnose.py`.
"""

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import pytest_asyncio
from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.facts import FACT_KEYS
from app.domain.states import S_DIAGNOSING, S_ESCALATED, S_RETRIEVING
from app.graph.builder import wrap_node
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b06_diagnose
from app.tools.registry import ToolRegistry
from app.tools.wiring import build_read_registry
from tests.e2e.mock_server import MockServer
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans

pytestmark = pytest.mark.asyncio


def _state(user_id: str, slots: dict[str, str] | None = None) -> dict[str, Any]:
    ctx = RequesterContext(
        user_id=user_id, role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=365, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip
    return {"ticket_id": "t1", "turn_id": "T1", "status": S_DIAGNOSING, "intent": "vpn", "slots": slots or {},
            "requester_context": ctx, "reasoning_loops": 1}  # fmt: skip


@pytest_asyncio.fixture
async def directory(mock_server: MockServer, reset: None) -> AsyncIterator[tuple[ToolRegistry, FakeClock]]:
    clock = FakeClock()
    registry, http = build_read_registry(mock_server.settings(), clock)
    try:
        yield registry, clock
    finally:
        await http.aclose()


async def _diagnose(directory: tuple[ToolRegistry, FakeClock], st: dict[str, Any]) -> dict[str, Any]:
    registry, clock = directory
    h = GraphHarness(clock=clock, directory=registry)
    run = RunContext(turn_id="T1", trace_id="0" * 32, audit=MemoryAudit(), effects=MemoryEffects(),
                     spans=MemorySpans(), clock=clock, txlog=MemoryTxLog())  # fmt: skip
    with bind_run(run):
        return await wrap_node("b06_diagnose", b06_diagnose.make(h.deps()))(st)


async def test_f7_nv001_no_device(directory: tuple[ToolRegistry, FakeClock]) -> None:
    u = await _diagnose(directory, _state("nv001"))
    assert u["slots"] == {"device_id": "LAP-0342", "action": "renew_vpn_cert"}
    assert (u["facts"]["cert_status"], u["facts"]["device_owner_is_requester"]) == ("expired", True)
    assert set(u["facts"]) <= FACT_KEYS and u["tool_retry_count"] == 0


async def test_f8_nv002_two_devices(directory: tuple[ToolRegistry, FakeClock]) -> None:
    u = await _diagnose(directory, _state("nv002"))
    assert "device_id" not in u["slots"] and u["facts"]["device_count"] == 2


async def test_f9_nv007_no_device(directory: tuple[ToolRegistry, FakeClock]) -> None:
    u = await _diagnose(directory, _state("nv007"))
    assert (u["facts"]["has_registered_device"], u["facts"]["device_count"]) == (False, 0)


async def test_f10_nv001_names_lap0417(directory: tuple[ToolRegistry, FakeClock]) -> None:
    u = await _diagnose(directory, _state("nv001", {"device_id": "LAP-0417"}))
    assert (u["facts"]["device_owner_is_requester"], u["facts"]["cert_status"]) == (False, "none")
    assert "action" not in u["slots"]


async def test_f11_nv001_names_lap9999(directory: tuple[ToolRegistry, FakeClock]) -> None:
    u = await _diagnose(directory, _state("nv001", {"device_id": "LAP-9999"}))
    assert u["status"] == S_RETRIEVING and u["facts"]["device_registered"] is False


async def test_f12_nv005_revoked(directory: tuple[ToolRegistry, FakeClock]) -> None:
    u = await _diagnose(directory, _state("nv005"))
    assert u["slots"]["action"] == "reissue_vpn_access"


async def test_f13_certs_500_e2(mock_server: MockServer, directory: tuple[ToolRegistry, FakeClock]) -> None:
    async with httpx.AsyncClient(base_url=mock_server.url) as admin:
        fault = {"path_prefix": "/vpn/certs", "mode": "error", "status": 500}
        (await admin.post("/_admin/faults", json=fault)).raise_for_status()
        try:
            u = await _diagnose(directory, _state("nv001"))
        finally:
            (await admin.delete("/_admin/faults")).raise_for_status()
    assert (u["status"], u["exit_code"], u["escalation_reason_detail"]) == (S_ESCALATED, "E2", "tool_system_error")
    assert u["tool_retry_count"] == 2 and u["tool_errors"] == ["check_vpn_cert_expiry: HTTPStatusError"]
    assert "facts" not in u  # không báo "không tồn tại"


async def test_f14_three_tools_300ms_in_parallel(
    mock_server: MockServer, directory: tuple[ToolRegistry, FakeClock]
) -> None:
    async with httpx.AsyncClient(base_url=mock_server.url) as admin:
        fault = {"path_prefix": "/vpn", "mode": "latency", "delay_ms": 300}
        (await admin.post("/_admin/faults", json=fault)).raise_for_status()
        try:
            t0 = time.perf_counter()
            u = await _diagnose(directory, _state("nv001"))
            elapsed = time.perf_counter() - t0
        finally:
            (await admin.delete("/_admin/faults")).raise_for_status()
    assert u["status"] == S_RETRIEVING
    assert elapsed < 0.5, f"B6 mất {elapsed:.2f}s — 3 tool 300 ms phải chạy song song"
