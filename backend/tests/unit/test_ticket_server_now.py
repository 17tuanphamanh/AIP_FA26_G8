"""`GET /api/tickets/{id}` — `server_now` + `deadline` của ticket CHA (đồng hồ chờ duyệt cho nhân viên, P10 mục 3.1). Nguồn giả:
`env.h.deadlines.waits` / `env.h.approvals._table` / `env.h.tickets.rows` (SQL thật: test_ticket_parent_deadline_pg.py).

- `server_now` = `desk.clock.now()` (có múi giờ, đổi theo `FakeClock`); tập khoá TicketView = tập R3 cũ + `server_now` — không lộ trường phiếu duyệt.
- Ticket thường chờ duyệt → `deadline` = hạn phiếu `pending` (giữ nghĩa R3); không chờ / đã kết thúc → null.
- Ticket CHA chưa kết thúc: (1) có hạn chờ riêng chưa bắn → hạn của CHA (kể cả khi con chờ duyệt); (2) không có → hạn SỚM NHẤT các phiếu
  `pending` của con (không tính phiếu của chính cha, phiếu đã đóng); (3) không có gì → null.
"""

from datetime import datetime, timedelta
from typing import Any

import pytest
from app.domain.final import FinalSummary
from app.domain.states import S_RESOLVED
from tests.fakes.desk import DeskEnv, desk_env

pytestmark = pytest.mark.asyncio

OLD_KEYS = {
    "ticket_id", "status", "waiting_for", "conversation", "exit_code", "close_reason", "final_state", "created_at", "closed_at",
    "children_progress", "deadline",
    "request_text",  # be-api8-cau-dau: câu đầu ĐÃ CHE (đổi CÓ CHỦ ĐÍCH tập trường TicketView)
    "can_follow_up",  # Q13b (D-79): chỉ một bool — ticket kết thúc có được "Hỏi tiếp" không (đổi CÓ CHỦ ĐÍCH)
}  # fmt: skip


async def _pending(env: DeskEnv, an: dict[str, str]) -> tuple[str, str]:
    ticket = await env.create(an)
    await env.drain()
    return ticket, env.approval_of(ticket)


async def _family(env: DeskEnv) -> tuple[dict[str, str], str, str, str, str, str]:
    """Ba ticket chờ duyệt của an.nv; P được đánh dấu cha, C1/C2 là con của P. Trả (token, P, C1, C2, aid_C1, aid_C2)."""
    an = await env.token("an.nv")
    (p, _), (c1, a1), (c2, a2) = [await _pending(env, an) for _ in range(3)]
    env.h.tickets.rows[p]["is_parent"] = True
    for child in (c1, c2):
        env.h.tickets.rows[child]["parent_ticket_id"] = p
    return an, p, c1, c2, a1, a2


def _at(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)  # Python 3.12 nhận cả hậu tố Z


def _wait(env: DeskEnv, ticket: str, deadline: Any, fired_at: Any = None) -> None:
    env.h.deadlines.waits.append({
        "ticket_id": ticket, "kind": "confirm", "deadline": deadline, "created_turn": "t", "fired_at": fired_at, "is_parent": True,
    })  # fmt: skip


async def test_server_now_aware_follows_clock_and_key_set_is_old_plus_server_now() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        ticket, aid = await _pending(env, an)
        body = await env.ticket(ticket, an)
        assert set(body) == OLD_KEYS | {"server_now"}  # không lộ approval_id, approver, hash, ghi chú...
        first = _at(body["server_now"])
        assert first is not None and first.tzinfo is not None and first == env.clock.now()
        env.clock.advance(timedelta(minutes=7))
        later = _at((await env.ticket(ticket, an))["server_now"])
        assert later is not None and later - first == timedelta(minutes=7)
        assert _at(body["deadline"]) == env.h.approvals._table[aid]["deadline"]


async def test_deadline_null_when_not_waiting_for_approval() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        body = await env.ticket(ticket, an)
        assert body["deadline"] is None and body["waiting_for"] != "approval" and "server_now" in body


async def test_parent_own_wait_deadline_wins_even_with_children_pending() -> None:
    async with desk_env() as env:
        an, p, _, _, a1, _ = await _family(env)
        own = env.clock.now() + timedelta(hours=24)
        _wait(env, p, own)
        env.h.approvals._table[a1]["deadline"] = env.clock.now() + timedelta(minutes=5)  # sớm hơn hạn cha
        body = await env.ticket(p, an)
        assert _at(body["deadline"]) == own


async def test_parent_without_own_wait_takes_earliest_pending_child_deadline() -> None:
    async with desk_env() as env:
        an, p, _, _, a1, a2 = await _family(env)
        late, early = env.clock.now() + timedelta(minutes=50), env.clock.now() + timedelta(minutes=20)
        env.h.approvals._table[a1]["deadline"] = late
        env.h.approvals._table[a2]["deadline"] = early
        env.h.approvals._table[env.approval_of(p)]["deadline"] = env.clock.now() + timedelta(minutes=1)  # phiếu của CHÍNH cha: bỏ qua
        _wait(env, p, env.clock.now() + timedelta(hours=1), fired_at=env.clock.now())  # hạn riêng đã bắn: không tính
        body = await env.ticket(p, an)
        assert _at(body["deadline"]) == early
        env.h.approvals._table[a2]["status"] = "approved"  # con 2 đã quyết → còn con 1
        assert _at((await env.ticket(p, an))["deadline"]) == late


async def test_parent_with_nothing_pending_is_null() -> None:
    async with desk_env() as env:
        an, p, _, _, a1, a2 = await _family(env)
        for aid in (a1, a2):
            env.h.approvals._table[aid]["status"] = "rejected"
        body = await env.ticket(p, an)
        assert body["deadline"] is None and set(body) == OLD_KEYS | {"server_now"}


async def test_finished_parent_deadline_null() -> None:
    async with desk_env() as env:
        an, p, *_ = await _family(env)
        _wait(env, p, env.clock.now() + timedelta(hours=1))
        env.h.tickets.rows[p]["final"] = FinalSummary(
            final_state=S_RESOLVED, exit_code=None, block_reason=None, close_reason=None, resolution_path=None,
            aggregate_status=None, auto_closed=False, intent=None, slots=None, total_turns=1, total_duration_seconds=0,
            closed_at=env.clock.now(),
        )  # fmt: skip
        assert (await env.ticket(p, an))["deadline"] is None
