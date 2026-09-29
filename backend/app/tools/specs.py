"""Khai báo tool bằng Python, kiểm lúc import (P5 mục 4).

Registry viết bằng Python thay vì bảng DB vì `input_model`/`output_model` là class chỉ tồn tại trong
code và không có UI nào cần sửa tool [Chốt thiết kế DB vòng 3]. File này **chỉ là metadata**: nó
không import adapter nào — hợp đồng import-linter số 3 cấm cả import gián tiếp tới adapter ghi, mà
module nào (graph, B6…) cũng cần đọc khai báo tool. Handler được gắn vào `ToolRegistry` từ bên ngoài.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.settings import get_policy, get_slots
from app.tools import models as m

READ_STEPS = frozenset({"B6", "B11"})  # [Chốt 17.3]: chẩn đoán + kiểm target
WRITE_STEPS = frozenset({"B17"})  # [Chốt]: B17 là điểm ghi duy nhất
RECHECK_STEP = "B17_RECHECK"  # 3-Q37: B17 ĐỌC lại AD trước khi ghi (tool đọc không bao giờ khai báo "B17")
READ_TIMEOUT_S = 5.0  # [Chốt 17.3]: đọc 5 giây, 2 lần retry
WRITE_TIMEOUT_S = 5.0  # [Chốt 17.3]: ghi 5 giây, KHÔNG retry

TargetSystem = Literal["ad", "vpn", "software", "files"]


class ToolSpecError(ValueError):
    """Khai báo tool sai — phát hiện lúc import, không để lọt tới runtime."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: Literal["read", "write"]
    target_system: TargetSystem
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    timeout_s: float
    retries: int  # read: TOOL_RETRY (policy.json), write: 0 [Chốt 17.3]
    allowed_steps: frozenset[str]  # {"B6","B11"} cho read; {"B17"} cho write
    arg_slots: frozenset[str] = frozenset()  # slot dùng làm tham số (chỉ tool đọc) [Đề xuất D-20]
    reversible: Literal["full", "partial", "none"] | None = None  # chỉ tool ghi chính
    undo_tool: str | None = None  # ví dụ reset_password → lock_account (partial)


def _read(
    name: str,
    system: TargetSystem,
    inp: type[BaseModel],
    out: type[BaseModel],
    arg_slots: Iterable[str] = (),
    steps: frozenset[str] = READ_STEPS,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        kind="read",
        target_system=system,
        input_model=inp,
        output_model=out,
        timeout_s=READ_TIMEOUT_S,
        retries=get_policy().constants.TOOL_RETRY,
        allowed_steps=steps,
        arg_slots=frozenset(arg_slots),
    )


def _write(
    name: str,
    system: TargetSystem,
    inp: type[BaseModel],
    out: type[BaseModel],
    reversible: Literal["full", "partial", "none"] | None = None,
    undo_tool: str | None = None,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        kind="write",
        target_system=system,
        input_model=inp,
        output_model=out,
        timeout_s=WRITE_TIMEOUT_S,
        retries=0,
        allowed_steps=WRITE_STEPS,
        reversible=reversible,
        undo_tool=undo_tool,
    )


