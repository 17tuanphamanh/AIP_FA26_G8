"""P3 "Gần đây": `GET /api/tickets` — danh sách ticket CỦA CHÍNH người gọi (sống qua F5 / đăng nhập lại).

Hợp đồng: quyền `ticket:read:own`; CHỈ `requester_id = người gọi` (kể cả staff có `ticket:read:any`); chỉ ticket gốc/cha
(`parent_ticket_id IS NULL`); `created_at DESC, ticket_id DESC`; `limit` mặc định 20, 1–50 (ngoài khoảng → 422 kiểu sẵn có);
mỗi phần tử ĐÚNG 6 khoá, `request_text` = `request_text_of` (bản ĐÃ CHE, cắt 500 — không bao giờ câu gốc); CHỈ đọc DB (không
đọc checkpoint). Bản giả `MemoryTickets.list_own` cùng ngữ nghĩa SQL — bản SQL kiểm ở `integration/test_tickets_http_pg.py`.
"""

from datetime import timedelta
from typing import Any

import pytest
from app.api.tickets import (
    LIST_LIMIT_DEFAULT,
    LIST_LIMIT_MAX,
    REQUEST_TEXT_MAX,
    TicketListItem,
)
from app.guard.privacy import RegexPrivacyGuard
from app.settings import Settings
from tests.fakes.auth import EPOCH
from tests.fakes.desk import MASK, SECRET, DeskEnv, desk_env

pytestmark = pytest.mark.asyncio

ITEM_KEYS = {"ticket_id", "request_text", "final_state", "exit_code", "created_at", "closed_at"}


