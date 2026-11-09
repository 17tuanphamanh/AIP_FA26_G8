"""Chặng mock-ad với mock THẬT (HTTP, tiến trình riêng): backend đọc được `email` AD (notify-email dùng `AdUser.email`); khoá AD
→ `AdIdentityProvider.authenticate` trả None (như sai mật khẩu, không phải AD sập); reset SMS làm mật khẩu cũ hỏng ngay.

Mật khẩu tạm không bao giờ rời mock qua API nên không thử được ở đây — nhánh 403 `password_change_required` có test respx ở
`unit/test_reset_sms_backend.py` và test mock ở `mock_services/tests/test_mock_ad.py`.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from app.auth.ports import IdentityUnavailable, PasswordChangeRequired
from app.core.clock import FakeClock
from app.tools.adapters.ad_read import AdIdentityProvider
from app.tools.specs import READ_TIMEOUT_S
from app.tools.wiring import build_read_registry
from tests.e2e.mock_server import REPO, MockServer
from tests.fakes.demo import DEMO_PASSWORD

# mock con kế thừa env của máy: có seed.local.json thì email của nv001 có thể đã bị nạp đè
LOCAL = Path(REPO / "mock_services" / "seed.local.json")


@pytest_asyncio.fixture
async def idp(mock_server: MockServer, reset: None) -> AsyncIterator[AdIdentityProvider]:
    registry, http = build_read_registry(mock_server.settings(), FakeClock())
    try:
        yield AdIdentityProvider(http, registry, timeout=READ_TIMEOUT_S, unavailable=IdentityUnavailable,
                                 password_change=PasswordChangeRequired)  # fmt: skip
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_backend_reads_ad_email_from_mock(idp: AdIdentityProvider) -> None:
    user = await idp.get_user("nv001")
    assert user is not None and isinstance(user.email, str) and "@" in user.email
    if not LOCAL.exists():
        assert user.email == "nv001@demo-corp.local"
    logged = await idp.authenticate("an.nv", DEMO_PASSWORD)
    assert logged is not None and logged.email == user.email


@pytest.mark.asyncio
async def test_locked_ad_account_is_wrong_login_not_outage(idp: AdIdentityProvider) -> None:
    assert await idp.authenticate("mai.tt", DEMO_PASSWORD) is None  # hr_head: AD khoá trong seed → 403 account_locked


@pytest.mark.asyncio
async def test_sms_reset_kills_old_password(idp: AdIdentityProvider, mock_server: MockServer) -> None:
    async with httpx.AsyncClient(base_url=mock_server.url, headers={"X-Service-Token": mock_server.executor}) as c:
        r = await c.post("/ad/users/nv001/reset-password", json={"account_type": "ad", "channel": "sms"})
    assert r.status_code == 200 and r.json()["sent_to"] == "0900***001" and "password" not in r.text.lower()
    assert await idp.authenticate("an.nv", DEMO_PASSWORD) is None
