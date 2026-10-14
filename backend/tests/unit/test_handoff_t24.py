"""T24 bảng 7.5 — test-first: ghi chú bàn giao E7 theo hành động (phase5 7.1 P5, bảng 7.4) — ca m4.

`handoff_note` đủ 4 phần "Đã làm: … Lỗi ở bước: <tool> (<mã>). Hoàn tác: … L2 cần làm tay: …"; câu "L2 cần làm tay" theo bảng 7.4
(`{loại}`: ad → "đăng nhập (AD)", email → "email", erp → "ERP"); lỗi `timeout`/`http_5xx`/`other` có tiền tố "lệnh ở bước {tool} có thể
đã được áp dụng — kiểm trên hệ thống đích trước khi làm lại". Không bao giờ chép chữ lỗi / thân phản hồi của hệ thống ngoài.
"""

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from app.domain.action import Action
from tests.fakes.executor import http_error
from tests.unit._t24 import RAW_DETAIL, action, executor

pytestmark = pytest.mark.asyncio

PARTS = ("Đã làm:", "Lỗi ở bước:", "Hoàn tác:", "L2 cần làm tay:")


def _prefix(tool: str) -> str:
    return f"lệnh ở bước {tool} có thể đã được áp dụng — kiểm trên hệ thống đích trước khi làm lại"


def _paid() -> Action:
    return action("install_software", params={"device_id": "LAP-0342", "software_name": "adobe-acrobat-pro"},
                  facts={"license_paid": True})  # fmt: skip


def _free() -> Action:
    return action("install_software", params={"device_id": "LAP-0342", "software_name": "zoom"},
                  facts={"license_paid": False})  # fmt: skip


async def _note(act: Action, faults: dict[str, Callable[[], BaseException]]) -> str:
    ex, writes, _, _ = executor()
    writes.faults.update(faults)
    res = await ex.execute("t1", "T1", act)
    assert not res.success
    return res.handoff_note or ""


def _four_parts(note: str) -> None:
    for part in PARTS:
        assert part in note, (part, note)
    assert RAW_DETAIL not in note and "http://" not in note


CASES: list[Any] = [
    pytest.param(
        action("reset_password", rf="nv005", params={"account_type": "ad"}), {"reset_password": lambda: http_error(404, RAW_DETAIL)},
        "reset_password (http_404)",
        ["tài khoản đăng nhập (AD) của nv005 không tồn tại — xác minh lại với người dùng"], id="m4-reset-404",
    ),
    pytest.param(
        action("unlock_account", rf="nv001", params={"account_type": "email"}),
        {"unlock_account": lambda: http_error(404, RAW_DETAIL)}, "unlock_account (http_404)",
        ["tài khoản email của nv001 không tồn tại — xác minh lại với người dùng"], id="m4-unlock-404-email",
    ),
    pytest.param(
        action("reset_password", rf="nv005", params={"account_type": "erp"}), {"reset_password": lambda: http_error(409, RAW_DETAIL)},
        "reset_password (http_409)",
        ["kiểm tài khoản ERP của nv005 trên AD; thực hiện reset_password bằng tay nếu vẫn cần"], id="m4-reset-409-khac",
    ),
    pytest.param(
        action("unlock_account", rf="nv001", params={"account_type": "ad"}), {"unlock_account": lambda: http_error(500, RAW_DETAIL)},
        "unlock_account (http_5xx)",
        [_prefix("unlock_account"), "kiểm tài khoản đăng nhập (AD) của nv001 trên AD; thực hiện unlock_account bằng tay nếu vẫn cần"],
        id="m4-unlock-500",
    ),
    pytest.param(
        _paid(), {"assign_paid_license": lambda: http_error(409, "no_license_available")}, "assign_paid_license (http_409)",
        ["hết license adobe-acrobat-pro (hoặc không phải phần mềm có phí) — xin thêm license rồi cài lại"], id="m4-install-assign-409",
    ),
    pytest.param(
        _free(), {"install_software": lambda: http_error(404, RAW_DETAIL)}, "install_software (http_404)",
        ["máy LAP-0342 hoặc phần mềm zoom không có trên hệ thống — xác minh lại"], id="m4-install-404",
    ),
    pytest.param(
        _paid(), {"install_software": lambda: http_error(500, RAW_DETAIL)}, "install_software (http_5xx)",
        [_prefix("install_software"),
         "license adobe-acrobat-pro ĐÃ cấp cho nv001 và KHÔNG được thu hồi tự động — cài bằng tay hoặc thu hồi license",
         "assign_paid_license: not_reversible"],
        id="m4-install-sau-license-500",
    ),
    pytest.param(
        _free(), {"install_software": lambda: httpx.ReadTimeout(RAW_DETAIL)}, "install_software (timeout)",
        [_prefix("install_software")], id="m4-install-timeout",
    ),
    pytest.param(
        action("grant_permission"), {"grant_permission": lambda: http_error(404, RAW_DETAIL)}, "grant_permission (http_404)",
        ["thư mục finance/public-reports không tồn tại — xác minh lại đường dẫn"], id="m4-grant-404",
    ),
    pytest.param(
        action("grant_permission"), {"grant_permission": lambda: http_error(502, RAW_DETAIL)}, "grant_permission (http_5xx)",
        [_prefix("grant_permission")], id="m4-grant-502",
    ),
    pytest.param(
        action("extend_permission", rf="nv005"), {"extend_permission": lambda: http_error(404, RAW_DETAIL)},
        "extend_permission (http_404)",
        ["nv005 chưa có quyền trên finance/Q3 — không gia hạn được, cân nhắc cấp mới (cần duyệt)"], id="m4-extend-404",
    ),
    pytest.param(
        action("extend_permission"), {"extend_permission": lambda: httpx.ReadTimeout(RAW_DETAIL)}, "extend_permission (timeout)",
        [_prefix("extend_permission")], id="m4-extend-timeout",
    ),
]  # fmt: skip


