"""Q13b (D-79, 11/11, bản nộp main) — "Hỏi tiếp" sau khi ticket ĐÃ kết thúc (test viết trước).

Hợp đồng:
- `POST /api/tickets {text, follows_ticket_id}`: ticket cũ phải TỒN TẠI, của ĐÚNG người gửi, là ticket GỐC, ĐÃ kết thúc; sai bất kỳ →
  404 `not_found` GIỐNG HỆT nhau, không tạo ticket. Cờ `ENABLE_SESSION_MEMORY` tắt → 422 `body.follows_ticket_id` (như trước lô).
- Ticket mới chạy ĐỦ đường như mọi ticket; state đầu có `follows_ticket_id` + `prior_hint` = MỘT dòng dựng từ cột đóng (intent, kết quả
  cuối) — không chữ người dùng, không slot. B3 nhận `prior_hint` ở biến `label_hint` có sẵn.
- `GET` → `can_follow_up` = cờ bật VÀ đã kết thúc VÀ ticket gốc VÀ người đọc là chủ.
- Chỉ `b03_classify` đọc `prior_hint`/`follows_ticket_id` (M5/B12/B14/B15/B17 không đọc — AST).
"""

import ast
import dataclasses
from pathlib import Path
from typing import Any

import pytest
from app.domain.session_memory import FollowUpSource, can_follow, prior_label_hint
from app.domain.states import S_ESCALATED
from tests.fakes.desk import DeskEnv, desk_env

NOT_FOUND = {"detail": "not_found"}
APP = Path(__file__).resolve().parents[2] / "app"
CANARY = "chuoi-canary-q13b-khong-duoc-sang-ticket-moi"


def src(**over: Any) -> FollowUpSource:
    base: dict[str, Any] = {"ticket_id": "t0", "requester_id": "nv001", "parent_ticket_id": None, "is_parent": False,
                            "final_state": S_ESCALATED, "intent": "vpn"}  # fmt: skip
    return FollowUpSource(**{**base, **over})


# ---- domain thuần ----------------------------------------------------------------------------------------------------------------


def test_can_follow_rules() -> None:
    assert can_follow(src(), "nv001") is True
    assert can_follow(None, "nv001") is False
    assert can_follow(src(requester_id="nv002"), "nv001") is False
    assert can_follow(src(parent_ticket_id="p"), "nv001") is False
    assert can_follow(src(final_state=None), "nv001") is False
    assert can_follow(src(is_parent=True, intent=None), "nv001") is True  # cha nhiều ý đã kết thúc: hỏi tiếp được, không gợi ý


def test_prior_hint_only_closed_columns() -> None:
    hint = prior_label_hint(src())
    assert hint is not None and hint.startswith("vpn ") and "đã chuyển kỹ thuật viên" in hint
    assert prior_label_hint(src(intent=None)) is None
    assert prior_label_hint(src(intent="out_of_scope")) is None
    assert prior_label_hint(src(intent="khong-biet")) is None
    assert "đã xong" in str(prior_label_hint(src(final_state="S_RESOLVED", intent="it_help")))


# ---- API --------------------------------------------------------------------------------------------------------------------------


async def _closed(env: DeskEnv, headers: dict[str, str], text: str = "VPN không vào được") -> str:
    ticket = await env.create(headers, text=text)
    await env.drain()
    assert env.h.tickets.final(ticket) is not None
    return ticket


async def _follow(env: DeskEnv, headers: dict[str, str], follows: str, text: str = "vẫn chưa được") -> Any:
    return await env.client.post("/api/tickets", json={"text": text, "follows_ticket_id": follows}, headers=headers)


@pytest.mark.asyncio
async def test_follow_up_creates_new_ticket_with_hint_and_no_old_text() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        old = await _closed(env, an, text=f"VPN lỗi {CANARY}")
        env.h.tickets.rows[old]["final"] = dataclasses.replace(env.h.tickets.rows[old]["final"], intent="vpn")
        r = await _follow(env, an, old)
        assert r.status_code == 202, r.text
        new = r.json()["ticket_id"]
        assert new != old
        await env.drain()
        state = (await env.h.runner.snapshot(new)).values
        assert state["follows_ticket_id"] == old
        assert state["prior_hint"] == prior_label_hint(src(intent="vpn"))
        assert CANARY not in str(state) and state["redacted_request"] == "vẫn chưa được"
        assert (await env.ticket(old, an))["can_follow_up"] is True


