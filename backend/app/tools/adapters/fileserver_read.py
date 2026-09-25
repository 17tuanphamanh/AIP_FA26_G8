"""Đọc file server: quyền hiện có, độ nhạy thư mục."""

from app.tools.adapters.http import ServiceHttp, path, seg
from app.tools.models import ResourceIn, UserResourceIn
from app.tools.registry import Handler


def read_handlers(http: ServiceHttp) -> dict[str, Handler]:
    async def check_current_permissions(a: UserResourceIn, timeout: float) -> object:
        return await http.get(f"/files/permissions/{seg(a.user_id)}", timeout=timeout,
                              params={"resource_path": a.resource_path})  # fmt: skip

    async def check_resource_sensitivity(a: ResourceIn, timeout: float) -> object:
        return await http.get(f"/files/resources/{path(a.resource_path)}", timeout=timeout)

    return {
        "check_current_permissions": check_current_permissions,
        "check_resource_sensitivity": check_resource_sensitivity,
    }
