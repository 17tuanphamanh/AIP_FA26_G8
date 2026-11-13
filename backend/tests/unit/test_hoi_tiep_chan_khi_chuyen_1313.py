"""13/11 19:40 (TA chốt, sửa D-79): ticket ĐÃ CHUYỂN KỸ THUẬT VIÊN (`S_ESCALATED`) hoặc BỊ CHẶN (`S_BLOCKED`) không còn ô "Hỏi tiếp":
`can_follow_up` = false (FE khoá ô nhập, chỉ còn "Tạo yêu cầu mới") và `POST /api/tickets` kèm `follows_ticket_id` trỏ tới ticket đó → 404
GIỐNG HỆT "không có" (như các trường hợp từ chối khác của D-79). Ticket đã xong / bị từ chối vẫn hỏi tiếp được như cũ."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from app.domain.session_memory import FollowUpSource, can_follow, follow_up_open
from app.domain.states import S_BLOCKED, S_ESCALATED, S_REJECTED, S_RESOLVED
from tests.fakes.desk import DeskEnv, desk_env

NOT_FOUND = {"detail": "not_found"}


def src(final_state: str | None) -> FollowUpSource:
    return FollowUpSource("t0", "nv001", None, False, final_state, "vpn")


@pytest.mark.parametrize(
    ("state", "ok"), [(S_RESOLVED, True), (S_REJECTED, True), (S_ESCALATED, False), (S_BLOCKED, False), (None, False)]
)
def test_follow_up_open_theo_trang_thai_cuoi(state: str | None, ok: bool) -> None:
    assert follow_up_open(state) is ok
    assert can_follow(src(state), "nv001") is ok


async def _closed_as(env: DeskEnv, headers: dict[str, str], final_state: str) -> str:
    ticket = await env.create(headers, text="VPN không vào được")
    await env.drain()
    row = env.h.tickets.rows[ticket]
    row["final"] = dataclasses.replace(row["final"], final_state=final_state, intent="vpn")
    return ticket


async def _follow(env: DeskEnv, headers: dict[str, str], follows: str) -> Any:
    return await env.client.post("/api/tickets", json={"text": "vẫn chưa được", "follows_ticket_id": follows}, headers=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [S_ESCALATED, S_BLOCKED])
async def test_da_chuyen_hoac_bi_chan_khong_hoi_tiep(state: str) -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        old = await _closed_as(env, an, state)
        assert (await env.ticket(old, an))["can_follow_up"] is False
        before = len(env.h.tickets.rows)
        r = await _follow(env, an, old)
        assert (r.status_code, r.json()) == (404, NOT_FOUND)
        assert len(env.h.tickets.rows) == before  # không tạo ticket nào


@pytest.mark.asyncio
async def test_da_xong_van_hoi_tiep_duoc() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        old = await _closed_as(env, an, S_RESOLVED)
        assert (await env.ticket(old, an))["can_follow_up"] is True
        r = await _follow(env, an, old)
        assert r.status_code == 202, r.text