SPECS: tuple[ToolSpec, ...] = (
    # ---- 12 tool đọc [Chốt B6] + arg_slots [Đề xuất D-20, bảng P5 mục 4] ----
    _read("check_account_status", "ad", m.UserAccountIn, m.AccountStatus, {"target_user", "account_type"}),
    _read("check_lockout_history", "ad", m.UserIn, m.LockoutList, {"target_user"}),
    _read("check_privilege_level", "ad", m.UserAccountIn, m.Privilege, {"target_user", "account_type"}),
    _read("check_device_registered", "vpn", m.UserDeviceIn, m.DeviceList, {"device_id"}),
    _read("check_vpn_cert_expiry", "vpn", m.UserDeviceIn, m.CertList, {"device_id"}),
    _read("check_last_connection", "vpn", m.UserIn, m.ConnectionList),
    _read("check_catalog_entry", "software", m.SoftwareIn, m.CatalogEntry, {"software_name"}),
    _read("check_license_available", "software", m.SoftwareIn, m.LicenseInfo, {"software_name"}),
    _read("check_installed_list", "software", m.DeviceIn, m.InstalledList, {"device_id"}),
    _read("check_current_permissions", "files", m.UserResourceIn, m.PermissionList, {"resource_path"}),
    _read("check_resource_sensitivity", "files", m.ResourceIn, m.ResourceInfo, {"resource_path"}),
    _read("check_manager_chain", "ad", m.UserIn, m.ManagerChain),
    # ---- Tool đọc nội bộ: B1 chụp requester_context, B11 kiểm target (B01 mục 3, B11 mục 3), B17 kiểm lại người gửi +
    # người hưởng lợi (3-Q37: nhãn riêng `B17_RECHECK` — nhãn `B17` chỉ dành cho tool ghi, `validate_specs` giữ luật đó) ----
    _read("ad_get_user", "ad", m.UserIn, m.AdUser, steps=frozenset({"B1", "B11", RECHECK_STEP})),
    # ---- Tool ghi (chỉ B17) [Suy luận từ 4 loại yêu cầu + 20 luật, P5 mục 4] ----
    _write("reset_password", "ad", m.UserAccountIn, m.ResetPasswordResult, "partial", "lock_account"),
    _write("unlock_account", "ad", m.UserAccountIn, m.LockStateResult, "full", "lock_account"),
    _write("renew_vpn_cert", "vpn", m.UserDeviceRequiredIn, m.Cert, "full", "revoke_vpn_cert"),
    _write("reissue_vpn_access", "vpn", m.UserDeviceRequiredIn, m.Cert, "full", "revoke_vpn_cert"),
    _write("install_software", "software", m.InstallIn, m.InstallResult, "full", "uninstall_software"),
    _write("assign_paid_license", "software", m.AssignLicenseIn, m.AssignLicenseResult, "none"),
    _write("grant_permission", "files", m.GrantIn, m.PermissionEntry, "full", "revoke_permission"),
    _write(
        "extend_permission", "files", m.ExtendIn, m.ExtendPermissionResult, "full",
        "restore_permission_expiry",
    ),
    # ---- Tool hoàn tác — cũng là tool ghi, chỉ TransactionLog của B17 gọi ----
    _write("lock_account", "ad", m.LockIn, m.LockStateResult),
    _write("revoke_vpn_cert", "vpn", m.RevokeCertIn, m.Cert),
    _write("uninstall_software", "software", m.InstallIn, m.UninstallResult),
    _write("revoke_permission", "files", m.UserPathIn, m.RevokePermissionResult),
    _write("restore_permission_expiry", "files", m.RestoreExpiryIn, m.PermissionEntry),
)

# Bản đồ tool chẩn đoán theo intent [Chốt B6 mục 0.3] — B6 chọn tool bằng code, không để LLM chọn.
TOOL_MAP: Mapping[str, tuple[str, str, str]] = {
    "account": ("check_account_status", "check_lockout_history", "check_privilege_level"),
    "vpn": ("check_device_registered", "check_vpn_cert_expiry", "check_last_connection"),
    "software": ("check_catalog_entry", "check_license_available", "check_installed_list"),
    "access": ("check_current_permissions", "check_resource_sensitivity", "check_manager_chain"),
}


def validate_specs(
    specs: Iterable[ToolSpec], tool_arg_slots: frozenset[str], tool_map: Mapping[str, Iterable[str]]
) -> dict[str, ToolSpec]:
    """Kiểm khai báo; trả dict tên → spec. Sai ở đâu thì nêu tên tool."""
    registry: dict[str, ToolSpec] = {}
    for s in specs:
        if s.name in registry:
            raise ToolSpecError(f"{s.name}: khai báo trùng tên")
        registry[s.name] = s
    for s in registry.values():
        if s.kind == "write":
            if s.allowed_steps != WRITE_STEPS:
                raise ToolSpecError(f"{s.name}: tool ghi phải có allowed_steps == {{'B17'}}")
            if s.retries != 0:
                raise ToolSpecError(f"{s.name}: tool ghi không được retry")
            if s.arg_slots:
                raise ToolSpecError(f"{s.name}: arg_slots chỉ dành cho tool đọc")
            if (s.reversible in ("full", "partial")) != (s.undo_tool is not None):
                raise ToolSpecError(f"{s.name}: reversible full/partial phải có undo_tool và ngược lại")
            undo = registry.get(s.undo_tool) if s.undo_tool else None
            if s.undo_tool and (undo is None or undo.kind != "write"):
                raise ToolSpecError(f"{s.name}: undo_tool {s.undo_tool!r} không phải tool ghi đã khai báo")
        else:
            if "B17" in s.allowed_steps:
                raise ToolSpecError(f"{s.name}: tool đọc không khai báo bước B17")
            if s.reversible is not None or s.undo_tool is not None:
                raise ToolSpecError(f"{s.name}: reversible/undo_tool chỉ dành cho tool ghi")
        if not s.arg_slots <= tool_arg_slots:
            raise ToolSpecError(
                f"{s.name}: arg_slots {sorted(s.arg_slots - tool_arg_slots)} ngoài TOOL_ARG_SLOTS"
            )
    for intent, names in tool_map.items():
        for name in names:
            spec = registry.get(name)
            if spec is None or spec.kind != "read" or "B6" not in spec.allowed_steps:
                raise ToolSpecError(f"TOOL_MAP[{intent}]: {name} không phải tool đọc gọi được từ B6")
    return registry


REGISTRY: Mapping[str, ToolSpec] = validate_specs(SPECS, get_slots().tool_arg_slots, TOOL_MAP)
