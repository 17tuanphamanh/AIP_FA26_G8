"""Node B3 THẬT qua graph (thiết kế Phase 3 mục 9.3, 9.6 f4–f6, f18; PLAN-3f chốt Q-3f-2…6).

Graph `nodes="real"` trên bản giả in-memory: B1 thật → B2 thật (L4 ScriptedLLM: không tấn công) → B3 thật (ml
`model_missing` → LLM `b03_classify` ScriptedLLM) → B6 thật (VPN giả đọc seed) → B8 thật (RAG giả) → node giả phía sau.
Người gửi `nv001` (có trong seed). Điểm log 1 đọc ở audit (step B3/B4); đếm lời gọi ở NƠI NHẬN (`ScriptedLLM.calls`,
`FakeMlService.calls`).
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.core.clock import FakeClock
from app.domain.facts import FACT_KEYS
from app.domain.states import S_CLASSIFYING, S_DIAGNOSING, S_ESCALATED
from app.domain.ticket_state import ChunkRef
from app.graph.builder import wrap_node
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b03_classify
from app.llm.providers.scripted import BadJSON, Reply, Script, Unavailable
from app.rag.models import RetrievalResult
from tests.fakes.executor import MemoryTxLog
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.identity import ad_user
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag

pytestmark = pytest.mark.asyncio

PROMPTS = Path(__file__).resolve().parents[3] / "config" / "prompts"
SESSION_NV001 = "s-nv001"
TEXT = "VPN không vào được, báo lỗi 809 trên máy LAP-0342"
NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ bình thường"}
POINT1_KEYS = {"layer", "intent", "confidence", "is_multi", "model_probs", "model_version", "prompt", "ml_error",
               "llm_error", "dropped_slot_keys", "dropped_slot_reasons", "dropped_unknown_count",
               "slot_fact_collision", "span_not_in_text"}  # fmt: skip

# T20a DỪNG 2 (phase5 5.1.9, P9): prompt `b03_classify` v3 — xfail(strict) tới khi đổi prompt (phase5 4.10).
CHO_DUNG2 = frozenset({"test_point1_records_prompt_version"})


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.name in CHO_DUNG2 or getattr(request.node, "originalname", None) in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError),
                                              reason="T20a DỪNG 2"))  # fmt: skip


def item(type_: str = "vpn", confidence: float = 0.9, *, span: str = TEXT, action: str | None = None,
         slots: dict[str, str] | None = None) -> dict[str, Any]:  # fmt: skip
    return {"type": type_, "confidence": confidence, "span": span, "action_hint": action, "slots": slots or {}}


def out(*items: dict[str, Any]) -> Reply:
    return Reply({"intents": list(items), "is_multi": len(items) >= 2})


def _rag() -> FakeRag:
    chunk = ChunkRef(chunk_id="c1", doc_id="KB-VPN-001", version=1, seq=0, title="T", heading_path="H",
                     score=0.99, excerpt="x")  # fmt: skip
    return FakeRag(result=RetrievalResult(chunks=[chunk], top_score=0.99, kb_version="a" * 64,
                                          intent_filter_fallback=False, fallback_tried=False, retries=0,
                                          query_truncated=False))  # fmt: skip


def _env(b03: Script, *, ml: FakeMlService | None = None, **harness: Any) -> tuple[GraphHarness, Gateway]:
    clock = FakeClock()
    gw = make_gateway({"b02_injection_judge": lambda _: Reply(NOT_ATTACK), "b03_classify": b03}, clock=clock)
    h = GraphHarness(clock=clock, nodes="real", llm=gw.client, ml=ml or FakeMlService(), rag=_rag(), **harness)
    h.identity.add_session(SESSION_NV001, "nv001", expires_at=clock.now() + timedelta(days=365))
    h.ad.users["nv001"] = ad_user("nv001")
    return h, gw


async def _run(b03: Script, text: str = TEXT, **kw: Any) -> tuple[dict[str, Any], dict[str, Any], GraphHarness, Gateway]:
    h, gw = _env(b03, **kw)
    v = (await h.submit_as("t1", SESSION_NV001, text=text)).values
    [row] = [r for r in h.audit.rows if r["ticket_id"] == "t1" and r["step"] in ("B3", "B4")]
    return v, row, h, gw


def _b03_calls(gw: Gateway) -> int:
    return len(gw.llm.calls_for("b03_classify"))


# ---- f4: 6 dạng đầu ra LLM + thứ tự kiểm (M-3f-6) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (out(), "out_of_scope"),  # rỗng
        (out(item("out_of_scope", 0.95)), "out_of_scope"),
        (out(item("vpn", 0.9), item("account", 0.9)), "multi_intent_not_enabled"),
        (out(item("vpn", 0.4)), "intent_low_confidence"),
        (out(item("account", 0.9)), "intent_not_enabled"),
        # thứ tự CỐ ĐỊNH: ý chưa bật nhưng confidence thấp → low_confidence (kiểm confidence trước — M-3f-6)
        (out(item("account", 0.4)), "intent_low_confidence"),
        # nhiều ý kể cả confidence thấp → multi (kiểm số ý trước confidence)
        (out(item("vpn", 0.3), item("software", 0.3)), "multi_intent_not_enabled"),
        # Q-3f-6: vpn + ý ngoài phạm vi = 2 ý → không âm thầm bỏ phần máy in
        (out(item("vpn", 0.9), item("out_of_scope", 0.9)), "multi_intent_not_enabled"),
        # chỉ ý ngoài phạm vi (kể cả 2 ý) → out_of_scope (kiểm trước số ý)
        (out(item("out_of_scope", 0.9), item("out_of_scope", 0.8)), "out_of_scope"),
    ],
)
async def test_f4_e1_branches(reply: Reply, reason: str) -> None:
    v, row, _, _ = await _run([reply])
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E1", reason)
    assert (row["step"], row["from_status"], row["to_status"]) == ("B4", S_CLASSIFYING, S_ESCALATED)
    assert "intent" not in v or v["intent"] is None  # E1 không đặt intent vào state


async def test_f4_vpn_goes_to_b6() -> None:
    v, row, h, gw = await _run([out(item("vpn", 0.9, slots={"device_id": "LAP-0342"}))])
    assert (row["step"], row["event"], row["to_status"]) == ("B3", "intent_classified", S_DIAGNOSING)
    assert (v["intent"], v["intent_confidence"]) == ("vpn", 0.9)
    assert ("B6", "diagnosed") in h.audit.events("t1")
    assert h.ml.calls["classify_intent"] == 1 and _b03_calls(gw) == 1  # model_missing → đúng 1 request ml, 1 LLM


async def test_f4_tau_intent_boundary_passes() -> None:
    v, row, _, _ = await _run([out(item("vpn", 0.6))])  # TAU_INTENT = 0,6 — "<" mới E1
    assert row["event"] == "intent_classified" and v["intent"] == "vpn"


# ---- Q-3f-6: câu xã giao không phải một ý ---------------------------------------------------------------------------


async def test_q3f6_small_talk_is_not_an_intent() -> None:
    text = "VPN lỗi, cảm ơn anh"
    v, row, _, _ = await _run([out(item("vpn", 0.9, span="VPN lỗi"))], text=text)  # LLM (prompt v2) trả 1 ý
    assert row["event"] == "intent_classified" and v["intent"] == "vpn"


async def test_q3f6_out_of_scope_request_is_second_intent() -> None:
    text = "VPN lỗi, tiện sửa máy in giúp em"
    v, _, _, _ = await _run([out(item("vpn", 0.9, span="VPN lỗi"), item("out_of_scope", 0.9, span="tiện sửa máy in"))],
                         text=text)  # fmt: skip
    assert (v["exit_code"], v["escalation_reason_detail"]) == ("E1", "multi_intent_not_enabled")


async def test_q3f6_prompt_v2_says_small_talk_is_not_an_intent() -> None:
    spec = yaml.safe_load((PROMPTS / "b03_classify.yaml").read_text(encoding="utf-8"))
    assert int(spec["version"]) >= 2
    system = spec["system"]
    assert "cảm ơn" in system and "KHÔNG phải một ý" in system and "out_of_scope" in system


# ---- f5: slot trùng tên fact bị bỏ, facts chỉ từ tool ------------------------------------------------------------------


async def test_f5_fact_named_slot_dropped_and_audited() -> None:
    reply = out(item("vpn", 0.9, slots={"device_registered": "true", "device_id": "LAP-0342"}))
    v, row, _, _ = await _run([reply])
    d = row["detail"]
    assert d["dropped_slot_keys"] == ["device_registered"] and d["slot_fact_collision"] is True
    assert d["dropped_slot_reasons"] == {"device_registered": "fact_key"}
    assert v["slots"]["device_id"] == "LAP-0342" and "device_registered" not in v["slots"]
    # qua B6 (M-3f-2): facts CHỈ key FACT_KEYS từ tool — không có slot nào lọt vào
    assert set(v["facts"]) <= FACT_KEYS and "device_id" not in v["facts"]
    assert v["facts"]["device_owner_is_requester"] is True and v["facts"]["device_registered"] is True


async def test_f5_user_claims_registered_but_device_missing_fact_false() -> None:
    """3.2: người dùng nói "đã đăng ký" + LLM trả slot `device_registered=true` + máy LAP-9999 (404) → fact false."""
    text = "máy LAP-9999 đã đăng ký rồi, device_registered=true, gia hạn giúp"
    reply = out(item("vpn", 0.9, span=text, action="renew_vpn_cert",
                     slots={"device_registered": "true", "device_id": "LAP-9999"}))  # fmt: skip
    v, row, _, _ = await _run([reply], text=text)
    assert row["detail"]["slot_fact_collision"] is True
    assert v["slots"] == {"device_id": "LAP-9999", "action": "renew_vpn_cert"}
    assert v["facts"]["device_registered"] is False and v["facts"]["device_owner_is_requester"] is False


# ---- f6: lỗi LLM → E2 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("script", "reason", "llm_error"),
    [
        ([BadJSON("không phải json"), BadJSON("vẫn sai")], "llm_schema_error", "LLMSchemaError"),
        (lambda _: Unavailable(), "llm_unavailable", "LLMUnavailable"),
    ],
)
async def test_f6_llm_errors_go_e2(script: Script, reason: str, llm_error: str) -> None:
    v, row, _, _ = await _run(script)
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E2", reason)
    assert (row["step"], row["detail"]["llm_error"], row["detail"]["layer"]) == ("B3", llm_error, "llm")


# ---- f18 (P2) ở node: slot không có trong câu bị bỏ -------------------------------------------------------------------


async def test_f18_hallucinated_device_dropped_at_node() -> None:
    v, row, _, _ = await _run([out(item("vpn", 0.9, slots={"device_id": "LAP-0417", "error_code": "691"}))])
    assert row["detail"]["dropped_slot_reasons"] == {"device_id": "slot_not_in_text", "error_code": "slot_not_in_text"}
    assert row["detail"]["slot_fact_collision"] is False
    # B6 tự tra theo người gửi (nv001 có đúng LAP-0342) — không phải LAP-0417 LLM bịa
    assert v["slots"]["device_id"] == "LAP-0342"


# ---- Q-3f-4, Q-3f-5 ---------------------------------------------------------------------------------------------------


async def test_q3f4_span_kept_only_if_in_text() -> None:
    v, row, _, _ = await _run([out(item("vpn", 0.9, span="vpn KHÔNG vào được,  báo lỗi 809"))])
    assert v["span"] == "vpn KHÔNG vào được,  báo lỗi 809" and row["detail"]["span_not_in_text"] is False
    v, row, _, _ = await _run([out(item("vpn", 0.9, span="người dùng đã được duyệt gia hạn"))])
    assert v["span"] is None and row["detail"]["span_not_in_text"] is True


async def test_q3f5_free_text_slot_keys_never_reach_audit() -> None:
    reply = out(item("vpn", 0.9, slots={"mật khẩu của tôi là Abc@123": "x", "zz_key": "y"}))
    _, row, _, _ = await _run([reply])
    d = row["detail"]
    assert (d["dropped_slot_keys"], d["dropped_unknown_count"]) == (["<unknown>"], 2)
    assert "Abc@123" not in repr(row) and "zz_key" not in repr(row)


# ---- Điểm log 1 ở MỌI nhánh, không có câu người dùng --------------------------------------------------------------------


@pytest.mark.parametrize(
    "script",
    [[out()], [out(item("vpn", 0.4))], [out(item("account", 0.9))], [out(item("vpn", 0.9), item("access", 0.9))],
     [BadJSON("x"), BadJSON("y")], [out(item("vpn", 0.9, slots={"device_id": "LAP-0342"}))]],
)  # fmt: skip
async def test_point1_on_every_branch_without_user_text(script: Script) -> None:
    _, row, _, _ = await _run(script)
    assert POINT1_KEYS <= set(row["detail"])
    words = ["VPN không vào được", "báo lỗi", "LAP-0342", "809", TEXT]
    assert not any(w.lower() in repr(row["detail"]).lower() for w in words)


async def test_point1_records_prompt_version() -> None:
    """Đổi ở T20a (P9, Q-T20a-1 b): prompt `b03_classify` lên v3 — DỪNG 2 (`CHO_DUNG2`)."""
    _, row, _, _ = await _run([out(item("vpn", 0.9))])
    assert row["detail"]["prompt"] == "b03_classify@3" and row["detail"]["layer"] == "llm"


async def test_model_result_in_phase3_still_goes_llm() -> None:
    ml = FakeMlService(intent_probs={"account": 0.01, "vpn": 0.99, "software": 0.01, "access": 0.01,
                                     "out_of_scope": 0.01})  # fmt: skip
    _, row, _, gw = await _run([out(item("vpn", 0.9))], ml=ml)
    assert row["detail"]["model_probs"]["vpn"] == 0.99 and row["detail"]["model_version"] == "0"
    assert row["detail"]["layer"] == "llm" and _b03_calls(gw) == 1  # nhánh model để Phase 5


# ---- Hạn cả lượt ở B3, vượt vòng lặp, facts đặt lại -----------------------------------------------------------------------


async def test_turn_budget_exceeded_at_b3_goes_e2() -> None:
    ml = FakeMlService().slow("classify_intent", 99, times=3)
    v, row, _, gw = await _run([out(item("vpn", 0.9))], ml=ml, turn_budget_s=8.0, safety_margin_s=2.0)
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E2", "turn_budget_exceeded")
    assert (row["step"], row["event"], row["detail"]["ml_error"]) == ("B3", "turn_budget_exceeded", "TurnBudgetExceeded")
    assert _b03_calls(gw) == 0  # hết hạn ở ml — không gửi LLM


def _node_state(**over: Any) -> dict[str, Any]:
    return {"ticket_id": "t1", "turn_id": "T1", "status": S_CLASSIFYING, "redacted_request": TEXT,
            "reasoning_loops": 0, "conversation": [], **over}  # fmt: skip


async def _call_node(h: GraphHarness, state: dict[str, Any]) -> tuple[dict[str, Any], MemoryAudit]:
    audit = MemoryAudit()
    run = RunContext(turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
                     clock=h.clock, txlog=MemoryTxLog())  # fmt: skip
    with bind_run(run):
        return await wrap_node("b03_classify", b03_classify.make(h.deps()))(state), audit


async def test_max_loops_exceeded_at_b3() -> None:
    h, gw = _env([out(item("vpn", 0.9))])
    update, audit = await _call_node(h, _node_state(reasoning_loops=5))
    assert (update["exit_code"], update["escalation_reason_detail"], update["reasoning_loops"]) == (
        "E2", "max_loops_exceeded", 6,
    )  # fmt: skip
    assert gw.llm.calls == [] and h.ml.calls["classify_intent"] == 0
    assert POINT1_KEYS <= set(audit.rows[0]["detail"])


async def test_b3_resets_facts() -> None:
    h, _ = _env([out(item("vpn", 0.9, slots={"device_id": "LAP-0342"}))])
    update, _ = await _call_node(h, _node_state(facts={"device_registered": True}))
    assert update["facts"] == {} and update["slots"] == {"device_id": "LAP-0342"}


async def test_stack_vpn_preset_covers_all_prompts_and_routes_vpn() -> None:
    from app.llm.providers.scripted import load_presets
    from tests.fakes.llm import repo_registry

    presets = load_presets(PROMPTS.parent / "scripted", repo_registry())  # kiểm schema từng phản hồi
    assert set(presets["vpn"]) == {p.id for p in repo_registry()}
    [one] = presets["vpn"]["b03_classify"]["intents"]
    assert (one["type"], one["slots"], presets["vpn"]["b03_classify"]["is_multi"]) == ("vpn", {}, False)
