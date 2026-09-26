"""RequesterContext — do B1 chụp từ AD, chỉ đọc sau đó (B01 mục 4).

Role chỉ lấy từ nhóm AD (bất biến 11), không bao giờ từ lời người dùng. Bảng nhóm → role nằm ở đây
(domain) vì cả đăng nhập (auth, P6) lẫn B1 (`from_ad`) cùng dùng, và domain không import auth.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from app.core.errors import DomainError

Role = Literal["employee", "l1", "manager", "l2"]

BASE_GROUP = "IT-Users"  # mọi nhân viên; chỉ có nhóm này → employee
PRIVILEGED_GROUPS: Mapping[str, Role] = {"IT-L1": "l1", "IT-Manager": "manager", "IT-L2": "l2"}


def role_from_groups(groups: Iterable[str]) -> Role | None:
    """Nhóm AD → role (P6 mục 3). None = không ánh xạ được → đăng nhập bị từ chối (fail-closed):
    thuộc hơn 1 nhóm đặc quyền [Suy luận], hoặc không thuộc nhóm nào đã biết."""
    names = set(groups)
    privileged = {PRIVILEGED_GROUPS[g] for g in names if g in PRIVILEGED_GROUPS}
    if len(privileged) > 1:
        return None
    if privileged:
        return privileged.pop()
    return "employee" if BASE_GROUP in names else None


class AdAttributes(Protocol):
    """Thuộc tính AD mà `from_ad` cần — `tools.models.AdUser` khớp theo cấu trúc."""

    @property
    def user_id(self) -> str: ...
    @property
    def department(self) -> str: ...
    @property
    def groups(self) -> Sequence[str]: ...
    @property
    def manager_id(self) -> str | None: ...
    @property
    def employment_status(self) -> str: ...
    @property
    def hired_at(self) -> date: ...
    @property
    def is_privileged_account(self) -> bool: ...


class RequesterContext(BaseModel, frozen=True):  # frozen: không node nào sửa được sau B1
    user_id: str
    role: Role
    department: str
    manager_id: str | None
    employment_status: Literal["active", "probation", "disabled", "terminated"]
    tenure_days: int  # cho luật "nhân viên mới chưa qua thử việc"
    is_privileged_account: bool  # tài khoản quản trị/dịch vụ
    source: Literal["ad"] = "ad"  # role chỉ lấy từ AD, không từ lời người dùng
    captured_at: datetime

    @classmethod
    def from_ad(cls, user: AdAttributes, now: datetime) -> "RequesterContext":
        """Chụp ngữ cảnh người gửi từ AD tại thời điểm `now` (clock tiêm vào, B01 mục 5)."""
        role = role_from_groups(user.groups)
        if role is None:
            raise DomainError(f"không ánh xạ được role từ nhóm AD của {user.user_id}")
        return cls.model_validate(
            {
                "user_id": user.user_id,
                "role": role,
                "department": user.department,
                "manager_id": user.manager_id,
                "employment_status": user.employment_status,
                "tenure_days": max(0, (now.date() - user.hired_at).days),
                "is_privileged_account": user.is_privileged_account,
                "captured_at": now,
            }
        )
