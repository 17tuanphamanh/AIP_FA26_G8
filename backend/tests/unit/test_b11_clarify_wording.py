"""P6 lời nói (ĐP 08/11), mục 2: prompt `b11_clarify_question` (câu hỏi bổ sung thông tin — KHÔNG phải `b11_extract_slots`) v2.

Ba chỉ dẫn mới: (a) chỉ chào ở lượt hỏi đầu tiên, các lượt sau đi thẳng vào ý; (b) câu trả lời trước không dùng được → mở đầu ngắn
"Mình chưa rõ ý bạn," rồi hỏi lại đúng thông tin còn thiếu; (c) tối đa 2 câu.

LLM không được thấy câu người dùng ở prompt này, nên "lượt nào" và "câu trả lời trước có dùng được không" do NODE tính và đưa vào biến
`previous_reply` (enum, không chữ tự do): `none` = câu hỏi đầu tiên; `unusable` = câu trả lời trước không cho slot sạch nào hoặc lạc đề
(`off_topic_streak` ≥ 1 — cùng khái niệm với luật [Chốt] "lạc đề 2 lần liên tiếp → E4"); `usable` = có slot sạch.

Chất lượng câu chữ thật chỉ đo được với LLM thật (mốc G, "Dồn về mốc G") — ở đây chỉ kiểm: văn bản prompt, whitelist biến, giá trị biến
node đưa vào, và output guard + dọn khoá slot vẫn chạy như cũ. Không gọi LLM thật.
"""

from pathlib import Path
from typing import Any, cast

import pytest
from app.domain.states import S_CLARIFYING, S_ESCALATED
from app.guard.output import OutputGuard
from app.llm.context import check_variables, render
from app.llm.errors import PromptVariableError
from app.llm.providers.scripted import Reply
from app.llm.registry import PromptRegistry, load_prompts
from app.settings import get_slots
from tests.unit.test_b11_slots import (
    CANARY,
    CONFIG,
    _graph,
    _node,
    _node_harness,
    _reply,
    _state,
    _submit,
)

PROMPTS = Path(__file__).resolve().parents[3] / "config" / "prompts"
PID = "b11_clarify_question"
VARS = {"missing", "diagnostics_summary", "intent", "previous_reply"}
OPENER = "Mình chưa rõ ý bạn,"


@pytest.fixture(scope="module")
def registry() -> PromptRegistry:
    return load_prompts(PROMPTS)


def _reply_line(content: str, value: str) -> bool:
    """Dòng "…: <value>" trong khối đầu vào — khớp CẢ dòng, vì "usable" là chuỗi con của "unusable"."""
    return any(line.endswith(f": {value}") for line in content.splitlines())


def _vars(**over: Any) -> dict[str, Any]:
    return {"missing": ["device_id"], "diagnostics_summary": {"devices": []}, "intent": "vpn", "previous_reply": "none", **over}


# ---- prompt: phiên bản, hợp đồng, nội dung ---------------------------------------------------------------------------


def test_version_bumped_and_contract_kept(registry: PromptRegistry) -> None:
    prompt = registry.get(PID)
    assert prompt.version == "2"  # sửa nội dung → tăng version (khoá cache + llm_calls.prompt_version)
    assert (prompt.spec.role, prompt.spec.cache, prompt.spec.schema_name) == ("fast", "default", "QuestionOut")
    assert set(prompt.spec.allowed_vars) == VARS


def test_system_prompt_has_the_three_instructions_and_keeps_old_ones(registry: PromptRegistry) -> None:
    system = registry.get(PID).spec.system
    assert OPENER in system  # (b) câu mở đầu đúng chữ
    assert "tối đa 2 câu" in system.casefold()  # (c) — đầu câu viết hoa cũng tính
    assert "chào" in system  # (a) có nhắc chào…
    assert "KHÔNG chào" in system  # …và cấm chào ở các lượt sau
    for value in ("none", "usable", "unusable"):  # cả ba giá trị biến đều được giải thích
        assert value in system
    # chỉ dẫn cũ giữ nguyên
    assert "Không hỏi mật khẩu, mã OTP" in system
    assert "300 ký tự" in system and "tối đa 2 thông tin" in system
    assert "Không hỏi thông tin đã có trong kết quả" in system


def test_user_block_shows_previous_reply(registry: PromptRegistry) -> None:
    for value in ("none", "usable", "unusable"):
        user = render(registry.get(PID), _vars(previous_reply=value), budget_in=4000).messages[1]["content"]
        assert _reply_line(user, value) and "device_id" in user


# ---- whitelist biến ---------------------------------------------------------------------------------------------------------


def test_previous_reply_is_required_and_nothing_else_is_accepted(registry: PromptRegistry) -> None:
    prompt = registry.get(PID)
    check_variables(prompt, _vars())  # đủ 4 biến: qua
    without = _vars()
    del without["previous_reply"]
    with pytest.raises(PromptVariableError, match=r"thiếu biến \['previous_reply'\]"):
        check_variables(prompt, without)
    with pytest.raises(PromptVariableError, match=r"biến ngoài allowed_vars \['redacted_request'\]"):
        check_variables(prompt, _vars(redacted_request="câu người dùng"))  # không đưa chữ người dùng vào prompt này


