"""T24 bảng 7.5 — test-first: registry ghi đủ 4 hệ thống (phase5 7.1 P6) — ca w1.

`build_write_registry` nạp `ad_write` + `vpn_write` + `software_write` + `fileserver_write` (token `svc_executor`): MỌI tool `kind ==
"write"` trong `tools.specs.REGISTRY` có handler — gọi từ "B17" qua `httpx.MockTransport` → đúng 1 POST tới endpoint của adapter, header
`X-Service-Token` = token executor, không lỗi "chưa gắn handler" (khuôn `test_executor_plans.py::test_h24_*`).
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from app.core.clock import FakeClock
from app.executor.wiring import build_write_registry
from app.settings import Settings
from app.tools.specs import REGISTRY
from pydantic import SecretStr

AGENT = "a" * 43  # giá trị giả, không phải bí mật
EXECUTOR = "e" * 43
MOCK_URL = "http://mock.invalid"
AT = datetime(2026, 9, 29, 3, 0, tzinfo=UTC).isoformat()

CERT = {"serial": "VPN-2026-9999", "device_id": "LAP-0342", "issued_at": AT, "expires_at": AT, "status": "valid",
        "days_to_expiry": 365}  # fmt: skip
PERM = {"path": "finance/Q3", "level": "read", "granted_at": AT, "expires_at": None, "status": "active"}

# tool → (input, đường dẫn mock, thân phản hồi đúng hình output_model)
WRITES: dict[str, tuple[dict[str, Any], str, dict[str, Any]]] = {
    "reset_password": ({"user_id": "nv001", "account_type": "ad"}, "/ad/users/nv001/reset-password",
                       {"user_id": "nv001", "account_type": "ad", "delivered_via": "email", "must_change_at_next_login": True}),
    "unlock_account": ({"user_id": "nv001", "account_type": "email"}, "/ad/users/nv001/unlock",
                       {"user_id": "nv001", "account_type": "email", "locked": False, "was_locked": True}),
    "lock_account": ({"user_id": "nv001", "account_type": "ad", "reason": "admin"}, "/ad/users/nv001/lock",
                     {"user_id": "nv001", "account_type": "ad", "locked": True}),
    "renew_vpn_cert": ({"user_id": "nv001", "device_id": "LAP-0342"}, "/vpn/certs/nv001/renew", CERT),
    "reissue_vpn_access": ({"user_id": "nv005", "device_id": "LAP-0610"}, "/vpn/access/nv005/reissue", CERT),
    "revoke_vpn_cert": ({"user_id": "nv001", "serial": "VPN-2025-0342"}, "/vpn/certs/nv001/revoke", CERT),
    "install_software": ({"device_id": "LAP-0342", "software_name": "zoom"}, "/software/installed/LAP-0342/install",
                         {"device_id": "LAP-0342", "name": "zoom", "version": "6.1.0", "installed_at": AT}),
    "uninstall_software": ({"device_id": "LAP-0342", "software_name": "zoom"}, "/software/installed/LAP-0342/uninstall",
                           {"device_id": "LAP-0342", "name": "zoom", "removed": True}),
    "assign_paid_license": ({"user_id": "nv001", "software_name": "adobe-acrobat-pro"},
                            "/software/licenses/adobe-acrobat-pro/assign",
                            {"name": "adobe-acrobat-pro", "assignment_id": "LIC-adobe-acrobat-pro-008", "user_id": "nv001",
                             "available": 12}),
    "grant_permission": ({"user_id": "nv001", "resource_path": "finance/Q3", "level": "read", "duration_days": 30},
                         "/files/permissions/nv001/grant", PERM),
    "revoke_permission": ({"user_id": "nv001", "resource_path": "finance/Q3"}, "/files/permissions/nv001/revoke",
                          {"path": "finance/Q3", "revoked": True}),
    "extend_permission": ({"user_id": "nv001", "resource_path": "finance/Q3", "duration_days": 30},
                          "/files/permissions/nv001/extend", {**PERM, "previous_expires_at": AT}),
    "restore_permission_expiry": ({"user_id": "nv001", "resource_path": "finance/Q3", "expires_at": AT},
                                  "/files/permissions/nv001/restore-expiry", PERM),
}  # fmt: skip

WRITE_TOOLS = sorted(name for name, spec in REGISTRY.items() if spec.kind == "write")


class Recorder:
    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, mock_url=MOCK_URL, svc_agent_token=SecretStr(AGENT), svc_executor_token=SecretStr(EXECUTOR)
    )


def test_w1_table_covers_every_declared_write_tool() -> None:
    """Danh sách quét không rỗng và khớp ĐÚNG tập tool ghi đã khai báo (thêm tool ghi mới → bảng này phải thêm)."""
    assert len(WRITE_TOOLS) >= 13 and set(WRITES) == set(WRITE_TOOLS)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", WRITE_TOOLS)
async def test_w1_every_write_tool_has_handler_one_post(tool: str) -> None:
    """w1 (M-T24-11): từ "B17" → đúng 1 POST tới endpoint của adapter, token executor, kết quả hợp lệ (không lỗi thiếu handler)."""
    args, path, body = WRITES[tool]
    rec = Recorder(lambda _: httpx.Response(200, json=body))
    registry, http = build_write_registry(_settings(), FakeClock(), transport=httpx.MockTransport(rec))
    try:
        result = await registry.call(tool, args, caller_step="B17")
    finally:
        await http.aclose()
    assert result.error is None and result.data is not None
    assert len(rec.requests) == 1
    req = rec.requests[0]
    assert (req.method, req.url.path) == ("POST", path)
    assert req.headers["X-Service-Token"] == EXECUTOR
