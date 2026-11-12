"""Q2 (soát 12/11, agent 13 F1 — sửa (b)): route quyết phiếu kiểm AD của NGƯỜI DUYỆT trước `start_event`.

- Người duyệt không còn hợp lệ trong AD (nghỉ việc / khoá, không còn trong AD, nhóm không còn ra l1 lẫn Trưởng BP — cùng tiêu chí
  B17 `approver_no_longer_valid`, `domain.approval.invalid_reason`) → 403 + `permission_denied`; phiếu giữ `pending`, ticket không
  chạy tiếp (0 lượt resume → 0 lời gọi ghi).
- AD không trả lời → 503 `identity_unavailable` (fail-closed); phiếu giữ `pending`.
- Hợp lệ → như cũ (202).
"""

from dataclasses import replace

import pytest
from tests.fakes.desk import DeskEnv, desk_env
from tests.unit.test_approvals_view import _decide, _login, _pending, _resumes, _row

pytestmark = pytest.mark.asyncio

APPROVER = "l1_01"  # ha.lt — người B15 giả giao


def _ad_set(env: DeskEnv, **changes: object) -> None:
    env.idp.set(replace(env.idp.users[APPROVER], **changes))  # type: ignore[arg-type]


async def _assert_untouched(env: DeskEnv, ticket: str, aid: str) -> None:
    await env.drain()
    assert _row(env, aid)["status"] == "pending"
    assert _row(env, aid).get("decided_by") is None
    assert _resumes(env, ticket) == 0


@pytest.mark.parametrize("status", ["terminated", "disabled"])
async def test_nguoi_duyet_nghi_viec_sau_dang_nhap_bi_403(status: str) -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        headers = await _login(env, "ha.lt")  # access token còn hạn
        _ad_set(env, employment_status=status)
        denied = env.sink.of("permission_denied")
        r = await _decide(env, aid, headers)
        assert r.status_code == 403, r.text
        [event] = env.sink.of("permission_denied")[len(denied):]
        assert event.user_id == APPROVER and event.detail["reason"] == "approver_inactive"
        await _assert_untouched(env, ticket, aid)


async def test_nguoi_duyet_khong_con_trong_ad_bi_403() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        headers = await _login(env, "ha.lt")
        del env.idp.users[APPROVER]
        r = await _decide(env, aid, headers)
        assert r.status_code == 403, r.text
        assert env.sink.of("permission_denied")[-1].detail["reason"] == "approver_not_found"
        await _assert_untouched(env, ticket, aid)


async def test_nhom_ad_khong_con_ra_l1_hay_truong_bp_bi_403() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        headers = await _login(env, "ha.lt")
        _ad_set(env, groups=["IT-Users"])
        r = await _decide(env, aid, headers)
        assert r.status_code == 403, r.text
        assert env.sink.of("permission_denied")[-1].detail["reason"] == "approver_wrong_group"
        await _assert_untouched(env, ticket, aid)


async def test_ad_khong_tra_loi_503_phieu_giu_nguyen() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        headers = await _login(env, "ha.lt")
        env.idp.down = True
        r = await _decide(env, aid, headers, decision="rejected", note="không đủ căn cứ")
        assert r.status_code == 503, r.text
        assert r.json()["detail"] == "identity_unavailable"
        await _assert_untouched(env, ticket, aid)


async def test_nguoi_duyet_hop_le_nhu_cu() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        r = await _decide(env, aid, await _login(env, "ha.lt"))
        assert r.status_code == 202, r.text
        await env.drain()
        assert _row(env, aid)["status"] == "approved" and _resumes(env, ticket) == 1


async def test_nguoi_khac_khong_duoc_giao_van_403_khong_hoi_ad() -> None:
    """Không phải người được giao → 403 như cũ, TRƯỚC khi hỏi AD (AD tắt cũng không thành 503)."""
    async with desk_env() as env:
        _, aid = await _pending(env)
        headers = await _login(env, "duc.pv")
        env.idp.down = True
        r = await _decide(env, aid, headers)
        assert r.status_code == 403, r.text
