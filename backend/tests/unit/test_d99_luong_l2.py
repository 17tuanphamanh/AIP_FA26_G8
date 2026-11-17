"""D-99 (Tuấn Anh chốt 17/11/2026: phần 1–5, L3 = Trưởng bộ phận IT) — vòng xử lý sau khi chuyển IT, qua API thật + bản giả
(`MemoryEscalations` + `MemoryAudit` của harness). SQL thật + migration 0018: `integration/test_d99_luong_l2_pg.py`.

1. Nhận ca: L1/L2 nhận ca cấp 2; bấm lại không đổi gì; người khác đã nhận → 409 `already_claimed`; nhân viên 403; Trưởng IT 403 với ca
   cấp 2; người gửi ticket không tự nhận (403); ca đóng → 409. Audit `L2`/`escalation_claimed`, `detail` không có chữ tự do.
2. Chuyển cấp 3: ca rời hàng đợi L2, vào hàng đợi cấp 3, bỏ người nhận cũ; L2 không còn đóng / chuyển được (403); ghi chú qua privacy
   guard; đích lạ → 422 `target`.
3. Trưởng IT nhận + đóng ca cấp 3 kèm lời nhắn người dùng (đã che; chép prompt → 422 `user_message`). Ca người khác giữ → 409.
4. `due_at` theo mức ưu tiên, `overdue` theo đồng hồ server; cấp 3 tính lại từ lúc chuyển.
5. `reopened_as_new` tạo ticket thật (đã kiểm ở test_escalation_close.py); thông báo + màn chat (`handling`) theo từng bước.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
import pytest
from app.api import notifications as notif
from app.db.escalations import CLAIM_EVENT, FLOW_STEP, RAISE_EVENT
from app.db.notifications import NotificationRow
from app.domain.escalation_flow import (
    L3_SLA_HOURS,
    SLA_HOURS_BY_RANK,
    due_at,
    is_overdue,
)
from app.domain.final import FinalSummary
from app.domain.states import S_ESCALATED
from app.guard.output import OutputGuard
from app.llm.registry import load_prompts
from app.settings import get_settings
from tests.fakes.auth import EPOCH
from tests.fakes.desk import MASK, SECRET, DeskEnv, desk_env
from tests.fakes.graph import MemoryEscalations
from tests.unit.test_approvals_view import _login

pytestmark = pytest.mark.asyncio

NOTE = "Đã kiểm tra với người dùng qua điện thoại."
QUEUE = "/api/escalations/queue"


def _final(code: str) -> FinalSummary:
    return FinalSummary(
        final_state=S_ESCALATED, exit_code=code, block_reason=None, close_reason=None, resolution_path="escalated",
        aggregate_status=None, auto_closed=False, intent=None, slots=None, total_turns=1, total_duration_seconds=1, closed_at=EPOCH,
    )  # fmt: skip


@asynccontextmanager
async def env_with(*codes: str, requester: str = "nv001") -> AsyncIterator[tuple[DeskEnv, MemoryEscalations]]:
    async with desk_env() as env:
        esc = MemoryEscalations(env.h.tickets, env.h.audit)
        for i, code in enumerate(codes, 1):
            tid = f"esc-{i}"
            env.h.tickets.register(tid, EPOCH, requester_id=requester, redacted_request="VPN báo lỗi 809")
            env.h.tickets.rows[tid]["final"] = _final(code)
            await esc.create(ticket_id=tid, exit_code=code, reason_detail=None, handoff_note={"request": "x"},
                             is_deny_case=code == "E5", created_at=EPOCH)  # fmt: skip
        env.app.state.escalations = esc
        yield env, esc


async def _post(env: DeskEnv, path: str, headers: dict[str, str], body: Any = None) -> httpx.Response:
    return await env.client.post(path, json=body, headers=headers) if body is not None else await env.client.post(path, headers=headers)


async def _queue(env: DeskEnv, headers: dict[str, str], tier: int, status: str = "open") -> list[dict[str, Any]]:
    r = await env.client.get(f"{QUEUE}?tier={tier}&status={status}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]  # type: ignore[no-any-return]


def _flow_audit(env: DeskEnv, event: str) -> list[dict[str, Any]]:
    return [r for r in env.h.audit.rows if (r["step"], r["event"]) == (FLOW_STEP, event)]


# ---- 1. nhận ca -----------------------------------------------------------------------------------------------------------------


async def test_l2_claims_then_reclaim_is_noop_and_others_get_409() -> None:
    async with env_with("E1") as (env, esc):
        long_ = await _login(env, "long.nh")
        r = await _post(env, "/api/escalations/1/claim", long_)
        assert r.status_code == 200, r.text
        assert r.json() == {"escalation_id": 1, "tier": 2, "assigned_to": "l2_01"}
        assert (esc.rows[0]["assigned_to"], esc.rows[0]["assigned_at"]) == ("l2_01", env.clock.now())
        assert (await _post(env, "/api/escalations/1/claim", long_)).status_code == 200  # bấm lại
        [audit] = _flow_audit(env, CLAIM_EVENT)
        assert audit["detail"] == {"escalation_id": 1, "by": "l2_01", "tier": 2}
        r = await _post(env, "/api/escalations/1/claim", await _login(env, "ha.lt"))
        assert (r.status_code, r.json()) == (409, {"detail": "already_claimed"})
        [item] = await _queue(env, long_, 2)
        assert (item["assigned_to"], item["tier"]) == ("l2_01", 2)


@pytest.mark.parametrize("user", ["an.nv", "quan.tm"])  # nhân viên; Trưởng IT với ca cấp 2
async def test_claim_forbidden_for_wrong_role_or_tier(user: str) -> None:
    async with env_with("E1") as (env, esc):
        denied = env.denied()
        r = await _post(env, "/api/escalations/1/claim", await _login(env, user))
        assert r.status_code == 403
        assert env.denied() == denied + 1 and esc.rows[0]["assigned_to"] is None


async def test_requester_cannot_claim_own_ticket() -> None:
    async with env_with("E1", requester="l2_01") as (env, esc):
        r = await _post(env, "/api/escalations/1/claim", await _login(env, "long.nh"))
        assert r.status_code == 403 and esc.rows[0]["assigned_to"] is None


async def test_claim_404_and_closed_409() -> None:
    async with env_with("E1") as (env, _):
        long_ = await _login(env, "long.nh")
        assert (await _post(env, "/api/escalations/9/claim", long_)).status_code == 404
        assert (await _post(env, "/api/escalations/abc/claim", long_)).status_code == 404
        r = await _post(env, "/api/escalations/1/close", long_, {"close_result": "completed", "note": NOTE})
        assert r.status_code == 200, r.text
        r = await _post(env, "/api/escalations/1/claim", long_)
        assert (r.status_code, r.json()) == (409, {"detail": "already_closed"})


async def test_close_without_claim_assigns_closer_and_other_holder_blocks_close() -> None:
    async with env_with("E1", "E1") as (env, esc):
        long_, ha = await _login(env, "long.nh"), await _login(env, "ha.lt")
        assert (await _post(env, "/api/escalations/1/close", long_, {"close_result": "completed", "note": NOTE})).status_code == 200
        assert esc.rows[0]["assigned_to"] == "l2_01"
        assert (await _post(env, "/api/escalations/2/claim", ha)).status_code == 200
        r = await _post(env, "/api/escalations/2/close", long_, {"close_result": "completed", "note": NOTE})
        assert (r.status_code, r.json()) == (409, {"detail": "already_claimed"}) and esc.rows[1]["closed_at"] is None


# ---- 2. chuyển cấp 3 --------------------------------------------------------------------------------------------------------------


async def test_raise_moves_case_to_l3_queue_and_l2_loses_it() -> None:
    async with env_with("E5") as (env, esc):
        long_ = await _login(env, "long.nh")
        assert (await _post(env, "/api/escalations/1/claim", long_)).status_code == 200
        r = await _post(env, "/api/escalations/1/raise", long_, {"target": "it_manager", "note": f"Cần ngoại lệ chính sách {SECRET}"})
        assert r.status_code == 200, r.text
        assert {k: r.json()[k] for k in ("escalation_id", "tier", "raise_target", "raised_by")} == {
            "escalation_id": 1, "tier": 3, "raise_target": "it_manager", "raised_by": "l2_01",
        }  # fmt: skip
        row = esc.rows[0]
        assert (row["tier"], row["assigned_to"], row["assigned_at"]) == (3, None, None)
        assert SECRET not in row["raise_note"] and MASK in row["raise_note"]  # ghi chú qua privacy guard
        [audit] = _flow_audit(env, RAISE_EVENT)
        assert audit["detail"] == {"escalation_id": 1, "by": "l2_01", "target": "it_manager", "note_length": len(row["raise_note"])}
        assert await _queue(env, long_, 2) == []
        [item] = await _queue(env, long_, 3)  # L2 vẫn THEO DÕI được ca đã chuyển (chỉ đọc)
        assert (item["tier"], item["raise_target"], item["assigned_to"]) == (3, "it_manager", None)
        # L2 không còn xử lý ca cấp 3
        assert (await _post(env, "/api/escalations/1/claim", long_)).status_code == 403
        assert (await _post(env, "/api/escalations/1/raise", long_, {"target": "vendor", "note": NOTE})).status_code == 403
        assert (await _post(env, "/api/escalations/1/close", long_, {"close_result": "confirmed_denial", "note": NOTE})).status_code == 403


@pytest.mark.parametrize(
    ("body", "fields"),
    [({"target": "ceo", "note": NOTE}, ["target"]), ({"target": "vendor"}, ["note"]), ({"target": "vendor", "note": "  "}, ["note"])],
)
async def test_raise_body_validated(body: dict[str, Any], fields: list[str]) -> None:
    async with env_with("E1") as (env, esc):
        r = await _post(env, "/api/escalations/1/raise", await _login(env, "long.nh"), body)
        assert r.status_code == 422 and r.json() == {"error": "invalid_request", "fields": fields}
        assert esc.rows[0]["tier"] == 2


async def test_raise_blocked_when_other_holds_case() -> None:
    async with env_with("E1") as (env, esc):
        assert (await _post(env, "/api/escalations/1/claim", await _login(env, "ha.lt"))).status_code == 200
        r = await _post(env, "/api/escalations/1/raise", await _login(env, "long.nh"), {"target": "vendor", "note": NOTE})
        assert (r.status_code, r.json()) == (409, {"detail": "already_claimed"}) and esc.rows[0]["tier"] == 2


# ---- 3. Trưởng IT xử lý ca cấp 3 + lời nhắn người dùng ------------------------------------------------------------------------


async def _raised(env: DeskEnv) -> None:
    long_ = await _login(env, "long.nh")
    r = await _post(env, "/api/escalations/1/raise", long_, {"target": "vendor", "note": "Cần nhà cung cấp thay bàn phím"})
    assert r.status_code == 200, r.text


async def test_l3_claims_and_closes_with_user_message() -> None:
    async with env_with("E1") as (env, esc):
        await _raised(env)
        quan = await _login(env, "quan.tm")
        r = await _post(env, "/api/escalations/1/claim", quan)
        assert r.status_code == 200 and r.json() == {"escalation_id": 1, "tier": 3, "assigned_to": "it_mgr01"}
        msg = f"Nhà cung cấp sẽ thay bàn phím vào sáng thứ Hai, mật khẩu cũ {SECRET} bạn nên đổi."
        r = await _post(env, "/api/escalations/1/close", quan, {"close_result": "completed", "note": NOTE, "user_message": msg})
        assert r.status_code == 200, r.text
        stored = esc.rows[0]["user_message"]
        assert r.json()["user_message"] == stored and SECRET not in stored and MASK in stored
        assert (esc.rows[0]["closed_by"], esc.rows[0]["tier"]) == ("it_mgr01", 3)
        [closed] = await _queue(env, quan, 3, "closed")
        assert closed["user_message"] == stored and closed["overdue"] is False


async def test_user_message_copying_a_prompt_is_rejected() -> None:
    prompt_line = next(
        line for p in load_prompts(get_settings().config_dir / "prompts") for line in p.spec.system.splitlines() if len(line) >= 80
    )
    async with env_with("E1") as (env, esc):
        r = await _post(env, "/api/escalations/1/close", await _login(env, "long.nh"),
                        {"close_result": "completed", "note": NOTE, "user_message": prompt_line[:400]})  # fmt: skip
        assert r.status_code == 422 and r.json() == {"error": "invalid_request", "fields": ["user_message"]}
        assert esc.rows[0]["closed_at"] is None


@pytest.mark.parametrize("bad", ["", "   ", "x" * 501])
async def test_user_message_length_validated(bad: str) -> None:
    async with env_with("E1") as (env, _):
        r = await _post(env, "/api/escalations/1/close", await _login(env, "long.nh"),
                        {"close_result": "completed", "note": NOTE, "user_message": bad})  # fmt: skip
        assert r.status_code == 422 and r.json()["fields"] == ["user_message"]


# ---- 4. hạn xử lý ---------------------------------------------------------------------------------------------------------------


def test_due_at_by_rank_and_l3_restart() -> None:
    assert due_at(created_at=EPOCH, rank=2, tier=2, raised_at=None) == EPOCH + timedelta(hours=SLA_HOURS_BY_RANK[2])
    assert due_at(created_at=EPOCH, rank=99, tier=2, raised_at=None) == EPOCH + timedelta(hours=24)
    raised = EPOCH + timedelta(hours=5)
    assert due_at(created_at=EPOCH, rank=6, tier=3, raised_at=raised) == raised + timedelta(hours=L3_SLA_HOURS)
    due = EPOCH + timedelta(hours=1)
    assert is_overdue(due=due, now=due + timedelta(seconds=1), closed_at=None)
    assert not is_overdue(due=due, now=due, closed_at=None)
    assert not is_overdue(due=due, now=due + timedelta(days=9), closed_at=EPOCH)


async def test_queue_reports_due_and_overdue_with_server_clock() -> None:
    async with env_with("E0") as (env, _):  # E0 rank 2 → 1 giờ
        long_ = await _login(env, "long.nh")
        [item] = await _queue(env, long_, 2)
        assert item["due_at"].startswith((EPOCH + timedelta(hours=1)).isoformat()[:19]) and item["overdue"] is False
        env.clock.advance(timedelta(hours=2))
        assert (await _queue(env, await _login(env, "long.nh"), 2))[0]["overdue"] is True  # token cũ đã hết hạn


async def test_cursor_not_shared_across_tiers() -> None:
    async with env_with("E1", "E1", "E1") as (env, _):
        long_ = await _login(env, "long.nh")
        r = await env.client.get(f"{QUEUE}?limit=1", headers=long_)
        cursor = r.json()["next_cursor"]
        assert cursor is not None
        r = await env.client.get(f"{QUEUE}?tier=3&limit=1&after={cursor}", headers=long_)
        assert r.status_code == 422 and r.json()["fields"] == ["query.after"]
        assert (await env.client.get(f"{QUEUE}?tier=4", headers=long_)).status_code == 422


# ---- 5. thông báo + màn chat --------------------------------------------------------------------------------------------------------


def _row(kind: str, result: str, **kw: Any) -> NotificationRow:
    return NotificationRow(f"x:{kind}", kind, "t1", result, EPOCH, **kw)


def _guard() -> OutputGuard:
    settings = get_settings()
    return OutputGuard.from_config(settings.config_dir, settings.output_canaries)


def test_notification_texts_for_each_step() -> None:
    g = _guard()
    assert notif.notification_text(_row("escalation_claimed", "in_progress", tier=2), g) == notif.CLAIMED_TEXT[2]
    assert notif.notification_text(_row("escalation_claimed", "in_progress", tier=3), g).startswith("Trưởng bộ phận IT")
    assert notif.notification_text(_row("escalation_raised", "raised", raise_target="vendor"), g) == notif.RAISED_TEXT["vendor"]
    text = notif.notification_text(_row("escalation_closed", "completed", user_message="Đã thay bàn phím."), g)
    assert text == f"{notif.CLOSED_TEXT['completed']} {notif.USER_MESSAGE_PREFIX} Đã thay bàn phím."
    assert notif.notification_text(_row("escalation_closed", "reopened_as_new", new_ticket_id="n1"), g) == notif.REOPENED_TEXT
    assert notif.notification_text(_row("escalation_closed", "reopened_as_new"), g) == notif.CLOSED_TEXT["reopened_as_new"]
    for row in (_row("escalation_raised", "raised", raise_target="it_manager"), _row("escalation_claimed", "in_progress", tier=3)):
        text = notif.notification_text(row, g)
        assert not any(w in text for w in ("R1", "E5", "it_manager", "l2_01", "ghi chú"))


async def test_ticket_view_handling_follows_each_step() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        env.app.state.escalations = env.h.escalations
        stages = [(await env.ticket(ticket, an))["handling"][0]["stage"]]
        long_ = await _login(env, "long.nh")
        eid = env.h.escalations.rows[0]["escalation_id"]
        assert (await _post(env, f"/api/escalations/{eid}/claim", long_)).status_code == 200
        stages.append((await env.ticket(ticket, an))["handling"][0]["stage"])
        assert (await _post(env, f"/api/escalations/{eid}/raise", long_, {"target": "it_manager", "note": NOTE})).status_code == 200
        stages.append((await env.ticket(ticket, an))["handling"][0]["stage"])
        quan = await _login(env, "quan.tm")
        body = {"close_result": "confirmed_denial", "note": NOTE, "user_message": "Không cấp được vì vượt quyền phòng ban."}
        assert (await _post(env, f"/api/escalations/{eid}/close", quan, body)).status_code == 200
        view = (await env.ticket(ticket, an))["handling"][0]
        stages.append(view["stage"])
        assert stages == ["waiting", "claimed", "raised", "closed"]
        assert set(view) == {"ticket_id", "stage", "tier", "raise_target", "close_result", "user_message", "new_ticket_id", "updated_at"}
        assert (view["tier"], view["raise_target"], view["close_result"]) == (3, "it_manager", "confirmed_denial")
        assert view["user_message"] == "Không cấp được vì vượt quyền phòng ban."


async def test_ticket_view_handling_null_without_cases() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        assert (await env.ticket(ticket, an))["handling"] is None
