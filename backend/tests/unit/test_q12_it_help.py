"""Q12 (ĐP 09/11, lô Q1+Q12) — intent chỉ-trả-lời `it_help` (test viết trước, DỪNG 1 phần 2).

Hợp đồng (PLAN "Q1 + Q12" ở PROGRESS.md, ĐP duyệt 09/11 09:35):
- `it_help` KHÔNG thuộc `ENABLED_INTENTS` (harness chỉ bật `vpn`) — B3 xử lý trước kiểm `intent_not_enabled`; slot `{}`, không báo trùng M1.
- Đường đi (không cạnh mới): B3 → `b06_diagnose` (0 lời gọi tool, event `diagnosis_not_applicable`) → B8 (lọc `request_type ∈ ["general"]`)
  → B10 ép `info` (KHÔNG `b10_need_type`) → B9 ngưỡng → `b10_answer` → `S_CONFIRMING`. Thiếu căn cứ → E3. Không bao giờ B11/B12/B15/B17.
- Chặn tường minh: `b11_slots` / `b12_assess` gặp intent ∈ `ANSWER_ONLY_INTENTS` → `ValueError` → E9.
- Nhiều ý: ý `it_help` coi như `out_of_scope` (con E1 ngay; tin tổng hợp của cha có khối `escalation` cho ý đó).
- Cờ `ENABLE_IT_HELP` (mặc định bật): tắt → `it_help` như `out_of_scope` (E1). Câu E1 có vế "và hướng dẫn…" khi bật, bỏ khi tắt.

ScriptedLLM, không gọi LLM thật.
"""

from datetime import timedelta
from typing import Any, cast

import pytest
from app.core.clock import FakeClock
from app.domain.intents import ANSWER_ONLY_INTENTS, IT_HELP
from app.domain.messages import ANSWER_CLOSING
from app.domain.states import S_CONFIRMING, S_ESCALATED
from app.domain.ticket_state import ChunkRef
from app.graph.routing import ROUTES
from app.llm.providers.scripted import Reply, Step
from app.rag import filters
from app.rag.models import EvidenceBlock, RetrievalResult
from app.settings import get_escalation_templates
from qdrant_client.models import FieldCondition, MatchAny
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import ad_user
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts
from tests.unit import test_b12_assess
from tests.unit._t20b import RESET, classify, item, make_flow, reset_item
from tests.unit.test_b11_slots import _node_harness, _state
from tests.unit.test_t20b_flows import digests
from tests.unit.test_t20b_split import assert_not_runnable

SESSION = "s-nv001"
NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ bình thường"}
PRINTER_Q = "máy in không in được"
E1_TAIL = "Yêu cầu này mình đã chuyển kỹ thuật viên hỗ trợ bạn."
SCOPE_OFF = "Mình là trợ lý IT, hiện hỗ trợ: VPN, tài khoản và mật khẩu, cài phần mềm, quyền truy cập thư mục."
SCOPE_ON = (
    "Mình là trợ lý IT, hiện hỗ trợ: VPN, tài khoản và mật khẩu, cài phần mềm, quyền truy cập thư mục; và hướng dẫn các sự cố IT "
    "thường gặp như máy in, Wi-Fi, Outlook."
)
FORBIDDEN_STEPS = {"B11", "B12", "B13", "B14", "B15", "B16", "B17", "B18"}


def it(type_: str = "it_help", confidence: float = 0.9, span: str = PRINTER_Q) -> dict[str, Any]:
    return {"type": type_, "confidence": confidence, "span": span, "action_hint": None, "slots": {}}


def out(*items: dict[str, Any]) -> Reply:
    return Reply({"intents": list(items), "is_multi": len(items) >= 2})


def _rag(n: int = 5) -> FakeRag:
    chunks = [ChunkRef(chunk_id=f"g{i}", doc_id="KB-GEN-002", version=1, seq=i, title="Máy in", heading_path=f"Mục {i}",
                       score=0.95, excerpt="x") for i in range(1, n + 1)]  # fmt: skip
    evidence = [EvidenceBlock(anchor_chunk_id=c.chunk_id, doc_id=c.doc_id, title=c.title, heading_path=c.heading_path, score=c.score,
                              text="Kiểm tra giấy và hàng đợi in.", tokens=12) for c in chunks]  # fmt: skip
    return FakeRag(result=RetrievalResult(chunks=chunks, top_score=0.95 if chunks else 0.0, kb_version="a" * 64,
                                          intent_filter_fallback=False, fallback_tried=False, retries=0,
                                          query_truncated=False), evidence=evidence)  # fmt: skip


def _answer(v: Any) -> Step:
    """b10_answer "ngoan" nhưng trả 5 bước — code phải cắt còn 3 (Q2 M2)."""
    anchors = [str(e.anchor_chunk_id if not isinstance(e, dict) else e["anchor_chunk_id"]) for e in v["evidence"]]
    return Reply({"answer_markdown": "Bạn thử các bước sau.", "citations": anchors[:2],
                  "steps": [f"Bước số {i}" for i in range(1, 6)], "cannot_answer": False})  # fmt: skip


