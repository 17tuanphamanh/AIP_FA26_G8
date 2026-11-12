"""V9 soát 12/11 (agent 12 M1, D-90): bước GHI trả 2xx hợp schema nhưng kết quả nói "chưa làm" hoặc làm trên đối tượng khác →
KHÔNG được coi là thành công (trước: tin "Đã …", S_CONFIRMING). Executor coi là lỗi `unexpected_result` (thuộc nhóm "có thể đã áp
dụng") → E7 `exec_failed` có ghi chú bàn giao; KHÔNG gọi hoàn tác chính bước đó (định danh trả về có thể sai — hoàn tác theo nó là
ghi vào đối tượng khác), chỉ hoàn tác các bước trước như mọi lỗi khác.

Ghi giả bằng `StubWriter` (trả ToolResult với `data` tuỳ ý) — registry thật luôn validate schema nên `data` là model.
"""

from collections import Counter
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.executor.plan_executor import MAYBE_APPLIED_KINDS, PlanExecutor, error_kind
from app.executor.plans import unexpected_result
from app.tools.models import (
    AssignLicenseResult,
    Cert,
    ExtendPermissionResult,
    InstallResult,
    LockStateResult,
    PermissionEntry,
    ResetPasswordResult,
)
from app.tools.registry import ToolResult
from tests.fakes.executor import MemoryTxLog
from tests.unit._t24 import NOW, TZ, action

pytestmark = pytest.mark.asyncio

MAYBE_APPLIED = "có thể đã được áp dụng"
LATER = NOW + timedelta(days=365)


def _cert(device: str = "LAP-0342", status: str = "valid") -> Cert:
    return Cert.model_validate({"serial": "SN-1", "device_id": device, "issued_at": NOW, "expires_at": LATER,
                                "status": status, "days_to_expiry": 365})  # fmt: skip


def _reset(user: str = "nv001", via: str = "email", account_type: str = "ad") -> ResetPasswordResult:
    return ResetPasswordResult.model_validate({"user_id": user, "account_type": account_type, "delivered_via": via,
                                               "must_change_at_next_login": True})  # fmt: skip


def _unlock(user: str = "nv001", locked: bool = False) -> LockStateResult:
    return LockStateResult.model_validate({"user_id": user, "account_type": "ad", "locked": locked, "was_locked": True})


def _install(device: str = "LAP-0342", name: str = "zoom") -> InstallResult:
    return InstallResult.model_validate({"device_id": device, "name": name, "version": "6.1.0", "installed_at": NOW})


def _assign(user: str = "nv001") -> AssignLicenseResult:
    return AssignLicenseResult.model_validate({"name": "adobe-acrobat-pro", "assignment_id": "LIC-1", "user_id": user,
                                               "available": 3})  # fmt: skip


def _grant(path: str = "finance/public-reports", level: str = "read", status: str = "active") -> PermissionEntry:
    return PermissionEntry.model_validate({"path": path, "level": level, "granted_at": NOW, "expires_at": LATER,
                                           "status": status})  # fmt: skip


def _extend(path: str = "finance/Q3", status: str = "active") -> ExtendPermissionResult:
    return ExtendPermissionResult.model_validate({"path": path, "level": "read", "granted_at": NOW, "expires_at": LATER,
                                                  "status": status, "previous_expires_at": NOW + timedelta(days=5)})  # fmt: skip


GOOD: dict[str, Any] = {
    "renew_vpn_cert": _cert(), "reissue_vpn_access": _cert(), "reset_password": _reset(), "unlock_account": _unlock(),
    "install_software": _install(), "assign_paid_license": _assign(), "grant_permission": _grant(),
    "extend_permission": _extend(),
    "lock_account": _unlock(locked=True), "revoke_vpn_cert": _cert(status="revoked"),
    "uninstall_software": None, "revoke_permission": None, "restore_permission_expiry": None,
}  # fmt: skip


