"""Đọc danh mục phần mềm: mục danh mục, license, phần mềm đã cài."""

from app.tools.adapters.http import ServiceHttp, seg
from app.tools.models import DeviceIn, SoftwareIn
from app.tools.registry import Handler


def read_handlers(http: ServiceHttp) -> dict[str, Handler]:
    async def check_catalog_entry(a: SoftwareIn, timeout: float) -> object:
        return await http.get(f"/software/catalog/{seg(a.software_name)}", timeout=timeout)

    async def check_license_available(a: SoftwareIn, timeout: float) -> object:
        return await http.get(f"/software/licenses/{seg(a.software_name)}", timeout=timeout)

    async def check_installed_list(a: DeviceIn, timeout: float) -> object:
        return await http.get(f"/software/installed/{seg(a.device_id)}", timeout=timeout)

    return {
        "check_catalog_entry": check_catalog_entry,
        "check_license_available": check_license_available,
        "check_installed_list": check_installed_list,
    }
