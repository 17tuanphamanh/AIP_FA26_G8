"""Q1 điểm 2 (ĐP chốt 09/11, bản demo lo-0811): renderer giữ NGUYÊN `keep_tail` ký tự cuối, cắt PHẦN ĐẦU phần trước ở ranh giới từ; riêng
phần cuối đã vượt trần → bỏ phần đầu rồi cắt ĐUÔI phần cuối như cũ. Khoá `keep_tail` ngoài `trim_vars` → `PromptContractError` (gateway)."""

from pathlib import Path

import pytest
from app.core.errors import LLMBudgetExceeded
from app.llm.context import _clip_head, _keep_tail_fitting, render
from app.llm.errors import PromptContractError
from app.llm.registry import PromptRegistry, load_prompts
from app.llm.schemas import ClassifyOut
from tests.fakes.llm import make_gateway, scripted_runtime

PROMPTS = Path(__file__).resolve().parents[3] / "config" / "prompts"
ORIGINAL = ("máy em bị lỗi <SĐT_1> gì đó không rõ " * 200)[:4000]
REPLY = ("máy in tầng 2 báo kẹt giấy [BÍ_MẬT_ĐÃ_ẨN] vẫn không in được " * 40)[:1500].rstrip()


@pytest.fixture(scope="module")
def registry() -> PromptRegistry:
    return load_prompts(PROMPTS)


def _budget() -> int:
    return scripted_runtime().roles["fast"].budget_in


def test_clip_head_word_boundary_and_marker() -> None:
    assert _clip_head("một hai ba", 100) == "một hai ba"
    assert _clip_head("một hai ba", 3) == "…ba"
    assert _clip_head("một hai ba", 4) == "…ba"  # " ba" → không cắt giữa từ
    assert _clip_head("mộthaiba", 3) == ""  # không ranh giới → rỗng
    assert _clip_head("x", 0) == ""


def test_keep_tail_cuts_head_first() -> None:
    text = f"{ORIGINAL}\n{REPLY}"
    out = _keep_tail_fitting(text, len(REPLY), lambda c: len(c) <= 2500)
    assert out.endswith("\n" + REPLY) and out.startswith("…") and len(out) <= 2500
    head = out[: -len(REPLY) - 1]
    assert ORIGINAL.endswith(head[1:]) and head.count("<SĐT_") == head.count("<SĐT_1>")


def test_keep_tail_alone_too_long_cuts_tail_of_reply() -> None:
    text = f"{ORIGINAL}\n{REPLY}"
    out = _keep_tail_fitting(text, len(REPLY), lambda c: len(c) <= 600)
    assert out.endswith("…") and REPLY.startswith(out[:-1].rstrip()) and len(out) <= 600  # bỏ hết câu gốc, cắt ĐUÔI câu trả lời
    assert "[BÍ_MẬT_ĐÃ_ẨN" not in out or out.count("[BÍ_MẬT_ĐÃ_ẨN") == out.count("[BÍ_MẬT_ĐÃ_ẨN]")


def test_render_b03_keep_tail_keeps_whole_reply(registry: PromptRegistry) -> None:
    reply = REPLY[:1000].rstrip()  # vừa phần còn lại của trần (khung v6 1612/2000 token — xem test_q1_triage CHO_BUDGET)
    text = f"{ORIGINAL}\n{reply}"
    variables = {"redacted_request": text, "label_hint": None}
    plain = render(registry.get("b03_classify"), variables, budget_in=_budget())
    kept = render(registry.get("b03_classify"), variables, budget_in=_budget(), keep_tail={"redacted_request": len(reply)})
    assert plain.est_tokens <= _budget() and kept.est_tokens <= _budget()
    assert reply not in plain.messages[1]["content"]  # cắt đuôi như cũ → mất câu trả lời (lý do của điểm 2)
    assert reply in kept.messages[1]["content"] and kept.trimmed_chars > 0


def test_render_keep_tail_frame_too_big_still_raises(registry: PromptRegistry) -> None:
    with pytest.raises(LLMBudgetExceeded):
        render(registry.get("b03_classify"), {"redacted_request": ORIGINAL, "label_hint": None}, budget_in=50,
               keep_tail={"redacted_request": 10})  # fmt: skip


@pytest.mark.asyncio
async def test_gateway_rejects_keep_tail_outside_trim_vars() -> None:
    gw = make_gateway({})
    with pytest.raises(PromptContractError):
        await gw.client.complete("fast", "b03_classify", {"redacted_request": "x", "label_hint": None}, ClassifyOut,
                                 keep_tail={"label_hint": 1})  # fmt: skip