class StubWriter:
    """WriteCaller giả: trả `GOOD[tool]` hoặc `override[tool]`; đếm lời gọi."""

    def __init__(self, override: Mapping[str, Any] | None = None) -> None:
        self.override = dict(override or {})
        self.calls: Counter[str] = Counter()
        self.order: list[str] = []

    async def call(
        self, name: str, args: Mapping[str, Any], *, caller_step: str
    ) -> ToolResult:
        assert caller_step == "B17"
        self.calls[name] += 1
        self.order.append(name)
        return ToolResult(name, self.override.get(name, GOOD.get(name)), None, 1, False)


def _ex(
    override: Mapping[str, Any] | None = None,
) -> tuple[PlanExecutor, StubWriter, MemoryTxLog]:
    writer = StubWriter(override)
    txlog = MemoryTxLog()
    return PlanExecutor(writer, txlog, FakeClock(NOW), tz=TZ), writer, txlog


def _paid() -> Any:
    return action("install_software", params={"device_id": "LAP-0342", "software_name": "adobe-acrobat-pro"},
                  facts={"in_catalog": True, "license_paid": True, "requires_local_admin": False})  # fmt: skip


# ---- kết quả đúng → vẫn thành công như trước ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_type",
    ["renew_vpn_cert", "reissue_vpn_access", "reset_password", "unlock_account", "install_software", "grant_permission",
     "extend_permission"],
)  # fmt: skip
async def test_dung_ket_qua_van_thanh_cong(action_type: str) -> None:
    ex, writer, _ = _ex()
    res = await ex.execute("t1", "T1", action(action_type))
    assert res.success, res.handoff_note
    assert sum(writer.calls.values()) == 1


async def test_dung_ket_qua_hai_buoc_co_phi() -> None:
    ex, writer, _ = _ex()
    res = await ex.execute("t1", "T1", _paid())
    assert res.success and writer.order == ["assign_paid_license", "install_software"]


async def test_duong_dan_chuan_hoa_va_ma_may_khong_phan_biet_hoa_thuong_van_dung() -> (
    None
):
    """Mock chuẩn hoá đường dẫn (bỏ "/" hai đầu); mã máy so không phân biệt hoa thường."""
    ex, _, _ = _ex(
        {
            "grant_permission": _grant(path="/finance/public-reports/"),
            "renew_vpn_cert": _cert(device="lap-0342"),
        }
    )
    assert (await ex.execute("t1", "T1", action("grant_permission"))).success
    ex, _, _ = _ex({"renew_vpn_cert": _cert(device="lap-0342")})
    assert (await ex.execute("t1", "T1", action("renew_vpn_cert"))).success


# ---- kết quả sai → lỗi unexpected_result, E7 có ghi chú ---------------------------------------------------------------------


SAI: list[tuple[str, str, Any, str]] = [
    ("renew_vpn_cert", "renew_vpn_cert", _cert(status="revoked"), "cert_not_valid"),
    ("renew_vpn_cert", "renew_vpn_cert", _cert(device="LAP-0417"), "device_mismatch"),
    (
        "reissue_vpn_access",
        "reissue_vpn_access",
        _cert(status="expired"),
        "cert_not_valid",
    ),
    ("unlock_account", "unlock_account", _unlock(locked=True), "still_locked"),
    ("unlock_account", "unlock_account", _unlock(user="nv002"), "user_mismatch"),
    ("reset_password", "reset_password", _reset(user="nv002"), "user_mismatch"),
    ("reset_password", "reset_password", _reset(via="none"), "not_delivered"),
    (
        "reset_password",
        "reset_password",
        _reset(account_type="email"),
        "account_type_mismatch",
    ),
    (
        "install_software",
        "install_software",
        _install(device="LAP-0417"),
        "device_mismatch",
    ),
    (
        "grant_permission",
        "grant_permission",
        _grant(status="expired"),
        "permission_not_active",
    ),
    ("grant_permission", "grant_permission", _grant(level="write"), "level_mismatch"),
    (
        "grant_permission",
        "grant_permission",
        _grant(path="hr/salaries"),
        "path_mismatch",
    ),
    (
        "extend_permission",
        "extend_permission",
        _extend(status="expired"),
        "permission_not_active",
    ),
    (
        "extend_permission",
        "extend_permission",
        _extend(path="finance/Q4"),
        "path_mismatch",
    ),
]


