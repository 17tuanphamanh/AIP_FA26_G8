"""Route ticket (2b-3): tạo, đọc, trả lời, xác nhận — qua HTTP thật của app (auth thật, graph trên
bản giả). Thứ tự đồng thời điều khiển bằng `asyncio.Event`, không `sleep`.

Người: an.nv = nv001 (employee, chủ ticket), binh.tt = nv002 (employee khác), ha.lt = l1_01 (l1, người
duyệt giả).
"""

import asyncio
import dataclasses
import logging
from datetime import timedelta
from typing import Any

import pytest
from app.api.background import BackgroundRuns
from app.api.tickets import TicketView
from app.domain.states import (
    S_BLOCKED,
    S_CLARIFYING,
    S_CONFIRMING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
    S_RESOLVED,
)
from app.graph.late_event import start_event
from tests.fakes.auth import EPOCH
from tests.fakes.desk import MASK, SECRET, DeskEnv, desk_env, wait_for
from tests.fakes.graph import GraphHarness

NOT_FOUND = {"detail": "not_found"}
CLARIFY_PLAN: dict[str, str | list[str]] = {"b11_slots": ["missing", "complete"]}


# ---- Tạo ticket -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_202_then_graph_runs_in_background() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        r = await env.client.post("/api/tickets", json={"text": "VPN lỗi"}, headers=an)
        assert r.status_code == 202
        ticket = r.json()["ticket_id"]
        assert r.json() == {"ticket_id": ticket, "status": "S_NEW", "notices": []}  # 3e: notices (8.3)
        await env.drain()
        view = await env.ticket(ticket, an)
        assert (view["status"], view["waiting_for"]) == (S_PENDING_APPROVAL, "approval")
        row = env.h.tickets.rows[ticket]
        assert (row["requester_id"], row["requester_role"], row["requester_dept"]) == (
            "nv001", "employee", "finance")  # fmt: skip
        [session] = env.store.sessions.values()
        assert row["session_id"] == session.session_id
        [turn] = env.h.turns.of(ticket)
        assert turn["event_type"] == "submit" and turn["ended_at"] is not None


@pytest.mark.asyncio
async def test_create_stores_redacted_text() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        ticket = await env.create(an, text=f"mật khẩu của tôi là {SECRET}")
        await env.drain()
        row = env.h.tickets.rows[ticket]
        assert SECRET not in row["redacted_request"] and MASK in row["redacted_request"]
        state = (await env.h.runner.snapshot(ticket)).values
        assert state["redacted_request"] == row["redacted_request"]


@pytest.mark.asyncio
async def test_duration_300s_from_app_clock() -> None:
    async with desk_env() as env:
        an, l1 = await env.token("an.nv"), await env.token("ha.lt")
        ticket = await env.create(an)
        await env.drain()
        assert env.h.tickets.rows[ticket]["created_at"] == EPOCH
        env.clock.advance(timedelta(seconds=300))
        r = await env.client.post(f"/api/approvals/{env.approval_of(ticket)}/decision",
                                  json={"decision": "approved"}, headers=l1)  # fmt: skip
        assert r.status_code == 202
        await env.drain()
        r = await env.client.post(f"/api/tickets/{ticket}/confirm", json={"confirmed": True}, headers=an)
        assert r.status_code == 202
        await env.drain()
        final = env.h.tickets.final(ticket)
        assert final is not None and final.final_state == S_RESOLVED
        assert final.total_duration_seconds == 300
        [point8] = env.h.audit.of(ticket, "closed")
        assert point8["total_duration_seconds"] == 300


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, {}, {"text": ""}, {"text": "x", "role": "l1"}, "không phải json"])
async def test_create_invalid_body_422_writes_nothing(body: Any) -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        kw: dict[str, Any] = {"content": body} if isinstance(body, str) else {"json": body}
        r = await env.client.post("/api/tickets", headers=an, **kw)
        assert r.status_code == 422
        assert env.h.tickets.rows == {} and env.guard.calls == 0


