"""Action — hành động agent DỰ ĐỊNH làm, không phải câu người dùng nói. Input duy nhất M5 được đọc.

Trường theo B11 mục 4 [Chốt 3, bổ sung trường]. `build_action` (phase3 mục 3.2, 3f): `facts` CHỈ lấy từ state (B6/B11
ghi từ tool), không bao giờ từ `slots`; key ngoài `FACT_KEYS` → `FactKeyViolation` (bug → E9). Thuộc tính rủi ro của
hành động (`reversible`, `scope`…) lấy từ `config/action_metadata.yaml` (`ActionMeta`) — thiếu → không khởi động
(`settings.check_intent_config`), không bao giờ mặc định "reversible". B11 gọi hàm này ở 3g.

Phase 4 S0 (Q-4-U A+, D-34): `ActionMeta.procedure_doc` = `doc_id` tài liệu QUY TRÌNH trong KB cho hành động — căn cứ của
hành động là quy trình được khai báo và có mặt trong KB đang chạy (B11 kiểm tất định), không phải độ giống văn bản (B9).
KHÔNG chép vào `Action` (`action_plan_hash` không đổi).
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.context import RequesterContext
from app.domain.facts import check_facts

type FactValue = str | int | bool
type Scope = Literal["single_account", "single_device", "multiple", "org_wide"]
type PrivilegeLevel = Literal["standard_user", "elevated", "admin"]
type Reversibility = Literal["full", "partial", "none"]
type Sensitivity = Literal["low", "medium", "high"]

# Mẫu `doc_id` KB — MỘT nguồn cho ingest (`rag.models.FrontMatter`, loader) và `ActionMeta.procedure_doc`. Nằm ở domain vì
# domain không được import rag (import-linter 4); không đặt ở `ticket_state.py` vì module đó import `Action` (vòng).
DOC_ID_PATTERN = r"^KB-(VPN|ACC|SW|ACS|GEN)-\d{3}$"


class ActionMeta(BaseModel):
    """Một dòng `config/action_metadata.yaml` (phase3 mục 9.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reversible: bool
    reversibility: Reversibility
    data_sensitivity: Sensitivity
    scope: Scope
    privilege_level: PrivilegeLevel
    procedure_doc: str = Field(pattern=DOC_ID_PATTERN)  # S0-P10: bắt buộc — thiếu/sai mẫu → không khởi động

    @model_validator(mode="after")
    def _reversible_matches(self) -> "ActionMeta":
        if self.reversible != (self.reversibility != "none"):
            raise ValueError("reversible phải khớp reversibility (none ↔ false)")
        return self


class Action(BaseModel, frozen=True):
    type: str  # reset_password, grant_permission, install_software…
    target: str  # "user:nv001", "folder:finance/Q3", "device:LAP-0342"
    requested_for: str  # user_id người hưởng lợi
    scope: Scope
    privilege_level: PrivilegeLevel
    reversible: bool  # từ ACTION_METADATA [Chốt]
    reversibility: Reversibility  # chi tiết cho TransactionLog [Đề xuất]
    data_sensitivity: Sensitivity
    params: dict[str, FactValue]  # software_name, duration_days, permission_level…
    facts: dict[str, FactValue]  # dữ kiện cho luật: device_registered, in_catalog, paid…


def build_action(
    intent: str,
    slots: Mapping[str, str],
    facts: Mapping[str, FactValue],
    requester: RequesterContext,
    metadata: Mapping[str, ActionMeta],
) -> Action:
    """Dựng `Action` cho M5. `facts` chỉ từ state (B6/B11) — vi phạm `FACT_KEYS` = bug → `FactKeyViolation` → E9.
    `metadata` = `action_metadata[intent]`. Phase 3 chỉ `vpn`; intent khác → `ValueError` (E9) tới Phase 5."""
    check_facts(facts)
    if intent != "vpn":
        raise ValueError(f"build_action chưa hỗ trợ intent {intent!r} (Phase 5)")
    action_type = slots["action"]
    meta = metadata[action_type]  # thiếu = cấu hình lệch mà check_intent_config bỏ sót → KeyError → E9
    device_id = slots["device_id"]
    return Action(
        type=action_type, target=f"device:{device_id}", requested_for=requester.user_id, scope=meta.scope,
        privilege_level=meta.privilege_level, reversible=meta.reversible, reversibility=meta.reversibility,
        data_sensitivity=meta.data_sensitivity, params={"device_id": device_id}, facts=dict(facts),
    )  # fmt: skip