async def _list(env: DeskEnv, headers: dict[str, str], query: str = "") -> list[dict[str, Any]]:
    r = await env.client.get(f"/api/tickets{query}", headers=headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert isinstance(items, list)
    return items


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [i["ticket_id"] for i in items]


async def test_only_own_tickets_two_users() -> None:
    async with desk_env() as env:
        an, binh = await env.token("an.nv"), await env.token("binh.tt")
        a1 = await env.create(an, text="VPN lỗi của An")
        b1 = await env.create(binh, text="Outlook lỗi của Bình")
        a2 = await env.create(an, text="Zoom lỗi của An")
        await env.drain()
        assert set(_ids(await _list(env, an))) == {a1, a2}
        assert _ids(await _list(env, binh)) == [b1]


@pytest.mark.parametrize("staff", ["ha.lt", "long.nh"])
async def test_staff_with_read_any_still_sees_only_own(staff: str) -> None:
    """l1/l2 có `ticket:read:any` — danh sách VẪN chỉ ticket họ tự gửi, không bao giờ của người khác."""
    async with desk_env() as env:
        an, who = await env.token("an.nv"), await env.token(staff)
        await env.create(an, text="VPN lỗi của An")
        await env.drain()
        assert await _list(env, who) == []
        mine = await env.create(who, text="máy in của tôi lỗi")
        await env.drain()
        assert _ids(await _list(env, who)) == [mine]


async def test_child_tickets_excluded() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        parent, child = await env.create(an, text="đặt lại mật khẩu AD, tiện cài Zoom"), await env.create(an, text="cài Zoom")
        await env.drain()
        rows = env.h.tickets.rows
        rows[parent]["is_parent"] = True
        rows[child]["parent_ticket_id"] = parent
        assert _ids(await _list(env, an)) == [parent]


async def test_newest_first_tie_by_ticket_id_desc() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        t = env.h.tickets
        t.register("tk-a", EPOCH, requester_id="nv001")
        t.register("tk-c", EPOCH + timedelta(minutes=5), requester_id="nv001")
        t.register("tk-b", EPOCH + timedelta(minutes=5), requester_id="nv001")  # cùng giờ với tk-c → id lớn trước
        t.register("tk-z", EPOCH + timedelta(minutes=1), requester_id="nv001")
        assert _ids(await _list(env, an)) == ["tk-c", "tk-b", "tk-z", "tk-a"]


async def test_limit_default_20_max_50_and_custom() -> None:
    assert (LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX) == (20, 50)
    async with desk_env() as env:
        an = await env.token("an.nv")
        for i in range(55):
            env.h.tickets.register(f"tk-{i:03d}", EPOCH + timedelta(minutes=i), requester_id="nv001")
        newest = [f"tk-{i:03d}" for i in range(54, -1, -1)]
        assert _ids(await _list(env, an)) == newest[:20]
        assert _ids(await _list(env, an, "?limit=3")) == newest[:3]
        assert _ids(await _list(env, an, "?limit=1")) == newest[:1]
        assert _ids(await _list(env, an, "?limit=50")) == newest[:50]


@pytest.mark.parametrize("bad", ["0", "-1", "51", "1000", "abc", "2.5", ""])
async def test_limit_out_of_range_is_422_invalid_request(bad: str) -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        r = await env.client.get(f"/api/tickets?limit={bad}", headers=an)
        assert (r.status_code, r.json()) == (422, {"error": "invalid_request", "fields": ["query.limit"]})


async def test_item_shape_exactly_six_keys_and_final_fields() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        ticket = await env.create(an, text="VPN lỗi 809")
        await env.drain()
        [item] = await _list(env, an)
        assert set(item) == ITEM_KEYS == set(TicketListItem.model_fields)
        view = await env.ticket(ticket, an)
        for key in ITEM_KEYS:
            assert item[key] == view[key], key


async def test_request_text_is_redacted_never_raw() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        await env.create(an, text=f"VPN lỗi 809, mật khẩu của tôi là {SECRET}")
        await env.drain()
        [item] = await _list(env, an)
        assert SECRET not in str(item) and MASK in item["request_text"]


async def test_request_text_email_and_phone_masked_with_real_guard() -> None:
    real = RegexPrivacyGuard.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    async with desk_env(guard=real) as env:
        an = await env.token("an.nv")
        await env.create(an, text="Không vào được VPN, gọi mình 0901234567 hoặc mail an.nguyen@example.com")
        await env.drain()
        r = await env.client.get("/api/tickets", headers=an)
        assert r.status_code == 200
        assert "0901234567" not in r.text and "an.nguyen@example.com" not in r.text
        [item] = r.json()["items"]
        assert "<SĐT_1>" in item["request_text"] and "<EMAIL_1>" in item["request_text"]


async def test_request_text_cut_to_500() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        await env.create(an, text="VPN " + "a" * 900)
        await env.drain()
        [item] = await _list(env, an)
        assert len(item["request_text"]) == REQUEST_TEXT_MAX


async def test_reads_db_only_not_checkpoint() -> None:
    """Checkpoint hỏng vẫn 200: danh sách CHỈ đọc bảng `tickets` (GET chi tiết thì 503)."""
    async with desk_env() as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()

        async def broken(*_: Any, **__: Any) -> Any:
            raise RuntimeError("checkpoint down")

        env.h.runner.snapshot = broken  # type: ignore[method-assign]
        assert _ids(await _list(env, an)) == [ticket]
        assert (await env.client.get(f"/api/tickets/{ticket}", headers=an)).status_code == 503


async def test_no_token_is_401() -> None:
    async with desk_env() as env:
        r = await env.client.get("/api/tickets")
        assert (r.status_code, r.json()) == (401, {"detail": "unauthorized"})


async def test_empty_list() -> None:
    async with desk_env() as env:
        assert await _list(env, await env.token("an.nv")) == []


async def test_list_does_not_touch_rate_limit_or_guard() -> None:
    """Route đọc: không đi qua bộ đếm 429 (như GET chi tiết), không gọi privacy guard."""
    async with desk_env() as env:
        an = await env.token("an.nv")
        await env.create(an)
        await env.drain()
        calls, guard_calls = len(env.rate.calls), env.guard.calls
        await _list(env, an)
        assert (len(env.rate.calls), env.guard.calls) == (calls, guard_calls)