@pytest.mark.asyncio
async def test_create_without_token_401() -> None:
    async with desk_env() as env:
        r = await env.client.post("/api/tickets", json={"text": "x"})
        assert r.status_code == 401
        assert env.h.tickets.rows == {} and env.guard.calls == 0


# ---- Đọc ticket -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_view_exact_keys() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        assert set(await env.ticket(ticket, an)) == set(TicketView.model_fields)


@pytest.mark.asyncio
async def test_idor_404_same_body_as_missing() -> None:
    """TC30 qua route thật: A đọc ticket của B → 404 giống hệt id không tồn tại."""
    async with desk_env() as env:
        an, binh = await env.token("an.nv"), await env.token("binh.tt")
        ticket = await env.create(an)
        await env.drain()
        other = await env.client.get(f"/api/tickets/{ticket}", headers=binh)
        missing = await env.client.get("/api/tickets/khong-co", headers=binh)
        assert (other.status_code, other.json()) == (missing.status_code, missing.json()) == (404, NOT_FOUND)
        assert env.denied() == 1  # chỉ ticket có thật mới ghi permission_denied
        l1 = await env.token("ha.lt")
        assert (await env.client.get(f"/api/tickets/{ticket}", headers=l1)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(("plan", "status", "waiting"), [
    ({"b11_slots": "missing"}, S_CLARIFYING, "clarify"),
    ({}, S_PENDING_APPROVAL, "approval"),
    ({"b12_assess": "auto"}, S_CONFIRMING, "confirm"),
])  # fmt: skip
async def test_waiting_for_each_wait_state(
    plan: dict[str, str | list[str]], status: str, waiting: str
) -> None:
    async with desk_env(plan=plan) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        view = await env.ticket(ticket, an)
        assert (view["status"], view["waiting_for"], view["final_state"]) == (status, waiting, None)


@pytest.mark.asyncio
async def test_closed_status_from_final_state() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        final = env.h.tickets.final(ticket)
        assert final is not None and final.final_state == S_ESCALATED
        # Cho `tickets` và checkpoint LỆCH nhau: status phải theo `tickets.final_state`.
        env.h.tickets.rows[ticket]["final"] = dataclasses.replace(final, final_state=S_BLOCKED)
        view = await env.ticket(ticket, an)
        assert (view["status"], view["final_state"], view["waiting_for"]) == (S_BLOCKED, S_BLOCKED, None)
        assert view["exit_code"] == "E5" and view["closed_at"] is not None


@pytest.mark.asyncio
async def test_checkpoint_error_503() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()

        async def broken(_: str) -> Any:
            raise ConnectionError("checkpoint DB chết")

        object.__setattr__(env.h.runner, "snapshot", broken)  # thay method trên instance
        r = await env.client.get(f"/api/tickets/{ticket}", headers=an)
        assert r.status_code == 503


# ---- messages / confirm: thứ tự kiểm (a) + dòng ghi khi bị từ chối (b) ------------------------


async def _clarifying(env: DeskEnv, headers: dict[str, str]) -> str:
    ticket = await env.create(headers)
    await env.drain()
    assert (await env.ticket(ticket, headers))["status"] == S_CLARIFYING
    return ticket


def _counts(env: DeskEnv, ticket: str) -> tuple[int, int, int, int, int]:
    """(permission_denied, late_event, turns của ticket, số ticket, số lần gọi guard)."""
    return (env.denied(), len(env.late(ticket)), len(env.h.turns.of(ticket)), len(env.h.tickets.rows),
            env.guard.calls)  # fmt: skip


@pytest.mark.asyncio
async def test_owner_message_202_and_graph_continues() -> None:
    async with desk_env(plan=CLARIFY_PLAN) as env:
        an = await env.token("an.nv")
        ticket = await _clarifying(env, an)
        r = await env.client.post(f"/api/tickets/{ticket}/messages",
                                  json={"text": f"máy LAP-1 {SECRET}"}, headers=an)  # fmt: skip
        assert r.status_code == 202
        await env.drain()
        view = await env.ticket(ticket, an)
        assert view["status"] == S_PENDING_APPROVAL
        assert {"role": "user", "text": f"máy LAP-1 {MASK}"} in view["conversation"]


@pytest.mark.asyncio
async def test_stranger_to_child_ticket_404() -> None:
    async with desk_env(plan=CLARIFY_PLAN) as env:
        an, binh = await env.token("an.nv"), await env.token("binh.tt")
        ticket = await _clarifying(env, an)
        env.h.tickets.rows[ticket]["parent_ticket_id"] = "cha-1"  # ticket con
        denied, *rest = _counts(env, ticket)
        r = await env.client.post(f"/api/tickets/{ticket}/messages", json={"text": "x"}, headers=binh)
        assert (r.status_code, r.json()) == (404, NOT_FOUND)
        assert _counts(env, ticket) == (denied + 1, *rest)


@pytest.mark.asyncio
async def test_owner_child_ticket_409_before_body_and_guard() -> None:
    async with desk_env(plan=CLARIFY_PLAN) as env:
        an = await env.token("an.nv")
        ticket = await _clarifying(env, an)
        env.h.tickets.rows[ticket]["parent_ticket_id"] = "cha-1"
        before = _counts(env, ticket)
        r = await env.client.post(f"/api/tickets/{ticket}/messages", content="hỏng", headers=an)
        assert r.status_code == 409 and "hội thoại chung" in r.json()["detail"]
        assert _counts(env, ticket) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["messages", "confirm"])
