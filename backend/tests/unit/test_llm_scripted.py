"""ScriptedLLM trên stack dev (d19, Q-3d-12) và kịch bản VPN dùng chung (d18, phase3 mục 3.8)."""

from pathlib import Path
from typing import Any

import pytest
from app.graph.fakes import FAKE_TAG as GRAPH_FAKE_TAG
from app.llm.config import SCRIPTED_MODEL
from app.llm.errors import PromptContractError, ScriptExhausted
from app.llm.ports import TraceParent
from app.llm.providers.scripted import (
    DEFAULT_PRESET,
    FAKE_TAG,
    PresetScriptedLLM,
    load_presets,
)
from app.llm.schemas import (
    AnswerOut,
    ClassifyOut,
    ExtractSlotsOut,
    NeedTypeOut,
    QuestionOut,
)
from tests.fakes.llm import REPO_CONFIG, make_gateway, repo_registry
from tests.fixtures.llm.vpn import vpn_scripts

TRACE = TraceParent("turn-1", "trace-1", None)


class FakeResolver:
    """Thay `SqlPresetResolver` (bản SQL kiểm ở integration d16): thẻ theo turn_id."""

    def __init__(self, tags: dict[str, str | None]) -> None:
        self.tags = tags
        self.asked: list[str | None] = []

    async def tag_for(self, trace: TraceParent | None) -> str | None:
        self.asked.append(trace.turn_id if trace else None)
        return self.tags.get(trace.turn_id) if trace else None


def _presets() -> dict[str, dict[str, dict[str, Any]]]:
    presets = load_presets(REPO_CONFIG / "scripted", repo_registry())
    presets["vpn_demo"] = {"b10_need_type": {"type": "action", "confidence": 0.95}}
    return presets


NEED = {"text": "gia hạn VPN", "evidence_titles": []}


# ---- d19: preset stack ------------------------------------------------------------------------------


def test_d19_fake_tag_syntax_same_as_graph_scenario() -> None:
    """Một nguồn (`core.fake_tag`, Q-3h-11 a): gate2, ScriptedLLM và câu truy hồi RAG dùng CÙNG đối tượng regex."""
    from app.core.fake_tag import FAKE_TAG as CORE_FAKE_TAG

    assert FAKE_TAG is GRAPH_FAKE_TAG is CORE_FAKE_TAG


def test_d19_repo_default_preset_covers_all_prompts_and_validates() -> None:
    presets = load_presets(REPO_CONFIG / "scripted", repo_registry())
    assert set(presets[DEFAULT_PRESET]) == {p.id for p in repo_registry()}
    assert presets[DEFAULT_PRESET]["b02_injection_judge"]["is_attack"] is False  # "an toàn" (7.5)
    assert presets[DEFAULT_PRESET]["b03_classify"]["intents"][0]["type"] == "out_of_scope"


@pytest.mark.asyncio
@pytest.mark.parametrize(("tag", "expected"), [("vpn_demo", "action"), (None, "info")])
async def test_d19_tag_selects_preset_else_default(tag: str | None, expected: str) -> None:
    resolver = FakeResolver({"turn-1": tag})
    gw = make_gateway(providers={"scripted": PresetScriptedLLM(_presets(), resolver)}, trace=lambda: TRACE)
    out, meta = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert out.type == expected and meta.model == SCRIPTED_MODEL
    assert resolver.asked == ["turn-1"]  # chọn theo lượt đang chạy (turn_id → ticket), không theo bộ nhớ process


@pytest.mark.asyncio
async def test_d19_unknown_tag_or_missing_prompt_is_script_exhausted() -> None:
    for tags, match in (({"turn-1": "khong_co"}, "khong_co"), ({"turn-1": "vpn_demo"}, "b11_clarify_question")):
        gw = make_gateway(providers={"scripted": PresetScriptedLLM(_presets(), FakeResolver(tags))},
                          trace=lambda: TRACE)  # fmt: skip
        with pytest.raises(ScriptExhausted, match=match):
            await gw.client.complete("fast", "b11_clarify_question",
                                     {"missing": ["device_id"], "diagnostics_summary": "", "intent": "vpn"},
                                     QuestionOut)  # fmt: skip


def _write(tmp: Path, name: str, text: str) -> None:
    (tmp / f"{name}.yaml").write_text(text, encoding="utf-8")


