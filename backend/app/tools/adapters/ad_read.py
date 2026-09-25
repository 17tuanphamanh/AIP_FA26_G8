"""Đọc AD: thuộc tính người dùng, trạng thái tài khoản, lịch sử khoá, đặc quyền, chuỗi quản lý."""

from app.tools.adapters.http import ServiceHttp, seg
from app.tools.models import UserAccountIn, UserIn
from app.tools.registry import Handler


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
