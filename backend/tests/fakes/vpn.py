"""VPN giả cho test đơn vị B6 (PLAN-3f S5, S6) — ĐỌC `mock_services/seed.json` (không chép tay dữ liệu) và trả JSON đúng như
mock thật (`mock_services/app/vpn.py`): người dùng lạ → 404; `/vpn/devices/{id}` không có → 404; cert chỉ của chính người
gửi, sắp theo `issued_at` giảm dần, `status` revoked/expired/valid, `days_to_expiry` làm tròn ngày; kết nối mới nhất trước,
≤ 10. Ngày tương đối trong seed tính từ đồng hồ lúc dựng (`FakeClock`).

Đếm lời gọi ở NƠI NHẬN (`calls`, quy ước 3.9). `fail(tool, status, times)` → lỗi HTTP (500 → registry retry → E2);
`latency(seconds)` → mỗi lời gọi ngủ thật (f14: song song). Bản với mock thật: `tests/e2e/test_b06_vs_mock.py`.
"""

import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from app.core.clock import Clock
from app.tools.models import UserDeviceIn, UserIn

SEED = Path(__file__).resolve().parents[3] / "mock_services" / "seed.json"
CONNECTION_LIMIT = 10


def _status(code: int, path: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"http://mock.test{path}")
    return httpx.HTTPStatusError(str(code), request=request, response=httpx.Response(code, request=request))


class SeedVpn:
    def __init__(self, clock: Clock, seed: Path = SEED) -> None:
        data = json.loads(seed.read_text(encoding="utf-8"))
        now = clock.now()
        self.clock = clock
        self.users = {u["user_id"] for u in data["users"]}
        self.devices = {
            d["device_id"]: {
                "device_id": d["device_id"], "owner_id": d["owner_id"], "kind": d["kind"], "os": d["os"],
                "registered": d["registered"],
                "registered_at": _iso(now - timedelta(days=d["registered_days_ago"]))
                if d.get("registered_days_ago") is not None else None,
            }
            for d in data["devices"]
        }  # fmt: skip
        self.certs = [
            {"serial": c["serial"], "user_id": c["user_id"], "device_id": c["device_id"],
             "issued_at": now - timedelta(days=c["issued_days_ago"]),
             "expires_at": now + timedelta(days=c["expires_in_days"]), "revoked": bool(c.get("revoked"))}
            for c in data["certs"]
        ]  # fmt: skip
        self.connections = [
            {"user_id": c["user_id"], "device_id": c["device_id"], "at": now - timedelta(days=c["days_ago"]),
             "result": c["result"], "error_code": c.get("error_code")}
            for c in data["connections"]
        ]  # fmt: skip
        self.calls: Counter[str] = Counter()
        self._fail: dict[str, list[int]] = {}
        self.latency_s = 0.0

    def fail(self, tool: str, status: int = 500, times: int = 99) -> "SeedVpn":
        self._fail.setdefault(tool, []).extend([status] * times)
        return self

    async def _enter(self, tool: str, path: str) -> None:
        self.calls[tool] += 1
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        faults = self._fail.get(tool)
        if faults:
            raise _status(faults.pop(0), path)

    def _user(self, user_id: str, path: str) -> None:
        if user_id not in self.users:
            raise _status(404, path)

    async def check_device_registered(self, a: UserDeviceIn, timeout: float) -> object:
        if a.device_id is None:
            path = f"/vpn/devices?owner_id={a.user_id}"
            await self._enter("check_device_registered", path)
            self._user(a.user_id, path)
            return sorted((d for d in self.devices.values() if d["owner_id"] == a.user_id),
                          key=lambda d: d["device_id"])  # fmt: skip
        path = f"/vpn/devices/{a.device_id}"
        await self._enter("check_device_registered", path)
        dev = self.devices.get(a.device_id)
        if dev is None:
            raise _status(404, path)
        return [dev]

    async def check_vpn_cert_expiry(self, a: UserDeviceIn, timeout: float) -> object:
        path = f"/vpn/certs/{a.user_id}"
        await self._enter("check_vpn_cert_expiry", path)
        self._user(a.user_id, path)
        now = self.clock.now()
        rows = [c for c in self.certs if c["user_id"] == a.user_id and a.device_id in (None, c["device_id"])]
        rows.sort(key=lambda c: c["issued_at"], reverse=True)
        return [
            {"serial": c["serial"], "device_id": c["device_id"], "issued_at": _iso(c["issued_at"]),
             "expires_at": _iso(c["expires_at"]),
             "status": "revoked" if c["revoked"] else ("expired" if c["expires_at"] <= now else "valid"),
             "days_to_expiry": round((c["expires_at"] - now) / timedelta(days=1))}
            for c in rows
        ]  # fmt: skip

    async def check_last_connection(self, a: UserIn, timeout: float) -> object:
        path = f"/vpn/connections/{a.user_id}"
        await self._enter("check_last_connection", path)
        self._user(a.user_id, path)
        rows = sorted((c for c in self.connections if c["user_id"] == a.user_id), key=lambda c: c["at"],
                      reverse=True)[:CONNECTION_LIMIT]  # fmt: skip
        return [{"at": _iso(c["at"]), "device_id": c["device_id"], "result": c["result"],
                 "error_code": c["error_code"]} for c in rows]  # fmt: skip

    def handlers(self) -> dict[str, Any]:
        return {
            "check_device_registered": self.check_device_registered,
            "check_vpn_cert_expiry": self.check_vpn_cert_expiry,
            "check_last_connection": self.check_last_connection,
        }


def _iso(at: datetime) -> str:
    return at.isoformat()
