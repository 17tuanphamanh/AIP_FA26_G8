"""Adapter gửi đúng token và URL (respx, không mạng): đọc dùng svc_agent, ghi dùng svc_executor (D-03)."""

import json
from typing import Any

import httpx
import pytest
import respx
from app.tools.adapters import ad_write, fileserver_write, software_write, vpn_write
from app.tools.adapters.http import ServiceHttp
from app.tools.specs import REGISTRY
from app.tools.wiring import read_handlers
from pydantic import SecretStr

BASE = "http://mock:8100"
AGENT, EXECUTOR = "a" * 43, "e" * 43


READ_CALLS: list[tuple[str, dict[str, Any], str, dict[str, str]]] = [
    ("ad_get_user", {"user_id": "nv001"}, "/ad/users/nv001", {}),
    ("check_account_status", {"user_id": "nv007", "account_type": "email"}, "/ad/users/nv007",
     {"account_type": "email"}),
    ("check_lockout_history", {"user_id": "nv007"}, "/ad/users/nv007/lockouts", {}),
    ("check_privilege_level", {"user_id": "nv001"}, "/ad/users/nv001/privilege", {"account_type": "ad"}),
    ("check_manager_chain", {"user_id": "l1_01"}, "/ad/users/l1_01/manager-chain", {}),
    ("check_device_registered", {"user_id": "nv002"}, "/vpn/devices", {"owner_id": "nv002"}),
    ("check_vpn_cert_expiry", {"user_id": "nv001", "device_id": "LAP-0342"}, "/vpn/certs/nv001",
     {"device_id": "LAP-0342"}),
    ("check_vpn_cert_expiry", {"user_id": "nv001"}, "/vpn/certs/nv001", {}),
    ("check_last_connection", {"user_id": "nv001"}, "/vpn/connections/nv001", {}),
    ("check_catalog_entry", {"software_name": "Adobe Acrobat Pro"}, "/software/catalog/Adobe%20Acrobat%20Pro", {}),
    ("check_license_available", {"software_name": "zoom"}, "/software/licenses/zoom", {}),
    ("check_installed_list", {"device_id": "PC-0977"}, "/software/installed/PC-0977", {}),
    ("check_current_permissions", {"user_id": "nv002", "resource_path": "finance/Q3"},
     "/files/permissions/nv002", {"resource_path": "finance/Q3"}),
    ("check_resource_sensitivity", {"resource_path": "/finance/Q3"}, "/files/resources/finance/Q3", {}),
]  # fmt: skip

WRITE_CALLS: list[tuple[str, dict[str, Any], str, dict[str, Any]]] = [
    ("reset_password", {"user_id": "nv001"}, "/ad/users/nv001/reset-password", {"account_type": "ad", "channel": "sms"}),
    ("reset_password", {"user_id": "nv007", "account_type": "email"}, "/ad/users/nv007/reset-password",
     {"account_type": "email", "channel": "email"}),
    ("reset_password", {"user_id": "nv001", "account_type": "erp"}, "/ad/users/nv001/reset-password",
     {"account_type": "erp", "channel": "email"}),
    ("unlock_account", {"user_id": "nv007", "account_type": "email"}, "/ad/users/nv007/unlock",
     {"account_type": "email"}),
    ("lock_account", {"user_id": "nv007", "account_type": "email"}, "/ad/users/nv007/lock",
     {"account_type": "email", "reason": "admin"}),
    ("renew_vpn_cert", {"user_id": "nv001", "device_id": "LAP-0342"}, "/vpn/certs/nv001/renew",
     {"device_id": "LAP-0342"}),
    ("reissue_vpn_access", {"user_id": "nv001", "device_id": "LAP-0342"}, "/vpn/access/nv001/reissue",
     {"device_id": "LAP-0342"}),
    ("revoke_vpn_cert", {"user_id": "nv001", "serial": "S1"}, "/vpn/certs/nv001/revoke", {"serial": "S1"}),
    ("install_software", {"device_id": "PC-0977", "software_name": "zoom"},
     "/software/installed/PC-0977/install", {"software_name": "zoom"}),
    ("uninstall_software", {"device_id": "PC-0977", "software_name": "zoom"},
     "/software/installed/PC-0977/uninstall", {"software_name": "zoom"}),
    ("assign_paid_license", {"software_name": "autocad", "user_id": "nv002"},
     "/software/licenses/autocad/assign", {"user_id": "nv002"}),
    ("grant_permission", {"user_id": "nv003", "resource_path": "finance/Q3", "level": "read",
                          "duration_days": 30}, "/files/permissions/nv003/grant",
     {"resource_path": "finance/Q3", "level": "read", "duration_days": 30}),
    ("revoke_permission", {"user_id": "nv003", "resource_path": "finance/Q3"},
     "/files/permissions/nv003/revoke", {"resource_path": "finance/Q3"}),
    ("extend_permission", {"user_id": "nv002", "resource_path": "finance/Q3", "duration_days": 30},
     "/files/permissions/nv002/extend", {"resource_path": "finance/Q3", "duration_days": 30}),
    ("restore_permission_expiry", {"user_id": "nv002", "resource_path": "finance/Q3", "expires_at": None},
     "/files/permissions/nv002/restore-expiry", {"resource_path": "finance/Q3", "expires_at": None}),
]  # fmt: skip


