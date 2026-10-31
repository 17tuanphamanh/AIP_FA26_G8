"""R3 — `GET /api/tickets/{ticket_id}` → `TicketView.deadline`. Viết TỪ HỢP ĐỒNG (lời giao agent chính), trước code — không mở
`api/tickets.py`, `api/approvals.py`, `approval/store.py`.

`deadline`: datetime ISO có múi giờ (UTC) | null — hạn của LẦN CHỜ HIỆN TẠI. Không đổi `waiting_for`, không đổi thứ tự 403/404/503,
(`server_now` + hạn của ticket CHA: test_ticket_server_now.py).
- ticket đã kết thúc (`tickets.final_state` có) → null; ticket cha (`tickets.is_parent`): hạn riêng của cha / hạn sớm nhất phiếu `pending` của con (test_ticket_server_now.py).
- `waiting_for == "approval"` → `approvals.deadline` của phiếu `pending` của ticket (phiếu đã đóng → không tính → null).
- `waiting_for == "confirm"` / `"clarify"` → `deadline` của dòng `wait_deadlines` cùng loại, `fired_at` None (dòng worker dùng).
- `waiting_for` "reply" / None → null. Ticket con chờ clarify/confirm → null (không có dòng — hạn do cha giữ).
- quá hạn mà worker chưa bắn → vẫn trả mốc (trong quá khứ).

`desk_env`: mặc định → ticket của an.nv (nv001) tới chờ duyệt, phiếu giao ha.lt (l1_01); `b11_slots=missing` → chờ hỏi lại;
`b12_assess=deny` → kết thúc. Người: an.nv = chủ, binh.tt = nhân viên khác, ha.lt = l1. Bảng giả: `env.h.deadlines.waits`
(list dict {ticket_id, kind, deadline, created_turn, fired_at, is_parent}), `env.h.approvals._table`, `env.h.tickets.rows`.
"""

from datetime import datetime
from typing import Any

import pytest
from app.domain.final import FinalSummary
from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_PENDING_APPROVAL, S_REJECTED
from app.main import create_app
from tests.fakes.desk import DeskEnv, desk_env
from tests.unit.auth_helpers import auth_settings
from tests.unit.test_t20b_api import api, tc35

pytestmark = pytest.mark.asyncio

NOT_FOUND = {"detail": "not_found"}
TICKET_ROUTE = "/api/tickets/{ticket_id}"


# ---- helpers ---------------------------------------------------------------------------------------------------------------


async def _pending(env: DeskEnv) -> tuple[str, str, dict[str, str]]:
    """Ticket của an.nv tới chờ duyệt (B15 giả giao l1_01). Trả (ticket_id, approval_id, header của an.nv)."""
    an = await env.token("an.nv")
    ticket = await env.create(an)
    await env.drain()
    assert (await env.ticket(ticket, an))["status"] == S_PENDING_APPROVAL
    aid = env.approval_of(ticket)
    assert env.h.approvals._table[aid]["status"] == "pending"
    return ticket, aid, an


def _deadline(body: dict[str, Any]) -> datetime | None:
    """`deadline` của thân TicketView: khoá phải có; có giá trị thì là ISO CÓ múi giờ."""
    assert "deadline" in body, sorted(body)
    raw = body["deadline"]
    if raw is None:
        return None
    value = datetime.fromisoformat(raw)
    assert value.tzinfo is not None, raw
    return value


def _open_wait(env: DeskEnv, ticket: str, kind: str) -> dict[str, Any]:
    """Dòng `wait_deadlines` chưa bắn (đúng 1) của ticket theo loại."""
    rows = [w for w in env.h.deadlines.waits if w["ticket_id"] == ticket and w["kind"] == kind and w["fired_at"] is None]  # fmt: skip
    assert len(rows) == 1, env.h.deadlines.waits
    return rows[0]


async def _decide(env: DeskEnv, aid: str, **body: Any) -> None:
    ha = await env.token("ha.lt")
    r = await env.client.post(f"/api/approvals/{aid}/decision", json=body, headers=ha)
    assert r.status_code == 202, r.text
    await env.drain()


# ---- r1–r2: chờ duyệt -----------------------------------------------------------------------------------------------------------