async def test_l1_not_owner_403(route: str) -> None:
    async with desk_env(plan=CLARIFY_PLAN) as env:
        an, l1 = await env.token("an.nv"), await env.token("ha.lt")
        ticket = await _clarifying(env, an)
        denied, *rest = _counts(env, ticket)
        body = {"text": "x"} if route == "messages" else {"confirmed": True}
        r = await env.client.post(f"/api/tickets/{ticket}/{route}", json=body, headers=l1)
        assert r.status_code == 403
        assert _counts(env, ticket) == (denied + 1, *rest)
        assert env.sink.of("permission_denied")[-1].detail["reason"] == "not_owner"


@pytest.mark.asyncio
async def test_missing_ticket_404_writes_nothing() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        r = await env.client.post("/api/tickets/khong-co/messages", json={"text": "x"}, headers=an)
        assert (r.status_code, r.json()) == (404, NOT_FOUND)
        assert env.denied() == 0 and env.guard.calls == 0 and env.h.audit.rows == []


@pytest.mark.asyncio
async def test_denied_request_never_calls_guard() -> None:
    async with desk_env(plan=CLARIFY_PLAN) as env:
        an, binh, l1 = await env.token("an.nv"), await env.token("binh.tt"), await env.token("ha.lt")
        ticket = await _clarifying(env, an)
        calls = env.guard.calls
        for who in (binh, l1):
            r = await env.client.post(f"/api/tickets/{ticket}/messages", json={"text": SECRET}, headers=who)
            assert r.status_code in (403, 404)
        assert env.guard.calls == calls


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"text": ""}, {"text": "x", "extra": 1}, None])
async def test_owner_bad_body_422_after_checks(body: Any) -> None:
    async with desk_env(plan=CLARIFY_PLAN) as env:
        an = await env.token("an.nv")
        ticket = await _clarifying(env, an)
        before = _counts(env, ticket)
        r = await env.client.post(f"/api/tickets/{ticket}/messages", json=body, headers=an)
        assert r.status_code == 422
        assert _counts(env, ticket) == before