def _write_handlers(http: ServiceHttp) -> dict[str, Any]:
    return {
        **ad_write.write_handlers(http),
        **vpn_write.write_handlers(http),
        **software_write.write_handlers(http),
        **fileserver_write.write_handlers(http),
    }


def test_every_declared_tool_has_exactly_one_adapter() -> None:
    reads = read_handlers(ServiceHttp(BASE, SecretStr(AGENT)))
    writes = _write_handlers(ServiceHttp(BASE, SecretStr(EXECUTOR)))
    assert set(reads) == {n for n, s in REGISTRY.items() if s.kind == "read"}
    assert set(writes) == {n for n, s in REGISTRY.items() if s.kind == "write"}
    assert {c[0] for c in READ_CALLS} == set(reads) and {c[0] for c in WRITE_CALLS} == set(writes)


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "args", "url", "params"), READ_CALLS, ids=[c[0] for c in READ_CALLS])
async def test_read_adapter_url_params_and_agent_token(
    tool: str, args: dict[str, Any], url: str, params: dict[str, str]
) -> None:
    spec = REGISTRY[tool]
    with respx.mock(base_url=BASE, assert_all_called=True) as mock:
        route = mock.get(url__regex=".*").mock(return_value=httpx.Response(200, json=[]))
        await read_handlers(ServiceHttp(BASE, SecretStr(AGENT)))[tool](spec.input_model(**args), 5.0)
    req = route.calls.last.request
    assert req.url.raw_path.decode().split("?")[0] == url
    assert dict(req.url.params) == params
    assert req.headers["X-Service-Token"] == AGENT


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "args", "url", "body"), WRITE_CALLS, ids=[c[0] for c in WRITE_CALLS])
async def test_write_adapter_url_body_and_executor_token(
    tool: str, args: dict[str, Any], url: str, body: dict[str, Any]
) -> None:
    spec = REGISTRY[tool]
    with respx.mock(base_url=BASE, assert_all_called=True) as mock:
        route = mock.post(url__regex=".*").mock(return_value=httpx.Response(200, json={}))
        await _write_handlers(ServiceHttp(BASE, SecretStr(EXECUTOR)))[tool](spec.input_model(**args), 5.0)
    req = route.calls.last.request
    assert req.url.raw_path.decode() == url
    assert json.loads(req.content) == body
    assert req.headers["X-Service-Token"] == EXECUTOR


@pytest.mark.asyncio
async def test_path_segment_cannot_escape_route() -> None:
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(url__regex=".*").mock(return_value=httpx.Response(200, json={}))
        handlers = read_handlers(ServiceHttp(BASE, SecretStr(AGENT)))
        await handlers["ad_get_user"](REGISTRY["ad_get_user"].input_model(user_id="../../vpn/x"), 5.0)
    assert route.calls.last.request.url.raw_path.decode() == "/ad/users/..%2F..%2Fvpn%2Fx"


@pytest.mark.asyncio
async def test_timeout_is_passed_to_httpx() -> None:
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(url__regex=".*").mock(return_value=httpx.Response(200, json=[]))
        await read_handlers(ServiceHttp(BASE, SecretStr(AGENT)))["check_last_connection"](
            REGISTRY["check_last_connection"].input_model(user_id="nv001"), 1.5)  # fmt: skip
    assert route.calls.last.request.extensions["timeout"]["read"] == 1.5
