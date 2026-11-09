"""P3 "Gần đây" — menu ⋯ "Xóa" = ẨN ticket khỏi danh sách "Gần đây" của CHÍNH người gọi (`POST /api/tickets/{id}/hide`).

Hợp đồng (PLAN p5-gan-day-menu, DỪNG 1): quyền `ticket:read:own`; CHỈ ticket gốc có `requester_id = người gọi` — còn lại (không
có, của người khác kể cả staff `ticket:read:any`, ticket con) → CÙNG một 404 `not_found` như `GET /{id}`; gọi lại → vẫn 204
(idempotent). `GET /api/tickets` loại ticket đã ẩn của người gọi (lọc TRƯỚC `LIMIT`); `GET /api/tickets/{id}` KHÔNG đổi. Không xoá
gì: không đụng `tickets`, audit, approval, escalation, checkpoint; không ghi audit (đề xuất PLAN). Bản SQL ở
`integration/test_tickets_http_pg.py`, migration ở `integration/test_migration_0014.py`.
"""

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from tests.fakes.auth import EPOCH
from tests.fakes.desk import DeskEnv, desk_env

pytestmark = pytest.mark.asyncio

NOT_FOUND = {"detail": "not_found"}  # thân 404 của route ticket — KHÁC 404 mặc định của FastAPI ("Not Found")


async def _hide(env: DeskEnv, ticket_id: str, headers: dict[str, str]) -> Any:
    return await env.client.post(f"/api/tickets/{ticket_id}/hide", headers=headers)


async def _ids(env: DeskEnv, headers: dict[str, str], query: str = "") -> list[str]:
    r = await env.client.get(f"/api/tickets{query}", headers=headers)
    assert r.status_code == 200, r.text
    return [i["ticket_id"] for i in r.json()["items"]]


def _three(env: DeskEnv, owner: str = "nv001") -> list[str]:
    """3 ticket gốc của `owner`, mới nhất trước."""
    for i, tid in enumerate(("tk-1", "tk-2", "tk-3")):
        env.h.tickets.register(tid, EPOCH + timedelta(minutes=i), requester_id=owner)
    return ["tk-3", "tk-2", "tk-1"]


async def test_hide_removes_only_that_item_keeps_order_and_204_empty_body() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        newest_first = _three(env)
        assert await _ids(env, an) == newest_first
        r = await _hide(env, "tk-2", an)
        assert (r.status_code, r.content) == (204, b"")
        assert await _ids(env, an) == ["tk-3", "tk-1"]


async def test_hidden_stays_hidden_after_relogin() -> None:
    """F5 / đăng xuất-đăng nhập lại: trạng thái ẩn ở server, không theo phiên/token."""
    async with desk_env() as env:
        an = await env.token("an.nv")
        _three(env)
        assert (await _hide(env, "tk-3", an)).status_code == 204
        again = await env.token("an.nv")  # phiên mới
        assert await _ids(env, again) == ["tk-2", "tk-1"]


async def test_hide_twice_is_204_both_times() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        _three(env)
        first, second = await _hide(env, "tk-1", an), await _hide(env, "tk-1", an)
        assert (first.status_code, second.status_code) == (204, 204)
        assert await _ids(env, an) == ["tk-3", "tk-2"]


async def test_filter_applies_before_limit() -> None:
    """Ẩn mục mới nhất, `limit=2` → vẫn đủ 2 mục kế tiếp (lọc trong truy vấn, không lọc sau khi cắt)."""
    async with desk_env() as env:
        an = await env.token("an.nv")
        _three(env)
        assert (await _hide(env, "tk-3", an)).status_code == 204
        assert await _ids(env, an, "?limit=2") == ["tk-2", "tk-1"]


async def test_other_users_lists_unaffected() -> None:
    async with desk_env() as env:
        an, binh = await env.token("an.nv"), await env.token("binh.tt")
        a1 = await env.create(an, text="VPN lỗi của An")
        a2 = await env.create(an, text="Zoom lỗi của An")
        b1 = await env.create(binh, text="Outlook lỗi của Bình")
        await env.drain()
        assert (await _hide(env, a1, an)).status_code == 204
        assert await _ids(env, binh) == [b1]
        assert set(await _ids(env, an)) == {a2}