# ---- Sự kiện muộn / khoá ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("plan", "route", "body"), [
    ({}, "messages", {"text": "x"}),                              # đang chờ duyệt, gửi trả lời
    ({"b11_slots": "missing"}, "confirm", {"confirmed": True}),   # đang hỏi, gửi xác nhận
    ({"b12_assess": "deny"}, "confirm", {"confirmed": True}),     # đã đóng (E5)
])  # fmt: skip
async def test_late_event_409_exactly_one_late_row(
    plan: dict[str, str | list[str]], route: str, body: Any
) -> None:
    async with desk_env(plan=plan) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        before = (await env.h.runner.snapshot(ticket)).values
        r = await env.client.post(f"/api/tickets/{ticket}/{route}", json=body, headers=an)
        assert r.status_code == 409
        await env.drain()
        [late] = env.late(ticket)
        assert late["detail"]["source"] == "user"
        assert (await env.h.runner.snapshot(ticket)).values == before


@pytest.mark.asyncio
async def test_busy_503_retry_after_then_late_409() -> None:
    async with desk_env(plan={"b11_slots": "missing"}, lock_timeout=0.05, ticket_lock_timeout=3) as env:
        an = await env.token("an.nv")
        ticket = await _clarifying(env, an)
        held, release = asyncio.Event(), asyncio.Event()

        async def hold() -> None:
            async with env.h.lock.hold(ticket):
                held.set()
                await wait_for(release)

        holder = asyncio.create_task(hold())
        await wait_for(held)
        r = await env.client.post(f"/api/tickets/{ticket}/messages", json={"text": "x"}, headers=an)
        assert r.status_code == 503 and r.headers["retry-after"] == "3"
        assert env.late(ticket) == []
        release.set()
        await holder
        # khoá đã nhả; sự kiện không đúng trạng thái chờ → 409 (không 503)
        r = await env.client.post(f"/api/tickets/{ticket}/confirm", json={"confirmed": True}, headers=an)
        assert r.status_code == 409 and len(env.late(ticket)) == 1


@pytest.mark.asyncio
async def test_cancelled_request_releases_lock() -> None:
    """Giao khoá (Q1): request bị huỷ SAU khi lấy khoá, TRƯỚC khi giao → request tự nhả."""
    h = GraphHarness(lock_timeout=0.05)
    await h.submit("t1", b11_slots="missing")
    entered, never = asyncio.Event(), asyncio.Event()
    original = h.runner.snapshot

    async def slow_snapshot(ticket_id: str) -> Any:
        entered.set()
        await never.wait()  # guard đứng ở đây, đang giữ khoá
        return await original(ticket_id)

    h.runner.snapshot = slow_snapshot  # type: ignore[method-assign]
    spawned: list[Any] = []
    task = asyncio.create_task(start_event(
        h.runner, "t1", S_CLARIFYING, {"kind": "user_reply", "text": "x"},
        spawn=lambda coro, **_: spawned.append(coro)))  # fmt: skip
    await wait_for(entered)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert spawned == []
    # Kiểm NGAY khi task kết thúc, không nhường vòng lặp: nếu request không tự nhả, khoá chỉ được nhả
    # khi generator của context manager bị gom rác (không được dựa vào đó — với khoá Postgres là giữ
    # kết nối tới lúc GC).
    assert not h.lock._locks["t1"].locked()
    async with h.lock.hold("t1"):  # lấy lại được NGAY (lock_timeout 0,05 giây — không thì TicketBusy)
        pass


@pytest.mark.asyncio
async def test_task_cancelled_before_start_releases_lock() -> None:
    """Đã giao nhưng task bị huỷ trước khi kịp chạy dòng nào → `on_cancel` nhả khoá."""
    h = GraphHarness(lock_timeout=0.05)
    await h.submit("t1", b11_slots="missing")
    runs = BackgroundRuns()
    loop_blocker = asyncio.Event()

    def spawn_then_cancel(coro: Any, **kw: Any) -> None:
        runs.spawn(coro, **kw).cancel()  # huỷ NGAY, task chưa từng chạy

    await start_event(h.runner, "t1", S_CLARIFYING, {"kind": "user_reply", "text": "x"},
                      spawn=spawn_then_cancel)  # fmt: skip
    await runs.drain()
    async with h.lock.hold("t1"):
        pass
    assert (await h.runner.snapshot("t1")).values["status"] == S_CLARIFYING
    del loop_blocker


