"""Đọc AD: thuộc tính người dùng, trạng thái tài khoản, lịch sử khoá, đặc quyền, chuỗi quản lý;
`AdIdentityProvider` cho đăng nhập (P6)."""

import httpx
from pydantic import ValidationError

from app.tools.adapters.http import ServiceHttp, seg
from app.tools.models import AdUser, UserAccountIn, UserIn
from app.tools.registry import Handler, ToolRegistry


def read_handlers(http: ServiceHttp) -> dict[str, Handler]:
    async def ad_get_user(a: UserIn, timeout: float) -> object:
        return await http.get(f"/ad/users/{seg(a.user_id)}", timeout=timeout)

    async def check_account_status(a: UserAccountIn, timeout: float) -> object:
        return await http.get(f"/ad/users/{seg(a.user_id)}", timeout=timeout,
                              params={"account_type": a.account_type})  # fmt: skip

    async def check_lockout_history(a: UserIn, timeout: float) -> object:
        return await http.get(f"/ad/users/{seg(a.user_id)}/lockouts", timeout=timeout)

    async def check_privilege_level(a: UserAccountIn, timeout: float) -> object:
        return await http.get(f"/ad/users/{seg(a.user_id)}/privilege", timeout=timeout,
                              params={"account_type": a.account_type})  # fmt: skip

    async def check_manager_chain(a: UserIn, timeout: float) -> object:
        return await http.get(f"/ad/users/{seg(a.user_id)}/manager-chain", timeout=timeout)

    return {
        "ad_get_user": ad_get_user,
        "check_account_status": check_account_status,
        "check_lockout_history": check_lockout_history,
        "check_privilege_level": check_privilege_level,
        "check_manager_chain": check_manager_chain,
    }


class IdentityUnavailableError(Exception):
    """AD không trả lời được — main.create_app đổi sang `auth.ports.IdentityUnavailable`."""


class PasswordChangeRequiredError(Exception):
    """AD: mật khẩu tạm đúng, phải đổi — main.create_app đổi sang `auth.ports.PasswordChangeRequired`."""


def _detail(response: httpx.Response) -> object:
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("detail") if isinstance(body, dict) else None


class AdIdentityProvider:
    """Khớp `auth.ports.IdentityProvider` theo cấu trúc (tools không import auth — 01 mục 4.2).

    - `authenticate`: POST `/ad/authenticate` MỘT lần, không retry (AD thật có thể đếm hai lần
      sai), KHÔNG qua ToolRegistry — không phải tool của P5, và mật khẩu không được lọt vào
      input/span của registry. 401 → None; 403 `password_change_required` → `password_change` (trạng thái, không phải
      AD sập); 403 `account_locked` (AD khoá) → None như sai mật khẩu (không lộ trạng thái khoá); lỗi khác → `unavailable`.
    - `get_user`: qua registry (`ad_get_user`, retry + breaker như B1) — B01 mục 3.
    """

    def __init__(
        self,
        http: ServiceHttp,
        registry: ToolRegistry,
        *,
        timeout: float,
        unavailable: type[Exception] = IdentityUnavailableError,
        password_change: type[Exception] = PasswordChangeRequiredError,
    ) -> None:
        self._http = http
        self._registry = registry
        self._timeout = timeout
        self._unavailable = unavailable
        self._password_change = password_change

    async def authenticate(self, username: str, password: str) -> AdUser | None:
        try:
            raw = await self._http.post(
                "/ad/authenticate", timeout=self._timeout,
                json={"username": username, "password": password},
            )  # fmt: skip
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                return None
            if status == 403 and _detail(e.response) == "password_change_required":
                raise self._password_change("AD authenticate: cần đổi mật khẩu") from None
            if status == 403 and _detail(e.response) == "account_locked":
                return None
            raise self._unavailable(f"AD authenticate: HTTP {e.response.status_code}") from None
        except httpx.HTTPError as e:
            raise self._unavailable(f"AD authenticate: {type(e).__name__}") from None
        try:
            return AdUser.model_validate(raw)
        except ValidationError:
            raise self._unavailable("AD authenticate: phản hồi sai schema") from None

    async def get_user(self, user_id: str) -> AdUser | None:
        result = await self._registry.call_internal(
            "ad_get_user", UserIn(user_id=user_id), caller_step="B1"
        )
        if result.error is not None:
            raise self._unavailable(f"AD get_user: {result.error}")
        if result.empty:
            return None
        assert isinstance(result.data, AdUser)
        return result.data
