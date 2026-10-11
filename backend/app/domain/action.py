"""Action — hành động agent DỰ ĐỊNH làm, không phải câu người dùng nói. Input duy nhất M5 được đọc.

Trường theo B11 mục 4 [Chốt 3, bổ sung trường]. `build_action` (phase3 mục 3.2, 3f): `facts` CHỈ lấy từ state (B6/B11
ghi từ tool), không bao giờ từ `slots`; key ngoài `FACT_KEYS` → `FactKeyViolation` (bug → E9). Thuộc tính rủi ro của
hành động (`reversible`, `scope`…) lấy từ `config/action_metadata.yaml` (`ActionMeta`) — thiếu → không khởi động
(`settings.check_intent_config`), không bao giờ mặc định "reversible". B11 gọi hàm này ở 3g.

Phase 4 S0 (Q-4-U A+, D-34): `ActionMeta.procedure_doc` = `doc_id` tài liệu QUY TRÌNH trong KB cho hành động — căn cứ của
hành động là quy trình được khai báo và có mặt trong KB đang chạy (B11 kiểm tất định), không phải độ giống văn bản (B9).
KHÔNG chép vào `Action` (`action_plan_hash` không đổi).

Phase 5 T22a (D-41):
- **`requested_for` = NGƯỜI BỊ TÁC ĐỘNG** (P4): account — chủ tài khoản đích; access — người được cấp/gia hạn/xem quyền; software, vpn —
  người gửi (chủ máy kiểm bằng fact `device_owner_is_requester`). Fact `target_*` (`domain/facts.py`) mô tả người này.
- **`PARAM_TYPES`** (P3, Q-5-3): danh sách TRẮNG khoá `params` mà luật M5 được đọc (nguồn DSL `action.params`). `params` là đúng thứ B17
  thực thi và đã băm vào `action_plan_hash` → luật xét đúng hành động thật. Sai kiểu / ngoài tập → `param_ok` False → luật coi như
  THIẾU (điều kiện sai), không ném lỗi.
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

# P3: khoá `params` luật được đọc → kiểu CHẶT (`bool` không phải `int`) + tập/khoảng giá trị.
PARAM_TYPES: Mapping[str, type] = {"permission_level": str, "duration_days": int}
PERMISSION_LEVELS: frozenset[str] = frozenset({"read", "write", "full"})
DURATION_DAYS_MIN, DURATION_DAYS_MAX = 1, 365


def param_ok(key: str, value: object) -> bool:
    """Giá trị `params[key]` có được đưa cho luật không — khoá ngoài `PARAM_TYPES`, sai kiểu, ngoài tập → False (coi như thiếu)."""
    if key == "permission_level":
        return type(value) is str and value in PERMISSION_LEVELS
    if key == "duration_days":
        return type(value) is int and DURATION_DAYS_MIN <= value <= DURATION_DAYS_MAX
    return False  # khoá ngoài PARAM_TYPES (vd device_id, software_name) — luật không đọc


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
    requested_for: str  # user_id người BỊ TÁC ĐỘNG (P4, D-41) — xem docstring module
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
