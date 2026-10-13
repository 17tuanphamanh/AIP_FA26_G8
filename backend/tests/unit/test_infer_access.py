"""T20a — `tools/diagnosis/access` (phase5 5.1.2 bảng access, 5.1.1 P1, 5.1.6 c1–c8; PLAN-T20a TQ-2, TQ-6, TQ-7, TQ-9).

Viết TỪ ĐẶC TẢ, trước code. `rf` = `slots.target_user` nếu có, không thì người gửi (P6); `path` = `resource_path.strip().strip("/")`.
Lời gọi: `check_current_permissions {user_id: rf, resource_path: path}` (không path → không khoá `resource_path`);
`check_resource_sensitivity {resource_path: path}` chỉ khi có path; `check_manager_chain {user_id: rf}`; `check_account_status
{user_id: rf}` (account_type mặc định ad). Fact: `existing_permission_level` = mức cao nhất read < write < full trên MỌI dòng của đúng
path (kể cả hết hạn), không dòng → không đặt; permissions 404 → không đặt `has_permission_record`, rỗng → False; `same_department`
chỉ khi có cả thư mục lẫn account_status.

Seed: nv001 Finance — quyền `finance/public-reports` read (vĩnh viễn), `finance/Q3` read (còn hạn); nv002 Engineering — `finance/Q3`
read HẾT hạn; nv004 Sales `disabled`/`security`, không dòng quyền; thư mục finance/Q3 high, finance/public-reports low,
engineering/specs medium (Engineering).
"""

from typing import Any

import pytest
from app.tools.diagnosis import access
from tests.unit._t20a import Env

ME = "nv001"
asyncio = pytest.mark.asyncio


async def _run(requester: str, slots: dict[str, str], env: Env | None = None) -> tuple[Any, ...]:
    env = env or Env()
    calls, diag, inferred, facts = await env.diagnose(access, requester, slots)
    return env, calls, diag, inferred, facts


def _extend(path: str, **more: str) -> dict[str, str]:
    return {"action": "extend_permission", "resource_path": path, "duration": "30", **more}


# ---- lời gọi --------------------------------------------------------------------------------------------------------------


def test_calls_with_path_in_tools_order() -> None:
    """5.1.2 access: có path → đủ 4 tool, thứ tự `TOOLS`."""
    assert access.calls(ME, _extend("finance/public-reports")) == [
        ("check_current_permissions", {"user_id": ME, "resource_path": "finance/public-reports"}),
        ("check_resource_sensitivity", {"resource_path": "finance/public-reports"}),
        ("check_manager_chain", {"user_id": ME}),
        ("check_account_status", {"user_id": ME}),
    ]  # fmt: skip


def test_c6_calls_strip_slashes() -> None:
    """c6 / TQ-7: `/finance/Q3/` → tra `finance/Q3` (= `normalize_path` của mock)."""
    calls = dict(access.calls(ME, _extend("/finance/Q3/")))
    assert calls["check_current_permissions"] == {"user_id": ME, "resource_path": "finance/Q3"}
    assert calls["check_resource_sensitivity"] == {"resource_path": "finance/Q3"}


def test_c7_calls_without_path() -> None:
    """c7: không path (`view_permissions`) → không gọi `check_resource_sensitivity`; permissions không khoá `resource_path`."""
    assert access.calls(ME, {"action": "view_permissions"}) == [
        ("check_current_permissions", {"user_id": ME}),
        ("check_manager_chain", {"user_id": ME}),
        ("check_account_status", {"user_id": ME}),
    ]  # fmt: skip


def test_c8_calls_use_target_user() -> None:
    """c8 (P6): `target_user=nv004`, người gửi nv001 → mọi lời gọi có `user_id` đều nv004."""
    calls = access.calls(ME, {"action": "grant_permission", "resource_path": "engineering/specs", "target_user": "nv004"})
    users = [a["user_id"] for _, a in calls if "user_id" in a]
    assert len(users) == 3 and set(users) == {"nv004"}


def test_target_calls_same_rule_on_final_slots() -> None:
    """TQ-3: `target_calls` (B11) cùng quy tắc với `calls` trên slot cuối."""
    for slots in (_extend("finance/Q3"), {"action": "view_permissions"}, _extend("x/y", target_user="nv004")):
        assert access.target_calls(ME, slots) == access.calls(ME, slots)


# ---- c1–c8 ----------------------------------------------------------------------------------------------------------------


@asyncio
async def test_c1_nv001_public_reports() -> None:
    """c1: nv001 `finance/public-reports` → low, same_department True, has_permission_record True, existing read, active."""
    _, _, _, inferred, facts = await _run(ME, _extend("finance/public-reports"))
    assert facts == {
        "resource_sensitivity": "low", "same_department": True, "has_permission_record": True,
        "existing_permission_level": "read", "target_user_status": "active",
    }  # fmt: skip
    assert inferred == {}


@asyncio
async def test_c2_nv002_finance_q3_expired_row() -> None:
    """c2: nv002 `finance/Q3` (dòng hết hạn) → same_department False, has_permission_record True, existing read, high."""
    _, _, _, _, facts = await _run("nv002", _extend("finance/Q3"))
    assert facts["same_department"] is False
    assert (facts["has_permission_record"], facts["existing_permission_level"]) == (True, "read")
    assert facts["resource_sensitivity"] == "high"
    assert facts["target_user_status"] == "active"