@pytest.mark.parametrize("who", ["binh.tt", "ha.lt", "long.nh"])  # nhân viên khác; l1/l2 có `ticket:read:any`
async def test_hide_someone_elses_ticket_is_same_404_as_missing(who: str) -> None:
    async with desk_env() as env:
        an, other = await env.token("an.nv"), await env.token(who)
        a1 = await env.create(an, text="VPN lỗi của An")
        await env.drain()
        foreign, missing = await _hide(env, a1, other), await _hide(env, str(uuid4()), other)
        assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json()) == (404, NOT_FOUND)
        assert await _ids(env, an) == [a1]  # chủ ticket không bị ẩn hộ


async def test_foreign_hide_records_permission_denied_missing_does_not() -> None:
    """Như `GET /{id}`: id giả → không ghi gì; ticket người khác → một `permission_denied` (IDOR — M9 đếm được)."""
    async with desk_env() as env:
        an, binh = await env.token("an.nv"), await env.token("binh.tt")
        a1 = await env.create(an)
        await env.drain()
        before = env.denied()
        await _hide(env, str(uuid4()), binh)
        assert env.denied() == before
        await _hide(env, a1, binh)
        assert env.denied() == before + 1


async def test_hide_child_ticket_is_404() -> None:
    """Chỉ ticket gốc: danh sách không có ticket con nên không có gì để ẩn — id con → 404 như id không có."""
    async with desk_env() as env:
        an = await env.token("an.nv")
        t = env.h.tickets
        t.register("tk-p", EPOCH, requester_id="nv001", is_parent=True)
        t.register("tk-p-1", EPOCH, requester_id="nv001", parent_ticket_id="tk-p")
        r = await _hide(env, "tk-p-1", an)
        assert (r.status_code, r.json()) == (404, NOT_FOUND)
        assert await _ids(env, an) == ["tk-p"]


async def test_detail_still_readable_after_hide_unchanged() -> None:
    """Người đó vẫn mở được bằng link; IT (`ticket:read:any`) vẫn xem được — `GET /{id}` không đổi một khoá nào."""
    async with desk_env() as env:
        an, l1 = await env.token("an.nv"), await env.token("ha.lt")
        a1 = await env.create(an)
        await env.drain()
        before = {k: v for k, v in (await env.ticket(a1, an)).items() if k != "server_now"}
        assert (await _hide(env, a1, an)).status_code == 204
        after = {k: v for k, v in (await env.ticket(a1, an)).items() if k != "server_now"}
        assert after == before
        assert (await env.ticket(a1, l1))["ticket_id"] == a1


async def test_hide_deletes_nothing_and_writes_no_audit() -> None:
    """Không xoá/sửa dòng `tickets`, không thêm/bớt audit, không gọi runner, guard, bộ đếm 429."""
    async with desk_env() as env:
        an = await env.token("an.nv")
        a1 = await env.create(an)
        await env.drain()
        row = dict(env.h.tickets.rows[a1])
        audit = list(env.h.audit.rows)
        rate_calls, guard_calls = len(env.rate.calls), env.guard.calls
        assert (await _hide(env, a1, an)).status_code == 204
        await env.drain()
        assert env.h.tickets.rows[a1] == row
        assert env.h.audit.rows == audit
        assert (len(env.rate.calls), env.guard.calls) == (rate_calls, guard_calls)


async def test_hide_without_token_is_401() -> None:
    async with desk_env() as env:
        r = await env.client.post("/api/tickets/tk-1/hide")
        assert (r.status_code, r.json()) == (401, {"detail": "unauthorized"})


async def test_hidden_row_of_another_user_does_not_hide_for_owner() -> None:
    """Ẩn tính theo (người, ticket): dòng ẩn của người KHÁC (không đi qua API được — chỉ dựng thẳng ở store) không làm mất mục của
    chủ ticket. Cùng ca với `test_hide_store_filters_before_limit_pg` (bản SQL)."""
    async with desk_env() as env:
        an = await env.token("an.nv")
        _three(env)
        await env.h.tickets.hide("nv002", "tk-2", EPOCH)
        assert await _ids(env, an) == ["tk-3", "tk-2", "tk-1"]
