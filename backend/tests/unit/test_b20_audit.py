"""B20 thật (B20 mục 5, 5.1, 11 — phần làm được ở Phase 2) trên runtime giả.

Mỗi mã E0–E9 do node giả sinh → đúng 1 escalation, rank theo seed, ghi chú bàn giao 4 phần, 1 tin theo
mẫu; 6/8 `close_reason` (2 giá trị của L2 ở Phase 7, 2b-Q5); `resolution_path` suy ở B20 (Q-A); B20
chạy lại ở mọi khe hở → không trùng, audit khớp `tickets` (Q-C). Bản Postgres: `integration/test_b20_pg.py`.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from app.domain.states import (
    S_BLOCKED,
    S_CLARIFYING,
    S_CONFIRMING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
)
from app.graph.late_event import deliver_event
from app.settings import get_escalation_templates
from tests.fakes.graph import Crash, GraphHarness, seed_priority
from tests.fakes.identity import REQUESTER

TEMPLATES = get_escalation_templates()
PRIORITY = seed_priority()

type Scenario = Callable[[GraphHarness, str], Awaitable[Any]]


async def _submit(h: GraphHarness, t: str, **plan: str) -> Any:
    return await h.submit(t, **plan)


async def _then(h: GraphHarness, t: str, status: str, event: dict[str, Any], **plan: str) -> Any:
    await h.submit(t, **plan)
    return await deliver_event(h.runner, t, status, event)


async def _ad_down(h: GraphHarness, t: str) -> Any:
    h.ad.down = True
    return await h.submit(t)


E_CASES: dict[str, Scenario] = {
    "E0": lambda h, t: _submit(h, t, b02_screen="injection"),
    "E1": lambda h, t: _submit(h, t, b03_classify="out_of_scope"),
    "E2": _ad_down,
    "E3": lambda h, t: _submit(h, t, b08_retrieve="no_evidence"),
    "E4": lambda h, t: _then(h, t, S_CLARIFYING, {"kind": "timeout"}, b11_slots="missing"),
    "E5": lambda h, t: _submit(h, t, b12_assess="deny"),
    "E6": lambda h, t: _then(h, t, S_PENDING_APPROVAL, {"kind": "timeout"}),
    "E7": lambda h, t: _submit(h, t, b12_assess="auto", b17_execute="fail"),
    "E8": lambda h, t: _then(h, t, S_CONFIRMING, {"kind": "unresolved"}, b12_assess="auto"),
    "E9": lambda h, t: _submit(h, t, b06_diagnose="raise"),
}


def _closed(h: GraphHarness, t: str) -> list[dict[str, Any]]:
    return h.audit.of(t, "closed")


# ---- E0–E9: một escalation, đúng rank, ghi chú 4 phần, một tin ------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("code", sorted(E_CASES))
async def test_each_exit_code_one_escalation_with_handoff_and_message(code: str) -> None:
    h = GraphHarness()
    r = await E_CASES[code](h, "t1")
    assert (r.values["exit_code"], r.waiting_at) == (code, None)
    [esc] = h.escalations.of("t1")
    assert (esc["exit_code"], esc["priority"]) == (code, PRIORITY[code][0])  # rank từ seed 0001
    assert set(esc["handoff_note"]) == {"request", "done_so_far", "why_escalated", "next_for_l2"}
    assert all(v.strip() for v in esc["handoff_note"].values())
    assert esc["handoff_note"]["why_escalated"].startswith("Lý do chuyển: ")  # ĐP 02/11: "nhãn · mã", mã để cuối
    assert f" · {code}. Mức ưu tiên: " in esc["handoff_note"]["why_escalated"]
    assert esc["is_deny_case"] is (code == "E5")  # 2b-Q4
    message = TEMPLATES.of(code).user_message
    assert h.notifier.sent[-1] == ("t1", message, "none")
    assert r.values["conversation"][-1] == {
        "role": "assistant", "kind": "escalation", "text": message, "ref": r.values["conversation"][-1]["ref"]}
    assert h.effects.count("t1", "escalation_create") == 1
    [row] = _closed(h, "t1")  # điểm log 8
    final = h.tickets.final("t1")
    assert final is not None and final.exit_code == code == row["exit_code"]
    assert row["final_state"] == final.final_state == r.status
    assert final.resolution_path == ("escalated" if r.status == S_ESCALATED else None)


@pytest.mark.asyncio
async def test_e0_message_does_not_reveal_reason() -> None:
    text = TEMPLATES.of("E0").user_message.lower()
    assert not any(w in text for w in ("injection", "tấn công", "chặn", "độc hại", "an ninh"))


@pytest.mark.asyncio
async def test_e1_low_confidence_reason_detail() -> None:
    """D-27: E1 do confidence thấp tách khỏi E1 ngoài phạm vi thật."""
    h = GraphHarness()
    await h.submit("low", b03_classify="low_confidence")
    await h.submit("oos", b03_classify="out_of_scope")
    assert h.escalations.of("low")[0]["reason_detail"] == "intent_low_confidence"
    assert h.escalations.of("oos")[0]["reason_detail"] == "out_of_scope"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["deny", "high_risk"])
async def test_every_e5_is_deny_case_with_warning(outcome: str) -> None:
    """2b-Q4: MỌI E5 là deny case — cả luật deny lẫn LLM ước lượng rủi ro cao (không luật nào khớp)."""
    h = GraphHarness()
    await h.submit("t1", b12_assess=outcome)
    [esc] = h.escalations.of("t1")
    assert esc["is_deny_case"] is True
    assert esc["handoff_note"]["next_for_l2"].endswith(TEMPLATES.deny_warning)
    why = esc["handoff_note"]["why_escalated"]
    if outcome == "deny":
        assert "Đánh giá rủi ro: Chuyển kỹ thuật viên L2 · ESCALATE_L2 (Theo luật · FAKE)" in why
    else:
        assert "Đánh giá rủi ro: Chuyển kỹ thuật viên L2 · ESCALATE_L2 (Theo đánh giá của AI)" in why
    assert "p=" not in why and "bởi " not in why  # ĐP 02/11: không lộ p= hay khoá thô


@pytest.mark.asyncio
async def test_handoff_request_only_from_redacted_request() -> None:
    """Q-D: phần (1) chỉ lấy từ `redacted_request` (bản đã che), cắt 500 ký tự."""
    h = GraphHarness()
    for ticket, text in (("short", "VPN không vào được"), ("long", "y" * 800)):
        h.scenario.plan(ticket, b12_assess="deny")
        await h.submit_as(ticket, "s1", text)
    assert h.escalations.of("short")[0]["handoff_note"]["request"] == "VPN không vào được"
    request = h.escalations.of("long")[0]["handoff_note"]["request"]
    assert len(request) == 500 and request.endswith("…")


# ---- close_reason (6/8 ở 2b), resolution_path, ticket cha ---------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "close_reason", "resolution_path"),
    [
        ("confirmed", "resolved_user_confirmed", "auto"),
        ("auto_timeout", "resolved_auto_timeout_48h", "auto"),
        ("approved", "resolved_user_confirmed", "approved"),
        ("deflected", "resolved_user_confirmed", "deflected"),
        ("rejected", "rejected_by_approver", "rejected"),
        ("session_invalid", "blocked_invalid_credentials", None),
        ("locked", "blocked_repeated_auth_failure", None),
        ("injection", "blocked_injection_detected", None),
    ],
)
async def test_close_reason_and_resolution_path(
    case: str, close_reason: str, resolution_path: str | None
) -> None:
    h = GraphHarness()
    if case == "confirmed":
        await _then(h, "t1", S_CONFIRMING, {"kind": "confirmed"}, b12_assess="auto")
    elif case == "auto_timeout":
        await _then(h, "t1", S_CONFIRMING, {"kind": "timeout"}, b12_assess="auto")
    elif case == "approved":
        await _then(h, "t1", S_PENDING_APPROVAL, {"kind": "approved"})
        await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "confirmed"})
    elif case == "deflected":
        await _then(h, "t1", S_CONFIRMING, {"kind": "confirmed"}, b10_route="info")
    elif case == "rejected":
        await _then(h, "t1", S_PENDING_APPROVAL, {"kind": "rejected", "note": "không"})
    elif case == "session_invalid":
        await h.submit_as("t1", "khong-co")
    elif case == "locked":
        h.identity.locked[REQUESTER] = h.clock.now() + timedelta(minutes=5)
        await h.submit("t1")
    else:
        await h.submit("t1", b02_screen="injection")
    final = h.tickets.final("t1")
    assert final is not None
    assert (final.close_reason, final.resolution_path) == (close_reason, resolution_path)
    assert final.auto_closed is (close_reason == "resolved_auto_timeout_48h")
    [row] = _closed(h, "t1")
    assert row["close_reason"] == close_reason and row["detail"]["resolution_path"] == resolution_path
    if case in ("session_invalid", "locked"):  # B1 chặn: không mã E, không vào hàng đợi L2
        assert final.final_state == S_BLOCKED and h.escalations.of("t1") == []
        assert row["block_reason"] == final.block_reason is not None


@pytest.mark.asyncio
async def test_parent_ticket_closes_without_escalation_and_null_reasons() -> None:
    """D-30: cha tới B20 qua parent_wait, không exit_code → không escalation, close_reason NULL,
    resolution_path NULL (Q-A)."""
    h = GraphHarness()
    r = await h.submit("p1", b03_classify="split", parent_wait="done")
    assert r.values["is_parent"] is True and r.waiting_at is None
    final = h.tickets.final("p1")
    assert final is not None
    assert (final.close_reason, final.resolution_path, final.exit_code) == (None, None, None)
    assert final.aggregate_status == "ALL_RESOLVED"
    assert h.escalations.rows == []


@pytest.mark.asyncio
async def test_final_summary_counts_turns_and_duration() -> None:
    h = GraphHarness()
    await h.submit("t1", b12_assess="auto")
    h.clock.advance(timedelta(minutes=7))
    await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "confirmed"})
    final = h.tickets.final("t1")
    assert final is not None
    assert (final.total_turns, final.total_duration_seconds) == (2, 7 * 60)
    assert final.closed_at == h.clock.now()


# ---- chạy lại ở mọi khe hở → không trùng; audit khớp tickets (Q-C) -------------------------


@pytest.mark.asyncio
async def test_b20_rerun_after_each_crash_point_no_duplicates() -> None:
    """E7: process chết (1) sau `finalize_once`, trước điểm log 8; (2) sau `escalation_create`, giữa
    lúc gửi tin; (3) sau khi B20 xong, trước checkpoint. Mỗi lần worker recover (cùng turn_id) → cuối
    cùng: 1 escalation, 1 tin, 1 dòng điểm log 8 — và audit giống hệt `tickets` dù đồng hồ đã chạy."""
    h = GraphHarness()
    h.audit.crash_once.add("closed")
    with pytest.raises(Crash):
        await h.submit("t1", b12_assess="auto", b17_execute="fail")
    [turn] = [t for t, r in h.turns.rows.items() if r["ended_at"] is None]
    first = h.tickets.final("t1")
    assert first is not None and _closed(h, "t1") == []

    h.clock.advance(timedelta(minutes=5))
    h.notifier.crash_once.add("t1")
    with pytest.raises(Crash):
        await h.runner.recover("t1", turn)
    assert h.effects.count("t1", "escalation_create") == 1 and h.notifier.sent == []

    h.clock.advance(timedelta(minutes=5))
    h.spans.crash_once.add("node:b20_audit")
    with pytest.raises(Crash):
        await h.runner.recover("t1", turn)

    h.clock.advance(timedelta(minutes=5))
    r = await h.runner.recover("t1", turn)
    assert r is not None and r.waiting_at is None
    assert len(h.escalations.of("t1")) == 1
    assert h.notifier.count("t1") == 1 == h.effects.count("t1", "notify_user")
    assert [m["kind"] for m in r.values["conversation"]] == ["escalation"]
    [row] = _closed(h, "t1")
    assert h.tickets.final("t1") == first  # finalize_once không đè
    assert row["total_duration_seconds"] == first.total_duration_seconds  # audit từ dòng đã lưu
    assert row["turn_id"] == turn
