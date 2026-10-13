"""T24 bảng 7.5 — test-first: N8 (phase5 7.1 P9; chốt Q-T24-6 = A, duyệt MẪU B DỪNG 1 13/10) — `access.same_department`.

CẢ HAI phòng ban (`check_account_status.department` của `requested_for`, `check_resource_sensitivity.owner_department`) rỗng → KHÔNG có
fact `same_department` (chuỗi rỗng không phải "cùng phòng"); MỘT phía rỗng → `False` (R09 vẫn bắt — không xuống lớp 2, Q-T24-6).
Đối chứng: hai phía cùng "Finance" → True, khác → False. Dữ liệu: seed
(`tests/unit/_t20a.Env`, nv001 Finance, nv002 Engineering, `finance/public-reports` của Finance) — chỉ sửa bản giả trong test.
"""

from typing import Any

import pytest
from app.tools.diagnosis import access
from tests.unit._t20a import Env

pytestmark = pytest.mark.asyncio

PATH = "finance/public-reports"


def _slots(path: str = PATH) -> dict[str, str]:
    return {"action": "extend_permission", "resource_path": path, "duration": "30"}


async def _facts(env: Env, requester: str = "nv001") -> dict[str, Any]:
    _, _, _, facts = await env.diagnose(access, requester, _slots())
    return facts


async def test_n8_control_same_department_true() -> None:
    env = Env()
    assert env.tools.users["nv001"]["department"] == env.tools.resources[PATH]["owner_department"] == "Finance"
    assert (await _facts(env))["same_department"] is True


async def test_n8_control_other_department_false() -> None:
    env = Env()
    assert env.tools.users["nv002"]["department"] != env.tools.resources[PATH]["owner_department"]
    assert (await _facts(env, "nv002"))["same_department"] is False


async def test_n8_user_department_empty_false() -> None:
    """Q-T24-6 = A: chỉ phòng ban của người được cấp rỗng → `same_department=False` (R09 vẫn khớp)."""
    env = Env()
    env.tools.users["nv001"]["department"] = ""
    facts = await _facts(env)
    assert facts["same_department"] is False
    assert facts["resource_sensitivity"] == "low"  # fact khác của thư mục vẫn có


async def test_n8_owner_department_empty_false() -> None:
    """Q-T24-6 = A: chỉ `owner_department` của thư mục rỗng → `same_department=False` (R09 vẫn khớp)."""
    env = Env()
    env.tools.resources[PATH]["owner_department"] = ""
    assert (await _facts(env))["same_department"] is False


async def test_n8_both_empty_not_true() -> None:
    """N8 (M-T24-12): HAI phía đều rỗng — so sánh ngây thơ cho True — phải KHÔNG đặt `same_department`."""
    env = Env()
    env.tools.users["nv001"]["department"] = ""
    env.tools.resources[PATH]["owner_department"] = ""
    assert "same_department" not in await _facts(env)
