"""M3 — bỏ biến chết `recent_messages` ở B3 (prompt `b03_classify` v5).

B3 chỉ chạy một lần, ngay sau B2, lúc `conversation` của ticket luôn rỗng (`runner._initial_state`; B1/B2 không ghi tin; ticket con được
gieo như thể B3 đã chạy) → khối "Hội thoại gần nhất" luôn ra "(không có)". Khối đó và biến nạp nó bị gỡ khỏi prompt, `allowed_vars` và
code dựng của node. Cơ chế `recent_messages` chung của gateway (`llm/context.py`) vẫn còn — thử bằng prompt tổng hợp ở `test_llm_prompts.py`.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from app.llm.context import check_variables, render
from app.llm.errors import PromptVariableError
from app.llm.registry import load_prompts
from app.llm.schemas import ClassifyOut
from tests.fakes.llm import make_gateway
from tests.unit.test_b03_classify import _env, item, out

REPO = Path(__file__).resolve().parents[3]
PROMPT_FILE = REPO / "config" / "prompts" / "b03_classify.yaml"
VARS = {"redacted_request": "VPN không vào được", "label_hint": None}


def test_prompt_declares_only_request_and_hint_and_bumps_version() -> None:
    raw = yaml.safe_load(PROMPT_FILE.read_text(encoding="utf-8"))
    assert raw["allowed_vars"] == ["redacted_request", "label_hint"]
    assert int(raw["version"]) == 6  # lô Q1+Q12 (ĐP 09/11): v6 — allowed_vars giữ nguyên


def test_prompt_text_has_no_recent_messages_block() -> None:
    raw = yaml.safe_load(PROMPT_FILE.read_text(encoding="utf-8"))
    for part in ("system", "user"):
        assert "recent_messages" not in raw[part] and "Hội thoại gần nhất" not in raw[part], part


def test_rendered_user_message_has_no_conversation_line() -> None:
    prompt = load_prompts(PROMPT_FILE.parent).get("b03_classify")
    rendered = render(prompt, VARS, budget_in=100_000)
    user = rendered.messages[1]["content"]
    assert "Hội thoại" not in user and "(không có)" not in user
    assert user.splitlines() == ["Yêu cầu: VPN không vào được", "Gợi ý nhãn: null"]
    assert rendered.trimmed_messages == 0


def test_check_variables_rejects_recent_messages_for_b03() -> None:
    prompt = load_prompts(PROMPT_FILE.parent).get("b03_classify")
    check_variables(prompt, VARS)  # hai biến đủ
    with pytest.raises(PromptVariableError, match="recent_messages"):
        check_variables(prompt, {**VARS, "recent_messages": []})


@pytest.mark.asyncio
async def test_gateway_rejects_recent_messages_for_b03_before_any_request() -> None:
    gw = make_gateway({"b03_classify": [out(item("vpn", 0.9))]})
    with pytest.raises(PromptVariableError, match="recent_messages"):
        await gw.client.complete("fast", "b03_classify", {**VARS, "recent_messages": []}, ClassifyOut)
    assert gw.llm.calls_for("b03_classify") == []  # lỗi hợp đồng biến: không request nào được gửi


@pytest.mark.asyncio
async def test_b03_node_passes_exactly_two_variables_and_prompt_has_no_conversation_line() -> None:
    from tests.unit.test_b03_classify import SESSION_NV001, TEXT

    h, gw = _env([out(item("vpn", 0.9))])
    await h.submit_as("t1", SESSION_NV001, text=TEXT)
    [call] = gw.llm.calls_for("b03_classify")
    variables: dict[str, Any] = dict(call.variables)
    assert set(variables) == {"redacted_request", "label_hint"}
    assert "Hội thoại gần nhất" not in call.rendered_messages[1]["content"]


def test_b03_node_source_no_longer_builds_recent() -> None:
    src = (REPO / "backend" / "app" / "graph" / "nodes" / "b03_classify.py").read_text(encoding="utf-8")
    assert "recent_messages" not in src and "RECENT_MESSAGES" not in src
