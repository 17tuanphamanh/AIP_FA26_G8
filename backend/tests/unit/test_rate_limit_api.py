"""Gói 2b — chống spam (D-54 a) qua HTTP thật của app (auth thật, graph trên bản giả, cổng đếm `MemoryRateGate` của `desk_env`).
Viết TỪ ĐẶC TẢ trước code (không mở `api/ratelimit.py`, `db/rate_limits.py`): `claude/dac-ta-bat-2-model.md` 4.8 + 8 "Gói 2b — chống
spam", PLAN-2B1 mục 3.3 (công thức `Retry-After`) và bảng ca U1–U12, U21.

Thứ tự CHỐT (4.8): 413 → 401/403 (`require`) → **429** (dòng đầu handler: trước `_owned_leaf`, trước đọc thân) → 404/403/409 → 422.
Bộ A: `POST /api/tickets` (10 phút + 1 giờ, ticket con không tính). Bộ B: `/messages`, `/reply`, `/confirm` chung một bộ (10 phút).
Đếm theo `p.user_id`; request bị 429 không được đếm; request sau đó bị 404/403/409/422 vẫn đã đếm.

Người: an.nv = nv001 (employee), binh.tt = nv002 (employee), ha.lt = l1_01 (l1). Ngưỡng không truyền = 100000 (`conftest.py` gốc).
Mốc giờ: `EPOCH` của FakeClock; token truy cập sống 15 phút → tua quá 15 phút thì đăng nhập lại.
"""

from datetime import timedelta
from typing import Any

import httpx
import pytest
from app.auth.permissions import PERMS
from app.domain.states import S_CLARIFYING, S_PENDING_APPROVAL
from tests.fakes.auth import EPOCH
from tests.fakes.desk import MASK, SECRET, DeskEnv, desk_env

pytestmark = pytest.mark.asyncio

LIMITED = {"detail": "rate_limited"}
FAKE_ID = "khong-co"
CLARIFY_PLAN: dict[str, str | list[str]] = {"b11_slots": ["missing", "complete"]}
B_ROUTES = ("messages", "reply", "confirm")
ALL_ROUTES = ("tickets", *B_ROUTES)
ROUTE_TEMPLATE = {
    "tickets": "/api/tickets",
    "messages": "/api/tickets/{ticket_id}/messages",
    "reply": "/api/tickets/{ticket_id}/reply",
    "confirm": "/api/tickets/{ticket_id}/confirm",
}  # fmt: skip
PERM_OF = {"tickets": "ticket:create", "messages": "ticket:message", "reply": "ticket:message", "confirm": "ticket:confirm"}


def secs(n: float) -> timedelta:
    return timedelta(seconds=n)


def valid_body(route: str, ticket: str) -> dict[str, Any]:
    if route == "tickets":
        return {"text": "VPN không vào được"}
    if route == "messages":
        return {"text": "x"}
    if route == "confirm":
        return {"confirmed": True}
    return {"items": {f"{ticket}-1": {"confirmed": True}}}  # `/reply`: khoá `<cha>-<i>`


async def send(
    env: DeskEnv, route: str, headers: dict[str, str], ticket: str = FAKE_ID, **kw: Any
) -> httpx.Response:
    """POST tới một trong 4 route có đếm. Không truyền `json`/`content` → thân hợp lệ của route đó."""
    if not kw:
        kw = {"json": valid_body(route, ticket)}
    url = "/api/tickets" if route == "tickets" else f"/api/tickets/{ticket}/{route}"
    return await env.client.post(url, headers=headers, **kw)


def assert_429(r: httpx.Response, retry_after: int | None = None) -> None:
    """4.8 "Khi vượt ngưỡng": 429 `{"detail": "rate_limited"}` + `Retry-After` số nguyên giây ≥ 1."""
    assert (r.status_code, r.json()) == (429, LIMITED), r.text
    value = r.headers["retry-after"]
    assert value.isdigit() and int(value) >= 1, value
    if retry_after is not None:
        assert int(value) == retry_after


