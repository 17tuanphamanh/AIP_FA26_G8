"""Chẩn đoán software (phase5 5.1.2, T20a P3) — bộ lời gọi 4 tool đọc + `infer_software` (hàm thuần).

`requested_for` = người gửi (P6); tên tra cứu = `normalize_software_name(slot)` (P8 — một nguồn với `params.software_name`). Slot chỉ là
KHOÁ TRA CỨU — giá trị fact luôn từ đầu ra tool (test AST `test_facts_ast.py`).

`diag` (TQ-2): `ToolResult.data` — model đã validate; danh sách rỗng = RootModel rỗng; `None` = 404 hoặc không gọi.

- `check_catalog_entry(name)` (khi có tên) → `in_catalog`, `license_paid`, `requires_local_admin`. **404 → `in_catalog=False`** (mock
  trả 404 cho phần mềm ngoài danh mục — dữ liệu, không phải lỗi; chặt hơn: R13 bắt); `license_paid`, `requires_local_admin` không đặt.
  Q5: tên ngoài danh mục mà bị cấm → 200 `in_catalog=False, prohibited=True` (thuộc tính danh mục null) — cũng không đặt hai fact đó.
- `check_license_available(name)` (khi có tên), `check_installed_list(device_id)` (khi có máy) → chỉ `diagnostics`.
- `check_device_registered(người gửi, device_id?)` → phần máy dùng chung với VPN (`vpn.device_facts`, TQ-4): không nêu máy → đếm máy,
  đúng 1 máy → suy slot `device_id`; có máy → `device_registered`, `device_owner_is_requester` (404 → false).
"""

from collections.abc import Mapping
from typing import Any

from app.domain.action import normalize_software_name
from app.domain.facts import FACT_KEYS
from app.tools.diagnosis.vpn import device_facts
from app.tools.models import CatalogEntry, DeviceList

TOOLS = (
    "check_catalog_entry", "check_license_available", "check_installed_list", "check_device_registered",
)  # = tools.specs.TOOL_MAP["software"] (D-46)  # fmt: skip


def calls(requester_id: str, slots: Mapping[str, str]) -> list[tuple[str, dict[str, str]]]:
    """B6: tool phần mềm chỉ khi có tên (s7), danh sách đã cài chỉ khi có máy; luôn tra máy của người gửi."""
    out: list[tuple[str, dict[str, str]]] = []
    if (raw := slots.get("software_name")) is not None:
        name = normalize_software_name(raw)
        out += [("check_catalog_entry", {"software_name": name}), ("check_license_available", {"software_name": name})]
    device_id = slots.get("device_id")
    if device_id is not None:
        out.append(("check_installed_list", {"device_id": device_id}))
    out.append(("check_device_registered", {"user_id": requester_id, **({"device_id": device_id} if device_id else {})}))
    return out


def target_calls(requester_id: str, slots: Mapping[str, str]) -> list[tuple[str, dict[str, str]]]:
    """B11: cùng bộ lời gọi trên slot cuối (đủ tên + máy → cả 4 tool)."""
    return calls(requester_id, slots)


def infer_software(
    diag: Mapping[str, Any], *, requester_id: str, slots: Mapping[str, str], allow_infer: bool = True
) -> tuple[dict[str, str], dict[str, str | int | bool]]:
    """`allow_infer=False` (be-target-guard-2, cờ người khác): không suy máy duy nhất của người gửi — B11 hỏi mã máy."""
    devices = diag["check_device_registered"].root if isinstance(diag["check_device_registered"], DeviceList) else []
    entry = diag["check_catalog_entry"] if isinstance(diag["check_catalog_entry"], CatalogEntry) else None
    inferred, facts = device_facts(devices, requester_id=requester_id, device_id=slots.get("device_id"), allow_infer=allow_infer)
    if "software_name" in slots:  # đã gọi catalog (calls) — 404 là dữ liệu "ngoài danh mục"
        facts["in_catalog"] = entry is not None and entry.in_catalog
        # thuộc tính danh mục chỉ khi trong danh mục (Q5: tên cấm ngoài danh mục → 200 với thuộc tính null; model đã ép đủ khi in_catalog)
        if entry is not None and entry.in_catalog and entry.paid is not None and entry.requires_local_admin is not None:
            facts["license_paid"] = entry.paid
            facts["requires_local_admin"] = entry.requires_local_admin
    assert set(facts) <= FACT_KEYS  # hợp đồng nội bộ; build_action kiểm lại bằng FactKeyViolation
    return inferred, facts


infer = infer_software  # giao diện chung cho B6/B11 (`DIAGNOSERS`)
