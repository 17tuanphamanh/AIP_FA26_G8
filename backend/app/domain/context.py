"""RequesterContext — do B1 chụp từ AD, chỉ đọc sau đó (B01 mục 4)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class RequesterContext(BaseModel, frozen=True):  # frozen: không node nào sửa được sau B1
    user_id: str
    role: Literal["employee", "l1", "manager", "l2"]
    department: str
    manager_id: str | None
    employment_status: Literal["active", "probation", "disabled", "terminated"]
    tenure_days: int  # cho luật "nhân viên mới chưa qua thử việc"
    is_privileged_account: bool  # tài khoản quản trị/dịch vụ
    source: Literal["ad"] = "ad"  # role chỉ lấy từ AD, không từ lời người dùng
    captured_at: datetime