@pytest.mark.asyncio
async def test_follow_up_refused_404_same_for_missing_other_open() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an, binh = await env.token("an.nv"), await env.token("binh.tt")
        mine = await _closed(env, an)
        before = len(env.h.tickets.rows)
        missing = await _follow(env, an, "khong-co")
        other = await _follow(env, binh, mine)  # ticket của người khác
        assert (missing.status_code, missing.json()) == (other.status_code, other.json()) == (404, NOT_FOUND)
        assert len(env.h.tickets.rows) == before  # không tạo ticket nào
    async with desk_env(plan={"b11_slots": "missing"}) as env:  # ticket còn mở (đang hỏi lại)
        an = await env.token("an.nv")
        opened = await env.create(an)
        await env.drain()
        r = await _follow(env, an, opened)
        assert (r.status_code, r.json()) == (404, NOT_FOUND)
        assert (await env.ticket(opened, an))["can_follow_up"] is False


@pytest.mark.asyncio
async def test_follow_up_child_ticket_404() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an = await env.token("an.nv")
        old = await _closed(env, an)
        env.h.tickets.rows[old]["parent_ticket_id"] = "cha-nao-do"
        r = await _follow(env, an, old)
        assert (r.status_code, r.json()) == (404, NOT_FOUND)


@pytest.mark.asyncio
async def test_flag_off_rejects_field_and_hides_composer() -> None:
    async with desk_env(plan={"b12_assess": "deny"}, enable_session_memory=False) as env:
        an = await env.token("an.nv")
        old = await _closed(env, an)
        before = len(env.h.tickets.rows)
        r = await _follow(env, an, old)
        assert r.status_code == 422 and "body.follows_ticket_id" in r.text
        assert len(env.h.tickets.rows) == before
        assert (await env.ticket(old, an))["can_follow_up"] is False


@pytest.mark.asyncio
async def test_staff_reader_cannot_follow_up_for_owner() -> None:
    async with desk_env(plan={"b12_assess": "deny"}) as env:
        an, l1 = await env.token("an.nv"), await env.token("ha.lt")
        old = await _closed(env, an)
        assert (await env.ticket(old, l1))["can_follow_up"] is False


@pytest.mark.asyncio
async def test_plain_create_unchanged_no_hint() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        t = await env.create(an)
        await env.drain()
        state = (await env.h.runner.snapshot(t)).values
        assert state.get("follows_ticket_id") is None and state.get("prior_hint") is None


# ---- chỉ B3 đọc gợi ý ------------------------------------------------------------------------------------------------------------


def _names_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_only_b3_reads_prior_hint() -> None:
    readers = [p.relative_to(APP).as_posix() for p in APP.rglob("*.py")
               if {"prior_hint", "follows_ticket_id"} & _names_in(p)]  # fmt: skip
    assert sorted(readers) == ["graph/nodes/b03_classify.py", "graph/runner.py"]
    for core in ("policy", "risk", "graph/nodes/b12_assess.py", "graph/nodes/b15_prepare_approval.py", "graph/nodes/b17_execute.py"):
        assert not any(r.startswith(core) for r in readers), core


# ---- B3 nhận gợi ý qua `label_hint` (node thật, ScriptedLLM) -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b3_gets_prior_hint_as_label_hint_and_audits_flag() -> None:
    from datetime import timedelta

    from app.core.clock import FakeClock
    from app.db.tickets import NewTicket
    from app.llm.providers.scripted import Reply
    from tests.fakes.graph import GraphHarness
    from tests.fakes.identity import ad_user
    from tests.fakes.llm import make_gateway
    from tests.fixtures.llm.vpn import vpn_scripts
    from tests.unit.test_q12_it_help import NOT_ATTACK, SESSION, _rag

    clock = FakeClock()
    gw = make_gateway({**vpn_scripts(action=None), "b02_injection_judge": lambda _: Reply(NOT_ATTACK)}, clock=clock)  # type: ignore[dict-item]
    h = GraphHarness(clock=clock, nodes="real", llm=gw.client, rag=_rag())
    h.identity.add_session(SESSION, "nv001", expires_at=clock.now() + timedelta(days=365))
    h.ad.users["nv001"] = ad_user("nv001")
    hint = prior_label_hint(src(intent="vpn"))
    for ticket, turn, follows in (("t1", "turn-1", None), ("t2", "turn-2", "t0")):
        await h.tickets.create(
            NewTicket(ticket_id=ticket, requester_id="nv001", requester_role="employee", requester_dept="it", session_id=SESSION,
                      redacted_request="vẫn chưa được", created_at=clock.now()),
            turn_id=turn,
        )  # fmt: skip
        await h.runner.run_new(ticket, turn, follows_ticket_id=follows, prior_hint=hint if follows else None)
    first, second = gw.llm.calls_for("b03_classify")[:2]
    assert first.variables["label_hint"] is None and second.variables["label_hint"] == hint
    assert [r["detail"]["follows_ticket"] for t in ("t1", "t2") for r in h.audit.of(t, "intent_classified")[:1]] == [False, True]