async def test_r3_r1_pending_approval_deadline_is_approval_deadline() -> None:
    """r1: chờ duyệt → `waiting_for` "approval", `deadline` == `approvals.deadline` của phiếu `pending` (có múi giờ)."""
    async with desk_env() as env:
        ticket, aid, an = await _pending(env)
        body = await env.ticket(ticket, an)
        assert body["waiting_for"] == "approval"
        assert _deadline(body) == env.h.approvals._table[aid]["deadline"]


async def test_r3_r2_closed_approval_while_checkpoint_waiting_deadline_null() -> None:
    """r2: phiếu bị đóng ĐẶT TAY (approved, như c8) trong khi checkpoint vẫn ở `approval_wait` → `waiting_for` vẫn "approval"
    (không đổi cách tính), nhưng phiếu không còn `pending` → `deadline` null."""
    async with desk_env() as env:
        ticket, aid, an = await _pending(env)
        env.h.approvals._table[aid].update(status="approved", decided_at=env.clock.now(), decided_by="l1_01", note="x")  # fmt: skip
        snap = await env.h.runner.snapshot(ticket)
        assert snap.next == ("approval_wait",)
        body = await env.ticket(ticket, an)
        assert body["waiting_for"] == "approval"
        assert _deadline(body) is None


# ---- r3–r4: sau quyết định duyệt -----------------------------------------------------------------------------------------------


async def test_r3_r3_rejected_via_route_final_deadline_null() -> None:
    """r3: từ chối qua route → drain → ticket kết thúc (`final_state` có) → `deadline` null."""
    async with desk_env() as env:
        ticket, aid, an = await _pending(env)
        await _decide(env, aid, decision="rejected", note="x", reason_code="wrong_device")  # fmt: skip
        final = env.h.tickets.final(ticket)
        assert final is not None, "tiền điều kiện: từ chối phải kết thúc ticket"
        body = await env.ticket(ticket, an)
        assert body["final_state"] == final.final_state
        assert _deadline(body) is None


async def test_r3_r4_approved_confirm_wait_deadline_is_open_confirm_row() -> None:
    """r4: duyệt → drain → B17 giả → chờ xác nhận → `waiting_for` "confirm", `deadline` == dòng `wait_deadlines` kind "confirm"
    chưa bắn của ticket (đúng 1 dòng — dòng worker dùng để tự đóng 48 giờ), KHÁC hạn phiếu duyệt."""
    async with desk_env() as env:
        ticket, aid, an = await _pending(env)
        await _decide(env, aid, decision="approved")
        body = await env.ticket(ticket, an)
        assert (body["status"], body["waiting_for"]) == (S_CONFIRMING, "confirm")
        row = _open_wait(env, ticket, "confirm")
        assert _deadline(body) == row["deadline"]
        assert row["deadline"] != env.h.approvals._table[aid]["deadline"]


# ---- r5–r6: chờ hỏi lại / kết thúc ngay ---------------------------------------------------------------------------------------


