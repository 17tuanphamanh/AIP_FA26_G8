"""`POST /api/approvals/{id}/decision` (2b-Q3, 2b-3 chốt e, f, Q2): đúng handler B15-B16 mục 5.

Người duyệt giả (`FAKE_APPROVER_ID`) = l1_01 (ha.lt). duc.pv = l1_02 (l1 khác), long.nh = l2_01.
Thứ tự đồng thời điều khiển bằng `asyncio.Event` (hook scenario trong node), không `sleep`.
"""

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_PENDING_APPROVAL, S_REJECTED
from app.graph.worker_jobs import WorkerJobs
from tests.fakes.desk import SECRET, DeskEnv, desk_env, wait_for

SLA = timedelta(minutes=30)  # SLA_MINUTES của config/policy.json


async def _pending(env: DeskEnv) -> tuple[str, str, dict[str, str], dict[str, str]]:
    an, l1 = await env.token("an.nv"), await env.token("ha.lt")
    ticket = await env.create(an)
    await env.drain()
    assert (await env.ticket(ticket, an))["status"] == S_PENDING_APPROVAL
    return ticket, env.approval_of(ticket), an, l1


def _decide(env: DeskEnv, aid: str, headers: dict[str, str], **body: Any) -> Any:
    return env.client.post(f"/api/approvals/{aid}/decision", json=body or {"decision": "approved"},
                           headers=headers)  # fmt: skip


def _resumes(env: DeskEnv, ticket: str) -> int:
    return sum(1 for t in env.h.turns.of(ticket) if t["event_type"] == "resume")


@pytest.mark.asyncio
async def test_approval_pending_until_graph_runs() -> None:
    """Route không ghi quyết định: sau 202, trước khi B16 chạy, phiếu vẫn `pending`."""
    async with desk_env() as env:
        ticket, aid, an, l1 = await _pending(env)
        in_turn, go = asyncio.Event(), asyncio.Event()
        original = env.h.runner.resume_locked

        async def gated(*a: Any, **kw: Any) -> Any:  # task nền dừng TRƯỚC khi graph chạy B16
            in_turn.set()
            await wait_for(go)
            return await original(*a, **kw)

        env.h.runner.resume_locked = gated  # type: ignore[method-assign]
        r = await _decide(env, aid, l1)
        assert r.status_code == 202
        await wait_for(in_turn)
        assert env.h.approvals.status(aid) == "pending"
        go.set()
        await env.drain()
        row = env.h.approvals._table[aid]
        assert (row["status"], row["decided_by"]) == ("approved", "l1_01")
        assert (await env.ticket(ticket, an))["status"] == S_CONFIRMING


@pytest.mark.asyncio
async def test_rejected_records_note_and_decider() -> None:
    async with desk_env() as env:
        ticket, aid, an, l1 = await _pending(env)
        r = await _decide(env, aid, l1, decision="rejected", note=f"không đủ lý do {SECRET}")
        assert r.status_code == 202
        await env.drain()
        row = env.h.approvals._table[aid]
        assert (row["status"], row["decided_by"]) == ("rejected", "l1_01")
        assert row["note"] == "không đủ lý do [BÍ_MẬT_ĐÃ_ẨN]"
        assert (await env.ticket(ticket, an))["status"] == S_REJECTED


@pytest.mark.asyncio
async def test_approver_id_from_token() -> None:
    async with desk_env() as env:
        _, aid, _, l1 = await _pending(env)
        r = await _decide(env, aid, l1, decision="approved", approver_id="l1_02")
        assert r.status_code == 422  # không có đường nào đưa approver_id vào từ body
        assert await _decide(env, aid, l1) is not None
        await env.drain()
        assert env.h.approvals._table[aid]["decided_by"] == "l1_01"


@pytest.mark.asyncio
@pytest.mark.parametrize("note", [None, "", "   "])
async def test_reject_without_note_422(note: str | None) -> None:
    async with desk_env() as env:
        ticket, aid, _, l1 = await _pending(env)
        body: dict[str, Any] = {"decision": "rejected"}
        if note is not None:
            body["note"] = note
        r = await env.client.post(f"/api/approvals/{aid}/decision", json=body, headers=l1)
        assert r.status_code == 422
        await env.drain()
        assert _resumes(env, ticket) == 0 and env.h.approvals.status(aid) == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["duc.pv", "long.nh", "an.nv", "binh.tt"])
async def test_not_assignee_403(who: str) -> None:
    """l1 khác (TC30), L2, employee (kể cả chính người gửi) → 403; không resume, không late_event."""
    async with desk_env() as env:
        ticket, aid, _, _ = await _pending(env)
        denied = env.denied()
        r = await _decide(env, aid, await env.token(who))
        assert r.status_code == 403
        assert env.denied() == denied + 1
        assert _resumes(env, ticket) == 0 and env.late(ticket) == []


@pytest.mark.asyncio
async def test_missing_approval_404() -> None:
    async with desk_env() as env:
        await _pending(env)
        l1 = await env.token("ha.lt")
        assert (await _decide(env, "999", l1)).status_code == 404
        assert (await _decide(env, "abc", l1)).status_code == 404