# ---- Huỷ giữa lượt, task nền lỗi -----------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_mid_turn_no_e9_turn_stays_open() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        inside, never = asyncio.Event(), asyncio.Event()

        async def stuck(_: Any) -> None:
            inside.set()
            await never.wait()

        env.h.scenario.on_all("after_approval_create", stuck)
        ticket = await env.create(an)
        await wait_for(inside)
        [task] = list(env.background._tasks)
        task.cancel()
        await env.drain()
        assert env.h.audit.of(ticket, "unhandled_exception") == []
        values = (await env.h.runner.snapshot(ticket)).values
        assert values.get("exit_code") is None and values.get("status") != S_ESCALATED
        [turn] = env.h.turns.of(ticket)
        assert turn["ended_at"] is None  # worker sẽ phục hồi


@pytest.mark.asyncio
async def test_background_exception_logged(caplog: pytest.LogCaptureFixture) -> None:
    runs = BackgroundRuns()

    async def boom() -> None:
        raise ValueError("lỗi trong task nền")

    with caplog.at_level(logging.ERROR, logger="app.api.background"):
        runs.spawn(boom(), name="boom")
        await runs.drain()
    assert len(runs) == 0
    [rec] = [r for r in caplog.records if "boom" in r.getMessage()]
    assert rec.exc_info is not None and "lỗi trong task nền" in str(rec.exc_info[1])


# ---- TC24 / TC25 qua HTTP -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tc24_one_wrong_password_then_ticket_passes_b1() -> None:
    async with desk_env() as env:
        assert (await env.login("an.nv", "sai")).status_code == 401
        assert env.h.tickets.rows == {}
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        assert (await env.ticket(ticket, an))["status"] == S_PENDING_APPROVAL
        assert ("B1", "identity_established") in env.h.audit.events(ticket)
        assert env.h.alerts.rows == {}


@pytest.mark.asyncio
async def test_tc25_locked_user_ticket_blocked_one_alert() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")  # phiên có từ trước khi bị dò mật khẩu
        for _ in range(5):
            assert (await env.login("an.nv", "sai")).status_code == 401
        assert len(env.h.alerts.rows) == 1  # auth ghi lúc khoá
        ticket = await env.create(an)
        await env.drain()
        view = await env.ticket(ticket, an)
        assert (view["status"], view["final_state"]) == (S_BLOCKED, S_BLOCKED)
        final = env.h.tickets.final(ticket)
        assert final is not None and final.block_reason == "repeated_auth_failure"
        assert len(env.h.alerts.rows) == 1  # B1 ghi lại CÙNG khoá → vẫn một


@pytest.mark.asyncio
async def test_g18_other_user_404_does_not_see_conversation() -> None:
    """3g g18: ticket có `conversation` thật (câu hỏi B11 thật) — người khác GET → 404 y hệt id không tồn tại, không lộ
    tin nào; chủ ticket thấy câu hỏi."""
    from tests.fakes.llm import make_gateway
    from tests.fixtures.llm.vpn import vpn_scripts
    from tests.unit.test_b11_slots import _rag

    gw = make_gateway(vpn_scripts(action=None))  # type: ignore[arg-type]
    async with desk_env(harness={"nodes": "real", "llm": gw.client, "rag": _rag()}) as env:
        binh, an = await env.token("binh.tt"), await env.token("an.nv")
        ticket = await env.create(binh)  # nv002 có 2 máy → B11 thật hỏi máy
        await env.drain()
        mine = await env.ticket(ticket, binh)
        [question] = [m for m in mine["conversation"] if m.get("kind") == "question"]
        other = await env.client.get(f"/api/tickets/{ticket}", headers=an)
        missing = await env.client.get("/api/tickets/khong-co", headers=an)
        assert (other.status_code, other.json()) == (missing.status_code, missing.json()) == (404, NOT_FOUND)
        assert question["text"] not in other.text and "conversation" not in other.text
