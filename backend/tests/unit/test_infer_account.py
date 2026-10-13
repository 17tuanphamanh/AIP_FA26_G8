"""T20a — `tools/diagnosis/account` (phase5 5.1.2 bảng account, 5.1.6 i1–i8; PLAN-T20a TQ-2, TQ-6, TQ-8, TQ-9).

Viết TỪ ĐẶC TẢ, trước code. Dữ liệu từ `mock_services/seed.json` qua `tests/fakes/seed_tools.SeedTools` (JSON + 404 như mock).
Mỗi ca chạy `account.calls(...)` qua registry THẬT (bước B6), dựng `diag` theo TQ-2 rồi `infer_account` — vừa kiểm lời gọi vừa kiểm
fact. `rf` = `slots.target_user` nếu có, không thì người gửi (P6); `account_type` = slot, chưa có → `"ad"` (TQ-8).

Seed (đối chiếu 13/10): nv001 ad mặc định (standard_user, không khoá); nv007 email khoá `bad_password`; svc_backup dịch vụ, ad `admin`;
nv004 `disabled`/`security`; nv006 `terminated` (disable_reason null); nv005 không có tài khoản `erp` → 404.
"""

from typing import Any

import pytest
from app.tools.diagnosis import account
from tests.unit._t20a import Env

ME = "nv001"
asyncio = pytest.mark.asyncio


async def _run(requester: str, slots: dict[str, str], env: Env | None = None) -> tuple[Any, ...]:
    env = env or Env()
    calls, diag, inferred, facts = await env.diagnose(account, requester, slots)
    return env, calls, diag, inferred, facts


# ---- lời gọi (5.1.2: tham số theo rf + account_type) --------------------------------------------------------------------


def test_calls_account_type_from_slot_and_rf_requester() -> None:
    """5.1.2 account: ba tool, thứ tự `TOOLS`; `account_type` lấy từ slot."""
    assert account.calls(ME, {"account_type": "email", "action": "unlock_account"}) == [
        ("check_account_status", {"user_id": ME, "account_type": "email"}),
        ("check_lockout_history", {"user_id": ME}),
        ("check_privilege_level", {"user_id": ME, "account_type": "email"}),
    ]  # fmt: skip


def test_calls_default_account_type_ad() -> None:
    """TQ-8: chưa có slot `account_type` → tra `"ad"`."""
    assert account.calls(ME, {}) == [
        ("check_account_status", {"user_id": ME, "account_type": "ad"}),
        ("check_lockout_history", {"user_id": ME}),
        ("check_privilege_level", {"user_id": ME, "account_type": "ad"}),
    ]  # fmt: skip


def test_i7_calls_use_target_user_not_requester() -> None:
    """i7 (P6): `target_user=nv005`, người gửi nv001 → mọi lời gọi `user_id=nv005`."""
    calls = account.calls(ME, {"account_type": "ad", "target_user": "nv005"})
    assert len(calls) == 3
    for _, args in calls:
        assert args["user_id"] == "nv005"


def test_target_calls_same_rule_on_final_slots() -> None:
    """TQ-3: `target_calls` (B11) cùng quy tắc với `calls` trên slot cuối."""
    for slots in ({"account_type": "ad"}, {"account_type": "email", "target_user": "nv005"}, {}):
        assert account.target_calls(ME, slots) == account.calls(ME, slots)


# ---- i1–i8 --------------------------------------------------------------------------------------------------------------


@asyncio
async def test_i1_nv001_ad_standard_unlocked() -> None:
    """i1: nv001 `ad` → privilege standard_user, không dịch vụ, active, không khoá; không lock_reason, không disable_reason."""
    _, _, _, inferred, facts = await _run(ME, {"account_type": "ad", "action": "reset_password"})
    assert facts == {
        "target_account_privilege": "standard_user", "target_is_service_account": False,
        "target_user_status": "active", "target_account_locked": False,
    }  # fmt: skip
    assert "target_lock_reason" not in facts and "target_disable_reason" not in facts
    assert inferred == {}  # 5.1.2: không tự suy `action` cho account


@asyncio
async def test_i2_nv007_email_locked_bad_password() -> None:
    """i2: nv007 `email` (seed khoá `bad_password`) → locked True, lock_reason bad_password."""
    _, _, _, _, facts = await _run("nv007", {"account_type": "email", "action": "unlock_account"})
    assert (facts["target_account_locked"], facts["target_lock_reason"]) == (True, "bad_password")
    assert facts["target_account_privilege"] == "standard_user" and facts["target_is_service_account"] is False
    assert facts["target_user_status"] == "active"


