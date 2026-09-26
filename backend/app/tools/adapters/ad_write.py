"""Ghi AD (chỉ B17, token svc_executor): đặt lại mật khẩu, mở khoá, khoá (hoàn tác)."""

from app.tools.adapters.http import ServiceHttp, seg
from app.tools.models import LockIn, UserAccountIn
from app.tools.registry import Handler


def write_handlers(http: ServiceHttp) -> dict[str, Handler]:
    async def reset_password(a: UserAccountIn, timeout: float) -> object:
        return await http.post(f"/ad/users/{seg(a.user_id)}/reset-password", timeout=timeout,
                               json={"account_type": a.account_type})  # fmt: skip

    async def unlock_account(a: UserAccountIn, timeout: float) -> object:
        return await http.post(f"/ad/users/{seg(a.user_id)}/unlock", timeout=timeout,
                               json={"account_type": a.account_type})  # fmt: skip

    async def lock_account(a: LockIn, timeout: float) -> object:
        return await http.post(f"/ad/users/{seg(a.user_id)}/lock", timeout=timeout,
                               json={"account_type": a.account_type, "reason": a.reason})  # fmt: skip

    return {
        "reset_password": reset_password,
        "unlock_account": unlock_account,
        "lock_account": lock_account,
    }
