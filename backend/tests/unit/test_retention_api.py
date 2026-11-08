"""M2 (bn-a, 08/11) — đọc ticket SAU khi checkpoint đã bị job hạn giữ xoá (test viết trước, DỪNG 1).

Hợp đồng (PLAN bn-a mục M2, chờ ĐP chốt mã):
- `GET /api/tickets/{id}`: dòng `tickets` CÒN (FK của `audit_logs` append-only — không xoá được), `final_state` khác NULL, checkpoint rỗng
  → **410 `conversation_purged`** (lỗi rõ ràng; không 500, không 200 với `conversation=[]` im lặng). Thứ tự kiểm quyền giữ nguyên
  (404 cho người không được đọc — không lộ ticket tồn tại).
- Ticket CHƯA kết thúc mà checkpoint rỗng (vừa tạo, graph chưa chạy lượt đầu) → giữ hành vi cũ: 200, `status=S_NEW`.
- Sự kiện người dùng tới ticket đã dọn → 409 (guard sự kiện muộn — snapshot rỗng = `S_NEW`, không ở node chờ), không chạy lại graph.
Nguồn giả: `desk_env` (InMemorySaver của `GraphHarness`) — xoá thread bằng đúng API `adelete_thread` mà job dùng.
"""

import pytest
from tests.fakes.desk import desk_env

pytestmark = pytest.mark.asyncio


async def test_m2_purged_final_ticket_get_is_410_not_500() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        assert env.h.tickets.final(ticket) is not None
        await env.h.saver.adelete_thread(ticket)
        r = await env.client.get(f"/api/tickets/{ticket}", headers=an)
        assert (r.status_code, r.json()) == (410, {"detail": "conversation_purged"})


async def test_m2_purged_ticket_other_user_still_404() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        await env.h.saver.adelete_thread(ticket)
        other = await env.token("binh.tt")
        r = await env.client.get(f"/api/tickets/{ticket}", headers=other)
        assert r.status_code == 404  # không lộ ticket tồn tại/đã dọn


async def test_m2_open_ticket_without_checkpoint_keeps_old_behaviour() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        env.h.tickets.rows[ticket]["final"] = None  # ticket chưa kết thúc (giả lập) — checkpoint rỗng ≠ đã dọn
        await env.h.saver.adelete_thread(ticket)
        body = await env.ticket(ticket, an)
        assert body["status"] == "S_NEW" and body["conversation"] == []


async def test_m2_message_to_purged_ticket_is_409_not_rerun() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        await env.h.saver.adelete_thread(ticket)
        r = await env.client.post(f"/api/tickets/{ticket}/messages", json={"text": "còn đó không"}, headers=an)
        assert r.status_code == 409
        await env.drain()
        assert (await env.h.saver.aget_tuple({"configurable": {"thread_id": ticket}})) is None  # graph không chạy lại từ đầu