@pytest.mark.asyncio
async def test_already_decided_409_one_late_row() -> None:
    async with desk_env() as env:
        ticket, aid, _, l1 = await _pending(env)
        assert (await _decide(env, aid, l1)).status_code == 202
        await env.drain()
        r = await _decide(env, aid, l1, decision="rejected", note="đổi ý")
        assert r.status_code == 409
        [late] = env.late(ticket)
        assert late["detail"].items() >= {"approval_id": aid, "clicked_by": "l1_01",
                                          "reason": "already_decided", "source": "user"}.items()  # fmt: skip
        assert env.h.approvals.status(aid) == "approved"


@pytest.mark.asyncio
async def test_late_click_before_scan() -> None:
    """TC27 + Q2: quá hạn nhưng worker chưa quét → 409, 1 late_event, phiếu VẪN pending; worker quét
    → E6, phiếu timeout."""
    async with desk_env() as env:
        ticket, aid, an, l1 = await _pending(env)
        env.clock.advance(SLA + timedelta(seconds=1))
        l1 = await env.token("ha.lt")  # access token 15 phút — đăng nhập lại sau khi tua
        an = await env.token("an.nv")
        r = await _decide(env, aid, l1)
        assert r.status_code == 409
        [late] = env.late(ticket)
        assert late["detail"]["reason"] == "expired" and late["detail"]["approval_id"] == aid
        assert env.h.approvals.status(aid) == "pending"
        report = await WorkerJobs(env.h.runner, env.h.deadlines, env.h.turns).scan_deadlines()
        assert report.delivered == 1
        view = await env.ticket(ticket, an)
        assert (view["status"], view["exit_code"]) == (S_ESCALATED, "E6")
        assert env.h.approvals.status(aid) == "timeout"
        assert env.h.executor.calls[ticket] == 0


@pytest.mark.asyncio
async def test_deadline_boundary_409() -> None:
    async with desk_env() as env:
        ticket, aid, _, l1 = await _pending(env)
        deadline = env.h.approvals._table[aid]["deadline"]
        env.clock.set(deadline)  # đúng bằng hạn = muộn
        l1 = await env.token("ha.lt")
        assert (await _decide(env, aid, l1)).status_code == 409
        assert env.late(ticket)[0]["detail"]["reason"] == "expired"
        env.clock.set(deadline - timedelta(microseconds=1))
        l1 = await env.token("ha.lt")
        assert (await _decide(env, aid, l1)).status_code == 202


@pytest.mark.asyncio
async def test_tc27_late_click_409_uses_app_clock() -> None:
    """Giờ thật còn trước hạn (hạn năm 2026 + FakeClock tua qua) — so bằng Clock của app."""
    async with desk_env() as env:
        ticket, aid, _, l1 = await _pending(env)
        env.clock.advance(timedelta(hours=1))
        l1 = await env.token("ha.lt")
        assert (await _decide(env, aid, l1)).status_code == 409
        assert env.late(ticket)[0]["detail"]["reason"] == "expired"


@pytest.mark.asyncio
async def test_two_decisions_one_resume() -> None:
    """Hai request đồng thời: task nền của request đầu GIỮ khoá ticket tới hết lượt; request sau đứng
    chờ đúng khoá đó (lock_timeout đủ lớn) rồi gặp guard → 409 (không 503), đúng 1 lần resume, đúng 1
    late_event. Request sau phải tới chỗ lấy khoá TRƯỚC khi lượt đầu chạy — không thì nó ra 409 ở
    `lock_row` (phiếu đã quyết) và không kiểm được việc giao khoá."""
    async with desk_env() as env:
        ticket, aid, _, l1 = await _pending(env)
        in_turn, go, second_at_lock = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = env.h.runner.resume_locked

        async def gated(*a: Any, **kw: Any) -> Any:
            in_turn.set()
            await wait_for(go)
            return await original(*a, **kw)

        env.h.runner.resume_locked = gated  # type: ignore[method-assign]
        original_hold = env.h.lock.hold
        holds = 0

        def counting_hold(ticket_id: str) -> Any:
            nonlocal holds
            holds += 1
            if holds == 2:
                second_at_lock.set()
            return original_hold(ticket_id)

        env.h.lock.hold = counting_hold  # type: ignore[method-assign]
        first = await _decide(env, aid, l1)
        assert first.status_code == 202
        await wait_for(in_turn)  # task nền của request đầu đang giữ khoá, chưa chạy B16
        second = asyncio.create_task(_decide(env, aid, l1, decision="rejected", note="trùng"))
        await wait_for(second_at_lock)  # request sau đã qua lock_row (phiếu còn pending), tới khoá ticket
        await asyncio.sleep(0)
        assert not second.done()  # đang chờ khoá
        go.set()
        r2 = await second
        await env.drain()
        assert r2.status_code == 409
        assert _resumes(env, ticket) == 1
        [late] = env.late(ticket)
        assert late["detail"]["reason"] == "already_decided" and late["detail"]["clicked_by"] == "l1_01"
        assert env.h.approvals.status(aid) == "approved"