@pytest.mark.parametrize(
    ("action_type", "tool", "bad", "reason"),
    SAI,
    ids=[f"{t}-{r}" for _, t, _, r in SAI],
)
async def test_ket_qua_sai_la_loi_khong_bao_da_lam(
    action_type: str, tool: str, bad: Any, reason: str
) -> None:
    ex, writer, txlog = _ex({tool: bad})
    res = await ex.execute("t1", "T1", action(action_type))
    assert (res.success, res.failed_step, res.steps_done) == (False, tool, [])
    assert (
        writer.calls[tool] == 1 and sum(writer.calls.values()) == 1
    )  # KHÔNG hoàn tác chính bước trả sai
    assert (res.rollback_status, res.outputs) == ("none_needed", {})
    note = res.handoff_note or ""
    assert (
        f"Lỗi ở bước: {tool} (unexpected_result)" in note and MAYBE_APPLIED in note
    ), note
    assert "kết quả không khớp yêu cầu" in note
    assert txlog.statuses() == [(tool, "begun")]


@pytest.mark.parametrize(
    ("action_type", "tool", "bad", "reason"),
    SAI,
    ids=[f"{t}-{r}" for _, t, _, r in SAI],
)
async def test_ten_dieu_kien_hong(
    action_type: str, tool: str, bad: Any, reason: str
) -> None:
    from app.executor.plans import step_args

    assert unexpected_result(tool, step_args(tool, action(action_type)), bad) == reason


async def test_buoc_hai_sai_doi_tuong_sau_khi_cap_license_ghi_chu_license() -> None:
    """Hai bước: license đã cấp, cài trả về máy khác → lỗi ở bước 2, license KHÔNG hoàn tác, ghi chú nêu license đã cấp."""
    ex, writer, _ = _ex(
        {"install_software": _install(device="LAP-0417", name="adobe-acrobat-pro")}
    )
    res = await ex.execute("t1", "T1", _paid())
    assert (res.success, res.failed_step, res.steps_done) == (
        False,
        "install_software",
        ["assign_paid_license"],
    )
    assert writer.order == ["assign_paid_license", "install_software"]
    note = res.handoff_note or ""
    assert "ĐÃ cấp cho nv001" in note and MAYBE_APPLIED in note


async def test_buoc_mot_sai_nguoi_khong_cai() -> None:
    ex, writer, _ = _ex({"assign_paid_license": _assign(user="nv002")})
    res = await ex.execute("t1", "T1", _paid())
    assert (res.success, res.failed_step) == (False, "assign_paid_license")
    assert writer.order == ["assign_paid_license"]


async def test_ket_qua_rong_cua_buoc_ghi_la_loi() -> None:
    ex, _, _ = _ex({"renew_vpn_cert": None})
    res = await ex.execute("t1", "T1", action("renew_vpn_cert"))
    assert (res.success, res.failed_step) == (False, "renew_vpn_cert")


def test_ma_loi_tap_dong_va_thuoc_nhom_co_the_da_ap_dung() -> None:
    assert error_kind("unexpected_result") == "unexpected_result"
    assert "unexpected_result" in MAYBE_APPLIED_KINDS


def test_cong_cu_hoan_tac_khong_kiem() -> None:
    """Hậu điều kiện chỉ cho bước GHI chính; tool hoàn tác (lock/revoke/uninstall…) đi đường riêng của `_rollback`."""
    assert (
        unexpected_result("lock_account", {"user_id": "nv001"}, _unlock(locked=True))
        is None
    )
    assert (
        unexpected_result(
            "revoke_vpn_cert", {"user_id": "nv001"}, _cert(status="revoked")
        )
        is None
    )
