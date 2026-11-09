"""Hàm dùng chung cho test T24 (phase5 mục 7, bảng 7.5) — không phải file test (tên bắt đầu `_`, pytest không gom).

- `FakeWrites`: hệ thống ghi AD / phần mềm / file server giả sau registry GHI THẬT (retries=0) — trả JSON đúng hình phản hồi của mock
  (`mock_services/app/{ad,software,fileserver}.py`). Đếm ở NƠI NHẬN (`calls`, `order`, `seen` = input đã validate), `faults[tool]` →
  ném lỗi thay vì trả lời (khuôn `tests/fakes/executor.FakeVpnWrites`). `begun_before[tool]` = lúc lời gọi tới nơi nhận, txlog đã có dòng
  `(tool, begun)` chưa.
- `action(type, ...)`: `Action` theo `config/action_metadata.yaml` + `PARAMS_BY_ACTION` (bảng 7.2).
- `executor(plans=...)`: `PlanExecutor` thật (registry ghi thật + `MemoryTxLog`).
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.clock import FakeClock
from app.domain.action import Action, FactValue
from app.executor.plan_executor import PlanExecutor
from app.executor.plans import Step
from app.settings import get_action_metadata, get_policy
from app.tools.breaker import BreakerBoard
from app.tools.models import (
    AssignLicenseIn,
    ExtendIn,
    GrantIn,
    InstallIn,
    LockIn,
    RestoreExpiryIn,
    UserAccountIn,
    UserPathIn,
)
from app.tools.registry import ToolRegistry
from tests.fakes.executor import MemoryTxLog

NOW = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # thứ Ba 10:00 giờ VN
RAW_DETAIL = "chi-tiet-KHONG-duoc-chep"
TZ = get_policy().business_hours.tz

INTENT_OF: Mapping[str, str] = {
    "renew_vpn_cert": "vpn", "reissue_vpn_access": "vpn", "check_vpn_status": "vpn",
    "reset_password": "account", "unlock_account": "account", "install_software": "software",
    "view_permissions": "access", "grant_permission": "access", "extend_permission": "access",
}  # fmt: skip

type Fault = Callable[[], BaseException]


def _defaults(action_type: str, rf: str) -> tuple[str, dict[str, FactValue], dict[str, FactValue]]:
    """(target, params, facts) mặc định theo bảng 7.2 / PARAMS_BY_ACTION."""
    if action_type in ("reset_password", "unlock_account"):
        return f"user:{rf}", {"account_type": "ad"}, {"target_user_status": "active"}
    if action_type == "install_software":
        return "device:LAP-0342", {"device_id": "LAP-0342", "software_name": "zoom"}, {
            "in_catalog": True, "license_paid": False, "requires_local_admin": False,
        }  # fmt: skip
    if action_type == "view_permissions":
        return f"user:{rf}", {}, {"target_user_status": "active"}
    if action_type == "grant_permission":
        return "folder:finance/public-reports", {
            "resource_path": "finance/public-reports", "permission_level": "read", "duration_days": 30,
        }, {"resource_sensitivity": "low", "same_department": True}  # fmt: skip
    if action_type == "extend_permission":
        return "folder:finance/Q3", {"resource_path": "finance/Q3", "duration_days": 30}, {
            "has_permission_record": True, "existing_permission_level": "read",
        }  # fmt: skip
    return "device:LAP-0342", {"device_id": "LAP-0342"}, {
        "device_registered": True, "device_owner_is_requester": True, "cert_status": "expired", "cert_days_to_expiry": -3,
        "last_connection_ok": False,
    }  # fmt: skip


def action(
    action_type: str,
    *,
    rf: str = "nv001",
    target: str | None = None,
    params: Mapping[str, FactValue] | None = None,
    facts: Mapping[str, FactValue] | None = None,
    reversible: bool | None = None,
) -> Action:
    meta = get_action_metadata().root[INTENT_OF[action_type]][action_type]
    d_target, d_params, d_facts = _defaults(action_type, rf)
    return Action(
        type=action_type, target=target if target is not None else d_target, requested_for=rf, scope=meta.scope,
        privilege_level=meta.privilege_level,
        reversible=meta.reversible if reversible is None else reversible,
        reversibility=meta.reversibility if reversible is None else ("full" if reversible else "none"),
        data_sensitivity=meta.data_sensitivity,
        params=dict(d_params if params is None else params), facts=dict(d_facts if facts is None else facts),
    )  # fmt: skip


class FakeWrites:
    """Hệ thống ghi AD / phần mềm / file server giả (hình phản hồi = mock)."""

    def __init__(self, clock: FakeClock, txlog: MemoryTxLog | None = None) -> None:
        self.clock = clock
        self.txlog = txlog
        self.calls: Counter[str] = Counter()
        self.order: list[str] = []
        self.seen: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.faults: dict[str, Fault] = {}
        self.begun_before: dict[str, bool] = {}
        self.versions: dict[str, str] = {"zoom": "6.1.0", "adobe-acrobat-pro": "2024.1"}
        self.already_installed: set[str] = set()  # Q3 M6: phần mềm máy đã có — phản hồi kèm `already_installed: true` như mock
        self.license_used: dict[str, int] = {"adobe-acrobat-pro": 7}  # lần cấp kế tiếp → LIC-adobe-acrobat-pro-008
        self.license_total: dict[str, int] = {"adobe-acrobat-pro": 20}
        self.previous_expiry: datetime | None = NOW + timedelta(days=5)  # dòng quyền đang có (extend)

    def _hit(self, tool: str, args: Any, ok: Callable[[], object]) -> object:
        self.calls[tool] += 1
        self.order.append(tool)
        self.seen[tool].append(args.model_dump(mode="json"))
        if self.txlog is not None:
            self.begun_before[tool] = (tool, "begun") in self.txlog.statuses()
        fault = self.faults.get(tool)
        if fault is not None:
            raise fault()
        return ok()

    def _perm(self, path: str, level: str, expires: datetime | None) -> dict[str, Any]:
        now = self.clock.now()
        return {"path": path, "level": level, "granted_at": (now - timedelta(days=10)).isoformat(),
                "expires_at": None if expires is None else expires.isoformat(),
                "status": "expired" if expires is not None and expires <= now else "active"}  # fmt: skip

    def handlers(self) -> dict[str, Any]:
        def account(a: UserAccountIn) -> dict[str, Any]:
            return {"user_id": a.user_id, "account_type": a.account_type}

        async def reset_password(a: UserAccountIn, timeout: float) -> object:
            return self._hit("reset_password", a, lambda: {**account(a), "delivered_via": "email",
                                                            "must_change_at_next_login": True})  # fmt: skip

        async def unlock_account(a: UserAccountIn, timeout: float) -> object:
            return self._hit("unlock_account", a, lambda: {**account(a), "locked": False, "was_locked": True})

        async def lock_account(a: LockIn, timeout: float) -> object:
            return self._hit("lock_account", a, lambda: {**account(a), "locked": True})

        async def install_software(a: InstallIn, timeout: float) -> object:
            return self._hit("install_software", a, lambda: {
                "device_id": a.device_id, "name": a.software_name, "version": self.versions.get(a.software_name, "1.0"),
                "installed_at": self.clock.now().isoformat(),
                **({"already_installed": True} if a.software_name in self.already_installed else {}),
            })  # fmt: skip

        async def uninstall_software(a: InstallIn, timeout: float) -> object:
            return self._hit("uninstall_software", a, lambda: {"device_id": a.device_id, "name": a.software_name,
                                                                "removed": True})  # fmt: skip

        def assign(a: AssignLicenseIn) -> dict[str, Any]:
            used = self.license_used.get(a.software_name, 0) + 1
            self.license_used[a.software_name] = used
            return {"name": a.software_name, "assignment_id": f"LIC-{a.software_name}-{used:03d}", "user_id": a.user_id,
                    "available": self.license_total.get(a.software_name, 10) - used}  # fmt: skip

        async def assign_paid_license(a: AssignLicenseIn, timeout: float) -> object:
            return self._hit("assign_paid_license", a, lambda: assign(a))

        def grant(a: GrantIn) -> dict[str, Any]:
            now = self.clock.now()
            expires = None if a.duration_days is None else now + timedelta(days=a.duration_days)
            return {**self._perm(a.resource_path, a.level, expires), "granted_at": now.isoformat()}

        async def grant_permission(a: GrantIn, timeout: float) -> object:
            return self._hit("grant_permission", a, lambda: grant(a))

        async def revoke_permission(a: UserPathIn, timeout: float) -> object:
            return self._hit("revoke_permission", a, lambda: {"path": a.resource_path, "revoked": True})

        def extend(a: ExtendIn) -> dict[str, Any]:
            previous = self.previous_expiry
            base = max(previous, self.clock.now()) if previous is not None else self.clock.now()
            new = base + timedelta(days=a.duration_days)
            return {**self._perm(a.resource_path, "read", new),
                    "previous_expires_at": None if previous is None else previous.isoformat()}  # fmt: skip

        async def extend_permission(a: ExtendIn, timeout: float) -> object:
            return self._hit("extend_permission", a, lambda: extend(a))

        async def restore_permission_expiry(a: RestoreExpiryIn, timeout: float) -> object:
            return self._hit("restore_permission_expiry", a, lambda: self._perm(a.resource_path, "read", a.expires_at))

        return {
            "reset_password": reset_password, "unlock_account": unlock_account, "lock_account": lock_account,
            "install_software": install_software, "uninstall_software": uninstall_software,
            "assign_paid_license": assign_paid_license, "grant_permission": grant_permission,
            "revoke_permission": revoke_permission, "extend_permission": extend_permission,
            "restore_permission_expiry": restore_permission_expiry,
        }  # fmt: skip

    def registry(self) -> ToolRegistry:
        breakers = BreakerBoard(self.clock, failure_threshold=5, window_seconds=60, open_seconds=30)
        return ToolRegistry(self.handlers(), breakers=breakers, clock=self.clock)

    def total(self) -> int:
        return sum(self.calls.values())


def executor(
    plans: Mapping[str, tuple[Step, ...]] | None = None, *, at: datetime = NOW
) -> tuple[PlanExecutor, FakeWrites, MemoryTxLog, FakeClock]:
    clock = FakeClock(at)
    txlog = MemoryTxLog()
    writes = FakeWrites(clock, txlog)
    ex = PlanExecutor(writes.registry(), txlog, clock, tz=TZ, plans=plans)
    return ex, writes, txlog, clock
