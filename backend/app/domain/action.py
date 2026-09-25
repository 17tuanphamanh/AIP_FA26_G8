"""Action — hành động agent DỰ ĐỊNH làm, không phải câu người dùng nói. Input duy nhất M5 được đọc.

Trường theo B11 mục 4 [Chốt 3, bổ sung trường]. build_action (cần config/action_metadata.yaml,
REQUIRED_SLOTS) làm cùng B11 ở Phase 3.
"""

from typing import Literal

from pydantic import BaseModel

type FactValue = str | int | bool


class Action(BaseModel, frozen=True):
    type: str  # reset_password, grant_permission, install_software…
    target: str  # "user:nv001", "folder:finance/Q3", "device:LAP-0342"
    requested_for: str  # user_id người hưởng lợi
    scope: Literal["single_account", "single_device", "multiple", "org_wide"]
    privilege_level: Literal["standard_user", "elevated", "admin"]
    reversible: bool  # từ ACTION_METADATA [Chốt]
    reversibility: Literal["full", "partial", "none"]  # chi tiết cho TransactionLog [Đề xuất]
    data_sensitivity: Literal["low", "medium", "high"]
    params: dict[str, FactValue]  # software_name, duration_days, permission_level…
    facts: dict[str, FactValue]  # dữ kiện cho luật: device_registered, in_catalog, paid…
