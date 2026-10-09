"""Trạng thái trong bộ nhớ của mock: nạp từ seed.json, endpoint ghi sửa trực tiếp, `/_admin/reset`
đặt lại (P5 mục 7). Không có DB — mock là "hệ thống của bên khác", chỉ cần hành xử như thật qua HTTP.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.seed_model import SeedData

SEED_PATH = Path(__file__).resolve().parents[1] / "seed.json"

type Now = Callable[[], datetime]


def system_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Account:
    enabled: bool
    locked: bool
    lock_reason: str | None
    password_last_set: datetime
    privilege: str


@dataclass
class Lockout:
    account_type: str
    at: datetime
    reason: str
    source: str


@dataclass
class User:
    user_id: str
    username: str
    full_name: str
    title: str
    department: str
    groups: list[str]
    manager_id: str | None
    employment_status: str
    hired_at: date
    is_privileged_account: bool
    is_service_account: bool  # Phase 5 T22a P7
    disable_reason: str | None  # Phase 5 T22a P7 — chỉ khi disabled; endpoint quản trị đặt lại khi đổi trạng thái
    password_hash: str
    accounts: dict[str, Account]
    lockouts: list[Lockout]


@dataclass
class Device:
    device_id: str
    owner_id: str
    kind: str
    os: str
    registered: bool
    registered_at: datetime | None


@dataclass
class Cert:
    serial: str
    user_id: str
    device_id: str
    issued_at: datetime
    expires_at: datetime
    revoked: bool


@dataclass
class Connection:
    user_id: str
    device_id: str
    at: datetime
    result: str
    error_code: str | None


@dataclass
class CatalogEntry:
    name: str
    display_name: str
    license_type: str
    version: str
    requires_approval: bool
    requires_local_admin: bool  # Phase 5 T22a P7


@dataclass
class LicensePool:
    name: str
    total: int
    used: int
    assignments: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Installed:
    device_id: str
    name: str
    version: str
    installed_at: datetime


@dataclass
class Resource:
    path: str
    sensitivity: str
    owner_department: str
    owner_id: str


@dataclass
class Permission:
    user_id: str
    path: str
    level: str
    granted_at: datetime
    expires_at: datetime | None


@dataclass
class MockState:
    now: Now
    users: dict[str, User]
    devices: dict[str, Device]
    certs: list[Cert]
    connections: list[Connection]
    catalog: dict[str, CatalogEntry]
    licenses: dict[str, LicensePool]
    installed: list[Installed]
    resources: dict[str, Resource]
    permissions: list[Permission]
    serial_seq: int = 0

    def next_serial(self) -> str:
        self.serial_seq += 1
        return f"VPN-NEW-{self.serial_seq:04d}"


def load_seed(path: Path = SEED_PATH) -> SeedData:
    return SeedData.model_validate(json.loads(path.read_text(encoding="utf-8")))


def build_state(seed: SeedData, now: Now = system_now) -> MockState:
    t0 = now()

    def ago(days: float) -> datetime:
        return t0 - timedelta(days=days)

    def ahead(days: float) -> datetime:
        return t0 + timedelta(days=days)

    users = {
        u.user_id: User(
            user_id=u.user_id,
            username=u.username,
            full_name=u.full_name,
            title=u.title,
            department=u.department,
            groups=list(u.groups),
            manager_id=u.manager_id,
            employment_status=u.employment_status,
            hired_at=ago(u.hired_days_ago).date(),
            is_privileged_account=u.is_privileged_account,
            is_service_account=u.is_service_account,
            disable_reason=u.disable_reason,
            password_hash=u.password_hash,
            accounts={
                kind: Account(
                    enabled=a.enabled,
                    locked=a.locked,
                    lock_reason=a.lock_reason,
                    password_last_set=ago(a.password_last_set_days_ago),
                    privilege=a.privilege,
                )
                for kind, a in u.accounts.items()
            },
            lockouts=[Lockout(x.account_type, ago(x.days_ago), x.reason, x.source) for x in u.lockouts],
        )
        for u in seed.users
    }
    return MockState(
        now=now,
        users=users,
        devices={
            d.device_id: Device(
                device_id=d.device_id,
                owner_id=d.owner_id,
                kind=d.kind,
                os=d.os,
                registered=d.registered,
                registered_at=None if d.registered_days_ago is None else ago(d.registered_days_ago),
            )
            for d in seed.devices
        },
        certs=[
            Cert(
                serial=c.serial,
                user_id=c.user_id,
                device_id=c.device_id,
                issued_at=ago(c.issued_days_ago),
                expires_at=ahead(c.expires_in_days),
                revoked=c.revoked,
            )
            for c in seed.certs
        ],
        connections=[
            Connection(c.user_id, c.device_id, ago(c.days_ago), c.result, c.error_code)
            for c in seed.connections
        ],
        catalog={
            c.name: CatalogEntry(
                c.name, c.display_name, c.license_type, c.version, c.requires_approval, c.requires_local_admin
            )
            for c in seed.catalog
        },
        licenses={p.name: LicensePool(p.name, p.total, p.used) for p in seed.licenses},
        installed=[
            Installed(i.device_id, i.name, i.version, ago(i.installed_days_ago)) for i in seed.installed
        ],
        resources={
            r.path: Resource(r.path, r.sensitivity, r.owner_department, r.owner_id)
            for r in seed.resources
        },
        permissions=[
            Permission(
                user_id=p.user_id,
                path=p.path,
                level=p.level,
                granted_at=ago(p.granted_days_ago),
                expires_at=None if p.expires_in_days is None else ahead(p.expires_in_days),
            )
            for p in seed.permissions
        ],
    )