@asyncio
async def test_c3_nv001_engineering_specs_no_row() -> None:
    """c3: nv001 `engineering/specs` (không dòng) → has_permission_record False; KHÔNG `existing_permission_level`."""
    _, _, diag, _, facts = await _run(ME, {"action": "grant_permission", "resource_path": "engineering/specs",
                                           "permission_level": "read", "duration": "30"})  # fmt: skip
    assert diag["check_current_permissions"] is not None  # rỗng = RootModel rỗng, KHÔNG None (TQ-2)
    assert facts["has_permission_record"] is False
    assert "existing_permission_level" not in facts
    assert (facts["resource_sensitivity"], facts["same_department"]) == ("medium", False)


@asyncio
@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        pytest.param((("full", -30),), "full", id="c4-read-con-han+full-het-han-cao-nhat-full"),
        pytest.param((("write", None),), "write", id="c4-read+write-write"),
        pytest.param((("write", -1), ("full", 5)), "full", id="c4-read+write+full-full"),
    ],
)
async def test_c4_highest_level_over_all_rows_same_path(extra: tuple[tuple[str, int | None], ...], expected: str) -> None:
    """c4 (seed tạm, P1, M-T20a-2): nhiều dòng cùng path (read sẵn có + các dòng thêm) → mức CAO NHẤT read < write < full, kể cả
    dòng hết hạn."""
    env = Env()
    for level, expires in extra:
        env.tools.add_permission(ME, "finance/public-reports", level, expires_in_days=expires)
    _, _, _, _, facts = await _run(ME, _extend("finance/public-reports"), env)
    assert facts["existing_permission_level"] == expected
    assert facts["has_permission_record"] is True


@asyncio
async def test_c4_rows_of_other_paths_ignored() -> None:
    """P1 "của đúng resource_path": dòng `full` ở thư mục KHÁC không nâng mức của thư mục đang xét."""
    env = Env()
    env.tools.add_permission(ME, "finance/public-reports-2024", "full")
    env.tools.add_permission(ME, "finance", "full")
    _, _, _, _, facts = await _run(ME, _extend("finance/public-reports"), env)
    assert facts["existing_permission_level"] == "read"


@asyncio
async def test_c5_unknown_folder_404_no_folder_facts() -> None:
    """c5 (M-T20a-4): thư mục lạ (404) → không `resource_sensitivity`, không `same_department`."""
    _, _, diag, _, facts = await _run(ME, _extend("finance/khong-co"))
    assert diag["check_resource_sensitivity"] is None
    assert "resource_sensitivity" not in facts and "same_department" not in facts
    assert facts["has_permission_record"] is False  # permissions trả rỗng (user có) → False
    assert "existing_permission_level" not in facts


@asyncio
async def test_c6_slashes_same_as_plain_path() -> None:
    """c6: `/finance/Q3/` (có `/` thừa) → fact như `finance/Q3`."""
    _, _, _, _, plain = await _run(ME, _extend("finance/Q3"))
    _, _, _, _, slashed = await _run(ME, _extend("/finance/Q3/"))
    assert slashed == plain
    assert plain["resource_sensitivity"] == "high" and plain["existing_permission_level"] == "read"


@asyncio
async def test_c7_view_permissions_no_folder_facts() -> None:
    """c7: không path (`view_permissions`) → không gọi `check_resource_sensitivity` (đếm ở nơi nhận); không fact theo thư mục."""
    env, _, _, _, facts = await _run(ME, {"action": "view_permissions"})
    assert env.tools.calls["check_resource_sensitivity"] == 0
    for key in ("resource_sensitivity", "same_department", "has_permission_record", "existing_permission_level"):
        assert key not in facts, key
    assert facts == {"target_user_status": "active"}


@asyncio
async def test_c8_target_user_nv004_disabled_security() -> None:
    """c8 (P6, M-T20a-5): `target_user=nv004`, người gửi nv001, `engineering/specs` → lời gọi AD/quyền dùng `user_id=nv004` (đếm ở
    nơi nhận); `target_user_status=disabled`, `target_disable_reason=security`."""
    env, _, _, _, facts = await _run(ME, {"action": "grant_permission", "resource_path": "engineering/specs",
                                          "permission_level": "read", "duration": "30", "target_user": "nv004"})  # fmt: skip
    got = env.tools.user_ids()
    assert got and set(got) == {"nv004"}
    assert set(env.tools.user_ids("check_account_status")) == {"nv004"}
    assert set(env.tools.user_ids("check_current_permissions")) == {"nv004"}
    assert (facts["target_user_status"], facts["target_disable_reason"]) == ("disabled", "security")
    assert facts["same_department"] is False  # Sales ≠ Engineering — phòng ban của rf, không của người gửi
    assert facts["has_permission_record"] is False


@asyncio
async def test_same_department_follows_rf_not_requester() -> None:
    """P6 + bảng 4.3 (`same_department` của `requested_for`): nv002 (Engineering) xin cho nv001 (Finance) vào finance/Q3 → True."""
    _, _, _, _, facts = await _run("nv002", _extend("finance/Q3", target_user=ME))
    assert facts["same_department"] is True and facts["existing_permission_level"] == "read"


@asyncio
async def test_permissions_404_unknown_rf_no_record_fact() -> None:
    """5.1.2: permissions 404 (người lạ) → KHÔNG đặt `has_permission_record`; account_status 404 → không status, không
    same_department."""
    _, _, diag, _, facts = await _run(ME, _extend("finance/Q3", target_user="nv_khong_co"))
    assert diag["check_current_permissions"] is None
    assert "has_permission_record" not in facts and "existing_permission_level" not in facts
    assert "target_user_status" not in facts and "same_department" not in facts
    assert facts == {"resource_sensitivity": "high"}
