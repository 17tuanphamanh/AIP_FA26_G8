"""Ghi file server (chỉ B17, token svc_executor): cấp, thu hồi, gia hạn, khôi phục hạn quyền."""

from app.tools.adapters.http import ServiceHttp, seg
from app.tools.models import ExtendIn, GrantIn, RestoreExpiryIn, UserPathIn
from app.tools.registry import Handler


def write_handlers(http: ServiceHttp) -> dict[str, Handler]:
    def body(a: UserPathIn | GrantIn) -> dict[str, object]:
        return a.model_dump(mode="json", exclude={"user_id"})

    async def grant_permission(a: GrantIn, timeout: float) -> object:
        return await http.post(f"/files/permissions/{seg(a.user_id)}/grant", timeout=timeout, json=body(a))

    async def revoke_permission(a: UserPathIn, timeout: float) -> object:
        return await http.post(f"/files/permissions/{seg(a.user_id)}/revoke", timeout=timeout, json=body(a))

    async def extend_permission(a: ExtendIn, timeout: float) -> object:
        return await http.post(f"/files/permissions/{seg(a.user_id)}/extend", timeout=timeout, json=body(a))

    async def restore_permission_expiry(a: RestoreExpiryIn, timeout: float) -> object:
        return await http.post(f"/files/permissions/{seg(a.user_id)}/restore-expiry", timeout=timeout,
                               json=body(a))  # fmt: skip

    return {
        "grant_permission": grant_permission,
        "revoke_permission": revoke_permission,
        "extend_permission": extend_permission,
        "restore_permission_expiry": restore_permission_expiry,
    }
