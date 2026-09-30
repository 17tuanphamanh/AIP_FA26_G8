"""AdIdentityProvider (respx): 401 → None; lỗi/timeout/sai schema → IdentityUnavailable; không retry
authenticate; get_user qua registry (404 → None, lỗi sau retry → IdentityUnavailable)."""

import logging
import secrets

import httpx
import pytest
import respx
from app.auth.ports import IdentityUnavailable
from app.core.clock import FakeClock
from app.settings import Settings
from app.tools.adapters.ad_read import AdIdentityProvider
from app.tools.specs import READ_TIMEOUT_S
from app.tools.wiring import build_read_registry
from pydantic import SecretStr

MOCK = "http://mock.test"
USER = {
    "user_id": "nv001", "username": "an.nv", "full_name": "An", "title": "NV", "department": "finance",
    "groups": ["IT-Users"], "manager_id": "fin_head", "employment_status": "active",
    "hired_at": "2024-01-01", "is_privileged_account": False,
    "account": {"account_type": "ad", "enabled": True, "locked": False, "lock_reason": None,
                "password_last_set": "2026-09-01T00:00:00Z"},
}  # fmt: skip


@pytest.fixture
def idp() -> AdIdentityProvider:
    settings = Settings(_env_file=None, mock_url=MOCK, svc_agent_token=SecretStr(secrets.token_urlsafe(32)))  # type: ignore[call-arg]
    registry, http = build_read_registry(settings, FakeClock())
    return AdIdentityProvider(http, registry, timeout=READ_TIMEOUT_S, unavailable=IdentityUnavailable)


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_ok_and_wrong_password(idp: AdIdentityProvider) -> None:
    route = respx.post(f"{MOCK}/ad/authenticate").mock(
        side_effect=[httpx.Response(200, json=USER), httpx.Response(401, json={"detail": "x"})]
    )
    user = await idp.authenticate("an.nv", "Demo@2026!")
    assert user is not None and user.user_id == "nv001" and list(user.groups) == ["IT-Users"]
    assert await idp.authenticate("an.nv", "sai") is None
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "response",
    [httpx.Response(500), httpx.Response(503), httpx.Response(200, json={"user_id": "x"}),
     httpx.ConnectTimeout("chậm")],
)  # fmt: skip
async def test_authenticate_system_errors_are_unavailable_without_retry(
    idp: AdIdentityProvider, response: httpx.Response | Exception
) -> None:
    route = respx.post(f"{MOCK}/ad/authenticate").mock(side_effect=[response])
    with pytest.raises(IdentityUnavailable):
        await idp.authenticate("an.nv", "Demo@2026!")
    assert route.call_count == 1  # không retry lần đăng nhập


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_never_logs_password(
    idp: AdIdentityProvider, caplog: pytest.LogCaptureFixture
) -> None:
    respx.post(f"{MOCK}/ad/authenticate").mock(return_value=httpx.Response(500))
    with caplog.at_level(logging.DEBUG), pytest.raises(IdentityUnavailable) as exc:
        await idp.authenticate("an.nv", "Canary-Pw-77x")
    assert "Canary-Pw-77x" not in caplog.text and "Canary-Pw-77x" not in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_get_user_via_registry(idp: AdIdentityProvider) -> None:
    respx.get(f"{MOCK}/ad/users/nv001").mock(return_value=httpx.Response(200, json=USER))
    respx.get(f"{MOCK}/ad/users/ghost").mock(return_value=httpx.Response(404, json={"detail": "not_found"}))
    down = respx.get(f"{MOCK}/ad/users/nv002").mock(return_value=httpx.Response(500))
    user = await idp.get_user("nv001")
    assert user is not None and user.manager_id == "fin_head"
    assert await idp.get_user("ghost") is None
    with pytest.raises(IdentityUnavailable):
        await idp.get_user("nv002")
    assert down.call_count == 3  # TOOL_RETRY=2 → 3 lần (đọc thì có retry)
