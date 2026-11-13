"""Q13c (11/11, bản nộp main) — bớt lặp câu cố định E1/E3/E4 trong cùng phiên (test viết trước).

Hợp đồng:
- Mẫu E1/E3/E4 khai thêm `user_message_repeat` (≥ 2 câu, không LLM, không nêu lại câu phạm vi "Mình là trợ lý IT, hiện hỗ trợ…").
- B20 đếm số ticket KHÁC trong CÙNG phiên (`session_id`) đã kết thúc bằng một trong các mã có `user_message_repeat` (`TicketStore.
  session_exit_count`). 0 → câu đầy đủ như trước lô (ổn định cho ticket đầu phiên); n ≥ 1 → `user_message_repeat[(n - 1) % len]`.
- Câu theo lý do (`user_message_by_reason`) vẫn ưu tiên; E0 không bao giờ đổi (không tiết lộ, không biến thể).
- Đọc store lỗi → coi như 0 (câu đầy đủ), escalation vẫn tạo — không chặn lối thoát.
"""

from datetime import timedelta
from typing import Any

import pytest
from app.settings import get_escalation_templates
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import REQUESTER

TEMPLATES = get_escalation_templates()
SCOPE = "Mình là trợ lý IT, hiện hỗ trợ"
REPEAT_CODES = ("E1", "E3", "E4")


def _msg(v: Any) -> str:
    return str(v["conversation"][-1]["text"])


async def _e1(h: GraphHarness, t: str) -> Any:
    return (await h.submit(t, b03_classify="out_of_scope")).values


async def _e3(h: GraphHarness, t: str) -> Any:
    return (await h.submit(t, b08_retrieve="no_evidence")).values


def test_templates_have_repeat_variants_without_scope() -> None:
    for code in REPEAT_CODES:
        tpl = TEMPLATES.of(code)
        assert len(tpl.user_message_repeat) >= 2, code
        assert len(set(tpl.user_message_repeat)) == len(tpl.user_message_repeat)
        for text in tpl.user_message_repeat:
            assert SCOPE not in text and "kỹ thuật viên" in text, (code, text)
            assert text not in {tpl.user_message, tpl.user_message_it_help}
    assert TEMPLATES.of("E0").user_message_repeat == ()


def test_user_message_for_repeat_index() -> None:
    tpl = TEMPLATES.of("E3")
    assert tpl.user_message_for(None, repeat=0) == tpl.user_message
    assert tpl.user_message_for(None, repeat=1) == tpl.user_message_repeat[0]
    assert tpl.user_message_for(None, repeat=2) == tpl.user_message_repeat[1]
    n = len(tpl.user_message_repeat)
    assert tpl.user_message_for(None, repeat=n + 1) == tpl.user_message_repeat[0]  # xoay vòng
    e5 = TEMPLATES.of("E5")
    reason = next(iter(e5.user_message_by_reason))
    assert e5.user_message_for(reason, repeat=3) == e5.user_message_by_reason[reason]  # lý do vẫn ưu tiên


@pytest.mark.asyncio


async def test_first_ticket_in_session_keeps_full_message() -> None:
    h = GraphHarness()
    v = await _e3(h, "t1")
    assert _msg(v) == TEMPLATES.of("E3").user_message_for(None, it_help=True)


@pytest.mark.asyncio


async def test_second_and_third_ticket_same_session_vary() -> None:
    h = GraphHarness()
    first = _msg(await _e3(h, "t1"))
    second = _msg(await _e3(h, "t2"))
    third = _msg(await _e1(h, "t3"))
    assert first == TEMPLATES.of("E3").user_message_for(None, it_help=True)
    assert second == TEMPLATES.of("E3").user_message_repeat[0]
    assert third == TEMPLATES.of("E1").user_message_repeat[1]  # đã có 2 ticket E1/E3/E4 trong phiên
    assert len({first, second, third}) == 3
    assert SCOPE not in second and SCOPE not in third


@pytest.mark.asyncio


async def test_other_session_starts_fresh() -> None:
    h = GraphHarness()
    await _e3(h, "t1")
    h.identity.add_session("s-khac", REQUESTER, expires_at=h.clock.now() + timedelta(days=1))
    h.scenario.plan("t2", b08_retrieve="no_evidence")
    v = (await h.submit_as("t2", "s-khac")).values
    assert _msg(v) == TEMPLATES.of("E3").user_message_for(None, it_help=True)


@pytest.mark.asyncio


async def test_store_error_falls_back_to_full_message_and_still_escalates() -> None:
    h = GraphHarness()
    await _e3(h, "t1")
    h.tickets.session_exit_count_error = RuntimeError("db")
    v = await _e3(h, "t2")
    assert _msg(v) == TEMPLATES.of("E3").user_message_for(None, it_help=True)
    [esc] = h.escalations.of("t2")
    assert esc["exit_code"] == "E3"


@pytest.mark.asyncio


async def test_e0_never_varies() -> None:
    h = GraphHarness()
    await _e3(h, "t1")
    v = (await h.submit("t2", b02_screen="injection")).values
    assert _msg(v) == TEMPLATES.of("E0").user_message