async def exhaust(env: DeskEnv, route: str, headers: dict[str, str]) -> None:
    """Đưa người gửi tới ĐÚNG ngưỡng 1 của bộ đếm chứa `route` (env dựng với ngưỡng 1): bộ A — 1 ticket; bộ B — 1 request tới id
    giả (404 vẫn đếm). Request kế tiếp của người này ở bộ đó → 429."""
    if route == "tickets":
        await env.create(headers)
    else:
        assert (await send(env, route, headers)).status_code == 404
    assert_429(await send(env, route, headers))


def snapshot(env: DeskEnv) -> tuple[list[Any], dict[str, list[Any]]]:
    return list(env.rate.calls), {u: list(ts) for u, ts in env.rate.hits.items()}


# ---- U1, U2: biên ngưỡng --------------------------------------------------------------------------------------------------------


async def test_u1_ten_tickets_in_10min_pass_eleventh_429_retry_after_300() -> None:
    """U1 (8 "biên ngưỡng: request thứ 10 trong 10 phút qua, thứ 11 → 429"; 4.8 ngưỡng A 10/30) + PLAN 3.3 ví dụ 1: 10 ticket cách nhau
    30 giây → 10 × 202; thứ 11 lúc +5 phút → 429, `Retry-After: 300`. Bắt mutation 11 (`>=` → `>`)."""
    async with desk_env(ticket_rate_10min=10, ticket_rate_hour=30) as env:
        an = await env.token("an.nv")
        for _ in range(10):
            await env.create(an)  # assert 202 bên trong
            env.clock.advance(secs(30))
        assert env.clock.now() == EPOCH + secs(300)
        assert_429(await send(env, "tickets", an), 300)
        assert len(env.h.tickets.rows) == 10


async def test_u1_boundary_strict_ticket_leaves_window_at_exactly_10min() -> None:
    """U1/U13 qua route: cửa sổ `created_at > now − 10 phút` (chặt) — lúc +599 giây vẫn 429 (`Retry-After: 1`), đúng +600 giây ticket
    đầu ra khỏi cửa sổ → 202."""
    async with desk_env(ticket_rate_10min=3) as env:
        an = await env.token("an.nv")
        for _ in range(3):
            await env.create(an)  # cả 3 lúc EPOCH
        env.clock.advance(secs(599))
        assert_429(await send(env, "tickets", an), 1)
        env.clock.advance(secs(1))
        assert (await send(env, "tickets", an)).status_code == 202


async def test_u2_hour_window_fourth_429_then_202_after_first_leaves() -> None:
    """U2 (8 "cửa sổ giờ tương tự"): ngưỡng 10 phút lớn, giờ = 3; 3 ticket rải trong 59 phút → thứ 4 → 429 (`Retry-After` = 60: ticket
    đầu lúc EPOCH + 3600 − (EPOCH + 59 phút)); đúng 60 phút ticket đầu ra khỏi cửa sổ giờ → 202. Bắt mutation 11."""
    async with desk_env(ticket_rate_hour=3) as env:
        an = await env.token("an.nv")
        await env.create(an)  # EPOCH
        env.clock.advance(timedelta(minutes=20))
        an = await env.token("an.nv")
        await env.create(an)  # +20 phút
        env.clock.advance(timedelta(minutes=39))
        an = await env.token("an.nv")
        await env.create(an)  # +59 phút
        assert_429(await send(env, "tickets", an), 60)
        env.clock.advance(timedelta(minutes=1))
        assert (await send(env, "tickets", an)).status_code == 202


# ---- U3: ticket con không tính --------------------------------------------------------------------------------------------------


async def test_u3_child_tickets_not_counted_parent_counted() -> None:
    """U3 (4.8 bộ A: `parent_ticket_id IS NULL` — ticket con chép `requester_id` của cha; PLAN 3.2: ticket cha có tính)."""
    async with desk_env(ticket_rate_10min=2) as env:
        an = await env.token("an.nv")
        parent = await env.create(an)
        await env.drain()
        env.h.tickets.rows[parent]["is_parent"] = True  # cha: `parent_ticket_id` NULL → vẫn đếm
        for i in range(1, 6):
            env.h.tickets.register(f"{parent}-{i}", env.clock.now(), requester_id="nv001", parent_ticket_id=parent)
        assert (await send(env, "tickets", an)).status_code == 202  # 1 cha + 5 con → bộ A thấy 1 < 2
        assert_429(await send(env, "tickets", an))  # 2 ticket gốc → đủ ngưỡng


