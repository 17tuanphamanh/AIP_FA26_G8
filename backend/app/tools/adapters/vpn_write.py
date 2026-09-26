"""Ghi VPN (chỉ B17, token svc_executor): gia hạn, cấp lại, thu hồi chứng chỉ (hoàn tác)."""

from app.tools.adapters.http import ServiceHttp, seg
from app.tools.models import RevokeCertIn, UserDeviceRequiredIn
from app.tools.registry import Handler


def write_handlers(http: ServiceHttp) -> dict[str, Handler]:
    async def renew_vpn_cert(a: UserDeviceRequiredIn, timeout: float) -> object:
        return await http.post(f"/vpn/certs/{seg(a.user_id)}/renew", timeout=timeout,
                               json={"device_id": a.device_id})  # fmt: skip

    async def reissue_vpn_access(a: UserDeviceRequiredIn, timeout: float) -> object:
        return await http.post(f"/vpn/access/{seg(a.user_id)}/reissue", timeout=timeout,
                               json={"device_id": a.device_id})  # fmt: skip

    async def revoke_vpn_cert(a: RevokeCertIn, timeout: float) -> object:
        return await http.post(f"/vpn/certs/{seg(a.user_id)}/revoke", timeout=timeout,
                               json={"serial": a.serial})  # fmt: skip

    return {
        "renew_vpn_cert": renew_vpn_cert,
        "reissue_vpn_access": reissue_vpn_access,
        "revoke_vpn_cert": revoke_vpn_cert,
    }