async def test_r3_r5_clarify_deadline_is_open_clarify_row() -> None:
    """r5: B11 thiếu slot → chờ hỏi lại → `waiting_for` "clarify", `deadline` == dòng `wait_deadlines` kind "clarify" chưa bắn."""
    async with desk_env(plan={"b11_slots": "missing"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        body = await env.ticket(ticket, an)
        assert (body["status"], body["waiting_for"]) == (S_CLARIFYING, "clarify")
        assert _deadline(body) == _open_wait(env, ticket, "clarify")["deadline"]


async def test_r3_r6_deny_final_deadline_null() -> None:
    """r6: B12 deny → kết thúc ngay → `deadline` null."""
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        assert env.h.tickets.final(ticket) is not None
        body = await env.ticket(ticket, an)
        assert body["waiting_for"] is None
        assert _deadline(body) is None


# ---- r7: IDOR giữ nguyên --------------------------------------------------------------------------------------------------------


async def test_r3_r7_other_employee_404_l1_200_with_deadline() -> None:
    """r7: binh.tt (nhân viên khác) GET ticket của an.nv → 404 `{"detail": "not_found"}` GIỐNG HỆT id không có (không lộ
    `deadline`); ha.lt (l1) đọc được → 200 có khoá `deadline` = hạn phiếu."""
    async with desk_env() as env:
        ticket, aid, _ = await _pending(env)
        binh = await env.token("binh.tt")
        other = await env.client.get(f"/api/tickets/{ticket}", headers=binh)
        missing = await env.client.get("/api/tickets/khong-co", headers=binh)
        assert (other.status_code, other.json()) == (missing.status_code, missing.json()) == (404, NOT_FOUND)  # fmt: skip
        assert other.content == missing.content
        ha = await env.token("ha.lt")
        body = await env.ticket(ticket, ha)
        assert _deadline(body) == env.h.approvals._table[aid]["deadline"]


# ---- r8–r9: ticket cha + guard phòng thủ ---------------------------------------------------------------------------------------


async def test_r3_r8_real_parent_reply_wait_deadline_is_parents_own_wait() -> None:
    """r8 (đổi theo hợp đồng ĐP 27/10): ticket CHA thật (TC35, graph thật `_t20b.make_flow`) tới `parent_reply_wait` → `waiting_for` "reply",
    `deadline` = hạn chờ RIÊNG của cha (dòng `wait_deadlines` chưa bắn do `parent_wait` đặt) — trước đây null."""
    f = await tc35()
    assert f.h.tickets.rows["T1"]["is_parent"] is True
    open_waits = [w for w in f.h.deadlines.waits if w["ticket_id"] == "T1" and w["fired_at"] is None]  # fmt: skip
    assert open_waits, f.h.deadlines.waits
    async with api(f) as a:
        an = await a.token("an.nv")
        body = await a.get(an)
        assert body["waiting_for"] == "reply"
        assert _deadline(body) == max(w["deadline"] for w in open_waits)


async def test_r3_r9a_guard_is_parent_pending_approval_deadline_null() -> None:
    """r9a — GUARD PHÒNG THỦ theo hợp đồng ("ticket cha nhiều ý → null"): luồng thật cha KHÔNG BAO GIỜ ở `approval_wait`; test đặt
    tay `is_parent=True` lên ticket thường đang chờ duyệt (phiếu `pending` có hạn) để guard không bị bỏ lặng lẽ → `deadline` null."""
    async with desk_env() as env:
        ticket, aid, an = await _pending(env)
        assert env.h.approvals._table[aid]["status"] == "pending"
        env.h.tickets.rows[ticket]["is_parent"] = True
        body = await env.ticket(ticket, an)
        assert _deadline(body) is None


async def test_r3_r9b_guard_final_state_pending_approval_deadline_null() -> None:
    """r9b — GUARD PHÒNG THỦ ("đã kết thúc → null"): ticket đang chờ duyệt (checkpoint `approval_wait`, phiếu `pending`) nhưng dòng
    `tickets` có `final_state` ĐẶT TAY (S_REJECTED) → `deadline` null dù phiếu còn hạn."""
    async with desk_env() as env:
        ticket, aid, an = await _pending(env)
        assert env.h.approvals._table[aid]["status"] == "pending"
        env.h.tickets.rows[ticket]["final"] = FinalSummary(
            final_state=S_REJECTED, exit_code=None, block_reason=None, close_reason=None, resolution_path=None,
            aggregate_status=None, auto_closed=False, intent=None, slots=None, total_turns=1, total_duration_seconds=0,
            closed_at=env.clock.now(),
        )  # fmt: skip
        body = await env.ticket(ticket, an)
        assert body["final_state"] == S_REJECTED
        assert _deadline(body) is None


# ---- r10: OpenAPI ---------------------------------------------------------------------------------------------------------------


async def test_r3_r10_openapi_ticket_view_deadline_nullable_datetime() -> None:
    """r10: schema 200 của GET `/api/tickets/{ticket_id}` `$ref` TicketView; TicketView có `deadline` với anyOf gồm
    {type string, format date-time} và {type null}. (async chỉ vì `pytestmark` asyncio của module.)"""
    spec = create_app(auth_settings(), health_checks={}).openapi()
    ok = spec["paths"][TICKET_ROUTE]["get"]["responses"]["200"]["content"]["application/json"]["schema"]  # fmt: skip
    assert str(ok.get("$ref", "")).rsplit("/", 1)[-1] == "TicketView", ok
    props = spec["components"]["schemas"]["TicketView"]["properties"]
    assert "deadline" in props, sorted(props)
    assert "deadline" in spec["components"]["schemas"]["TicketView"]["required"]  # bắt buộc trong schema, có thể null
    any_of = props["deadline"].get("anyOf", [])
    is_datetime = [s.get("type") == "string" and s.get("format") == "date-time" for s in any_of]  # fmt: skip
    assert any(is_datetime), props["deadline"]
    assert {"type": "null"} in any_of, props["deadline"]