# ---- U4: 401/403 trước 429, không hao lượt -------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ALL_ROUTES)
async def test_u4_401_before_429_not_counted(route: str) -> None:
    """U4 (8 "401/403 đứng trước 429"; 4.8 "Request chưa xác thực không làm hao lượt"): người đã vượt ngưỡng; request không token /
    token hỏng → 401 (không 429), cổng đếm không được gọi, `hits` không đổi."""
    async with desk_env(ticket_rate_10min=1, message_rate_10min=1) as env:
        an = await env.token("an.nv")
        await exhaust(env, route, an)
        before = snapshot(env)
        for headers in ({}, {"Authorization": "Bearer khong-phai-token"}):
            r = await send(env, route, headers)
            assert r.status_code == 401, r.text
        assert snapshot(env) == before
        assert_429(await send(env, route, an))  # đối chứng: chính người này vẫn đang bị chặn


@pytest.mark.parametrize("route", ALL_ROUTES)
async def test_u4_403_permission_before_429_not_counted(route: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """U4: thiếu quyền (khi đã vượt ngưỡng) → 403 + `permission_denied` của `require`, không 429, cổng đếm không được gọi.
    Cả 4 vai trò đều có quyền của 4 route (G12) → rút quyền của vai trò employee trong `PERMS` rồi đăng nhập lại."""
    async with desk_env(ticket_rate_10min=1, message_rate_10min=1) as env:
        an = await env.token("an.nv")
        await exhaust(env, route, an)
        perms: Any = PERMS
        monkeypatch.setitem(perms, "employee", frozenset(perms["employee"]) - {PERM_OF[route]})
        stripped = await env.token("an.nv")
        before, denied = snapshot(env), env.denied()
        r = await send(env, route, stripped)
        assert r.status_code == 403, r.text
        assert env.denied() == denied + 1
        assert snapshot(env) == before


async def test_u4_every_role_is_limited() -> None:
    """4.8 "Áp cho mọi vai trò" (`ticket:create` có ở cả 4 vai trò): l1 cũng bị 429."""
    async with desk_env(ticket_rate_10min=1) as env:
        l1 = await env.token("ha.lt")
        await env.create(l1)
        assert_429(await send(env, "tickets", l1))


# ---- U5: 429 trước `_owned_leaf` ------------------------------------------------------------------------------------------------


async def test_u5_over_limit_fake_id_429_not_404_no_denied_no_guard() -> None:
    """U5 (8 "429 đứng trước `_owned_leaf`: tài khoản đã vượt ngưỡng gửi vào id giả vẫn nhận 429"): id giả → 429 (không 404); ticket
    của người khác → 429 (không 404, không `permission_denied`); guard không chạy, không `late_event`. Bắt mutation 13."""
    async with desk_env(message_rate_10min=2) as env:
        an, binh = await env.token("an.nv"), await env.token("binh.tt")
        theirs = await env.create(binh)
        await env.drain()
        for _ in range(2):
            assert (await send(env, "messages", an)).status_code == 404  # 404 vẫn đếm (4.8)
        denied, guard = env.denied(), env.guard.calls
        assert_429(await send(env, "messages", an, json={"text": SECRET}))
        assert_429(await send(env, "messages", an, ticket=theirs, json={"text": SECRET}))
        assert (env.denied(), env.guard.calls) == (denied, guard)
        assert env.late(theirs) == []


# ---- U6: 429 không tạo ticket, không spawn, có Retry-After -------------------------------------------------------------------


async def test_u6_429_creates_nothing_spawns_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """U6 (8 "429 không tạo ticket và không `spawn`; có `Retry-After`"; 4.8 "không tạo ticket, không gọi LLM, không lưu nội dung"):
    số ticket/lượt/audit không đổi, 0 lượt `spawn`, guard 0 lần; `Retry-After` theo PLAN 3.3: ticket đầu EPOCH + 600 − (EPOCH + 120)."""
    async with desk_env(ticket_rate_10min=2) as env:
        an = await env.token("an.nv")
        await env.create(an)
        env.clock.advance(secs(60))
        await env.create(an)
        env.clock.advance(secs(60))
        await env.drain()
        spawned: list[Any] = []
        original = env.background.spawn

        def spy(coro: Any, **kw: Any) -> Any:
            spawned.append(kw.get("name"))
            return original(coro, **kw)

        monkeypatch.setattr(env.background, "spawn", spy)

        def state() -> tuple[int, ...]:
            return (len(env.h.tickets.rows), len(env.h.turns.rows), len(env.h.audit.rows), env.guard.calls,
                    len(env.h.tickets.security_events))  # fmt: skip

        before = state()
        assert_429(await send(env, "tickets", an, json={"text": f"spam {SECRET}"}), 480)
        assert state() == before and spawned == []


async def test_u6_messages_retry_after_formula() -> None:
    """U6 + PLAN 3.3 cho bộ B: 3 request lúc EPOCH, +100, +200 giây (ngưỡng 3) → request lúc +250 giây → 429, `Retry-After` = request
    thứ (3 − 3 + 1) = EPOCH + 600 − (EPOCH + 250) = 350."""
    async with desk_env(message_rate_10min=3) as env:
        an = await env.token("an.nv")
        for step in (100, 100, 50):
            assert (await send(env, "messages", an)).status_code == 404
            env.clock.advance(secs(step))
        assert env.clock.now() == EPOCH + secs(250)
        assert_429(await send(env, "messages", an), 350)


# ---- U7, U8: sự kiện `rate_limited` ---------------------------------------------------------------------------------------------


async def test_u7_tickets_one_event_per_burst_exact_fields() -> None:
    """U7 (8 "`rate_limited` chỉ ghi một lần mỗi đợt; `detail` không có chữ người dùng"; 4.8 "Sự kiện"): 5 lần 429 liên tiếp cùng đợt →
    đúng 1 sự kiện; `user_id`, `route` mẫu, `ticket_id is None`, `detail` đúng 3 khoá; chữ thân (canary) không có ở đâu trong sự kiện."""
    async with desk_env(ticket_rate_10min=1) as env:
        an = await env.token("an.nv")
        await env.create(an)
        for i in range(5):
            env.clock.advance(secs(10))
            assert_429(await send(env, "tickets", an, json={"text": f"spam-{i} {SECRET}"}))
        [event] = env.sink.of("rate_limited")
        assert (event.user_id, event.route, event.ticket_id) == ("nv001", "/api/tickets", None)
        assert event.detail == {"counter": "tickets", "window": "10m", "limit": 1}
        assert event.occurred_at == EPOCH + secs(10)  # lần 429 ĐẦU của đợt
        for text in (SECRET, MASK, "spam"):
            assert text not in repr(event)
        assert env.rate.calls[-1] == ("tickets", "nv001", "/api/tickets")


@pytest.mark.parametrize("route", B_ROUTES)
async def test_u7_messages_event_route_template_no_ticket_id(route: str) -> None:
    """U7 cho bộ B: `route` = MẪU đường dẫn (không id), `ticket_id` NULL kể cả khi đường dẫn có id (id người gửi tự đặt — PLAN 3.2),
    `detail.counter = "messages"`; id/thân mang canary không lọt vào sự kiện."""
    async with desk_env(message_rate_10min=1) as env:
        an = await env.token("an.nv")
        assert (await send(env, route, an)).status_code == 404
        for _ in range(5):
            assert_429(await send(env, route, an, ticket=SECRET, content=f'{{"text": "{SECRET}"}}'))
        [event] = env.sink.of("rate_limited")
        assert (event.user_id, event.route, event.ticket_id) == ("nv001", ROUTE_TEMPLATE[route], None)
        assert event.detail == {"counter": "messages", "window": "10m", "limit": 1}
        assert SECRET not in repr(event)
        assert env.rate.calls[-1] == ("messages", "nv001", ROUTE_TEMPLATE[route])


async def test_u7_both_ticket_windows_over_two_events() -> None:
    """Q-2B1-4 (đợt = người, bộ đếm, cửa sổ): hai cửa sổ của bộ A cùng vượt trong một request → 2 dòng (`10m`, `1h`), lặp lại vẫn 2;
    `Retry-After` = lớn nhất của hai cửa sổ (3600 − 60 = 3540)."""
    async with desk_env(ticket_rate_10min=1, ticket_rate_hour=1) as env:
        an = await env.token("an.nv")
        await env.create(an)
        env.clock.advance(secs(60))
        assert_429(await send(env, "tickets", an), 3540)
        assert_429(await send(env, "tickets", an))
        events = env.sink.of("rate_limited")
        assert sorted(e.detail["window"] for e in events) == ["10m", "1h"]
        assert all(e.detail == {"counter": "tickets", "window": e.detail["window"], "limit": 1} for e in events)


async def test_u8_new_burst_after_one_window_length_second_event() -> None:
    """U8 (4.8 "Mỗi đợt một dòng … ghi khi người này chưa có `rate_limited` của bộ đếm đó trong cửa sổ đang vượt"): trong cùng 10 phút
    chỉ 1 sự kiện; sau một độ dài cửa sổ, lượt đầu ra khỏi cửa sổ (request qua), vượt lần nữa → sự kiện thứ 2."""
    async with desk_env(message_rate_10min=1) as env:
        an = await env.token("an.nv")
        assert (await send(env, "messages", an)).status_code == 404  # EPOCH — được đếm
        assert_429(await send(env, "messages", an), 600)  # EPOCH — sự kiện 1
        env.clock.advance(secs(300))
        assert_429(await send(env, "messages", an), 300)  # cùng đợt
        assert len(env.sink.of("rate_limited")) == 1
        env.clock.advance(secs(300))  # EPOCH + 600: lượt đầu ra khỏi cửa sổ (chặt)
        assert (await send(env, "messages", an)).status_code == 404
        assert_429(await send(env, "messages", an), 600)
        assert [e.occurred_at for e in env.sink.of("rate_limited")] == [EPOCH, EPOCH + secs(600)]


# ---- U9: hai bộ đếm tách nhau --------------------------------------------------------------------------------------------------


async def test_u9_messages_do_not_consume_ticket_bucket() -> None:
    """U9 (8 "bộ đếm tin nhắn tách riêng"): 30 tin nhắn (đủ ngưỡng B) không làm hao bộ A — vẫn tạo đủ 10 ticket; tin thứ 31 → 429."""
    async with desk_env(ticket_rate_10min=10, ticket_rate_hour=30, message_rate_10min=30) as env:
        an = await env.token("an.nv")
        for _ in range(30):
            assert (await send(env, "messages", an)).status_code == 404
        for _ in range(10):
            await env.create(an)
        assert_429(await send(env, "tickets", an))
        assert_429(await send(env, "messages", an))


async def test_u9_tickets_do_not_consume_message_bucket() -> None:
    """U9 chiều ngược: bộ A đã vượt (10 ticket + 1 lần 429) không làm hao bộ B — 30 tin nhắn vẫn qua cổng; thứ 31 → 429."""
    async with desk_env(ticket_rate_10min=10, ticket_rate_hour=30, message_rate_10min=30) as env:
        an = await env.token("an.nv")
        for _ in range(10):
            await env.create(an)
        assert_429(await send(env, "tickets", an))
        for _ in range(30):
            assert (await send(env, "messages", an)).status_code == 404
        assert_429(await send(env, "messages", an))


# ---- U10, U11: bộ B đếm cả 409/422, ba route chung bộ ---------------------------------------------------------------------------


async def test_u10_wrong_step_409_and_422_still_counted() -> None:
    """U10 (8 "tin gửi sai bước (409) vẫn được đếm: 30 request đầu trong 10 phút nhận mã thường (202/409/422), request thứ 31 nhận
    429"): 1 × 202 (đang hỏi) + 19 × 409 (đã sang chờ duyệt — `late_event`) + 10 × 422 (thân sai) → thứ 31 → 429. Bắt mutation 11."""
    async with desk_env(plan=CLARIFY_PLAN, message_rate_10min=30) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        assert (await env.ticket(ticket, an))["status"] == S_CLARIFYING
        statuses: list[int] = []
        for i in range(30):
            kw: dict[str, Any] = {"json": {"text": ""}} if i >= 20 else {}
            statuses.append((await send(env, "messages", an, ticket=ticket, **kw)).status_code)
            await env.drain()
        assert (statuses.count(202), statuses.count(409), statuses.count(422)) == (1, 19, 10), statuses
        assert (await env.ticket(ticket, an))["status"] == S_PENDING_APPROVAL
        assert len(env.late(ticket)) == 19
        assert_429(await send(env, "messages", an, ticket=ticket))
        assert len(env.late(ticket)) == 19  # request bị 429 không tới `start_event`


@pytest.mark.parametrize("last", B_ROUTES)
async def test_u11_messages_reply_confirm_share_one_bucket(last: str) -> None:
    """U11 (4.8 "Bộ đếm B … chung một bộ [Chốt 18/10 03:25]"; 8): 10 `/messages` + 10 `/reply` + 10 `/confirm` (ticket thường đang chờ
    duyệt → cả 3 đều 409 sai bước) → request thứ 31 ở route bất kỳ → 429. Bắt mutation 22 (`/confirm` không đếm)."""
    async with desk_env(message_rate_10min=30) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        for route in B_ROUTES:
            for _ in range(10):
                r = await send(env, route, an, ticket=ticket)
                assert r.status_code == 409, (route, r.text)
                await env.drain()
        assert_429(await send(env, last, an, ticket=ticket))


# ---- U12: hai người dùng -------------------------------------------------------------------------------------------------------


async def test_u12_two_users_independent() -> None:
    """U12 (4.8 "Đếm theo `user_id` trong token"): an vượt cả hai bộ không ảnh hưởng binh; sự kiện chỉ của an."""
    async with desk_env(ticket_rate_10min=1, message_rate_10min=1) as env:
        an, binh = await env.token("an.nv"), await env.token("binh.tt")
        await exhaust(env, "tickets", an)
        await exhaust(env, "messages", an)
        assert (await send(env, "tickets", binh)).status_code == 202
        assert (await send(env, "messages", binh)).status_code == 404
        assert {e.user_id for e in env.sink.of("rate_limited")} == {"nv001"}


# ---- U21: thân sai + đã vượt ngưỡng → 429 trước 422 ------------------------------------------------------------------------------

BAD_KINDS = ("json-hong", "thieu-truong", "truong-la")


def bad_body(kind: str, route: str, ticket: str) -> dict[str, Any]:
    """JSON hỏng / thiếu trường bắt buộc / trường lạ (`extra="forbid"`) — không vượt ngưỡng thì route trả 422."""
    if kind == "json-hong":
        return {"content": "{không phải json"}
    if kind == "thieu-truong":
        return {"json": {}}
    return {"json": {**valid_body(route, ticket), "role": "l1"}}


@pytest.mark.parametrize("kind", BAD_KINDS)
@pytest.mark.parametrize("route", ALL_ROUTES)
async def test_u21_bad_body_over_limit_429_not_422(route: str, kind: str) -> None:
    """U21 (G14; 4.8 "429 … trước đọc thân"): JSON hỏng / thiếu trường / trường lạ khi đã vượt ngưỡng, ở cả 4 route → 429 (không 422),
    guard không chạy. Route bộ B gửi vào ticket CỦA MÌNH (không vượt ngưỡng thì sẽ là 422)."""
    async with desk_env(ticket_rate_10min=1, message_rate_10min=1) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)  # bộ A: đủ ngưỡng 1
        await env.drain()
        if route != "tickets":
            assert (await send(env, "messages", an, ticket=ticket)).status_code == 409  # bộ B: đủ ngưỡng 1
            await env.drain()
        guard = env.guard.calls
        assert_429(await send(env, route, an, ticket=ticket, **bad_body(kind, route, ticket)))
        assert env.guard.calls == guard
