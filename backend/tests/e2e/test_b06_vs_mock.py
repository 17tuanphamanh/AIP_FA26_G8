"""f7–f14 (thiết kế Phase 3 mục 9.6; PLAN-3f S5) — node B6 THẬT trên mock hệ thống ngoài THẬT (uvicorn, `seed.json`):
registry tool đọc thật → HTTP thật → mock. Seed khác bảng mong đợi → test đỏ (không sửa seed/test cho khớp — báo Q).
Backoff chạy trên FakeClock; HTTP thật. Bản đơn vị (VPN giả đọc cùng seed): `tests/unit/test_b06_diagnose.py`.

T20a e1 (phase5 5.1.6): cùng node B6 cho account / software / access trên mock thật — fact phải khớp bảng i/s/c (kỳ vọng chép từ
5.1.2 + seed, như `tests/unit/test_infer_{account,software,access}.py`); seed khác → đỏ, báo Q. `enabled_intents` tiêm 4 intent
(`dataclasses.replace`). Ca T20a (e1) viết ở DỪNG 1, chạy từ DỪNG 2. Không chạy được trong sandbox (uvicorn mở cổng).
"""

import dataclasses
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


FOUR = frozenset({"vpn", "account", "software", "access"})



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


# ---- T20a e1: account / software / access trên mock thật -------------------------------------------------------------------

_EXTEND = {"action": "extend_permission", "duration": "30"}
# (user, intent, slots, fact kỳ vọng — chép bảng 5.1.6 i/s/c, slots suy ra kỳ vọng)
E1 = [
    pytest.param("nv001", "account", {"account_type": "ad", "action": "reset_password"},
                 {"target_account_privilege": "standard_user", "target_is_service_account": False,
                  "target_user_status": "active", "target_account_locked": False}, {}, id="e1-i1-nv001-ad"),
    pytest.param("nv007", "account", {"account_type": "email", "action": "unlock_account"},
                 {"target_account_privilege": "standard_user", "target_is_service_account": False,
                  "target_user_status": "active", "target_account_locked": True, "target_lock_reason": "bad_password"},
                 {}, id="e1-i2-nv007-email-khoa"),
    pytest.param("svc_backup", "account", {"account_type": "ad"},
                 {"target_account_privilege": "admin", "target_is_service_account": True, "target_user_status": "active",
                  "target_account_locked": False}, {}, id="e1-i4-svc_backup"),
    pytest.param("nv001", "account", {"account_type": "ad", "target_user": "nv004"},
                 {"target_account_privilege": "standard_user", "target_is_service_account": False,
                  "target_user_status": "disabled", "target_disable_reason": "security", "target_account_locked": False},
                 {}, id="e1-i5-nv004-qua-target_user"),
    pytest.param("nv005", "account", {"account_type": "erp"}, {}, {}, id="e1-i8-nv005-erp-404"),
    pytest.param("nv001", "software", {"software_name": "Zoom", "device_id": "LAP-0342"},
                 {"in_catalog": True, "license_paid": False, "requires_local_admin": False, "device_registered": True,
                  "device_owner_is_requester": True, "software_prohibited": False, "catalog_requires_approval": False,
                  "software_installed_on_device": True}, {},
                 id="e1-s1-zoom-LAP-0342"),  # D-93: + catalog_requires_approval; V10 M4: seed LAP-0342 đã có zoom
    pytest.param("nv001", "software", {"software_name": "AutoCAD", "device_id": "LAP-0342"},
                 {"in_catalog": True, "license_paid": True, "requires_local_admin": True, "device_registered": True,
                  "device_owner_is_requester": True, "software_prohibited": False, "catalog_requires_approval": True,
                  "software_installed_on_device": False}, {},
                 id="e1-s2-autocad"),
    pytest.param("nv001", "software", {"software_name": "Photoshop", "device_id": "LAP-0342"},
                 {"in_catalog": False, "device_registered": True, "device_owner_is_requester": True,
                  "software_prohibited": False}, {}, id="e1-s3-photoshop-404"),
    pytest.param("nv001", "software", {"software_name": "uTorrent", "device_id": "LAP-0342"},  # Q5: bị cấm (200, không thuộc tính)
                 {"in_catalog": False, "software_prohibited": True, "device_registered": True,
                  "device_owner_is_requester": True}, {}, id="e1-q5-utorrent-cam"),
    pytest.param("nv001", "software", {"software_name": "Zoom"},
                 {"in_catalog": True, "license_paid": False, "requires_local_admin": False, "device_count": 1,
                  "has_registered_device": True, "device_registered": True, "device_owner_is_requester": True,
                  "software_prohibited": False, "catalog_requires_approval": False}, {"device_id": "LAP-0342"}, id="e1-s4-suy-may"),
    pytest.param("nv001", "access", {**_EXTEND, "resource_path": "finance/public-reports"},
                 {"resource_sensitivity": "low", "same_department": True, "has_permission_record": True,
                  "existing_permission_level": "read", "target_user_status": "active"}, {}, id="e1-c1-public-reports"),
    pytest.param("nv002", "access", {**_EXTEND, "resource_path": "/finance/Q3/"},
                 {"resource_sensitivity": "high", "same_department": False, "has_permission_record": True,
                  "existing_permission_level": "read", "target_user_status": "active"}, {}, id="e1-c2-c6-nv002-Q3-het-han"),
    pytest.param("nv001", "access", {"action": "grant_permission", "resource_path": "engineering/specs",
                                     "permission_level": "read", "duration": "30"},
                 {"resource_sensitivity": "medium", "same_department": False, "has_permission_record": False,
                  "target_user_status": "active"}, {}, id="e1-c3-engineering-specs"),
    pytest.param("nv001", "access", {**_EXTEND, "resource_path": "finance/khong-co"},
                 {"has_permission_record": False, "target_user_status": "active"}, {}, id="e1-c5-thu-muc-la"),
    pytest.param("nv001", "access", {"action": "view_permissions"}, {"target_user_status": "active"}, {},
                 id="e1-c7-view"),
]  # fmt: skip


@pytest.mark.parametrize(("user", "intent", "slots", "facts", "inferred"), E1)
async def test_e1_t20a_b6_vs_mock(
    directory: tuple[ToolRegistry, FakeClock], user: str, intent: str, slots: dict[str, str], facts: dict[str, Any],
    inferred: dict[str, str],
) -> None:  # fmt: skip
    """e1: B6 THẬT (nhánh DIAGNOSERS) trên mock thật → `S_RETRIEVING`, fact khớp bảng i/s/c, slot suy ra bổ sung."""
    registry, clock = directory
    h = GraphHarness(clock=clock, directory=registry)
    deps = dataclasses.replace(h.deps(), enabled_intents=FOUR)
    st = {**_state(user, slots), "intent": intent, "facts": {}}
    run = RunContext(turn_id="T1", trace_id="0" * 32, audit=MemoryAudit(), effects=MemoryEffects(),
                     spans=MemorySpans(), clock=clock, txlog=MemoryTxLog())  # fmt: skip
    with bind_run(run):
        u = await wrap_node("b06_diagnose", b06_diagnose.make(deps))(st)
    assert u.get("status") == S_RETRIEVING, (u.get("exit_code"), u.get("escalation_reason_detail"))
    assert u["facts"] == facts and set(u["facts"]) <= FACT_KEYS
    assert u["slots"] == {**slots, **inferred}
