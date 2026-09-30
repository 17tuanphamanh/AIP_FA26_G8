"""Executor giả cho test B17 (3h): `transaction_log` trong bộ nhớ + hệ thống ghi VPN giả sau registry THẬT (retries=0,
404/409 = dữ liệu, 5xx = lỗi — đúng `tools/registry.py`). Đếm ở NƠI NHẬN (handler), không đếm bằng biến của code được test
(quy ước 3.9)."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
from app.core.clock import FakeClock
from app.tools.breaker import BreakerBoard
from app.tools.models import RevokeCertIn, UserDeviceRequiredIn
from app.tools.registry import ToolRegistry


@dataclass
class MemoryTxLog:
    rows: list[dict[str, Any]] = field(default_factory=list)

    async def has_begun(self, ticket_id: str) -> bool:
        return any(r["ticket_id"] == ticket_id and r["status"] == "begun" for r in self.rows)

    async def begin(self, ticket_id: str, turn_id: str, step_name: str) -> None:
        self.rows.append({"ticket_id": ticket_id, "turn_id": turn_id, "step_name": step_name, "status": "begun",
                          "detail": None})  # fmt: skip

    async def undone(self, ticket_id: str, turn_id: str, step_name: str) -> None:
        self.rows.append({"ticket_id": ticket_id, "turn_id": turn_id, "step_name": step_name, "status": "undone",
                          "detail": None})  # fmt: skip

    async def undo_failed(self, ticket_id: str, turn_id: str, step_name: str, detail: str) -> None:
        self.rows.append({"ticket_id": ticket_id, "turn_id": turn_id, "step_name": step_name, "status": "undo_failed",
                          "detail": detail})  # fmt: skip

    def statuses(self) -> list[tuple[str, str]]:
        return [(r["step_name"], r["status"]) for r in self.rows]


def http_error(code: int, detail: str = "injected_fault") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://mock.test/vpn/x")
    return httpx.HTTPStatusError(str(code), request=request, response=httpx.Response(code, json={"detail": detail},
                                                                                      request=request))  # fmt: skip


type Fault = Callable[[], BaseException] | None


class FakeVpnWrites:
    """Hệ thống ghi VPN giả: cấp cert mới hạn 365 ngày (như mock), `faults[tool]` → ném lỗi thay vì trả lời."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls: Counter[str] = Counter()
        self.faults: dict[str, Fault] = {}
        self.slow: dict[str, timedelta] = {}  # tool → tua đồng hồ khi được gọi (lời gọi "tốn" thời gian của lượt)
        self.serial = 0

    def _issue(self, a: UserDeviceRequiredIn) -> dict[str, Any]:
        self.serial += 1
        now: datetime = self.clock.now()
        return {"serial": f"VPN-NEW-{self.serial:04d}", "device_id": a.device_id, "issued_at": now.isoformat(),
                "expires_at": (now + timedelta(days=365)).isoformat(), "status": "valid", "days_to_expiry": 365}  # fmt: skip

    def handlers(self) -> dict[str, Any]:
        async def renew_vpn_cert(a: UserDeviceRequiredIn, timeout: float) -> object:
            return self._hit("renew_vpn_cert", lambda: self._issue(a))

        async def reissue_vpn_access(a: UserDeviceRequiredIn, timeout: float) -> object:
            return self._hit("reissue_vpn_access", lambda: self._issue(a))

        async def revoke_vpn_cert(a: RevokeCertIn, timeout: float) -> object:
            now = self.clock.now().isoformat()
            return self._hit("revoke_vpn_cert", lambda: {"serial": a.serial, "device_id": "LAP-0342", "issued_at": now,
                                                         "expires_at": now, "status": "revoked", "days_to_expiry": 0})  # fmt: skip

        return {"renew_vpn_cert": renew_vpn_cert, "reissue_vpn_access": reissue_vpn_access,
                "revoke_vpn_cert": revoke_vpn_cert}  # fmt: skip

    def _hit(self, tool: str, ok: Callable[[], object]) -> object:
        self.calls[tool] += 1
        if tool in self.slow:
            self.clock.advance(self.slow[tool])
        fault = self.faults.get(tool)
        if fault is not None:
            raise fault()
        return ok()

    def registry(self) -> ToolRegistry:
        breakers = BreakerBoard(self.clock, failure_threshold=5, window_seconds=60, open_seconds=30)
        return ToolRegistry(self.handlers(), breakers=breakers, clock=self.clock)