def env(b03: Reply | list[Reply], *, rag: FakeRag | None = None, it_help: bool = True) -> tuple[GraphHarness, Gateway]:
    clock = FakeClock()
    replies: list[Step] = [b03] if isinstance(b03, Reply) else list(b03)
    gw = make_gateway({**vpn_scripts(action=None), "b02_injection_judge": lambda _: Reply(NOT_ATTACK),  # type: ignore[dict-item]
                       "b03_classify": replies, "b10_answer": _answer}, clock=clock)  # fmt: skip
    h = GraphHarness(clock=clock, nodes="real", llm=gw.client, rag=rag or _rag(), enable_it_help=it_help)
    h.identity.add_session(SESSION, "nv001", expires_at=clock.now() + timedelta(days=365))
    h.ad.users["nv001"] = ad_user("nv001")
    return h, gw


async def submit(h: GraphHarness, text: str = PRINTER_Q, ticket: str = "t1") -> dict[str, Any]:
    h.tickets.register(ticket, h.clock.now(), requester_id="nv001", session_id=SESSION, redacted_request=text)
    return cast(dict[str, Any], (await h.submit_as(ticket, SESSION, text=text)).values)


def steps_of(h: GraphHarness, ticket: str = "t1") -> set[str]:
    return {step for step, _ in h.audit.events(ticket)}


# ---- luồng 6: B3 → B6 (0 tool) → B8 general → B10 info → S_CONFIRMING ----------------------------------------------------------


@pytest.mark.asyncio
async def test_it_help_answer_flow_end_to_end() -> None:
    h, gw = env(out(it()))
    v = await submit(h)
    assert v["status"] == S_CONFIRMING and (v["intent"], v["slots"], v["facts"]) == ("it_help", {}, {})
    [b3] = h.audit.of("t1", "intent_classified")
    assert (b3["step"], b3["detail"]["intent"]) == ("B3", "it_help")  # không bị `intent_not_enabled` (harness chỉ bật vpn)
    [b6] = h.audit.of("t1", "diagnosis_not_applicable")
    assert (b6["step"], b6["detail"]["tools_called"]) == ("B6", [])
    assert not h.audit.of("t1", "diagnosed")
    [(q, _ctx)] = h.rag.retrieve_calls
    assert q.intent == "it_help"
    assert gw.llm.calls_for("b10_need_type") == []  # ép info
    assert len(gw.llm.calls_for("b10_answer")) == 1
    [b10] = h.audit.of("t1", "deflected_info_only")
    assert (b10["detail"]["need_type"], b10["detail"]["answer_only"]) == ("info", True)
    msg = v["conversation"][-1]
    assert (msg["kind"], msg["needs"]) == ("answer", "confirm") and msg["sources"]
    numbered = [line for line in msg["text"].splitlines() if line[:2] in {"1.", "2.", "3.", "4.", "5."}]
    assert numbered == ["1. Bước số 1", "2. Bước số 2", "3. Bước số 3"]  # ≤ 3 bước
    assert ANSWER_CLOSING in msg["text"]
    assert not steps_of(h) & FORBIDDEN_STEPS


