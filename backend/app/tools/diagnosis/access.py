"""Chẩn đoán access (phase5 5.1.2, T20a P3) — bộ lời gọi 4 tool đọc + `infer_access` (hàm thuần).

`rf` = người BỊ TÁC ĐỘNG (`requested_for_of`: `slots.target_user` nếu có, không thì người gửi — P6); `path` = slot `resource_path` đã
bỏ khoảng trắng + `/` hai đầu (= `normalize_path` của mock, TQ-7). Slot chỉ là KHOÁ TRA CỨU (chọn tool, lọc dòng quyền) — giá trị fact
luôn từ đầu ra tool (test AST `test_facts_ast.py`).

`diag` (TQ-2): `ToolResult.data` — model đã validate; danh sách rỗng = RootModel rỗng; `None` = 404 hoặc không gọi.

- `check_account_status(rf)` → `target_user_status`, `target_disable_reason` (khác null); `department` cho `same_department`. 404 → không đặt.
- `check_resource_sensitivity(path)` (khi có path) → `resource_sensitivity`; `same_department` = `owner_department == department` của
  `rf` — CHỈ khi có cả hai (thư mục lạ → không luật nào khớp → lớp LLM; KHÔNG BAO GIỜ đặt giá trị "an toàn" giả). T24 N8 (Q-T24-6):
  CẢ HAI phòng ban rỗng → không đặt ("" == "" không phải "cùng phòng"); MỘT phía rỗng → `False` (R09 vẫn bắt, không xuống lớp 2).
- `check_current_permissions(rf, path?)` khi có path: dòng `p.path == path` (còn hạn và hết hạn) → `has_permission_record`;
  `existing_permission_level` = mức CAO NHẤT (read < write < full — Q-5-8) khi có dòng. 404 → không đặt; rỗng → `False`.
- `check_manager_chain(rf)` → chỉ `diagnostics`.
"""

from collections.abc import Mapping
from typing import Any

from app.domain.action import requested_for_of
from app.domain.facts import FACT_KEYS
from app.tools.models import AccountStatus, PermissionList, ResourceInfo

TOOLS = (
    "check_current_permissions", "check_resource_sensitivity", "check_manager_chain", "check_account_status",
)  # = tools.specs.TOOL_MAP["access"] (D-46)  # fmt: skip
LEVEL_RANK = {"read": 0, "write": 1, "full": 2}  # P1 (Q-5-8): read < write < full


def _path(slots: Mapping[str, str]) -> str | None:
    """Slot `resource_path` bỏ khoảng trắng + `/` hai đầu (TQ-7); rỗng sau khi bỏ → coi như chưa có."""
    raw = slots.get("resource_path")
    return (raw.strip().strip("/") or None) if raw is not None else None


def calls(requester_id: str, slots: Mapping[str, str]) -> list[tuple[str, dict[str, str]]]:
    """B6: mọi lời gọi tra `rf`; `check_resource_sensitivity` chỉ khi có path (c7)."""
    rf = requested_for_of("access", slots, requester_id)
    path = _path(slots)
    out: list[tuple[str, dict[str, str]]] = [
        ("check_current_permissions", {"user_id": rf, **({"resource_path": path} if path else {})}),
    ]
    if path:
        out.append(("check_resource_sensitivity", {"resource_path": path}))
    out += [("check_manager_chain", {"user_id": rf}), ("check_account_status", {"user_id": rf})]
    return out


def target_calls(requester_id: str, slots: Mapping[str, str]) -> list[tuple[str, dict[str, str]]]:
    """B11: cùng bộ lời gọi trên slot cuối — mọi fact access phụ thuộc slot (`rf`, path) nên tính lại toàn bộ."""
    return calls(requester_id, slots)


def infer_access(
    diag: Mapping[str, Any], *, requester_id: str, slots: Mapping[str, str]
) -> tuple[dict[str, str], dict[str, str | int | bool]]:
    status = diag["check_account_status"] if isinstance(diag["check_account_status"], AccountStatus) else None
    res = diag["check_resource_sensitivity"] if isinstance(diag["check_resource_sensitivity"], ResourceInfo) else None
    perms = diag["check_current_permissions"] if isinstance(diag["check_current_permissions"], PermissionList) else None
    path = _path(slots)
    facts: dict[str, str | int | bool] = {}
    if status is not None:
        facts["target_user_status"] = status.employment_status
        if status.disable_reason is not None:
            facts["target_disable_reason"] = status.disable_reason
    if path is not None and res is not None:
        facts["resource_sensitivity"] = res.sensitivity
        if status is not None and (res.owner_department or status.department):  # T24 N8 (Q-T24-6): hai phía rỗng ≠ "cùng phòng"
            facts["same_department"] = res.owner_department == status.department
    if path is not None and perms is not None:
        rows = [p for p in perms.root if p.path == path]
        facts["has_permission_record"] = bool(rows)
        if rows:
            facts["existing_permission_level"] = max(rows, key=lambda p: LEVEL_RANK[p.level]).level
    assert set(facts) <= FACT_KEYS  # hợp đồng nội bộ; build_action kiểm lại bằng FactKeyViolation
    return {}, facts


infer = infer_access  # giao diện chung cho B6/B11 (`DIAGNOSERS`)
