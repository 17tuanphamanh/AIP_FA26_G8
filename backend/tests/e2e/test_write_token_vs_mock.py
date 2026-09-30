"""h25 (phase3 mục 11.7) — adapter ghi dùng token `svc_agent` → mock THẬT trả 403; hệ thống đích không đổi.

Nguồn: P5 mục 8 "Mạng: gọi endpoint ghi bằng token svc_agent → 403"; B17-B18 mục 10 ("Mock ghi nhận token svc_agent →
403") + mục 11 "Bảo mật"; 11.4 (adapter ghi `vpn_write.py` dùng token svc_executor, registry ghi riêng). Registry ghi dựng
bằng `app.executor.wiring.build_write_registry` (đường thật của 3h), cố ý cấu hình SAI: `SVC_EXECUTOR_TOKEN` = token
svc_agent. P5 6.1: 4xx ngoài 404/409/429 là lỗi hợp đồng → raise (`ToolContractError`), không phải giá trị.

Seed (3.7): `nv001` — `LAP-0342`, cert `VPN-2025-0342` hết hạn 3 ngày; `nv005` — `LAP-0610`, cert bị thu hồi. Seed khác
bảng 3.7 → test đỏ, báo Q (không sửa seed/test cho khớp). Mỗi test dùng `reset` (seed sạch).
"""

from typing import Any

import httpx
import pytest
from app.core.clock import FakeClock
from app.executor.wiring import build_write_registry
from app.settings import Settings
from app.tools.registry import ToolContractError
from app.tools.wiring import build_read_registry
from pydantic import SecretStr
from tests.e2e.mock_server import MockServer

pytestmark = pytest.mark.asyncio

# (tool, input, endpoint mock theo bảng 11.4, body)
WRITES: list[tuple[str, dict[str, str], str, dict[str, str]]] = [
    ("renew_vpn_cert", {"user_id": "nv001", "device_id": "LAP-0342"}, "/vpn/certs/nv001/renew",
     {"device_id": "LAP-0342"}),
    ("reissue_vpn_access", {"user_id": "nv005", "device_id": "LAP-0610"}, "/vpn/access/nv005/reissue",
     {"device_id": "LAP-0610"}),
    ("revoke_vpn_cert", {"user_id": "nv001", "serial": "VPN-2025-0342"}, "/vpn/certs/nv001/revoke",
     {"serial": "VPN-2025-0342"}),
]  # fmt: skip
IDS = [w[0] for w in WRITES]

# Bảng 3.7: (serial, máy, trạng thái) chứng chỉ của từng người trong seed
SEED_CERTS = {
    "nv001": [("VPN-2025-0342", "LAP-0342", "expired")],
    "nv005": [("VPN-2025-0610", "LAP-0610", "revoked")],
}


def _write_settings(server: MockServer, executor_token: str) -> Settings:
    return Settings(_env_file=None, mock_url=server.url, svc_executor_token=SecretStr(executor_token))  # type: ignore[call-arg]


async def _certs(server: MockServer, user_id: str) -> list[tuple[str, str, str]]:
    """Đọc lại chứng chỉ bằng registry ĐỌC (token svc_agent) — quan sát ở hệ thống đích, không tin kết quả lời gọi ghi."""
    registry, http = build_read_registry(server.settings(), FakeClock())
    try:
        result = await registry.call("check_vpn_cert_expiry", {"user_id": user_id}, caller_step="B6")
    finally:
        await http.aclose()
    assert result.error is None, result.error
    rows = result.data.root if result.data is not None else []
    return sorted((c.serial, c.device_id, c.status) for c in rows)


@pytest.mark.parametrize(("tool", "args", "path", "body"), WRITES, ids=IDS)
async def test_h25_write_registry_with_agent_token_gets_403_nothing_changes(
    mock_server: MockServer, reset: None, tool: str, args: dict[str, str], path: str, body: dict[str, str]
) -> None:
    """h25: registry ghi (adapter `vpn_write`) mang token svc_agent → mock 403 → `ToolContractError` có "403";
    chứng chỉ của người đó y như seed (không cấp mới, không thu hồi cũ)."""
    user = args["user_id"]
    assert await _certs(mock_server, user) == SEED_CERTS[user]
    registry, http = build_write_registry(_write_settings(mock_server, mock_server.agent), FakeClock())
    try:
        with pytest.raises(ToolContractError, match="403"):
            await registry.call(tool, args, caller_step="B17")
    finally:
        await http.aclose()
    assert await _certs(mock_server, user) == SEED_CERTS[user]


@pytest.mark.parametrize(("tool", "args", "path", "body"), WRITES, ids=IDS)
async def test_h25_mock_write_endpoints_answer_403_to_agent_token(
    mock_server: MockServer, reset: None, tool: str, args: dict[str, str], path: str, body: dict[str, str]
) -> None:
    """h25 ở tầng HTTP ("Mock 403"): POST thẳng endpoint ghi của bảng 11.4 với header token svc_agent → đúng mã 403
    (token được nhận ra nhưng không có quyền ghi — khác 401 token lạ); hệ thống đích không đổi."""
    async with httpx.AsyncClient(base_url=mock_server.url, headers={"X-Service-Token": mock_server.agent}) as client:
        resp = await client.post(path, json=body)
    assert resp.status_code == 403, resp.text
    assert await _certs(mock_server, args["user_id"]) == SEED_CERTS[args["user_id"]]


@pytest.mark.parametrize(("tool", "args", "path", "body"), WRITES, ids=IDS)
async def test_h25_control_executor_token_writes(
    mock_server: MockServer, reset: None, tool: str, args: dict[str, str], path: str, body: dict[str, str]
) -> None:
    """h25 đối chứng: cùng lời gọi, token svc_executor đúng → thành công và hệ thống đích đổi đúng như 11.4 — chứng minh
    403 ở trên là do token, không do tham số/seed."""
    user = args["user_id"]
    settings = _write_settings(mock_server, mock_server.executor)
    registry, http = build_write_registry(settings, FakeClock())
    try:
        result = await registry.call(tool, args, caller_step="B17")
    finally:
        await http.aclose()
    assert result.error is None, result.error
    cert: Any = result.data
    after = await _certs(mock_server, user)
    old_serials = {s for s, _, _ in SEED_CERTS[user]}
    if tool == "revoke_vpn_cert":
        assert cert.serial == args["serial"] and cert.status == "revoked"
        assert after == [(args["serial"], "LAP-0342", "revoked")]
    else:
        assert cert.device_id == args["device_id"] and cert.status == "valid"
        assert cert.serial not in old_serials
        assert (cert.serial, args["device_id"], "valid") in after
        assert old_serials <= {s for s, _, _ in after} and len(after) == len(SEED_CERTS[user]) + 1
