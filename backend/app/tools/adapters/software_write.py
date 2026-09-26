"""Ghi phần mềm (chỉ B17, token svc_executor): cài, gỡ (hoàn tác), cấp license trả phí."""

from app.tools.adapters.http import ServiceHttp, seg
from app.tools.models import AssignLicenseIn, InstallIn
from app.tools.registry import Handler


def write_handlers(http: ServiceHttp) -> dict[str, Handler]:
    async def install_software(a: InstallIn, timeout: float) -> object:
        return await http.post(f"/software/installed/{seg(a.device_id)}/install", timeout=timeout,
                               json={"software_name": a.software_name})  # fmt: skip

    async def uninstall_software(a: InstallIn, timeout: float) -> object:
        return await http.post(f"/software/installed/{seg(a.device_id)}/uninstall", timeout=timeout,
                               json={"software_name": a.software_name})  # fmt: skip

    async def assign_paid_license(a: AssignLicenseIn, timeout: float) -> object:
        return await http.post(f"/software/licenses/{seg(a.software_name)}/assign", timeout=timeout,
                               json={"user_id": a.user_id})  # fmt: skip

    return {
        "install_software": install_software,
        "uninstall_software": uninstall_software,
        "assign_paid_license": assign_paid_license,
    }
