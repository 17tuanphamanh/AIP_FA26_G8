"""Schema của seed.json (P5 mục 7) — sai schema thì mock không khởi động, `make seed` báo lỗi.

Mốc thời gian trong seed là **tương đối** (`*_days_ago`, `expires_in_days`) và được quy ra
datetime lúc nạp: "chứng chỉ hết hạn 3 ngày trước" (TC06) luôn đúng dù chạy demo ngày nào.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EmploymentStatus = Literal["active", "probation", "disabled", "terminated"]
AdGroup = Literal["IT-Users", "IT-L1", "IT-Manager", "IT-L2"]
AccountType = Literal["ad", "email", "erp"]
PrivilegeLevel = Literal["standard_user", "elevated", "admin"]
Sensitivity = Literal["low", "medium", "high"]
PermissionLevel = Literal["read", "write", "full"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SeedAccount(_Strict):
    enabled: bool = True
    locked: bool = False
    lock_reason: Literal["bad_password", "admin", "inactivity"] | None = None
    password_last_set_days_ago: int = Field(default=30, ge=0)
    privilege: PrivilegeLevel = "standard_user"


class SeedLockout(_Strict):
    account_type: AccountType
    days_ago: float = Field(ge=0)
    reason: Literal["bad_password", "admin", "inactivity"]
    source: str  # máy/dịch vụ phát sinh lần khoá


class SeedUser(_Strict):
    user_id: str
    username: str
    full_name: str
    title: str
    department: str
    groups: list[AdGroup] = Field(min_length=1)
    manager_id: str | None
    employment_status: EmploymentStatus
    hired_days_ago: int = Field(ge=0)
    is_privileged_account: bool = False
    password_hash: str  # argon2id của mật khẩu demo — KHÔNG bao giờ trả ra API
    accounts: dict[AccountType, SeedAccount]
    lockouts: list[SeedLockout] = []

    @model_validator(mode="after")
    def _checks(self) -> "SeedUser":
        if not self.password_hash.startswith("$argon2id$"):
            raise ValueError(f"{self.user_id}: password_hash phải là argon2id")
        if "ad" not in self.accounts:
            raise ValueError(f"{self.user_id}: thiếu tài khoản 'ad'")
        return self


class SeedDevice(_Strict):
    device_id: str
    owner_id: str
    kind: Literal["laptop", "desktop"]
    os: str
    registered: bool
    registered_days_ago: int | None = None  # None khi chưa đăng ký

    @model_validator(mode="after")
    def _registered_date(self) -> "SeedDevice":
        if self.registered != (self.registered_days_ago is not None):
            raise ValueError(f"{self.device_id}: registered_days_ago chỉ có khi registered")
        return self


class SeedCert(_Strict):
    serial: str
    user_id: str
    device_id: str
    issued_days_ago: int = Field(ge=0)
    expires_in_days: int  # âm = đã hết hạn
    revoked: bool = False


class SeedConnection(_Strict):
    user_id: str
    device_id: str
    days_ago: float = Field(ge=0)
    result: Literal["success", "failed"]
    error_code: str | None = None


class SeedCatalogEntry(_Strict):
    name: str  # khoá tra cứu, chữ thường, không dấu cách
    display_name: str
    license_type: Literal["free", "paid"]
    version: str
    requires_approval: bool


class SeedLicensePool(_Strict):
    name: str
    total: int = Field(ge=0)
    used: int = Field(ge=0)


class SeedInstalled(_Strict):
    device_id: str
    name: str
    version: str
    installed_days_ago: int = Field(ge=0)


class SeedResource(_Strict):
    path: str
    sensitivity: Sensitivity
    owner_department: str
    owner_id: str  # người phê duyệt dữ liệu của thư mục


class SeedPermission(_Strict):
    user_id: str
    path: str
    level: PermissionLevel
    granted_days_ago: int = Field(ge=0)
    expires_in_days: int | None  # None = không hết hạn; âm = đã hết hạn


class SeedData(_Strict):
    users: list[SeedUser]
    devices: list[SeedDevice]
    certs: list[SeedCert]
    connections: list[SeedConnection]
    catalog: list[SeedCatalogEntry]
    licenses: list[SeedLicensePool]
    installed: list[SeedInstalled]
    resources: list[SeedResource]
    permissions: list[SeedPermission]

    @model_validator(mode="after")
    def _references(self) -> "SeedData":
        users = {u.user_id for u in self.users}
        if len(users) != len(self.users):
            raise ValueError("user_id trùng")
        if len({u.username for u in self.users}) != len(self.users):
            raise ValueError("username trùng")
        devices = {d.device_id for d in self.devices}
        catalog = {c.name for c in self.catalog}
        resources = {r.path for r in self.resources}
        problems = [
            *(f"manager_id {u.manager_id}" for u in self.users
              if u.manager_id is not None and u.manager_id not in users),
            *(f"device owner {d.owner_id}" for d in self.devices if d.owner_id not in users),
            *(f"cert {c.serial}" for c in self.certs
              if c.user_id not in users or c.device_id not in devices),
            *(f"connection {c.user_id}/{c.device_id}" for c in self.connections
              if c.user_id not in users or c.device_id not in devices),
            *(f"license {p.name}" for p in self.licenses if p.name not in catalog),
            *(f"installed {i.device_id}/{i.name}" for i in self.installed
              if i.device_id not in devices or i.name not in catalog),
            *(f"resource owner {r.owner_id}" for r in self.resources if r.owner_id not in users),
            *(f"permission {p.user_id}/{p.path}" for p in self.permissions
              if p.user_id not in users or p.path not in resources),
        ]  # fmt: skip
        if problems:
            raise ValueError(f"tham chiếu không tồn tại: {problems}")
        for pool in self.licenses:
            if pool.used > pool.total:
                raise ValueError(f"license {pool.name}: used > total")
        return self