@pytest.mark.parametrize(("act", "faults", "step", "sentences"), CASES)
async def test_m4_handoff_four_parts_and_l2_sentence(
    act: Action, faults: dict[str, Callable[[], BaseException]], step: str, sentences: list[str]
) -> None:
    """m4 (M-T24-7): đủ 4 cụm, "Lỗi ở bước: <tool> (<mã>)", câu "L2 cần làm tay" đúng bảng 7.4; không chép chữ hệ thống ngoài."""
    note = await _note(act, faults)
    _four_parts(note)
    assert step in note
    for sentence in sentences:
        assert sentence in note, (sentence, note)


async def test_m4_ambiguous_prefix_comes_before_action_sentence() -> None:
    """Bảng 7.4: câu "có thể đã được áp dụng" là TIỀN TỐ — đứng trước câu theo hành động."""
    note = await _note(action("unlock_account", params={"account_type": "ad"}), {"unlock_account": lambda: http_error(500)})
    assert note.index(_prefix("unlock_account")) < note.index("kiểm tài khoản đăng nhập (AD) của nv001 trên AD")


@pytest.mark.parametrize(
    ("fault", "maybe"),
    [(lambda: http_error(409), False), (lambda: http_error(404), False), (lambda: httpx.ConnectError("x"), False),
     (lambda: http_error(500), True), (lambda: httpx.ReadTimeout("x"), True)],
    ids=["409", "404", "connect", "500", "timeout"],
)  # fmt: skip
async def test_m4_maybe_applied_only_for_ambiguous_errors(fault: Callable[[], BaseException], maybe: bool) -> None:
    """Giữ 3h: chỉ lỗi mơ hồ (timeout / 5xx / other) mới nói "có thể đã được áp dụng"."""
    note = await _note(action("grant_permission"), {"grant_permission": fault})
    assert ("có thể đã được áp dụng" in note) is maybe


@pytest.mark.parametrize(
    ("act", "tool", "raw"),
    [
        pytest.param(action("grant_permission", params={"resource_path": "finance/../hr", "permission_level": "read",
                                                        "duration_days": 30}), "grant_permission", "finance/../hr",
                     id="path-co-dot-dot"),
        pytest.param(action("install_software", params={"device_id": "LAP-0342; <b>rm -rf</b>", "software_name": "zoom"},
                            facts={"license_paid": False}), "install_software", "rm -rf", id="device-rac"),
        pytest.param(action("reset_password", rf="NV005<script>", params={"account_type": "ad"}), "reset_password",
                     "<script>", id="user-rac"),
    ],
)  # fmt: skip
async def test_m4_identifiers_through_regex(act: Action, tool: str, raw: str) -> None:
    """P5: định danh trong ghi chú chỉ ghép khi qua mẫu (`USER_ID`, `DEVICE_ID`, `RESOURCE_PATH`) — chuỗi rác không vào ghi chú."""
    note = await _note(act, {tool: lambda: http_error(404, RAW_DETAIL)})
    _four_parts(note)
    assert raw not in note
