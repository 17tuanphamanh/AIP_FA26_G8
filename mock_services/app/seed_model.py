"""Schema của seed.json (P5 mục 7) — sai schema thì mock không khởi động, `make seed` báo lỗi.

Mốc thời gian trong seed là **tương đối** (`*_days_ago`, `expires_in_days`) và được quy ra
datetime lúc nạp: "chứng chỉ hết hạn 3 ngày trước" (TC06) luôn đúng dù chạy demo ngày nào.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EmploymentStatus = Literal["active", "probation", "disabled", "terminated"]
DisableReason = Literal["security", "other"]
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
    # Phase 5 T22a P7 (G5-3): BẮT BUỘC có khoá, không mặc định — một người thiếu khoá không được âm thầm thành "không phải tài
    # khoản dịch vụ" (R01/R02 AUTO nhầm). `disable_reason` chỉ có giá trị khi `employment_status == "disabled"`.
    is_service_account: bool
    disable_reason: DisableReason | None
    password_hash: str  # argon2id của mật khẩu demo — KHÔNG bao giờ trả ra API
    phone: str | None = Field(default=None, pattern=r"^0900000\d{3}$")  # F2: số nhận SMS đặt lại mật khẩu, số giả
    # Mock AD: email công ty. File trong repo CHỈ nhận đuôi @demo-corp.local (không lỡ commit địa chỉ thật); địa chỉ thật nạp đè
    # từ seed.local.json (đã gitignore — `app.state.local_emails`).
    email: str = Field(pattern=r"^[a-z0-9._+-]+@demo-corp\.local$")
    accounts: dict[AccountType, SeedAccount]
    lockouts: list[SeedLockout] = []

    @model_validator(mode="after")
    def _checks(self) -> "SeedUser":
        if not self.password_hash.startswith("$argon2id$"):
            raise ValueError(f"{self.user_id}: password_hash phải là argon2id")
        if "ad" not in self.accounts:
            raise ValueError(f"{self.user_id}: thiếu tài khoản 'ad'")
        if self.disable_reason is not None and self.employment_status != "disabled":
            raise ValueError(f"{self.user_id}: disable_reason chỉ có khi employment_status=disabled")
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


_JOINERS = str.maketrans("", "", "-._")


def compact_key(text: str) -> str:
    """K4 (soát 12/11): dạng RÚT GỌN để so tên cấm — chữ thường, bỏ khoảng trắng, '-', '.', '_': "KMSpico-Portable.exe" →
    "kmspicoportableexe". Chỉ dùng cho danh sách cấm (bắt biến thể) và kiểm "cấm không chạm danh mục"; tra danh mục giữ `_lookup_key`."""
    return "".join(text.lower().split()).translate(_JOINERS)


def _lookup_key(text: str) -> str:
    """Cùng cách chuẩn hoá với `software.normalize`: "Zoom  Workplace" → "zoom-workplace"."""
    return "-".join(text.strip().lower().split())


class SeedCatalogEntry(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")  # khoá tra cứu: slug chữ thường, không dấu cách
    display_name: str = Field(min_length=1)  # tên như KB viết (kb/software/KB-SW-001.md)
    aliases: list[str] = []  # tên gọi khác người dùng hay viết; tra cứu so khớp sau khi chuẩn hoá
    license_type: Literal["free", "paid"]
    version: str
    requires_approval: bool
    requires_local_admin: bool  # Phase 5 T22a P7 — bắt buộc có khoá (R11/R15), không mặc định

    @model_validator(mode="after")
    def _aliases(self) -> "SeedCatalogEntry":
        if self.display_name.strip() != self.display_name or not _lookup_key(self.display_name):
            raise ValueError(f"{self.name}: display_name rỗng hoặc thừa khoảng trắng đầu/cuối")
        keys = [_lookup_key(a) for a in self.aliases]
        if "" in keys:
            raise ValueError(f"{self.name}: alias rỗng")
        if len(set(keys)) != len(keys):
            raise ValueError(f"{self.name}: alias trùng nhau (sau chuẩn hoá)")
        own = {self.name, _lookup_key(self.display_name)}
        if own & set(keys):
            raise ValueError(f"{self.name}: alias trùng chính slug hoặc display_name của nó")
        return self


class SeedProhibitedName(_Strict):
    """Q5 (ĐP 09/11): phần mềm bị cấm theo quy định — tra như danh mục (slug / tên hiển thị / alias sau chuẩn hoá)."""

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=1)
    aliases: list[str] = []

    def lookup_keys(self) -> set[str]:
        return {self.name, _lookup_key(self.display_name), *(_lookup_key(a) for a in self.aliases)}

    @model_validator(mode="after")
    def _keys(self) -> "SeedProhibitedName":
        if "" in self.lookup_keys():
            raise ValueError(f"{self.name}: tên hiển thị/alias rỗng")
        return self


class SeedProhibited(_Strict):
    """Q5: danh sách cấm do hệ thống ngoài giữ. `keywords` lưu DẠNG ĐÃ CHUẨN HOÁ (`_lookup_key`) — so khớp chuỗi con trên tên đã chuẩn
    hoá; chỉ từ cụ thể (không "patch" đứng một mình — ĐP)."""

    names: list[SeedProhibitedName]
    keywords: list[str]

    @model_validator(mode="after")
    def _keywords(self) -> "SeedProhibited":
        for kw in self.keywords:
            if not kw or _lookup_key(kw) != kw:
                raise ValueError(f"từ khoá cấm {kw!r}: rỗng hoặc chưa chuẩn hoá (chữ thường, '-' thay khoảng trắng)")
        if len(set(self.keywords)) != len(self.keywords):
            raise ValueError("từ khoá cấm trùng nhau")
        owner: dict[str, str] = {}
        for n in self.names:
            for key in n.lookup_keys():
                if owner.setdefault(key, n.name) != n.name:
                    raise ValueError(f"tên cấm '{key}' trùng giữa {owner[key]} và {n.name}")
        return self


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
    prohibited_software: SeedProhibited  # Q5 — bắt buộc (thiếu mục = seed hỏng, không âm thầm "không cấm gì")
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
        phones = [u.phone for u in self.users if u.phone is not None]
        if len(set(phones)) != len(phones):
            raise ValueError("phone trùng")
        emails = [u.email for u in self.users]
        if len(set(emails)) != len(emails):
            raise ValueError("email trùng")
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
        owner_of: dict[str, str] = {}
        for c in self.catalog:  # slug, tên hiển thị và alias dùng chung một không gian tra cứu: không phần mềm nào được trùng
            for key in {c.name, _lookup_key(c.display_name), *(_lookup_key(a) for a in c.aliases)}:
                if owner_of.setdefault(key, c.name) != c.name:
                    raise ValueError(f"tên tra cứu '{key}' trùng giữa {owner_of[key]} và {c.name}")
        # Q5: danh sách cấm không được chạm danh mục — tên cấm trùng tên tra cứu, hoặc từ khoá là chuỗi con của slug/tên/alias → chặn nhầm
        for p in self.prohibited_software.names:
            if clash := sorted(p.lookup_keys() & set(owner_of)):
                raise ValueError(f"tên cấm {p.name}: trùng tên tra cứu danh mục {clash}")
        if hits := sorted({f"{kw} ⊂ {key}" for kw in self.prohibited_software.keywords for key in owner_of
                           if compact_key(kw) in compact_key(key)}):  # K4: so trên dạng rút gọn, như lúc tra
            raise ValueError(f"từ khoá cấm khớp phần mềm trong danh mục: {hits}")
        catalog_short = {compact_key(k): owner for k, owner in owner_of.items()}
        for p in self.prohibited_software.names:
            if clash := sorted({compact_key(k) for k in p.lookup_keys()} & set(catalog_short)):
                raise ValueError(f"tên cấm {p.name}: trùng tên tra cứu danh mục (dạng rút gọn) {clash}")
        for pool in self.licenses:
            if pool.used > pool.total:
                raise ValueError(f"license {pool.name}: used > total")
        return self
