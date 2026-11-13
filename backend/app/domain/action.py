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

Phase 5 T20a (D-47, phase5 5.1.1 P6–P8, bảng 5.1.3): `build_action` dựng 4 intent theo `PARAMS_BY_ACTION` (một nguồn cho test và danh
sách trắng N1 của Phase 6). `requested_for` account/access = `slots.target_user` nếu có (`requested_for_of`). Không slot chữ tự do nào
(`reason`, `justification`, `version`) vào `params`; `extend_permission` không mang `permission_level`; tên phần mềm chuẩn hoá không dấu
cách (`normalize_software_name`); đường dẫn bỏ `/` hai đầu như mock. Không có nhánh mặc định: intent lạ / thiếu slot → `ValueError` (E9 —
B11 đã đảm bảo đủ slot, thiếu là bug); `params` lệch `PARAMS_BY_ACTION` → `ValueError` (kiểm lại trước khi trả).
"""

import re
from collections.abc import Mapping
from typing import Literal, NamedTuple

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


class ParamKey(NamedTuple):
    """Một khoá `params` của một `action_type`: kiểu (chặt) và có bắt buộc không."""

    type: type
    required: bool


# T20a P7 (D-47, bảng phase5 5.1.3): hợp đồng `params` theo `action_type` — MỘT nguồn cho `build_action`, test và danh sách trắng N1 của
# Phase 6 (6C). Đủ khoá, không thêm: không slot chữ tự do (`reason`, `justification`, `version`) nào; `extend_permission` không mang
# `permission_level` (giữ hợp đồng `ExtendIn`, Q-T22a-8).
PARAMS_BY_ACTION: Mapping[str, Mapping[str, ParamKey]] = {
    "renew_vpn_cert": {"device_id": ParamKey(str, True)},
    "reissue_vpn_access": {"device_id": ParamKey(str, True)},
    "check_vpn_status": {"device_id": ParamKey(str, True)},
    "reset_password": {"account_type": ParamKey(str, True)},
    "unlock_account": {"account_type": ParamKey(str, True)},
    "install_software": {"device_id": ParamKey(str, True), "software_name": ParamKey(str, True)},
    "view_permissions": {"resource_path": ParamKey(str, False)},
    "grant_permission": {
        "resource_path": ParamKey(str, True), "permission_level": ParamKey(str, True), "duration_days": ParamKey(int, True),
    },
    "extend_permission": {"resource_path": ParamKey(str, True), "duration_days": ParamKey(int, True)},
}  # fmt: skip


SOFTWARE_NAME = re.compile(r"[a-z0-9][a-z0-9.+#-]{0,63}")  # P8: tên chuẩn hoá — không dấu cách, không chữ hoa (thu hẹp N1)
TARGET_USER_INTENTS = frozenset({"account", "access"})  # P6: intent mà `target_user` là người bị tác động


def normalize_software_name(name: str) -> str:
    """T20a P8: tên phần mềm chuẩn hoá — đúng thuật toán `software.normalize` của mock ("Adobe Acrobat Pro" → "adobe-acrobat-pro").
    Kết quả ngoài `SOFTWARE_NAME` → `ValueError` (không xảy ra nếu slot đã qua `value_rules`)."""
    out = "-".join(name.strip().lower().split())
    if SOFTWARE_NAME.fullmatch(out) is None:
        raise ValueError("software_name chuẩn hoá ngoài mẫu")
    return out


def requested_for_of(intent: str, slots: Mapping[str, str], requester_id: str) -> str:
    """T20a P6 (TQ-6): người BỊ TÁC ĐỘNG — account/access: `slots.target_user` nếu có, còn lại người gửi."""
    target_user = slots.get("target_user") if intent in TARGET_USER_INTENTS else None
    return target_user or requester_id


class ActionMeta(BaseModel):
    """Một dòng `config/action_metadata.yaml` (phase3 mục 9.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reversible: bool
    reversibility: Reversibility
    data_sensitivity: Sensitivity
    scope: Scope
    privilege_level: PrivilegeLevel
    procedure_doc: str = Field(pattern=DOC_ID_PATTERN)  # S0-P10: bắt buộc — thiếu/sai mẫu → không khởi động
    # 13/11: căn cứ khi tài khoản đích là tài khoản dịch vụ / quản trị (theo fact) — chỉ dùng để HIỂN THỊ căn cứ trên thẻ duyệt
    # (`procedure_doc_for`); B11 vẫn kiểm `procedure_doc` (lúc đó chưa có fact).
    procedure_doc_privileged: str | None = Field(default=None, pattern=DOC_ID_PATTERN)

    @model_validator(mode="after")
    def _reversible_matches(self) -> "ActionMeta":
        if self.reversible != (self.reversibility != "none"):
            raise ValueError("reversible phải khớp reversibility (none ↔ false)")
        return self


def procedure_doc_for(meta: ActionMeta, facts: Mapping[str, object]) -> str:
    """Căn cứ quy trình hiện cho người duyệt: tài khoản đích là tài khoản dịch vụ (`target_is_service_account is True`) hoặc
    quản trị (`target_account_privilege == "admin"`) và metadata có `procedure_doc_privileged` → bài đó; còn lại `procedure_doc`."""
    privileged = facts.get("target_is_service_account") is True or facts.get("target_account_privilege") == "admin"
    return meta.procedure_doc_privileged if privileged and meta.procedure_doc_privileged else meta.procedure_doc


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


def _slot(slots: Mapping[str, str], key: str) -> str:
    value = slots.get(key)
    if not value:
        raise ValueError(f"build_action: thiếu slot {key!r}")  # B11 đã đảm bảo đủ slot — thiếu là bug → E9
    return value


def _folder(raw: str) -> str:
    path = raw.strip().strip("/")  # TQ-7: = `normalize_path` của mock
    if not path:
        raise ValueError("build_action: resource_path rỗng")
    return path


def _target_params(intent: str, action_type: str, slots: Mapping[str, str], rf: str) -> tuple[str, dict[str, FactValue]]:
    """Bảng 5.1.3: (`target`, `params`) theo intent / `action_type`."""
    if intent == "vpn":
        device_id = _slot(slots, "device_id")
        return f"device:{device_id}", {"device_id": device_id}
    if intent == "account":
        return f"user:{rf}", {"account_type": _slot(slots, "account_type")}
    if intent == "software":
        device_id = _slot(slots, "device_id")
        return f"device:{device_id}", {
            "device_id": device_id, "software_name": normalize_software_name(_slot(slots, "software_name")),
        }  # fmt: skip
    if action_type == "view_permissions":
        raw = slots.get("resource_path")
        return f"user:{rf}", ({"resource_path": _folder(raw)} if raw else {})
    path = _folder(_slot(slots, "resource_path"))
    params: dict[str, FactValue] = {"resource_path": path, "duration_days": int(_slot(slots, "duration"))}
    if action_type == "grant_permission":
        params["permission_level"] = _slot(slots, "permission_level")
    return f"folder:{path}", params


def _check_params(action_type: str, params: Mapping[str, FactValue]) -> None:
    """Bất biến (d) 5.1.3: khoá ⊆ `PARAMS_BY_ACTION[type]`, đủ khoá bắt buộc, đúng kiểu (chặt)."""
    spec = PARAMS_BY_ACTION.get(action_type)
    if spec is None:
        raise ValueError(f"PARAMS_BY_ACTION thiếu {action_type!r}")
    if extra := sorted(set(params) - set(spec)):
        raise ValueError(f"params {action_type}: khoá ngoài hợp đồng {extra}")
    if missing := sorted(k for k, p in spec.items() if p.required and k not in params):
        raise ValueError(f"params {action_type}: thiếu {missing}")
    if wrong := sorted(k for k, v in params.items() if type(v) is not spec[k].type):
        raise ValueError(f"params {action_type}: sai kiểu {wrong}")


def build_action(
    intent: str,
    slots: Mapping[str, str],
    facts: Mapping[str, FactValue],
    requester: RequesterContext,
    metadata: Mapping[str, ActionMeta],
) -> Action:
    """Dựng `Action` cho M5. `facts` chỉ từ state (B6/B11) — vi phạm `FACT_KEYS` = bug → `FactKeyViolation` → E9.
    `metadata` = `action_metadata[intent]`. Intent lạ / thiếu slot / `action` ngoài metadata → `ValueError` (E9)."""
    check_facts(facts)
    if intent not in ("vpn", "account", "software", "access"):
        raise ValueError(f"build_action không hỗ trợ intent {intent!r}")
    action_type = slots.get("action")
    if action_type is None and intent == "software" and len(metadata) == 1:  # P4: intent chỉ có một hành động
        [action_type] = metadata
    if action_type is None or action_type not in metadata:
        raise ValueError(f"build_action: action {action_type!r} không thuộc intent {intent!r}")
    meta = metadata[action_type]
    rf = requested_for_of(intent, slots, requester.user_id)
    target, params = _target_params(intent, action_type, slots, rf)
    _check_params(action_type, params)
    return Action(
        type=action_type, target=target, requested_for=rf, scope=meta.scope,
        privilege_level=meta.privilege_level, reversible=meta.reversible, reversibility=meta.reversibility,
        data_sensitivity=meta.data_sensitivity, params=params, facts=dict(facts),
    )  # fmt: skip
