"""Cổng 1 (huong-dan 5.1) + P5 mục 8, tự động hoá phần "thủ công": gọi 12 tool đọc qua registry thật →
HTTP thật → mock thật (uvicorn, subprocess) với seed.json, đối chiếu bảng mong đợi; bật/tắt
`/_admin/faults`; token svc_agent gọi endpoint ghi → 403.

Bảng mong đợi này cũng có ở mock_services/README.md cho người xác nhận gọi tay.
Backoff chạy trên FakeClock; HTTP là thật.
"""

from typing import Any

import httpx
import pytest
from app.auth.ports import IdentityUnavailable
from app.core.clock import FakeClock
from app.tools.adapters import vpn_write
from app.tools.adapters.ad_read import AdIdentityProvider
from app.tools.adapters.http import ServiceHttp
from app.tools.registry import ToolRegistry
from app.tools.specs import READ_TIMEOUT_S
from app.tools.wiring import breaker_board, build_read_registry
from pydantic import SecretStr
from tests.e2e.mock_server import MockServer

# (tool, input, kiểm kết quả) — bảng mong đợi với seed.json
EXPECTED: list[tuple[str, dict[str, Any], Any]] = [
    ("check_account_status", {"user_id": "nv007", "account_type": "email"},
     lambda d: d.account.locked and d.account.lock_reason == "bad_password"),
    ("check_lockout_history", {"user_id": "nv007"},
     lambda d: [x.account_type for x in d.root] == ["email"] * 3),
    ("check_lockout_history", {"user_id": "nv002"}, None),  # rỗng — dữ liệu hợp lệ
    ("check_privilege_level", {"user_id": "svc_backup"},
     lambda d: d.level == "admin" and d.is_privileged_account),
    ("check_device_registered", {"user_id": "nv002"},
     lambda d: [(x.device_id, x.registered) for x in d.root] == [("LAP-0417", True), ("PC-0977", False)]),
    ("check_device_registered", {"user_id": "nv001", "device_id": "LAP-0342"},
     lambda d: d.root[0].registered),
    ("check_device_registered", {"user_id": "nv001", "device_id": "KHONG-CO"}, None),  # 404
    ("check_vpn_cert_expiry", {"user_id": "nv001", "device_id": "LAP-0342"},
     lambda d: [(c.status, c.days_to_expiry) for c in d.root] == [("expired", -3)]),  # TC06
    ("check_last_connection", {"user_id": "nv001"},
     lambda d: d.root[0].result == "failed" and d.root[0].error_code == "CERT_EXPIRED"),
    ("check_last_connection", {"user_id": "nv003"}, None),
    ("check_catalog_entry", {"software_name": "Zoom"}, lambda d: d.in_catalog and not d.paid and not d.prohibited),
    ("check_catalog_entry", {"software_name": "photoshop"}, None),  # TC17 (Q5: ví dụ photoshop): không tồn tại ≠ lỗi
    ("check_catalog_entry", {"software_name": "utorrent"},  # Q5: bị cấm → 200, không có thuộc tính danh mục
     lambda d: (d.name, d.in_catalog, d.prohibited, d.paid) == ("utorrent", False, True, None)),
    ("check_catalog_entry", {"software_name": "windows-crack"}, lambda d: (d.in_catalog, d.prohibited) == (False, True)),
    ("check_license_available", {"software_name": "ms-project"}, lambda d: d.available == 0),
    ("check_license_available", {"software_name": "adobe-acrobat-pro"}, lambda d: d.available == 3),
    ("check_installed_list", {"device_id": "LAP-0342"},
     lambda d: [x.name for x in d.root] == ["ms-office", "zoom"]),
    ("check_installed_list", {"device_id": "PC-0977"}, None),
    ("check_current_permissions", {"user_id": "nv002", "resource_path": "finance/Q3"},
     lambda d: [p.status for p in d.root] == ["expired"]),
    ("check_resource_sensitivity", {"resource_path": "finance/Q3"}, lambda d: d.sensitivity == "high"),
    ("check_manager_chain", {"user_id": "l1_01"},  # Phase 4 P14: l1_01 → l1_lead → it_mgr01
     lambda d: [m.user_id for m in d.root] == ["l1_lead", "it_mgr01"]),
    ("check_manager_chain", {"user_id": "fin_head"}, None),
]  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "args", "check"), EXPECTED,
                         ids=[f"{t}-{i}" for i, (t, _, _) in enumerate(EXPECTED)])  # fmt: skip
