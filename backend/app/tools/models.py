"""Schema vào/ra của tool (P5 mục 4). Input sai → lỗi hợp đồng (raise, không retry); output sai →
lỗi hợp đồng (P5 mục 6.1). Output bỏ qua trường thừa của hệ thống ngoài, nhưng thiếu trường
bắt buộc hay sai kiểu là lỗi — phát hiện sớm khi hệ thống ngoài đổi API.

Tên trường input trùng tên slot (B11) trừ `target_user` → `user_id`: người được tra cứu, mặc định
là người gửi (D-16, `scope_tool_target`).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

AccountType = Literal["ad", "email", "erp"]
PrivilegeLevel = Literal["standard_user", "elevated", "admin"]
EmploymentStatus = Literal["active", "probation", "disabled", "terminated"]

# slot → trường input của tool khi tên khác nhau (B6 dựng tham số theo bảng này ở Phase 3)
SLOT_TO_FIELD = {"target_user": "user_id"}


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


# ---- Input -----------------------------------------------------------------------------------


class UserIn(_In):
    user_id: str = Field(min_length=1)


class UserAccountIn(UserIn):
    account_type: AccountType = "ad"


class UserDeviceIn(UserIn):
    device_id: str | None = None  # không có → mọi thiết bị của người đó


class DeviceIn(_In):
    device_id: str = Field(min_length=1)


class SoftwareIn(_In):
    software_name: str = Field(min_length=1)


class UserResourceIn(UserIn):
    resource_path: str | None = None  # không có → mọi quyền của người đó


class ResourceIn(_In):
    resource_path: str = Field(min_length=1)


class LockIn(UserAccountIn):
    reason: Literal["bad_password", "admin", "inactivity"] = "admin"


class UserDeviceRequiredIn(UserIn):
    device_id: str = Field(min_length=1)


class RevokeCertIn(UserIn):
    serial: str = Field(min_length=1)


class InstallIn(_In):
    device_id: str = Field(min_length=1)
    software_name: str = Field(min_length=1)


class AssignLicenseIn(_In):
    software_name: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class GrantIn(UserIn):
    resource_path: str = Field(min_length=1)
    level: Literal["read", "write", "full"]
    duration_days: int | None = Field(default=None, gt=0)


class UserPathIn(UserIn):
    resource_path: str = Field(min_length=1)


class ExtendIn(UserPathIn):
    duration_days: int = Field(gt=0)


class RestoreExpiryIn(UserPathIn):
    expires_at: datetime | None


# ---- Output: AD ------------------------------------------------------------------------------


class AccountState(_Out):
    account_type: AccountType
    enabled: bool
    locked: bool
    lock_reason: str | None
    password_last_set: datetime


class AdUser(_Out):
    """Thuộc tính người dùng từ AD — nguồn duy nhất của role, phòng ban, trạng thái (B01)."""

    user_id: str
    username: str
    full_name: str
    title: str
    department: str
    groups: list[str]
    manager_id: str | None
    employment_status: EmploymentStatus
    hired_at: date
    is_privileged_account: bool
    account: AccountState


class AccountStatus(AdUser):
    """`check_account_status` — cùng endpoint với `ad_get_user`, kèm tài khoản theo `account_type`.

    Phase 5 T22a P7 (G5-3): `is_service_account`, `disable_reason` — nguồn của fact `target_is_service_account`,
    `target_disable_reason` (R01–R03, R12). BẮT BUỘC, không mặc định: mock/AD cũ thiếu trường → `ToolContractError` rõ ràng,
    không âm thầm coi là "không phải tài khoản dịch vụ" (R01/R02 sẽ AUTO nhầm). Không đặt ở `AdUser` (B1 không cần)."""

    is_service_account: bool
    disable_reason: Literal["security", "other"] | None  # chỉ có giá trị khi employment_status == "disabled"


class Lockout(_Out):
    account_type: AccountType
    at: datetime
    reason: str
    source: str


class LockoutList(RootModel[list[Lockout]]):
    pass


class Privilege(_Out):
    user_id: str
    account_type: AccountType
    level: PrivilegeLevel
    is_privileged_account: bool


class ManagerEntry(_Out):
    user_id: str
    full_name: str
    title: str
    department: str
    employment_status: EmploymentStatus


class ManagerChain(RootModel[list[ManagerEntry]]):
    pass


# ---- Output: VPN -----------------------------------------------------------------------------


class Device(_Out):
    device_id: str
    owner_id: str
    kind: str
    os: str
    registered: bool
    registered_at: datetime | None


class DeviceList(RootModel[list[Device]]):
    pass


class Cert(_Out):
    serial: str
    device_id: str
    issued_at: datetime
    expires_at: datetime
    status: Literal["valid", "expired", "revoked"]
    days_to_expiry: int


class CertList(RootModel[list[Cert]]):
    pass


class Connection(_Out):
    at: datetime
    device_id: str
    result: Literal["success", "failed"]
    error_code: str | None


class ConnectionList(RootModel[list[Connection]]):
    pass


# ---- Output: phần mềm ------------------------------------------------------------------------


class CatalogEntry(_Out):
    name: str
    display_name: str
    in_catalog: bool
    license_type: Literal["free", "paid"]
    paid: bool
    version: str
    requires_approval: bool
    # Phase 5 T22a P7: nguồn của fact `requires_local_admin` (R11, R15) — BẮT BUỘC, không mặc định (thiếu → lỗi rõ, không coi là false)
    requires_local_admin: bool


class LicenseInfo(_Out):
    name: str
    license_type: Literal["free", "paid"]
    total: int | None
    used: int | None
    available: int | None  # None = miễn phí, không giới hạn


class InstalledItem(_Out):
    name: str
    version: str
    installed_at: datetime


class InstalledList(RootModel[list[InstalledItem]]):
    pass


# ---- Output: file server ---------------------------------------------------------------------


class PermissionEntry(_Out):
    path: str
    level: Literal["read", "write", "full"]
    granted_at: datetime
    expires_at: datetime | None
    status: Literal["active", "expired"]


class PermissionList(RootModel[list[PermissionEntry]]):
    pass


class ResourceInfo(_Out):
    path: str
    sensitivity: Literal["low", "medium", "high"]
    owner_department: str
    owner_id: str


# ---- Output: tool ghi ------------------------------------------------------------------------


class ResetPasswordResult(_Out):
    user_id: str
    account_type: AccountType
    delivered_via: str
    must_change_at_next_login: bool
    # Kênh sms: hạn mật khẩu tạm (phút) và số nhận ĐÃ CHE (mock: `0900***123`). Kênh email không có → None.
    expires_in_minutes: int | None = None
    sent_to: str | None = None


class LockStateResult(_Out):
    user_id: str
    account_type: AccountType
    locked: bool
    was_locked: bool | None = None  # chỉ `unlock` trả (lock không có) — giữ lại thay vì bỏ qua như trường lạ


class InstallResult(_Out):
    device_id: str
    name: str
    version: str
    installed_at: datetime


class UninstallResult(_Out):
    device_id: str
    name: str
    removed: bool


class AssignLicenseResult(_Out):
    name: str
    assignment_id: str
    user_id: str
    available: int


class RevokePermissionResult(_Out):
    path: str
    revoked: bool


class ExtendPermissionResult(PermissionEntry):
    previous_expires_at: datetime | None  # tham số cho restore_permission_expiry (hoàn tác)
