"""Lô Q7 — nợ 39 (PROGRESS "Việc treo" 39; soát M2 bn-a mục 7): phòng thủ với ticket ĐÃ kết thúc mà checkpoint đã bị job hạn giữ dọn.

- `Runner.recover`: ticket đã kết thúc (`tickets.final_state` có giá trị) + snapshot rỗng → ĐÓNG lượt, KHÔNG `_run_initial` (không chạy graph từ
  START — sẽ dựng lại một ticket "mới" từ câu yêu cầu cũ và có thể làm lại việc). Ticket CHƯA kết thúc + snapshot rỗng → như cũ (chạy state đầu).
- `ChildOps._start`: con đã kết thúc mà snapshot rỗng → coi là "exists" (không khởi động lại).
- `late_event` của ticket đã dọn ghi `actual_status` = trạng thái cuối trong DB (trước: "S_NEW" — đọc audit dễ hiểu nhầm).
Nguồn giả: `desk_env` (InMemorySaver) — xoá thread bằng đúng `adelete_thread` mà job hạn giữ dùng.
"""

import pytest
from app.domain.states import S_NEW
from tests.fakes.desk import desk_env

pytestmark = pytest.mark.asyncio


async def _purged_final_ticket(env: object) -> str:
    e: object = env
    an = await e.token("an.nv")  # type: ignore[attr-defined]
    ticket = await e.create(an)  # type: ignore[attr-defined]
    await e.drain()  # type: ignore[attr-defined]
    assert e.h.tickets.final(ticket) is not None  # type: ignore[attr-defined]
    await e.h.saver.adelete_thread(ticket)  # type: ignore[attr-defined]
    return str(ticket)


async def _open_turn(env: object, ticket: str, turn_id: str) -> None:
    h = env.h  # type: ignore[attr-defined]
    await h.turns.start(turn_id=turn_id, ticket_id=ticket, session_id=None, event_type="resume", at=h.clock.now())


async def _thread(env: object, ticket: str) -> object:
    return await env.h.saver.aget_tuple({"configurable": {"thread_id": ticket}})  # type: ignore[attr-defined]


async def test_no39_recover_purged_final_ticket_closes_turn_without_rerun() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        ticket = await _purged_final_ticket(env)
        audit_before = [r for r in env.h.audit.rows if r.get("ticket_id") == ticket]
        await _open_turn(env, ticket, "T-don-39")
        r = await env.h.runner.recover(ticket, "T-don-39")
        assert r is not None and r.values == {}
        assert not await env.h.turns.is_open("T-don-39")  # lượt được đóng
        assert await _thread(env, ticket) is None  # graph KHÔNG chạy lại từ START
        assert [r for r in env.h.audit.rows if r.get("ticket_id") == ticket] == audit_before  # không node nào chạy (không dòng audit mới)


async def test_no39_open_ticket_without_checkpoint_still_runs_initial_state() -> None:
    """Đối chứng: ticket CHƯA kết thúc mà chưa có checkpoint (chết sau `tickets.create`, trước checkpoint đầu) → vẫn chạy state đầu."""
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        ticket = await _purged_final_ticket(env)
        env.h.tickets.rows[ticket]["final"] = None  # giả lập chưa kết thúc
        await _open_turn(env, ticket, "T-moi-39")
        await env.h.runner.recover(ticket, "T-moi-39")
        assert await _thread(env, ticket) is not None  # đã chạy lại từ state đầu như cũ


async def test_no39_late_event_on_purged_ticket_records_db_final_state() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        ticket = await _purged_final_ticket(env)
        final = env.h.tickets.final(ticket)
        assert final is not None
        r = await env.client.post(f"/api/tickets/{ticket}/messages", json={"text": "còn đó không"}, headers=an)
        assert r.status_code == 409
        late = [row for row in env.h.audit.rows if row.get("ticket_id") == ticket and row.get("event") == "late_event"]
        assert late, "phải ghi late_event"
        actual = late[-1]["detail"]["actual_status"]
        assert actual != S_NEW and actual == final.final_state