def test_d19_presets_rejected_at_startup(tmp_path: Path) -> None:
    default = (REPO_CONFIG / "scripted" / "default.yaml").read_text(encoding="utf-8")
    _write(tmp_path, "default", default)
    _write(tmp_path, "sai", "b10_need_type: {type: maybe, confidence: 0.5}\n")
    with pytest.raises(ValueError, match=r"sai\.yaml: phản hồi b10_need_type sai schema NeedTypeOut"):
        load_presets(tmp_path, repo_registry())
    _write(tmp_path, "sai", "khong_co_prompt: {}\n")
    with pytest.raises(PromptContractError, match="khong_co_prompt"):
        load_presets(tmp_path, repo_registry())
    (tmp_path / "sai.yaml").unlink()
    (tmp_path / "default.yaml").unlink()
    _write(tmp_path, "khac", "b10_need_type: {type: info, confidence: 0.5}\n")
    with pytest.raises(ValueError, match="thiếu preset 'default'"):
        load_presets(tmp_path, repo_registry())


# ---- d18: kịch bản VPN dùng chung ----------------------------------------------------------------------


EVIDENCE = [
    {"anchor_chunk_id": f"KB-VPN-003#{i}", "title": "Gia hạn chứng chỉ", "heading_path": f"Bước {i}",
     "text": f"nội dung {i}", "score": 0.9 - i / 10}
    for i in range(3)
]  # fmt: skip
CALLS: list[tuple[str, str, dict[str, Any]]] = [
    ("fast", "b02_injection_judge", {"text": "VPN báo lỗi chứng chỉ trên LAP-0342"}),
    ("fast", "b03_classify", {"redacted_request": "Gia hạn chứng chỉ VPN cho máy LAP-0342", "recent_messages": [],
                              "label_hint": None}),
    ("fast", "b10_need_type", {"text": "gia hạn giúp", "evidence_titles": ["Gia hạn chứng chỉ"]}),
    ("strong", "b10_answer", {"question": "gia hạn thế nào", "evidence": EVIDENCE}),
    ("fast", "b11_clarify_question", {"missing": ["device_id"], "diagnostics_summary": "", "intent": "vpn"}),
    ("fast", "b11_extract_slots", {"text": "máy em là PC-0977", "missing": ["device_id"], "intent": "vpn"}),
]  # fmt: skip


@pytest.mark.asyncio
async def test_d18_vpn_scripts_valid_through_gateway() -> None:
    gw = make_gateway(vpn_scripts())
    outs = {}
    for role, prompt_id, variables in CALLS:
        schema = repo_registry().get(prompt_id).schema
        out, meta = await gw.client.complete(role, prompt_id, variables, schema, cache_policy="bypass")  # type: ignore[arg-type]
        assert meta.json_valid_first_try, prompt_id
        outs[prompt_id] = out
    classify = outs["b03_classify"]
    assert isinstance(classify, ClassifyOut)
    assert classify.intents[0].slots == {"device_id": "LAP-0342"}  # đúng chữ người dùng viết (3-Q1)
    assert classify.intents[0].action_hint == "renew_vpn_cert"
    answer = outs["b10_answer"]
    assert isinstance(answer, AnswerOut)
    assert answer.citations == ["KB-VPN-003#0", "KB-VPN-003#1", "KB-VPN-003#2"] and len(answer.steps or []) == 3  # TC05
    extract = outs["b11_extract_slots"]
    assert isinstance(extract, ExtractSlotsOut) and extract.slots == {"device_id": "PC-0977"}


@pytest.mark.asyncio
async def test_d18_vpn_scripts_info_flow_and_overrides() -> None:
    gw = make_gateway(vpn_scripts(need="info"))
    out, _ = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert out.type == "info"
    classify, _ = await gw.client.complete("fast", "b03_classify", {"redacted_request": "VPN không vào được",
                                           "recent_messages": [], "label_hint": None}, ClassifyOut)  # fmt: skip
    assert classify.intents[0].slots == {} and classify.intents[0].action_hint is None  # TC06: không có mã máy
    no_ev, _ = await gw.client.complete("strong", "b10_answer", {"question": "x", "evidence": []}, AnswerOut)
    assert no_ev.cannot_answer and no_ev.citations == []
    scripts = vpn_scripts(b10_need_type=[])
    assert scripts["b10_need_type"] == []  # ghi đè theo prompt
