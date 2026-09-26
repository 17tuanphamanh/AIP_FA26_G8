"""Đọc VPN: thiết bị, chứng chỉ, lịch sử kết nối."""

from app.tools.adapters.http import ServiceHttp, seg
from app.tools.models import UserDeviceIn, UserIn
from app.tools.registry import Handler


def read_handlers(http: ServiceHttp) -> dict[str, Handler]:
    async def check_device_registered(a: UserDeviceIn, timeout: float) -> object:
        if a.device_id is None:  # người dùng chưa nêu máy → mọi máy của họ (TC06 tự suy device_id)
            return await http.get("/vpn/devices", timeout=timeout, params={"owner_id": a.user_id})
        return [await http.get(f"/vpn/devices/{seg(a.device_id)}", timeout=timeout)]

    async def check_vpn_cert_expiry(a: UserDeviceIn, timeout: float) -> object:
        return await http.get(f"/vpn/certs/{seg(a.user_id)}", timeout=timeout,
                              params={"device_id": a.device_id})  # fmt: skip

    async def check_last_connection(a: UserIn, timeout: float) -> object:
        return await http.get(f"/vpn/connections/{seg(a.user_id)}", timeout=timeout)

    return {
        "check_device_registered": check_device_registered,
        "check_vpn_cert_expiry": check_vpn_cert_expiry,
        "check_last_connection": check_last_connection,
    }
