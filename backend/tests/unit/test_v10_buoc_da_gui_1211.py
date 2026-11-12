"""V10 soát 12/11 (agent 12 M3): kế hoạch nhiều bước bị gián đoạn (lỗi SAU `begun`) → `ExecutionInterrupted.steps_begun` mang tên các
bước đã gửi; B17 ghép ghi chú L2 = câu "có thể đã gửi" + "Bước đã gửi: …" + câu license (KHÔNG thu hồi tự động — D-48)."""

import httpx
import pytest
from app.executor.errors import ExecutionInterrupted
from app.graph.nodes.b17_execute import steps_note
from tests.unit._t24 import action, executor

pytestmark = pytest.mark.asyncio


def _paid():  # type: ignore[no-untyped-def]
    return action("install_software", params={"device_id": "LAP-0342", "software_name": "adobe-acrobat-pro"},
                  facts={"in_catalog": True, "license_paid": True, "requires_local_admin": False})  # fmt: skip


async def test_buoc_hai_dut_ket_noi_mang_ten_buoc_da_gui() -> None:
    ex, writes, _, _ = executor()
    writes.faults["install_software"] = lambda: httpx.ReadError("đứt sau khi gửi")
    with pytest.raises(ExecutionInterrupted) as info:
        await ex.execute("t1", "T1", _paid())
    assert info.value.steps_begun == ("assign_paid_license", "install_software")
    assert info.value.write_calls == 2


def test_ghi_chu_neu_buoc_va_license() -> None:
    note = steps_note(_paid(), ("assign_paid_license", "install_software"))
    assert "Bước đã gửi: assign_paid_license, install_software." in note
    assert "License adobe-acrobat-pro có thể ĐÃ cấp cho nv001" in note and "KHÔNG được thu hồi tự động" in note


def test_mot_buoc_khong_co_cau_license() -> None:
    note = steps_note(action("renew_vpn_cert"), ("renew_vpn_cert",))
    assert note == " Bước đã gửi: renew_vpn_cert." and "License" not in note


def test_khong_buoc_nao_khong_them_gi() -> None:
    assert steps_note(_paid(), ()) == ""


async def test_m4_may_da_co_phan_mem_co_phi_khong_cap_license() -> None:
    """V10 (agent 12 M4): máy ĐÃ có phần mềm có phí → PLAN bỏ bước cấp license (trước: trừ license vô ích rồi "đã có sẵn")."""
    ex, writes, _, _ = executor()
    writes.already_installed.add("adobe-acrobat-pro")
    paid_installed = action("install_software", params={"device_id": "LAP-0342", "software_name": "adobe-acrobat-pro"},
                            facts={"in_catalog": True, "license_paid": True, "requires_local_admin": False,
                                   "software_installed_on_device": True})  # fmt: skip
    res = await ex.execute("t1", "T1", paid_installed)
    assert res.success and writes.order == ["install_software"]
    assert writes.license_used["adobe-acrobat-pro"] == 7  # không trừ
    assert res.outputs.get("already_installed") == "true"


async def test_m4_chua_co_van_cap_license_truoc() -> None:
    ex, writes, _, _ = executor()
    res = await ex.execute("t1", "T1", action("install_software", params={"device_id": "LAP-0342",
                                                                         "software_name": "adobe-acrobat-pro"},
                                              facts={"in_catalog": True, "license_paid": True, "requires_local_admin": False,
                                                     "software_installed_on_device": False}))  # fmt: skip
    assert res.success and writes.order == ["assign_paid_license", "install_software"]
