"""Mock VPN gateway: thiết bị, chứng chỉ, lịch sử kết nối; ghi: gia hạn, cấp lại, thu hồi (P5 mục 7)."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.ad import get_user, mock_state
from app.security import require_read, require_write
from app.state import Cert, Connection, Device, MockState

router = APIRouter(prefix="/vpn")

CERT_VALID_DAYS = 365  # chứng chỉ mới cấp sống 1 năm [Suy luận — chỉ là dữ liệu mock]
CONNECTION_LIMIT = 10


def cert_view(state: MockState, cert: Cert) -> dict[str, Any]:
    now = state.now()
    status = "revoked" if cert.revoked else ("expired" if cert.expires_at <= now else "valid")
    return {
        "serial": cert.serial,
        "device_id": cert.device_id,
        "issued_at": cert.issued_at,
        "expires_at": cert.expires_at,
        "status": status,
        # làm tròn tới ngày gần nhất: seed "hết hạn 3 ngày trước" đọc vài giây sau khi nạp vẫn là -3
        "days_to_expiry": round((cert.expires_at - now) / timedelta(days=1)),
    }


def device_view(d: Device) -> dict[str, Any]:
    return {
        "device_id": d.device_id,
        "owner_id": d.owner_id,
        "kind": d.kind,
        "os": d.os,
        "registered": d.registered,
        "registered_at": d.registered_at,
    }


@router.get("/devices", dependencies=[Depends(require_read)])
async def devices_of(owner_id: str, request: Request) -> list[dict[str, Any]]:
    """Thiết bị của một người — B6 tự tìm máy khi người dùng chưa nêu device_id (TC06)."""
    state = mock_state(request)
    get_user(state, owner_id)
    rows = sorted((d for d in state.devices.values() if d.owner_id == owner_id),
                  key=lambda d: d.device_id)  # fmt: skip
    return [device_view(d) for d in rows]


@router.get("/devices/{device_id}", dependencies=[Depends(require_read)])
async def device(device_id: str, request: Request) -> dict[str, Any]:
    d = mock_state(request).devices.get(device_id)
    if d is None:
        raise HTTPException(404, "not_found")
    return device_view(d)


@router.get("/certs/{user_id}", dependencies=[Depends(require_read)])
async def certs(user_id: str, request: Request, device_id: str | None = None) -> list[dict[str, Any]]:
    state = mock_state(request)
    get_user(state, user_id)
    rows = [c for c in state.certs if c.user_id == user_id
            and (device_id is None or c.device_id == device_id)]  # fmt: skip
    rows.sort(key=lambda c: c.issued_at, reverse=True)
    return [cert_view(state, c) for c in rows]


@router.get("/connections/{user_id}", dependencies=[Depends(require_read)])
async def connections(user_id: str, request: Request) -> list[dict[str, Any]]:
    state = mock_state(request)
    get_user(state, user_id)
    # cùng mốc `at` (đồng hồ test đứng yên, hoặc hai lần gọi trong cùng tick): lần ghi sau xếp trước
    indexed = [(c.at, i, c) for i, c in enumerate(state.connections) if c.user_id == user_id]
    rows = [c for _, _, c in sorted(indexed, key=lambda t: (t[0], t[1]), reverse=True)[:CONNECTION_LIMIT]]
    return [
        {"at": c.at, "device_id": c.device_id, "result": c.result, "error_code": c.error_code}
        for c in rows
    ]


# ---- Ghi (chỉ svc_executor) -------------------------------------------------------------------


class DeviceBody(BaseModel):
    device_id: str = Field(min_length=1)


class RevokeBody(BaseModel):
    serial: str = Field(min_length=1)


def _issue(request: Request, user_id: str, device_id: str) -> dict[str, Any]:
    state = mock_state(request)
    get_user(state, user_id)
    dev = state.devices.get(device_id)
    if dev is None or dev.owner_id != user_id:
        raise HTTPException(404, "not_found")
    if not dev.registered:
        # Gateway thật cũng từ chối cấp chứng chỉ cho máy chưa đăng ký (R17 chặn trước ở M5).
        raise HTTPException(409, "device_not_registered")
    now = state.now()
    for old in state.certs:
        if old.user_id == user_id and old.device_id == device_id and not old.revoked:
            old.revoked = True
    cert = Cert(state.next_serial(), user_id, device_id, now, now + timedelta(days=CERT_VALID_DAYS),
                False)  # fmt: skip
    state.certs.append(cert)
    return cert_view(state, cert)


class ConnectBody(BaseModel):
    user_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)


def _connect_outcome(state: MockState, user_id: str, device: Device) -> str | None:
    """Mã lỗi của lần kết nối thử theo trạng thái thật; None = kết nối được."""
    if not device.registered:
        return "DEVICE_NOT_REGISTERED"
    certs = [c for c in state.certs if c.user_id == user_id and c.device_id == device.device_id]
    if not certs:
        return "NO_CERT"
    statuses = {cert_view(state, c)["status"] for c in certs}
    if "valid" in statuses:
        return None
    return "CERT_EXPIRED" if "expired" in statuses else "CERT_REVOKED"  # chỉ còn chứng chỉ đã thu hồi


@router.post("/connect", dependencies=[Depends(require_write)])
async def connect(body: ConnectBody, request: Request) -> dict[str, Any]:
    """Kết nối thử một máy vào VPN; kết quả (cả thất bại) ghi vào lịch sử `/vpn/connections`."""
    state = mock_state(request)
    get_user(state, body.user_id)
    dev = state.devices.get(body.device_id)
    if dev is None or dev.owner_id != body.user_id:
        raise HTTPException(404, "not_found")
    error_code = _connect_outcome(state, body.user_id, dev)
    result = "success" if error_code is None else "failed"
    conn = Connection(body.user_id, body.device_id, state.now(), result, error_code)
    state.connections.append(conn)
    return {"at": conn.at, "user_id": conn.user_id, "device_id": conn.device_id, "result": result,
            "error_code": error_code}  # fmt: skip


@router.post("/certs/{user_id}/renew", dependencies=[Depends(require_write)])
async def renew(user_id: str, body: DeviceBody, request: Request) -> dict[str, Any]:
    return _issue(request, user_id, body.device_id)


@router.post("/access/{user_id}/reissue", dependencies=[Depends(require_write)])
async def reissue(user_id: str, body: DeviceBody, request: Request) -> dict[str, Any]:
    return _issue(request, user_id, body.device_id)


@router.post("/certs/{user_id}/revoke", dependencies=[Depends(require_write)])
async def revoke(user_id: str, body: RevokeBody, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    cert = next((c for c in state.certs if c.user_id == user_id and c.serial == body.serial), None)
    if cert is None:
        raise HTTPException(404, "not_found")
    cert.revoked = True
    return cert_view(state, cert)