@asyncio
async def test_i2_nv007_ad_not_locked_no_lock_reason() -> None:
    """i2 (đối chứng): cùng người, tài khoản `ad` không khoá → locked False, không đặt lock_reason (chỉ xét khi khoá)."""
    _, _, _, _, facts = await _run("nv007", {"account_type": "ad"})
    assert facts["target_account_locked"] is False and "target_lock_reason" not in facts


@asyncio
async def test_i3_unknown_lock_reason_becomes_other() -> None:
    """i3 (seed tạm, M-T20a-10): `lock_reason="policy"` (ngoài 3 giá trị) khi khoá → `target_lock_reason="other"`."""
    env = Env()
    env.tools.set_lock(ME, "ad", locked=True, lock_reason="policy")
    _, _, _, _, facts = await _run(ME, {"account_type": "ad"}, env)
    assert (facts["target_account_locked"], facts["target_lock_reason"]) == (True, "other")


@asyncio
@pytest.mark.parametrize("reason", ["bad_password", "admin", "inactivity"])
async def test_i3_known_lock_reasons_kept(reason: str) -> None:
    """i3 / TQ-9: ba giá trị của mock giữ nguyên."""
    env = Env()
    env.tools.set_lock(ME, "ad", locked=True, lock_reason=reason)
    _, _, _, _, facts = await _run(ME, {"account_type": "ad"}, env)
    assert facts["target_lock_reason"] == reason


@asyncio
async def test_i3_locked_with_null_reason_not_set() -> None:
    """i3 (seed tạm): khoá mà `lock_reason=null` → KHÔNG đặt `target_lock_reason` (không tự cho là bad_password)."""
    env = Env()
    env.tools.set_lock(ME, "ad", locked=True, lock_reason=None)
    _, _, _, _, facts = await _run(ME, {"account_type": "ad"}, env)
    assert facts["target_account_locked"] is True and "target_lock_reason" not in facts


@asyncio
async def test_i3_lock_reason_ignored_when_not_locked() -> None:
    """5.1.2 "chỉ xét khi locked": không khoá mà mock còn `lock_reason` → không đặt fact."""
    env = Env()
    env.tools.set_lock(ME, "ad", locked=False, lock_reason="admin")
    _, _, _, _, facts = await _run(ME, {"account_type": "ad"}, env)
    assert facts["target_account_locked"] is False and "target_lock_reason" not in facts


@asyncio
async def test_i4_svc_backup_service_account_admin() -> None:
    """i4: svc_backup → dịch vụ True, privilege admin."""
    _, _, _, _, facts = await _run("svc_backup", {"account_type": "ad"})
    assert (facts["target_is_service_account"], facts["target_account_privilege"]) == (True, "admin")


@asyncio
async def test_i5_nv004_disabled_security() -> None:
    """i5: nv004 → status disabled, disable_reason security."""
    _, _, _, _, facts = await _run("nv004", {"account_type": "ad"})
    assert (facts["target_user_status"], facts["target_disable_reason"]) == ("disabled", "security")


@asyncio
async def test_i5_terminated_without_disable_reason() -> None:
    """5.1.2: `target_disable_reason` chỉ khi khác null — nv006 terminated, seed `disable_reason=null`."""
    _, _, _, _, facts = await _run("nv006", {"account_type": "ad"})
    assert facts["target_user_status"] == "terminated" and "target_disable_reason" not in facts


@asyncio
async def test_i6_unknown_user_404_no_facts() -> None:
    """i6: người lạ (404 cả ba tool) → `facts == {}`."""
    _, _, diag, _, facts = await _run("nv-khong-co", {"account_type": "ad"})
    assert facts == {}
    assert diag["check_account_status"] is None and diag["check_privilege_level"] is None


@asyncio
async def test_i7_target_user_every_call_at_receiver_is_nv005() -> None:
    """i7 (P6, M-T20a-5): `target_user=nv005`, người gửi nv001 → mọi lời gọi tới AD đếm ở NƠI NHẬN đều `user_id=nv005`;
    fact mô tả nv005 (Sales, active, standard_user)."""
    env, _, _, _, facts = await _run(ME, {"account_type": "ad", "target_user": "nv005"})
    got = env.tools.user_ids()
    assert got and set(got) == {"nv005"}
    assert dict(env.tools.calls) == {"check_account_status": 1, "check_lockout_history": 1, "check_privilege_level": 1}
    assert facts["target_user_status"] == "active" and facts["target_account_privilege"] == "standard_user"


@asyncio
async def test_i8_nv005_erp_404_no_account_facts() -> None:
    """i8: nv005 `erp` (seed không có tài khoản erp → 404 ở `check_account_status` và `check_privilege_level`) → không đặt fact
    của hai tool đó."""
    _, _, diag, _, facts = await _run("nv005", {"account_type": "erp"})
    assert diag["check_account_status"] is None and diag["check_privilege_level"] is None
    assert facts == {}
