"""Q4 (soát 12/11, agent 04 V11): quyết phiếu duyệt của ticket CON khi ticket CHA đã kết thúc (`final_state` khác null — vd cha lỗi E9
trong lúc con chờ duyệt) → 409, phiếu GIỮ `pending`, ticket con không chạy tiếp (0 lượt resume, không thực thi). Ghi một dòng
`late_event` lý do `parent_closed` (như bấm trễ). Cha còn mở → như cũ (202).
"""

from datetime import UTC, datetime

import pytest
from app.domain.final import FinalSummary
from app.domain.states import S_PENDING_APPROVAL
from tests.fakes.desk import DeskEnv, desk_env
from tests.unit.test_approvals_view import _decide, _login, _pending, _resumes, _row

pytestmark = pytest.mark.asyncio

PARENT = "cha-1212"
CLOSED = FinalSummary(final_state="S_ESCALATED", exit_code="E9", block_reason=None, close_reason=None, resolution_path=None,
                      aggregate_status=None, auto_closed=False, intent=None, slots=None, total_turns=1,
                      total_duration_seconds=1, closed_at=datetime(2026, 11, 12, tzinfo=UTC))  # fmt: skip


def _make_child(env: DeskEnv, ticket: str, *, parent_closed: bool) -> None:
    rows = env.h.tickets.rows
    rows[ticket]["parent_ticket_id"] = PARENT
    env.h.tickets.register(PARENT, rows[ticket]["created_at"], is_parent=True, requester_id=rows[ticket]["requester_id"])
    rows[PARENT]["final"] = CLOSED if parent_closed else None


async def test_cha_da_ket_thuc_thi_409_phieu_giu_nguyen() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        _make_child(env, ticket, parent_closed=True)
        r = await _decide(env, aid, await _login(env, "ha.lt"))
        await env.drain()
        assert r.status_code == 409, r.text
        assert _row(env, aid)["status"] == "pending"
        assert _resumes(env, ticket) == 0
        assert (await env.h.runner.snapshot(ticket)).values["status"] == S_PENDING_APPROVAL
        [late] = [a for a in env.h.audit.rows if a["ticket_id"] == ticket and a["event"] == "late_event"]
        assert late["detail"]["reason"] == "parent_closed"


async def test_cha_con_mo_thi_nhu_cu() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        _make_child(env, ticket, parent_closed=False)
        r = await _decide(env, aid, await _login(env, "ha.lt"))
        assert r.status_code == 202, r.text


async def test_ticket_khong_co_cha_nhu_cu() -> None:
    async with desk_env() as env:
        _, aid = await _pending(env)
        r = await _decide(env, aid, await _login(env, "ha.lt"))
        assert r.status_code == 202, r.text