@pytest.mark.asyncio
async def test_it_help_never_reaches_policy_action_or_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mục 9: 0 lời gọi policy engine (M5), 0 Action, 0 phiếu duyệt, 0 thực thi — kể cả khi người dùng bấm "Chưa ổn" (E8)."""
    from app.graph.nodes import b12_assess

    calls: list[Any] = []
    monkeypatch.setattr(b12_assess, "evaluate", lambda *a: calls.append(a))
    h, gw = env(out(it()))
    v = await submit(h)
    assert v.get("intended_action") is None and v.get("risk") is None
    from app.graph.late_event import deliver_event

    v = cast(dict[str, Any], (await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "unresolved"})).values)
    assert (v["status"], v["exit_code"]) == (S_ESCALATED, "E8")
    assert calls == [] and h.executor.calls["t1"] == 0 and h.approvals.count("t1") == 0
    assert not steps_of(h) & FORBIDDEN_STEPS
    assert not [c for c in gw.llm.calls if c.prompt_id.startswith(("b11", "b14"))]


@pytest.mark.asyncio
async def test_it_help_no_grounding_goes_e3() -> None:
    h, gw = env(out(it()), rag=_rag(0))
    v = await submit(h)
    assert (v["status"], v.get("exit_code"), v.get("escalation_reason_detail")) == (S_ESCALATED, "E3", "no_grounding")
    assert gw.llm.calls_for("b10_answer") == [] and gw.llm.calls_for("b10_need_type") == []


@pytest.mark.asyncio
async def test_it_help_below_tau_intent_is_not_answered_directly() -> None:
    """`it_help` cũng qua ngưỡng TAU_INTENT như mọi ý: 0,4 → hỏi phân loại (Q1), không trả lời ngay."""
    h, gw = env(out(it(confidence=0.4)))
    v = await submit(h)
    assert v["status"] != S_CONFIRMING and gw.llm.calls_for("b10_answer") == []


# ---- bộ lọc truy hồi ----------------------------------------------------------------------------------------------------------


def test_intent_filter_it_help_is_general_only() -> None:
    assert filters.intent_filter("it_help") == FieldCondition(key="request_type", match=MatchAny(any=["general"]))
    assert filters.intent_filter("vpn") == FieldCondition(key="request_type", match=MatchAny(any=["vpn", "general"]))


# ---- hằng một nguồn + không vào ENABLED_INTENTS -------------------------------------------------------------------------------


def test_answer_only_constants() -> None:
    assert IT_HELP == "it_help" and ANSWER_ONLY_INTENTS == frozenset({"it_help"})
    from app.settings import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "it_help" not in s.enabled_intents and s.enable_it_help is True


def test_routes_unchanged_for_it_help() -> None:
    """Không cạnh mới cho it_help; Q1 chỉ thêm `b03 → clarify_wait` và `clarify_wait → b02_screen`."""
    assert ROUTES["b03_classify"] == {"b06_diagnose", "parent_wait", "clarify_wait", "b20_audit"}
    assert ROUTES["clarify_wait"] == {"b11_slots", "b06_diagnose", "b02_screen", "b20_audit"}
    assert ROUTES["b06_diagnose"] == {"b08_retrieve", "b11_slots", "b20_audit"}
    assert ROUTES["b10_route"] == {"b11_slots", "confirm_wait", "b20_audit"}


# ---- chặn tường minh ở B11 / B12 → E9 ----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b11_rejects_answer_only_intent_e9() -> None:
    from app.graph.builder import wrap_node
    from app.graph.nodes import b11_slots
    from tests.unit.test_b11_slots import _run

    h, _gw = _node_harness()
    with _run(h):
        update = await wrap_node("b11_slots", b11_slots.make(h.deps()))(_state({}, intent="it_help"))
    assert update["exit_code"] == "E9"
    [row] = [r for r in h.audit.rows if r["exit_code"] == "E9"]
    assert row["detail"]["exception"].startswith("ValueError") and "it_help" in row["detail"]["exception"]


@pytest.mark.asyncio
async def test_b12_rejects_answer_only_intent_e9(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.graph.nodes import b12_assess

    calls: list[Any] = []
    monkeypatch.setattr(b12_assess, "evaluate", lambda *a: calls.append(a))
    out_, h, _gw = await test_b12_assess._node(test_b12_assess._state(intent="it_help"), boundary=True)
    assert out_["exit_code"] == "E9" and calls == []
    [row] = [r for r in h.audit.rows if r["exit_code"] == "E9"]
    assert row["detail"]["exception"].startswith("ValueError") and "it_help" in row["detail"]["exception"]


# ---- M1 báo trùng: không bật cho it_help -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_not_triggered_for_it_help() -> None:
    h, _gw = env([out(it()), out(it())])
    await submit(h, ticket="t1")
    await submit(h, ticket="t2")  # t1 còn mở (S_CONFIRMING), cùng người, cùng intent
    assert [n for n in h.notifier.sent if n[0] == "t2" and "đang có một yêu cầu" in n[1]] == []
    [b3] = h.audit.of("t2", "intent_classified")
    assert "duplicate_of" not in b3["detail"]


# ---- nhiều ý: ý it_help = out_of_scope ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_intent_it_help_part_goes_to_technician_and_digest_says_so() -> None:
    f = make_flow(classify(reset_item(), item("it_help", PRINTER_Q)))
    await f.submit(f"{RESET}, {PRINTER_Q}")
    assert_not_runnable(f, "T1-2", "out_of_scope")
    [d1] = digests(await f.assistant_msgs())
    assert [(i["index"], i["kind"]) for i in d1["items"]] == [(1, "result"), (2, "escalation")]


# ---- cờ ENABLE_IT_HELP --------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_it_help_is_out_of_scope_e1() -> None:
    h, gw = env(out(it()), it_help=False)
    v = await submit(h)
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E1", "out_of_scope")
    assert h.rag.retrieve_calls == [] and gw.llm.calls_for("b10_answer") == []
    sent = [t for tid, t, _ in h.notifier.sent if tid == "t1"]
    assert sent[-1] == f"{SCOPE_OFF} {E1_TAIL}"


@pytest.mark.asyncio
async def test_e1_message_mentions_it_help_when_flag_on() -> None:
    h = GraphHarness()
    await h.submit("e1", b03_classify="out_of_scope")
    assert [t for tid, t, _ in h.notifier.sent if tid == "e1"][-1] == f"{SCOPE_ON} {E1_TAIL}"


@pytest.mark.asyncio
async def test_e1_message_without_it_help_when_flag_off() -> None:
    h = GraphHarness(enable_it_help=False)
    await h.submit("e1", b03_classify="out_of_scope")
    assert [t for tid, t, _ in h.notifier.sent if tid == "e1"][-1] == f"{SCOPE_OFF} {E1_TAIL}"
    assert get_escalation_templates().of("E1").user_message == f"{SCOPE_OFF} {E1_TAIL}"  # mẫu gốc giữ nguyên (test_messages_scope)

