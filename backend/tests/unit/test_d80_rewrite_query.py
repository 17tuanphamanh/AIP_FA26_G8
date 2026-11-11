"""D-80 (chấm thử hệ thống thật 11/11): câu hỏi thông tin gõ không dấu / viết tắt / có lời chào cho điểm truy hồi dưới ngưỡng dù KB có
bài → B9 viết lại câu (`b09_rewrite_query`) rồi truy hồi lại MỘT lần với CÙNG ngưỡng.

Bằng chứng (máy demo, LLM + RAG thật): "may in ko in dc thi lam sao" → E3, "máy in không in được thì làm sao" → trả lời; "o cung day roi
lam sao giai phong" → E3, bản có dấu → trả lời; "mình muốn hỏi cách kết nối Wi-Fi công ty trên laptop" → E3, "Cách kết nối Wi-Fi công
ty trên laptop?" → trả lời.

Hợp đồng:
- Chỉ nhánh TRẢ LỜI (info / it_help) khi sắp ra E3 vì dưới ngưỡng; cờ tắt → E3 ngay, 0 lời gọi viết lại (như trước).
- Câu viết lại chỉ dùng để truy hồi; `b10_answer` vẫn nhận câu gốc đã che; ngưỡng không đổi.
- Lỗi LLM / RAG khi viết lại, câu viết lại trùng câu gốc, hoặc vẫn dưới ngưỡng → E3 `no_grounding` như trước (KHÔNG thành E2).
- Nhánh hành động không bao giờ gọi viết lại. Audit chỉ điểm/cờ, không chữ.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_RETRIEVING
from app.domain.ticket_state import ChunkRef
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b10_route
from app.llm.providers.scripted import Reply, Script, Unavailable
from app.rag.models import EvidenceBlock, RetrievalResult, RetrievalSystemError
from tests.fakes.graph import GraphHarness
from tests.fakes.kb_index import KBV
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag

pytestmark = pytest.mark.asyncio

INFORMAL = "may in ko in dc thi lam sao"
REWRITTEN = "Máy in không in được thì làm sao?"


def _ctx() -> RequesterContext:
    return RequesterContext(
        user_id="nv-fake", role="employee", department="hr", manager_id=None, employment_status="active",
        tenure_days=10, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def _ref(seq: int, score: float) -> ChunkRef:
    return ChunkRef(chunk_id=f"KB-GEN-002#v1#{seq}", doc_id="KB-GEN-002", version=1, seq=seq, title="Máy in",
                    heading_path=f"Mục {seq}", score=score, excerpt="x")  # fmt: skip


LOW = [_ref(1, 0.12), _ref(2, 0.08)]
HIGH = [_ref(1, 0.91), _ref(2, 0.70)]


def _result(chunks: list[ChunkRef]) -> RetrievalResult:
    return RetrievalResult(chunks=chunks, top_score=chunks[0].score if chunks else 0.0, kb_version=KBV,
                           intent_filter_fallback=False, fallback_tried=False, retries=0, query_truncated=False)  # fmt: skip


def _state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "redacted_request": INFORMAL, "intent": "it_help",
        "retrieved": list(LOW), "retrieval_score": LOW[0].score, "kb_version": KBV, "requester_context": _ctx(),
        "slots": {}, "facts": {},
    }  # fmt: skip
    base.update(over)
    return base


def _answer() -> Reply:
    return Reply({"answer_markdown": "Bạn kiểm tra máy in như sau.", "citations": [HIGH[0].chunk_id],
                  "steps": ["Kiểm tra máy in đang bật"], "cannot_answer": False})  # fmt: skip


def _env(*, enabled: bool = True, rag: FakeRag | None = None, **scripts: Script) -> tuple[GraphHarness, Gateway, FakeRag]:
    clock = FakeClock()
    gw = make_gateway(dict(scripts), clock=clock)
    fake = rag or FakeRag(result=_result(HIGH), evidence=[
        EvidenceBlock(anchor_chunk_id=c.chunk_id, doc_id=c.doc_id, title=c.title, heading_path=c.heading_path, score=c.score,
                      text="Kiểm tra máy in đang bật.", tokens=20) for c in HIGH])  # fmt: skip
    h = GraphHarness(clock=clock, llm=gw.client, rag=fake, enable_query_rewrite=enabled)
    return h, gw, fake


async def _node(h: GraphHarness, state: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = RunContext(turn_id="T1", trace_id="0" * 32, audit=h.audit, effects=h.effects, spans=h.spans, clock=h.clock,
                     txlog=h.txlog)  # fmt: skip
    with bind_run(ctx):
        return await b10_route.make(h.deps())(state or _state())


def _b9_row(h: GraphHarness) -> dict[str, Any]:
    rows = [r for r in h.audit.rows if r["step"] in ("B9", "B10")]
    return rows[-1]


async def test_d80_informal_question_rewritten_and_answered_with_original_question() -> None:
    h, gw, rag = _env(b09_rewrite_query=[Reply({"query": REWRITTEN})], b10_answer=[_answer()])
    out = await _node(h)
    assert out["status"] == S_CONFIRMING  # trả lời thay vì E3
    [(q, _)] = rag.retrieve_calls
    assert q.text == REWRITTEN  # truy hồi lại bằng câu viết lại
    [answer_call] = gw.llm.calls_for("b10_answer")
    assert answer_call.variables["question"] == INFORMAL  # b10_answer nhận câu GỐC (đã che), không phải câu viết lại
    rec = _b9_row(h)["detail"]["rewrite"]
    assert rec == {"tried": True, "changed": True, "top_score": HIGH[0].score, "above_threshold": True, "error": None}
    assert INFORMAL not in str(rec) and REWRITTEN not in str(rec)  # audit không chữ


async def test_d80_flag_off_keeps_e3_and_never_calls_rewrite() -> None:
    h, gw, rag = _env(enabled=False)
    out = await _node(h)
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E3", "no_grounding")
    assert rag.retrieve_calls == [] and not gw.llm.calls_for("b09_rewrite_query")


async def test_d80_still_below_threshold_after_rewrite_is_e3() -> None:
    """Có bằng chứng và có kịch bản trả lời — chỉ NGƯỠNG chặn: E3 phải ra ở cổng B9 (không expand, không b10_answer)."""
    evidence = [EvidenceBlock(anchor_chunk_id=c.chunk_id, doc_id=c.doc_id, title=c.title, heading_path=c.heading_path, score=c.score,
                              text="x", tokens=5) for c in LOW]  # fmt: skip
    h, gw, rag = _env(rag=FakeRag(result=_result(LOW), evidence=evidence), b09_rewrite_query=[Reply({"query": REWRITTEN})],
                      b10_answer=[_answer()])  # fmt: skip
    out = await _node(h)
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E3", "no_grounding")
    row = _b9_row(h)
    assert row["step"] == "B9" and row["detail"]["rewrite"]["above_threshold"] is False
    assert rag.expand_calls == [] and not gw.llm.calls_for("b10_answer")


async def test_d80_rewrite_same_as_original_does_not_retrieve_again() -> None:
    h, _gw, rag = _env(b09_rewrite_query=[Reply({"query": "  " + INFORMAL.upper() + " "})])
    out = await _node(h)
    assert out["exit_code"] == "E3" and rag.retrieve_calls == []
    assert _b9_row(h)["detail"]["rewrite"]["changed"] is False


@pytest.mark.parametrize("failure", ["llm", "rag"])
async def test_d80_rewrite_failure_falls_back_to_e3_not_e2(failure: str) -> None:
    if failure == "llm":
        h, _gw, _rag = _env(b09_rewrite_query=[Unavailable(), Unavailable(), Unavailable()])
    else:
        h, _gw, _rag = _env(rag=FakeRag(error=RetrievalSystemError("rerank", 1)), b09_rewrite_query=[Reply({"query": REWRITTEN})])
    out = await _node(h)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "no_grounding")
    assert _b9_row(h)["detail"]["rewrite"]["error"] is not None


async def test_d80_above_threshold_first_time_never_rewrites() -> None:
    h, gw, rag = _env(b10_answer=[_answer()])
    out = await _node(h, _state(retrieved=list(HIGH), retrieval_score=HIGH[0].score))
    assert out["status"] == S_CONFIRMING and rag.retrieve_calls == []
    assert not gw.llm.calls_for("b09_rewrite_query")


async def test_d80_action_branch_never_rewrites() -> None:
    h, gw, rag = _env(b10_need_type=[Reply({"type": "action", "confidence": 0.9})])
    out = await _node(h, _state(intent="vpn", redacted_request="vpn ko vao dc"))
    assert out["next"] == "b11_slots"
    assert rag.retrieve_calls == [] and not gw.llm.calls_for("b09_rewrite_query")