async def test_twelve_read_tools_against_seed(
    mock_server: MockServer, reset: None, tool: str, args: dict[str, Any], check: Any
) -> None:
    registry, http = build_read_registry(mock_server.settings(), FakeClock())
    try:
        result = await registry.call(tool, args, caller_step="B6")
    finally:
        await http.aclose()
    assert result.error is None, result.error
    if check is None:
        assert result.empty
    else:
        assert not result.empty and check(result.data)


@pytest.mark.asyncio
async def test_all_twelve_tools_covered() -> None:
    from app.tools.specs import TOOL_MAP

    assert {t for tools in TOOL_MAP.values() for t in tools} == {t for t, _, _ in EXPECTED}


@pytest.mark.asyncio
async def test_ad_get_user_for_b1(mock_server: MockServer, reset: None) -> None:
    registry, http = build_read_registry(mock_server.settings(), FakeClock())
    try:
        user, err, _ = await registry.call_internal("ad_get_user", {"user_id": "nv004"}, caller_step="B1")
    finally:
        await http.aclose()
    assert err is None and user.employment_status == "disabled"  # D-15: người gửi đã bị vô hiệu hoá


@pytest.mark.asyncio
async def test_fault_on_gives_system_error_off_gives_data(mock_server: MockServer, reset: None) -> None:
    clock = FakeClock()
    registry, http = build_read_registry(mock_server.settings(), clock)
    try:
        async with httpx.AsyncClient(base_url=mock_server.url) as admin:
            fault = {"path_prefix": "/vpn", "mode": "error", "status": 500}
            (await admin.post("/_admin/faults", json=fault)).raise_for_status()
            broken = await registry.call("check_last_connection", {"user_id": "nv001"}, caller_step="B6")
            assert broken.error is not None and "500" in broken.error and not broken.empty  # E2 ≠ E3
            assert broken.attempts == 3 and clock.sleeps == [1, 2]
            (await admin.delete("/_admin/faults")).raise_for_status()
        fixed = await registry.call("check_last_connection", {"user_id": "nv001"}, caller_step="B6")
        assert fixed.error is None and not fixed.empty
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_agent_token_cannot_write_executor_can(mock_server: MockServer, reset: None) -> None:
    """P5 mục 8 "Mạng" / P6 test 9 qua HTTP thật."""
    args = {"user_id": "nv001", "device_id": "LAP-0342"}
    agent_http = ServiceHttp(mock_server.url, SecretStr(mock_server.agent))
    exec_http = ServiceHttp(mock_server.url, SecretStr(mock_server.executor))
    clock = FakeClock()
    settings = mock_server.settings()
    try:
        as_agent = ToolRegistry(vpn_write.write_handlers(agent_http), breakers=breaker_board(settings, clock),
                                clock=clock)  # fmt: skip
        from app.tools.registry import ToolContractError

        with pytest.raises(ToolContractError, match="403"):
            await as_agent.call("renew_vpn_cert", args, caller_step="B17")
        as_executor = ToolRegistry(vpn_write.write_handlers(exec_http),
                                   breakers=breaker_board(settings, clock), clock=clock)  # fmt: skip
        renewed = await as_executor.call("renew_vpn_cert", args, caller_step="B17")
        assert renewed.error is None and renewed.data is not None and renewed.data.status == "valid"
    finally:
        await agent_http.aclose()
        await exec_http.aclose()


# ---- P6: đăng nhập qua mock AD (argon2id) ----------------------------------------------------


@pytest.mark.asyncio
async def test_identity_provider_against_mock_ad(mock_server: MockServer, reset: None) -> None:
    registry, http = build_read_registry(mock_server.settings(), FakeClock())
    idp = AdIdentityProvider(http, registry, timeout=READ_TIMEOUT_S, unavailable=IdentityUnavailable)
    try:
        user = await idp.authenticate("quan.tm", "Demo@2026!")  # mật khẩu demo công khai (README mock)
        assert user is not None and user.user_id == "it_mgr01" and "IT-Manager" in user.groups
        assert await idp.authenticate("quan.tm", "sai") is None
        assert await idp.authenticate("khong.ton.tai", "Demo@2026!") is None  # hash giả, cùng 401
        boss = await idp.get_user("fin_head")
        assert boss is not None and boss.manager_id is None
        assert await idp.get_user("khong-co") is None
    finally:
        await http.aclose()
