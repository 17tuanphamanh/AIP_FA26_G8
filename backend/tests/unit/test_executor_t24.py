"""T24 bảng 7.5 — test-first: `PlanExecutor` (phase5 7.1 P3, P4; bảng 7.2) — ca x1–x9 + mẫu `outputs` (P4).

Registry GHI thật (retries=0) trên hệ thống ghi AD / phần mềm / file server giả (`tests/unit/_t24.FakeWrites`, đếm ở NƠI NHẬN) +
`transaction_log` trong bộ nhớ. Bất biến: `begun` TRƯỚC mỗi lời gọi, mỗi bước gọi ĐÚNG 1 lần. Lỗi bước k → hoàn tác ngược các bước
đã xong; bước `undo=None` KHÔNG gọi, chi tiết `(tool, "not_reversible")`.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.domain.ticket_state import ExecutionResult
from app.executor.plan_executor import PlanExecutor
from app.executor.plans import Step
from tests.fakes.executor import FakeVpnWrites, MemoryTxLog, http_error
from tests.unit._t24 import NOW, RAW_DETAIL, TZ, action, executor

pytestmark = pytest.mark.asyncio

MAYBE_APPLIED = "có thể đã được áp dụng"
LICENSE_KEPT = ("license adobe-acrobat-pro ĐÃ cấp cho nv001 và KHÔNG được thu hồi tự động — cài bằng tay hoặc thu hồi "
                "license")  # fmt: skip


def _paid(**facts: Any) -> Any:
    return action("install_software", params={"device_id": "LAP-0342", "software_name": "adobe-acrobat-pro"},
                  facts={"in_catalog": True, "license_paid": True, "requires_local_admin": False, **facts})  # fmt: skip


def _free() -> Any:
    return action("install_software", params={"device_id": "LAP-0342", "software_name": "zoom"},
                  facts={"in_catalog": True, "license_paid": False, "requires_local_admin": False})  # fmt: skip


# ---- x1–x3: install có phí / miễn phí --------------------------------------------------------------------------------------


async def test_x1_paid_install_fails_after_license_no_undo_call() -> None:
    """x1 (M-T24-1, M-T24-2): assign OK, install 500 → 2 lời gọi ghi, 0 hoàn tác (không uninstall, không thu hồi license);
    `not_attempted`, chi tiết `[("assign_paid_license", "not_reversible")]`; ghi chú có câu license 7.4 + "có thể đã được áp dụng"."""
    ex, writes, txlog, _ = executor()
    writes.faults["install_software"] = lambda: http_error(500, RAW_DETAIL)
    res = await ex.execute("t1", "T1", _paid())
    assert dict(writes.calls) == {"assign_paid_license": 1, "install_software": 1}
    assert writes.order == ["assign_paid_license", "install_software"]
    assert (res.success, res.steps_done, res.failed_step) == (False, ["assign_paid_license"], "install_software")
    assert res.rollback_status == "not_attempted"
    assert res.rollback_details == [("assign_paid_license", "not_reversible")]
    assert writes.seen["assign_paid_license"] == [{"software_name": "adobe-acrobat-pro", "user_id": "nv001"}]
    assert txlog.statuses()[:2] == [("assign_paid_license", "begun"), ("install_software", "begun")]
    assert not [r for r in txlog.rows if r["status"] == "undone"]
    note = res.handoff_note or ""
    assert LICENSE_KEPT in note and MAYBE_APPLIED in note
    assert "assign_paid_license: not_reversible" in note
    assert RAW_DETAIL not in note
    assert res.outputs == {}


async def test_x2_paid_install_assign_409_one_call_none_needed() -> None:
    """x2: assign 409 (`no_license_available`) → 1 lời gọi, KHÔNG cài; `none_needed`; ghi chú "hết license"."""
    ex, writes, _, _ = executor()
    writes.faults["assign_paid_license"] = lambda: http_error(409, "no_license_available")
    res = await ex.execute("t1", "T1", _paid())
    assert dict(writes.calls) == {"assign_paid_license": 1}
    assert (res.success, res.steps_done, res.failed_step) == (False, [], "assign_paid_license")
    assert (res.rollback_status, res.rollback_details) == ("none_needed", [])
    note = res.handoff_note or ""
    assert "hết license adobe-acrobat-pro" in note
    assert "no_license_available" not in note


async def test_x3_free_install_500_one_call_none_needed() -> None:
    """x3: miễn phí (`license_paid=False`) → không assign; install 500 → 1 lời gọi, `none_needed`, "có thể đã được áp dụng"."""
    ex, writes, _, _ = executor()
    writes.faults["install_software"] = lambda: http_error(500, RAW_DETAIL)
    res = await ex.execute("t1", "T1", _free())
    assert dict(writes.calls) == {"install_software": 1}
    assert (res.success, res.steps_done, res.failed_step) == (False, [], "install_software")
    assert (res.rollback_status, res.rollback_details) == ("none_needed", [])
    assert MAYBE_APPLIED in (res.handoff_note or "")
    assert RAW_DETAIL not in (res.handoff_note or "")


async def test_p3_executor_missing_license_paid_assigns_first() -> None:
    """p3 ở mức executor (M-T24-3, 7.8 mục 5): thiếu `license_paid` → VẪN cấp license trước khi cài."""
    ex, writes, _, _ = executor()
    res = await ex.execute("t1", "T1", action("install_software", params={"device_id": "LAP-0342",
                                                                         "software_name": "adobe-acrobat-pro"},
                                              facts={"in_catalog": True}))  # fmt: skip
    assert res.success and writes.order == ["assign_paid_license", "install_software"]


# ---- x4: thành công — outputs ----------------------------------------------------------------------------------------------


async def test_x4_reset_success_outputs_delivered_via() -> None:
    ex, writes, txlog, _ = executor()
    res = await ex.execute("t1", "T1", action("reset_password", rf="nv005"))
    assert (res.success, res.steps_done, res.rollback_status) == (True, ["reset_password"], "none_needed")
    assert res.outputs == {"delivered_via": "email"}
    assert dict(writes.calls) == {"reset_password": 1}
    assert writes.seen["reset_password"] == [{"user_id": "nv005", "account_type": "ad"}]
    assert txlog.statuses() == [("reset_password", "begun")]
    assert writes.begun_before == {"reset_password": True}


async def test_x4_unlock_success_single_call() -> None:
    ex, writes, _, _ = executor()
    res = await ex.execute("t1", "T1", action("unlock_account", rf="nv001", params={"account_type": "email"}))
    assert res.success and dict(writes.calls) == {"unlock_account": 1}
    assert writes.seen["unlock_account"] == [{"user_id": "nv001", "account_type": "email"}]


async def test_x4_grant_success_outputs_level_and_local_date() -> None:
    """x4: grant → `{"level": "read", "expires_on": <ngày ĐỊA PHƯƠNG>}` (NOW 03:00Z + 30 ngày = 29/10 giờ VN)."""
    ex, writes, _, _ = executor()
    res = await ex.execute("t1", "T1", action("grant_permission"))
    assert res.success and res.rollback_status == "none_needed"
    assert res.outputs == {"level": "read", "expires_on": "2026-10-29"}
    assert writes.seen["grant_permission"] == [{"user_id": "nv001", "resource_path": "finance/public-reports",
                                                "level": "read", "duration_days": 30}]  # fmt: skip


async def test_x4_grant_expires_on_is_local_date() -> None:
    """x4: 20:00Z = 03:00 hôm sau giờ VN → ngày hết hạn theo giờ địa phương (30/10, không phải 29/10)."""
    ex, _, _, _ = executor(at=datetime(2026, 9, 29, 20, 0, tzinfo=UTC))
    res = await ex.execute("t1", "T1", action("grant_permission"))
    assert res.outputs["expires_on"] == "2026-10-30"


async def test_x4_extend_success_outputs() -> None:
    """x4: extend → `{"level", "expires_on"}`; hạn cũ NOW+5 ngày + 30 ngày = 03/11; không gửi mức quyền (nơi nhận)."""
    ex, writes, _, _ = executor()
    res = await ex.execute("t1", "T1", action("extend_permission"))
    assert res.success and res.outputs == {"level": "read", "expires_on": "2026-11-03"}
    assert writes.seen["extend_permission"] == [{"user_id": "nv001", "resource_path": "finance/Q3", "duration_days": 30}]


async def test_x4_free_install_outputs_software_version() -> None:
    ex, writes, _, _ = executor()
    res = await ex.execute("t1", "T1", _free())
    assert res.success and dict(writes.calls) == {"install_software": 1}
    assert res.outputs == {"software": "zoom", "version": "6.1.0"}


async def test_x4_paid_install_outputs_license_id() -> None:
    ex, writes, txlog, _ = executor()
    res = await ex.execute("t1", "T1", _paid())
    assert res.success and res.steps_done == ["assign_paid_license", "install_software"]
    assert res.outputs == {"software": "adobe-acrobat-pro", "version": "2024.1", "license_id": "LIC-adobe-acrobat-pro-008"}
    assert txlog.statuses() == [("assign_paid_license", "begun"), ("install_software", "begun")]
    assert writes.begun_before == {"assign_paid_license": True, "install_software": True}


@pytest.mark.parametrize(
    ("outputs", "kept"),
    [
        pytest.param({"delivered_via": "email"}, {"delivered_via": "email"}, id="delivered-email"),
        pytest.param({"delivered_via": "sms"}, {"delivered_via": "sms"}, id="delivered-sms"),
        pytest.param({"delivered_via": "fax"}, {}, id="delivered-la"),
        pytest.param({"version": "6.1.0"}, {"version": "6.1.0"}, id="version"),
        pytest.param({"version": "1.0; rm -rf"}, {}, id="version-rac"),
        pytest.param({"version": "x" * 33}, {}, id="version-dai"),
        pytest.param({"version": "pay.evil-site.com"}, {}, id="version-ten-mien"),  # Q-T24-7: chỉ số + dấu chấm
        pytest.param({"version": "2024"}, {"version": "2024"}, id="version-mot-so"),
        pytest.param({"level": "write"}, {"level": "write"}, id="level"),
        pytest.param({"level": "admin"}, {}, id="level-la"),
        pytest.param({"software": "adobe-acrobat-pro"}, {"software": "adobe-acrobat-pro"}, id="software"),
        pytest.param({"software": "Zoom Pro; x"}, {}, id="software-rac"),
        pytest.param({"license_id": "LIC-adobe-acrobat-pro-008"}, {"license_id": "LIC-adobe-acrobat-pro-008"}, id="lic"),
        pytest.param({"license_id": "LIC-adobe-acrobat-pro-8"}, {}, id="lic-sai-mau"),
        pytest.param({"password": "Abc123!"}, {}, id="khoa-la-mat-khau"),
        pytest.param({"serial": "VPN-NEW-0001", "expires_on": "2027-09-29"},
                     {"serial": "VPN-NEW-0001", "expires_on": "2027-09-29"}, id="vpn-cu"),
    ],
)  # fmt: skip
async def test_x4_exec_output_patterns_p4(outputs: dict[str, Any], kept: dict[str, str]) -> None:
    """P4: `EXEC_OUTPUT_PATTERNS` thêm `delivered_via`, `version`, `level`, `software`, `license_id`; khoá lạ / sai mẫu bị BỎ."""
    res = ExecutionResult(success=True, steps_done=[], failed_step=None, rollback_status="none_needed", rollback_details=[],
                          action_plan_hash_matched=None, handoff_note=None, outputs=outputs)  # fmt: skip
    assert res.outputs == kept


# ---- x5: view_permissions ----------------------------------------------------------------------------------------------------


async def test_x5_view_permissions_no_write_no_begun() -> None:
    ex, writes, txlog, _ = executor()
    res = await ex.execute("t1", "T1", action("view_permissions"))
    assert res.success and res.steps_done == [] and res.failed_step is None
    assert (res.rollback_status, res.rollback_details, res.handoff_note) == ("none_needed", [], None)
    assert writes.total() == 0 and txlog.rows == []
    assert res.outputs == {}


# ---- x6–x8: PLAN tiêm — hoàn tác theo từng bước ------------------------------------------------------------------------------


def _grant_then_extend() -> dict[str, tuple[Step, ...]]:
    return {"grant_permission": (Step("grant_permission", undo="revoke_permission"),
                                 Step("extend_permission", undo="restore_permission_expiry"))}  # fmt: skip


async def test_x6_two_reversible_steps_second_fails_first_undone() -> None:
    """x6: bước 2 lỗi 409 → bước 1 `undone`, `rollback_status="undone"`, 3 lời gọi (grant, extend, revoke)."""
    ex, writes, txlog, _ = executor(_grant_then_extend())
    writes.faults["extend_permission"] = lambda: http_error(409, RAW_DETAIL)
    res = await ex.execute("t1", "T1", action("grant_permission"))
    assert (res.success, res.steps_done, res.failed_step) == (False, ["grant_permission"], "extend_permission")
    assert (res.rollback_status, res.rollback_details) == ("undone", [("grant_permission", "undone")])
    assert dict(writes.calls) == {"grant_permission": 1, "extend_permission": 1, "revoke_permission": 1}
    assert writes.order == ["grant_permission", "extend_permission", "revoke_permission"]
    assert writes.seen["revoke_permission"] == [{"user_id": "nv001", "resource_path": "finance/public-reports"}]
    assert txlog.statuses() == [("grant_permission", "begun"), ("extend_permission", "begun"), ("grant_permission", "undone")]


async def test_x7_undo_fails_undo_failed_logged() -> None:
    """x7: như x6, hoàn tác lỗi 503 → `undo_failed` + dòng txlog `undo_failed` detail `"UNDO_FAILED: http_5xx"`; ghi chú không chép
    chữ hệ thống ngoài."""
    ex, writes, txlog, _ = executor(_grant_then_extend())
    writes.faults["extend_permission"] = lambda: http_error(409)
    writes.faults["revoke_permission"] = lambda: http_error(503, RAW_DETAIL)
    res = await ex.execute("t1", "T1", action("grant_permission"))
    assert (res.rollback_status, res.rollback_details) == ("undo_failed", [("grant_permission", "UNDO_FAILED: http_5xx")])
    assert txlog.rows[-1] == {"ticket_id": "t1", "turn_id": "T1", "step_name": "grant_permission", "status": "undo_failed",
                              "detail": "UNDO_FAILED: http_5xx"}  # fmt: skip
    assert writes.calls["revoke_permission"] == 1
    assert RAW_DETAIL not in (res.handoff_note or "")


async def test_x8_three_steps_partial_rollback_order() -> None:
    """x8 (M-T24-1): grant[undo revoke] → assign[undo None] → install lỗi → `partial`; chi tiết theo thứ tự hoàn tác (ngược):
    `[("assign_paid_license", "not_reversible"), ("grant_permission", "undone")]`; KHÔNG gọi uninstall / thu hồi license."""
    plans = {"install_software": (Step("grant_permission", undo="revoke_permission"), Step("assign_paid_license"),
                                  Step("install_software", undo="uninstall_software"))}  # fmt: skip
    ex, writes, _, _ = executor(plans)
    writes.faults["install_software"] = lambda: http_error(500)
    act = action("install_software", params={"device_id": "LAP-0342", "software_name": "adobe-acrobat-pro",
                                             "resource_path": "finance/public-reports", "permission_level": "read",
                                             "duration_days": 30}, facts={"license_paid": True})  # fmt: skip
    res = await ex.execute("t1", "T1", act)
    assert res.steps_done == ["grant_permission", "assign_paid_license"] and res.failed_step == "install_software"
    assert res.rollback_status == "partial"
    assert res.rollback_details == [("assign_paid_license", "not_reversible"), ("grant_permission", "undone")]
    assert dict(writes.calls) == {"grant_permission": 1, "assign_paid_license": 1, "install_software": 1,
                                  "revoke_permission": 1}  # fmt: skip
    assert "uninstall_software" not in writes.calls


async def test_x8_not_reversible_action_not_attempted_zero_undo_calls() -> None:
    """P3: `action.reversible=False` → `not_attempted`, 0 lời gọi hoàn tác (như cũ)."""
    ex, writes, _, _ = executor(_grant_then_extend())
    writes.faults["extend_permission"] = lambda: http_error(500)
    res = await ex.execute("t1", "T1", action("grant_permission", reversible=False))
    assert res.rollback_status == "not_attempted" and writes.calls["revoke_permission"] == 0


async def test_x6_extend_undo_restores_previous_expiry() -> None:
    """Bảng 7.2: hoàn tác extend = `restore_permission_expiry(expires_at=previous_expires_at)` — PLAN tiêm extend → grant lỗi."""
    plans = {"extend_permission": (Step("extend_permission", undo="restore_permission_expiry"),
                                   Step("grant_permission", undo="revoke_permission"))}  # fmt: skip
    ex, writes, _, _ = executor(plans)
    writes.faults["grant_permission"] = lambda: http_error(404)
    act = action("extend_permission", params={"resource_path": "finance/Q3", "duration_days": 30,
                                              "permission_level": "read"})  # fmt: skip
    res = await ex.execute("t1", "T1", act)
    assert res.rollback_details == [("extend_permission", "undone")]
    [restore] = writes.seen["restore_permission_expiry"]
    assert restore["user_id"] == "nv001" and restore["resource_path"] == "finance/Q3"
    assert datetime.fromisoformat(restore["expires_at"]) == NOW + timedelta(days=5)


# ---- x9: VPN qua PlanExecutor ---------------------------------------------------------------------------------------------------


async def test_x9_vpn_renew_outputs_unchanged() -> None:
    """x9: VPN renew qua `PlanExecutor` (PLAN mặc định) — `outputs` serial + expires_on như cũ."""
    from app.core.clock import FakeClock

    clock = FakeClock(NOW)
    writes, txlog = FakeVpnWrites(clock), MemoryTxLog()
    ex = PlanExecutor(writes.registry(), txlog, clock, tz=TZ)
    res = await ex.execute("t1", "T1", action("renew_vpn_cert"))
    assert res.success and writes.calls == {"renew_vpn_cert": 1}
    assert res.outputs == {"serial": "VPN-NEW-0001", "expires_on": "2027-09-29"}
    assert txlog.statuses() == [("renew_vpn_cert", "begun")]


async def test_s7_reset_password_result_has_no_password_field() -> None:
    """Soát 7.8 mục 7 (NGHI-3 security-reviewer DỪNG 1): model đầu ra `reset_password` KHÔNG có trường mật khẩu — mật khẩu tạm không
    bao giờ vào `ExecutionResult`/tin/audit (mock gửi thẳng tới SMS/email). Thêm trường kiểu `temp_password` → test đỏ.
    Kênh sms thêm `expires_in_minutes` và `sent_to` (số ĐÃ CHE)."""
    from app.tools.models import ResetPasswordResult

    fields = set(ResetPasswordResult.model_fields)
    assert fields == {"user_id", "account_type", "delivered_via", "must_change_at_next_login", "expires_in_minutes",
                      "sent_to"}  # fmt: skip
    assert not [f for f in fields if "pass" in f.lower() or "secret" in f.lower()]