# ---- node: biến render đúng theo lượt ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("turns", "streak", "expected"),
    [(0, 0, "none"), (0, 1, "none"), (1, 0, "usable"), (2, 0, "usable"), (1, 1, "unusable"), (2, 1, "unusable")],
)
async def test_node_passes_previous_reply_by_turn_and_streak(turns: int, streak: int, expected: str) -> None:
    h, gw = _node_harness()
    out = await _node(h, _state({"action": "renew_vpn_cert"}, clarification_turns=turns, off_topic_streak=streak))
    assert out["status"] == S_CLARIFYING
    [call] = gw.llm.calls_for(PID)
    assert call.variables["previous_reply"] == expected
    assert set(call.variables) == VARS
    assert _reply_line(cast(str, call.rendered_messages[1]["content"]), expected)  # biến thật sự vào prompt đã render
    assert out["clarification_turns"] == turns + 1
    [row] = h.audit.of("t1", "asked")
    assert row["detail"]["prompt"] == f"{PID}@2"


@pytest.mark.asyncio
async def test_node_missing_streak_key_means_usable_after_first_turn() -> None:
    """State cũ chưa có `off_topic_streak` (None) không được làm node ném lỗi."""
    h, gw = _node_harness()
    await _node(h, _state({"action": "renew_vpn_cert"}, clarification_turns=1))
    assert gw.llm.calls_for(PID)[0].variables["previous_reply"] == "usable"


@pytest.mark.asyncio
async def test_node_target_question_is_fixed_text_without_llm() -> None:
    """Câu hỏi đích L-03 là câu cố định: vẫn không gọi LLM, nên không có `previous_reply`."""
    h, gw = _node_harness()
    out = await _node(h, _state({}, intent="account", ctx_flags={"target_is_other": True}, clarification_turns=1,
                                off_topic_streak=1))  # fmt: skip
    assert out["status"] == S_CLARIFYING and gw.llm.calls_for(PID) == []


# ---- đi qua graph thật: 3 lượt hỏi, biến đổi đúng theo câu trả lời -------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_three_asks_none_unusable_usable() -> None:
    h, gw = _graph("nv002", action=None)
    await _submit(h, "nv002", "VPN không vào được")  # lượt hỏi 1
    await _reply(h, "hôm nay trời đẹp quá")  # lạc đề → streak 1 → lượt hỏi 2
    await _reply(h, "PC-0977")  # có slot sạch (streak về 0), còn thiếu action → lượt hỏi 3
    calls = gw.llm.calls_for(PID)
    # Q3 M1: lượt 3 chỉ còn thiếu `action` (slot enum) → câu CỐ ĐỊNH, không gọi LLM — chỉ 2 lời gọi.
    assert [c.variables["previous_reply"] for c in calls] == ["none", "unusable"]
    assert [c.variables["missing"] for c in calls] == [["device_id", "action"], ["device_id", "action"]]
    assert h.notifier.sent[-1][1] == get_slots().intents["vpn"].fixed_questions["action"]


# ---- output guard + dọn khoá slot vẫn chạy như cũ ở lượt có câu mở đầu "Mình chưa rõ ý bạn," -------------------------------------


@pytest.mark.asyncio
async def test_scrub_slot_keys_still_runs_on_retry_question() -> None:
    text = f"{OPENER} bạn cho mình xin mã máy (device_id) nhé?"
    h, _ = _node_harness(b11_clarify_question=[Reply({"text": text})])
    out = await _node(h, _state({"action": "renew_vpn_cert"}, clarification_turns=1, off_topic_streak=1))
    clean = f"{OPENER} bạn cho mình xin mã máy nhé?"
    assert out["status"] == S_CLARIFYING
    assert out["conversation"][-1]["text"] == clean
    assert [t for _, t, _ in h.notifier.sent] == [clean]
    [row] = h.audit.of("t1", "asked")
    assert row["detail"]["slot_keys_removed"] == 1 and "device_id" not in repr(row["detail"]["prompt"])


@pytest.mark.asyncio
async def test_output_guard_still_blocks_retry_question() -> None:
    h, _ = _node_harness(b11_clarify_question=[Reply({"text": f"{OPENER} bạn cho mình mã máy nhé. {CANARY}"})])
    out = await _node(h, _state({"action": "renew_vpn_cert"}, clarification_turns=1, off_topic_streak=1),
                      output_guard=OutputGuard.from_config(CONFIG, [CANARY]))  # fmt: skip
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E3", "output_guard_block")
    [row] = h.audit.rows
    assert row["detail"]["guard"] == "canary"
    assert h.notifier.sent == [] and h.deadlines.waits == [] and "conversation" not in out
