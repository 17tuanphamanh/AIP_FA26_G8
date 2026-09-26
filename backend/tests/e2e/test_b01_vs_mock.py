"""B1 thật với mock AD THẬT (HTTP, seed.json, token svc_agent) — B01 mục 11: phiên hợp lệ → ngữ cảnh
đúng seed; AD tắt qua `/_admin/faults` → E2, không E9; disabled/terminated → invalid_credentials.

Runtime graph dùng bản giả in-memory (checkpoint, audit); phần Postgres ở `integration/test_b01_pg.py`.
TC24/TC25 qua HTTP đăng nhập → tạo ticket: làm ở chặng 2b-3 khi có route ticket.
"""

from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest
import pytest_asyncio
from app.core.clock import FakeClock
from app.domain.states import S_BLOCKED, S_ESCALATED, S_PENDING_APPROVAL
from app.tools.wiring import build_read_registry
from tests.e2e.mock_server import MockServer
from tests.fakes.graph import GraphHarness


@pytest_asyncio.fixture
async def harness(mock_server: MockServer, reset: None) -> AsyncIterator[GraphHarness]:
    clock = FakeClock()
    registry, http = build_read_registry(mock_server.settings(), clock)
    h = GraphHarness(clock=clock, directory=registry)
    for user in ("nv001", "l1_01", "nv004", "nv006"):
        h.identity.add_session(f"s-{user}", user, expires_at=clock.now() + timedelta(days=1))
    try:
        yield h
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_valid_session_context_matches_seed(harness: GraphHarness) -> None:
    r = await harness.submit_as("t-an", "s-nv001")
    assert r.status == S_PENDING_APPROVAL
    ctx = r.values["requester_context"]
    assert (ctx.user_id, ctx.role, ctx.manager_id, ctx.employment_status) == (
        "nv001", "employee", "fin_head", "active")
    r = await harness.submit_as("t-ha", "s-l1_01")
    assert r.values["requester_context"].role == "l1"  # nhóm IT-L1 trong seed


@pytest.mark.asyncio
@pytest.mark.parametrize("user", ["nv004", "nv006"])  # seed: disabled, terminated
async def test_inactive_seed_users_blocked(harness: GraphHarness, user: str) -> None:
    r = await harness.submit_as(f"t-{user}", f"s-{user}")
    assert (r.status, r.values["close_reason"]) == (S_BLOCKED, "blocked_invalid_credentials")


@pytest.mark.asyncio
async def test_ad_fault_gives_e2_not_e9(harness: GraphHarness, mock_server: MockServer) -> None:
    async with httpx.AsyncClient(base_url=mock_server.url) as admin:
        fault = {"path_prefix": "/ad", "mode": "error", "status": 503}
        (await admin.post("/_admin/faults", json=fault)).raise_for_status()
        try:
            r = await harness.submit_as("t-down", "s-nv001")
        finally:
            (await admin.delete("/_admin/faults")).raise_for_status()
    assert (r.status, r.values["exit_code"]) == (S_ESCALATED, "E2")
    assert r.values["escalation_reason_detail"] == "identity_unverifiable"
    assert harness.audit.of("t-down", "unhandled_exception") == []
    assert harness.clock.sleeps == [1, 2]  # retry thật qua HTTP, backoff trên FakeClock
