"""B10 thật (phase3 mục 10.3; PLAN-3g S3–S4; chốt Q-3g-1, Q-3g-2, Q-3g-3, f1).

- Hàm thuần: g3 (`check_citations`), `render_answer`, g26 (output guard không chặn nhầm chunk KB fixture).
- Node gọi trực tiếp (gateway THẬT + ScriptedLLM, `FakeRag`, store giả): mọi nhánh E2/E3, output guard, lineage, chạy lại
  trong cùng lượt, g9, g22 (hạn lượt ở B10).
- Graph `nodes="real"` (B1 → B2 → B3 → B6 → B8 thật → B10 thật, `FixtureRag` = chunk KB fixture thật + `expand` thật): g5
  (TC04), g6 (TC05), g7 (resume `confirm_wait`), g8, g2 (bản giả — bản Postgres ở `integration/test_b10_pg.py`).
- g25 (phần B10): AST — `goto` trong B10 dùng hằng chữ.
"""

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.core.turn_budget import TurnDeadline, bind_turn_deadline
from app.domain.answer import check_citations, render_answer
from app.domain.context import RequesterContext
from app.domain.messages import SOURCE_KEYS
from app.domain.states import (
    S_CLARIFYING,
    S_CONFIRMING,
    S_ESCALATED,
    S_RESOLVED,
    S_RETRIEVING,
)
from app.domain.ticket_state import ChunkRef
from app.graph.context import RunContext, bind_run
from app.graph.late_event import LateEvent, deliver_event
from app.graph.nodes import b10_route
from app.guard.output import OutputGuard
from app.llm.providers.scripted import BadJSON, Reply, Script, Timeout, Unavailable
from app.llm.registry import load_prompts
from app.rag.models import EvidenceBlock, RetrievalSystemError
from tests.fakes.graph import Crash, GraphHarness
from tests.fakes.identity import SESSION
from tests.fakes.kb import FIXTURE_KB
from tests.fakes.kb_index import KBV, chunk_ref, fixture_chunks, fixture_rag
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts

CONFIG = Path(__file__).resolve().parents[3] / "config"
QUESTION = "VPN công ty dùng cổng nào vậy anh?"
ANSWER_TEXT = "Máy chủ VPN dùng cổng 443 cho SSTP."
CANARY = "CANARY-B10-7781"


# ---- dựng dữ liệu ---------------------------------------------------------------------------------------------------


def _ctx() -> RequesterContext:
    return RequesterContext(
        user_id="nv-fake", role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=10, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def _ref(doc: str, seq: int, score: float, title: str = "Tài liệu VPN") -> ChunkRef:
    return ChunkRef(chunk_id=f"{doc}#v1#{seq}", doc_id=doc, version=1, seq=seq, title=title,
                    heading_path=f"Mục {seq}", score=score, excerpt="x")  # fmt: skip


TOP = [_ref("KB-VPN-001", 1, 0.9, "VPN công ty"), _ref("KB-VPN-003", 2, 0.8, "Lỗi 809")]


def _block(c: ChunkRef, text: str = "nội dung", tokens: int = 50) -> EvidenceBlock:
    return EvidenceBlock(anchor_chunk_id=c.chunk_id, doc_id=c.doc_id, title=c.title, heading_path=c.heading_path,
                         score=c.score, text=text, tokens=tokens)  # fmt: skip


def _state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "redacted_request": QUESTION, "intent": "vpn",
        "retrieved": list(TOP), "kb_version": KBV, "requester_context": _ctx(), "slots": {}, "facts": {},
    }  # fmt: skip
    base.update(over)
    return base


def _answer(citations: list[str], *, markdown: str = ANSWER_TEXT, steps: list[str] | None = None,
            cannot: bool = False) -> Reply:  # fmt: skip
    return Reply({"answer_markdown": markdown, "citations": citations, "steps": steps, "cannot_answer": cannot})


def _env(
    *, need: str = "info", answer: Script | None = None, evidence: list[EvidenceBlock] | None = None, **extra: Script
) -> tuple[GraphHarness, Gateway]:
    clock = FakeClock()
    scripts: dict[str, Script] = {"b10_need_type": [Reply({"type": need, "confidence": 0.9})], **extra}
    if answer is not None:
        scripts["b10_answer"] = answer
    gw = make_gateway(scripts, clock=clock)
    h = GraphHarness(clock=clock, llm=gw.client,
                     rag=FakeRag(evidence=[_block(c) for c in TOP] if evidence is None else evidence))  # fmt: skip
    return h, gw


@contextmanager
def _run(h: GraphHarness, turn_id: str = "T1") -> Iterator[RunContext]:
    ctx = RunContext(turn_id=turn_id, trace_id="0" * 32, audit=h.audit, effects=h.effects, spans=h.spans,
                     clock=h.clock)  # fmt: skip
    with bind_run(ctx):
        yield ctx


async def _node(h: GraphHarness, state: dict[str, Any] | None = None, **deps_over: Any) -> dict[str, Any]:
    deps = h.deps()
    for k, v in deps_over.items():
        setattr(deps, k, v)
    with _run(h):
        return await b10_route.make(deps)(state or _state())


def _nothing_sent(h: GraphHarness) -> None:
    assert h.notifier.sent == [] and h.deadlines.waits == [] and h.audit.lineage == []
    assert h.effects.count("t1", "notify_user") == h.effects.count("t1", "deadline_set") == 0


def _only(h: GraphHarness) -> dict[str, Any]:
    [row] = [r for r in h.audit.rows if r["step"] == "B10"]
    return row


# ---- g3: hậu kiểm trích dẫn (hàm thuần) — rỗng / ngoài top-5 / chunk liền kề / hợp lệ / cannot_answer ----------------

ANCHORS = {"KB-VPN-001#v1#1", "KB-VPN-003#v1#2"}


@pytest.mark.parametrize(("citations", "cannot", "verdict"), [
    ([], False, "invalid_citation"),  # Q-3g-2: ca rỗng chỉ tới được ở hàm thuần (validator AnswerOut chặn trước)
    (["KB-VPN-005#v1#0"], False, "invalid_citation"),  # ngoài top-5
    (["KB-VPN-003#v1#1"], False, "invalid_citation"),  # chunk LIỀN KỀ của anchor #2 (D-24: chỉ là ngữ cảnh)
    (["KB-VPN-003#v1#2", "KB-VPN-001#v1#1"], False, "ok"),
    (["KB-VPN-003#v1#2"], True, "no_grounding"),  # Q-3g-1: cannot_answer thắng kể cả khi có trích dẫn
    ([], True, "no_grounding"),
    (["KB-VPN-001#v1#1", "x"], False, "invalid_citation"),  # một trích dẫn sai là đủ
])  # fmt: skip
def test_g3_check_citations(citations: list[str], cannot: bool, verdict: str) -> None:
    assert check_citations(citations, cannot_answer=cannot, anchors=ANCHORS) == verdict


def test_render_answer_numbered_steps_and_dedup_sources() -> None:
    body = render_answer("  Bạn làm như sau.  ", ["Mở ABC Connect", " ", "Chọn SSTP"], [TOP[1], TOP[0], TOP[1]])
    assert body == (
        "Bạn làm như sau.\n\n1. Mở ABC Connect\n2. Chọn SSTP\n\n"
        "Nguồn:\n- Lỗi 809 › Mục 2\n- VPN công ty › Mục 1"
    )
    assert render_answer("Trả lời.", None, [TOP[0]]) == "Trả lời.\n\nNguồn:\n- VPN công ty › Mục 1"


# ---- đường vui ở node: gửi đúng 1 lần, hạn 48 h, lineage cùng audit, conversation đúng khuôn --------------------------


@pytest.mark.asyncio
async def test_info_answer_sends_once_sets_confirm_deadline_and_lineage() -> None:
    h, gw = _env(answer=[_answer([c.chunk_id for c in TOP], steps=["Mở ABC Connect"])])
    out = await _node(h)
    assert (out["status"], out["next"], out["need_type"]) == (S_CONFIRMING, "confirm_wait", "info")
    assert "intended_action" not in out
    [(ticket, text, needs)] = h.notifier.sent
    assert (ticket, needs, out["answer_ref"]) == ("t1", "confirm", "m1")
    [msg] = out["conversation"]
    assert msg == {"role": "assistant", "kind": "answer", "text": text, "ref": "m1", "needs": "confirm",
                   "sources": [{"chunk_id": c.chunk_id, "title": c.title, "heading_path": c.heading_path}
                               for c in TOP]}  # fmt: skip
    assert all(tuple(s) == SOURCE_KEYS for s in msg["sources"])  # P9: đúng 3 khoá, không đoạn trích
    [wait] = h.deadlines.waits
    assert (wait["kind"], wait["deadline"], wait["created_turn"]) == ("confirm", h.clock.now() + timedelta(hours=48),
                                                                      "T1")  # fmt: skip
    [lin] = h.audit.lineage
    assert lin == {"prompt_id": "b10_answer", "prompt_version": "1", "model": "scripted", "kb_version": KBV,
                   "ticket_id": "t1", "turn_id": "T1", "step": "B10", "created_at": h.clock.now()}  # fmt: skip
    row = _only(h)
    assert (row["event"], row["to_status"]) == ("deflected_info_only", S_CONFIRMING)
    assert row["detail"]["citation"] == "ok" and row["detail"]["cited"] == [c.chunk_id for c in TOP]
    assert row["detail"]["prompt"] == "b10_answer@1" and row["detail"]["evidence_truncated"] is False
    # audit/lineage không mang chữ người dùng hay chữ LLM (3.6)
    blob = repr(h.audit.rows) + repr(h.audit.lineage)
    assert QUESTION not in blob and ANSWER_TEXT not in blob and "Mở ABC Connect" not in blob
    assert [c.prompt_id for c in gw.llm.calls] == ["b10_need_type", "b10_answer"]


@pytest.mark.asyncio
async def test_rerun_same_turn_sends_nothing_more_single_lineage() -> None:
    """Chạy lại B10 trong CÙNG lượt (process chết sau goto, trước checkpoint): effects.once + audit/lineage idempotent."""
    h, _ = _env(answer=lambda v: _answer([e.anchor_chunk_id for e in v["evidence"]]),
                b10_need_type=lambda _: Reply({"type": "info", "confidence": 0.9}))  # fmt: skip
    first = await _node(h)
    again = await _node(h)
    assert first["answer_ref"] == again["answer_ref"] == "m1"
    assert len(h.notifier.sent) == 1 and len(h.deadlines.waits) == 1 and len(h.audit.lineage) == 1
    assert len([r for r in h.audit.rows if r["event"] == "deflected_info_only"]) == 1


# ---- g8: need=action → B11, không viết câu trả lời --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g8_action_goes_to_b11_without_answer() -> None:
    h, gw = _env(need="action")
    out = await _node(h)
    assert (out["status"], out["next"], out["need_type"]) == (S_RETRIEVING, "b11_slots", "action")
    assert gw.llm.calls_for("b10_answer") == [] and h.rag.expand_calls == []
    _nothing_sent(h)
    assert _only(h)["event"] == "needs_action"


# ---- g9 + Q-3g-2: lỗi LLM → E2 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("prompt", ["b10_need_type", "b10_answer"])
@pytest.mark.asyncio
async def test_g9_schema_error_e2(prompt: str) -> None:
    h, _ = _env(**{prompt: [BadJSON("{"), BadJSON("{")]})  # 1 lần sửa schema cũng hỏng
    out = await _node(h)
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E2", "llm_schema_error")
    _nothing_sent(h)
    assert _only(h)["detail"]["llm_error"] == "LLMSchemaError"


@pytest.mark.asyncio
async def test_q3g2_empty_citations_without_cannot_answer_is_schema_error_e2() -> None:
    """Q-3g-2: LLM trả `citations=[]` + `cannot_answer=false` (cả lần sửa) → validator AnswerOut → E2, không E3."""
    h, gw = _env(answer=[_answer([]), _answer([])])
    out = await _node(h)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E2", "llm_schema_error")
    assert len(gw.llm.calls_for("b10_answer")) == 2
    _nothing_sent(h)


@pytest.mark.parametrize("prompt", ["b10_need_type", "b10_answer"])
@pytest.mark.asyncio
async def test_llm_unavailable_e2(prompt: str) -> None:
    h, _ = _env(**{prompt: lambda _: Unavailable()})
    out = await _node(h)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E2", "llm_unavailable")
    _nothing_sent(h)


# ---- E3: không căn cứ / trích dẫn sai / bằng chứng bị cắt -----------------------------------------------------------


@pytest.mark.asyncio
async def test_q3g1_cannot_answer_is_e3_no_grounding() -> None:
    h, _ = _env(answer=[_answer([], markdown="", cannot=True)])
    out = await _node(h)
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E3", "no_grounding")
    assert _only(h)["event"] == "cannot_answer"
    _nothing_sent(h)


@pytest.mark.parametrize("cited", [["KB-VPN-005#v1#0"], ["KB-VPN-003#v1#1"], ["KB-VPN-001#v1#1", "KB-VPN-003#v1#3"]])
@pytest.mark.asyncio
async def test_g3_node_citation_outside_anchor_is_e3(cited: list[str]) -> None:
    """Ngoài top-5, hoặc chunk LIỀN KỀ của anchor (có trong bằng chứng mở rộng nhưng không phải anchor) → E3."""
    h, _ = _env(answer=[_answer(cited)])
    out = await _node(h)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "invalid_citation")
    assert _only(h)["detail"]["citation"] == "invalid_citation"
    _nothing_sent(h)


@pytest.mark.asyncio
async def test_citing_top5_chunk_dropped_from_evidence_is_e3() -> None:
    """Anchor = top-5 ∩ khối THẬT SỰ gửi LLM: khối điểm thấp bị `trim_to_budget` bỏ thì không được trích (LLM không thấy)."""
    h, _ = _env(evidence=[_block(TOP[0])], answer=[_answer([TOP[1].chunk_id])])
    out = await _node(h)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "invalid_citation")
    _nothing_sent(h)


@pytest.mark.asyncio
async def test_f1_gateway_trimmed_evidence_is_e3_truncated() -> None:
    """f1: gateway phải bỏ khối bằng chứng để vừa `budget_in` → E3 `invalid_citation`, `evidence_truncated=true` — kể cả
    khi trích dẫn trông hợp lệ (không đoán anchor)."""
    huge = _block(TOP[1], text="chữ " * 12_000, tokens=100)  # ước lượng ~16.000 token > budget_in strong (6000)
    h, gw = _env(evidence=[_block(TOP[0]), huge], answer=[_answer([TOP[0].chunk_id])])
    out = await _node(h)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "invalid_citation")
    detail = _only(h)["detail"]
    assert (detail["evidence_truncated"], detail["trimmed_evidence"]) == (True, 1)
    assert TOP[1].chunk_id not in gw.llm.calls_for("b10_answer")[0].rendered_messages[1]["content"]
    _nothing_sent(h)


@pytest.mark.asyncio
async def test_no_evidence_is_e3_without_answer_call() -> None:
    h, gw = _env(evidence=[])
    out = await _node(h)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "no_grounding")
    assert _only(h)["event"] == "no_evidence" and gw.llm.calls_for("b10_answer") == []
    _nothing_sent(h)


@pytest.mark.asyncio
async def test_expand_system_error_is_e2_rag_system_error() -> None:
    h, gw = _env()
    h.rag.expand_for_answer = _raise_expand  # type: ignore[method-assign]
    out = await _node(h)
    assert (out["exit_code"], out["escalation_reason_detail"], out["retrieval_error"]) == (
        "E2", "rag_system_error", "expand",
    )  # fmt: skip
    assert gw.llm.calls_for("b10_answer") == []
    _nothing_sent(h)


async def _raise_expand(*_: Any, **__: Any) -> list[EvidenceBlock]:
    raise RetrievalSystemError("expand", 2, kb_version=KBV)


# ---- output guard ở node (P4, M-3g-6, M-3g-16): chặn TRƯỚC khi gửi — 0 tin, 0 hạn, 0 lineage ------------------------


def _system_line() -> str:
    prompts = {p.id: p for p in load_prompts(CONFIG / "prompts")}
    return next(ln.strip() for ln in prompts["b11_extract_slots"].spec.system.splitlines() if len(ln.strip()) >= 60)


@pytest.mark.parametrize(("markdown", "steps", "kind"), [
    ("Mật khẩu VPN mặc định là Vpn@2026abc, bạn đăng nhập nhé.", None, "secret"),
    ("Bạn làm theo các bước.", ["Mở ABC Connect", f"Nhập mã {CANARY}"], "canary"),
    (f"Theo hướng dẫn: {_system_line()}", None, "system_prompt"),
])  # fmt: skip
@pytest.mark.asyncio
async def test_output_guard_blocks_before_sending(markdown: str, steps: list[str] | None, kind: str) -> None:
    h, _ = _env(answer=[_answer([TOP[0].chunk_id], markdown=markdown, steps=steps)])
    out = await _node(h, output_guard=OutputGuard.from_config(CONFIG, [CANARY]))
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (
        S_ESCALATED, "E3", "output_guard_block",
    )  # fmt: skip
    assert "conversation" not in out and "answer_ref" not in out
    assert _only(h)["detail"]["guard"] == kind
    _nothing_sent(h)


# ---- g22 (phần B10): hết hạn cả lượt ở b10_answer → E2, không lời gọi nào vượt phần còn lại ---------------------------

MARGIN = 2.0


@pytest.mark.asyncio
async def test_g22_turn_budget_at_b10_answer_is_e2() -> None:
    h, gw = _env(answer=lambda _: Timeout())
    deadline = TurnDeadline(h.clock.now() + timedelta(seconds=20 + MARGIN), MARGIN)  # 20 s dùng được < strong 50 s
    with bind_turn_deadline(deadline):
        out = await _node(h)
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (
        S_ESCALATED, "E2", "turn_budget_exceeded",
    )  # fmt: skip
    assert _only(h)["step"] == "B10"
    calls = gw.llm.calls_for("b10_answer")
    assert calls
    for c in gw.llm.calls:
        assert c.timeout_s is not None and c.at is not None
        assert c.timeout_s <= (deadline.at - c.at).total_seconds() - MARGIN + 1e-9
    _nothing_sent(h)


# ---- Graph thật tới B10: g5 (TC04), g6 (TC05), g7, g2 ---------------------------------------------------------------


async def _graph(top_ids: list[str], *, need: str = "info") -> tuple[GraphHarness, Gateway]:
    clock = FakeClock()
    gw = make_gateway(vpn_scripts(need=need), clock=clock)  # type: ignore[arg-type]
    h = GraphHarness(clock=clock, nodes="real", llm=gw.client, rag=await fixture_rag(top_ids, clock))  # type: ignore[arg-type]
    return h, gw


def _answers(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in values.get("conversation") or [] if m.get("kind") == "answer"]


@pytest.mark.asyncio
async def test_g5_tc04_port_question_answered_with_sources() -> None:
    h, _ = await _graph(["KB-VPN-001#v1#1", "KB-VPN-003#v1#0", "KB-VPN-005#v1#0"])
    v = (await h.submit_as("t1", SESSION, text="VPN công ty dùng cổng nào?")).values
    assert (v["status"], v["need_type"]) == (S_CONFIRMING, "info")
    assert v.get("intended_action") is None
    [msg] = _answers(v)
    assert any(s["chunk_id"].startswith("KB-VPN-001#") for s in msg["sources"])
    [wait] = h.deadlines.waits
    assert (wait["kind"], wait["deadline"] - h.clock.now()) == ("confirm", timedelta(hours=48))
    assert h.notifier.count("t1") == 1


@pytest.mark.asyncio
async def test_g6_tc05_evidence_spans_three_neighbor_chunks_citations_are_anchors() -> None:
    top = ["KB-VPN-003#v1#2", "KB-VPN-001#v1#1"]
    h, gw = await _graph(top)
    v = (await h.submit_as("t1", SESSION, text="Kết nối VPN báo lỗi 809, làm sao để sửa?")).values
    assert v["status"] == S_CONFIRMING
    [call] = gw.llm.calls_for("b10_answer")
    [block] = [b for b in call.variables["evidence"] if b.anchor_chunk_id == "KB-VPN-003#v1#2"]
    # ba chunk liền nhau seq 1–2–3 của KB-VPN-003 (Bước 1–2, 3–4, 5–6) nằm trong CÙNG một khối bằng chứng
    for phrase in ("phát Wi-Fi từ điện thoại", "SSTP (TCP 443)", "IKE and AuthIP IPsec Keying Modules"):
        assert phrase in block.text and phrase in call.rendered_messages[1]["content"]
    [msg] = _answers(v)
    assert {s["chunk_id"] for s in msg["sources"]} <= set(top)  # trích dẫn chỉ là anchor top-5
    assert "KB-VPN-003#v1#1" not in {s["chunk_id"] for s in msg["sources"]}


@pytest.mark.asyncio
async def test_g7_resume_confirm_wait_twice_single_answer() -> None:
    """Resume `confirm_wait` hai lần (lần đầu process chết trước khi ghi audit của B19 → recover chạy lại node chờ): chỉ
    MỘT câu trả lời — gửi tin nằm ở B10, không ở node chờ (M-3g-2)."""
    h, _ = await _graph(["KB-VPN-001#v1#1"])
    await h.submit_as("t1", SESSION, text="VPN công ty dùng cổng nào?")
    h.audit.crash_once.add("user_confirmed")
    with pytest.raises(Crash):
        await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "confirmed"})
    [open_turn] = [t for t, r in h.turns.rows.items() if r["ticket_id"] == "t1" and r["ended_at"] is None]
    r = await h.restart().recover("t1", open_turn)
    assert r is not None and r.status == S_RESOLVED
    with pytest.raises(LateEvent):
        await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "confirmed"})
    assert [n for _, _, n in h.notifier.sent] == ["confirm"]
    assert len(_answers(r.values)) == 1
    assert h.effects.count("t1", "notify_user") == 1


@pytest.mark.asyncio
async def test_g2_crash_after_b10_goto_then_recover_single_answer() -> None:
    """Process chết sau khi B10 đã gửi tin, trước checkpoint (audit của goto chưa ghi) → recover: đúng 1 tin, 1 lineage."""
    h, _ = await _graph(["KB-VPN-001#v1#1"])
    h.audit.crash_once.add("deflected_info_only")
    with pytest.raises(Crash):
        await h.submit_as("t1", SESSION, text="VPN công ty dùng cổng nào?")
    assert h.notifier.count("t1") == 1
    [open_turn] = [t for t, r in h.turns.rows.items() if r["ticket_id"] == "t1" and r["ended_at"] is None]
    r = await h.restart().recover("t1", open_turn)
    assert r is not None and r.status == S_CONFIRMING
    assert h.notifier.count("t1") == 1 and h.effects.count("t1", "notify_user") == 1
    assert len(_answers(r.values)) == 1 and len(h.audit.lineage) == 1


@pytest.mark.asyncio
async def test_g8_graph_action_continues_to_b11() -> None:
    h, gw = await _graph(["KB-VPN-004#v1#1"], need="action")
    v = (await h.submit_as("t1", SESSION, text="Gia hạn chứng chỉ VPN giúp mình")).values
    # DỪNG 2: B11 thật — người gửi giả không có máy nào (seed) → phải hỏi `device_id`
    assert v["need_type"] == "action" and v["status"] == S_CLARIFYING
    assert gw.llm.calls_for("b10_answer") == []


# ---- g26: output guard không chặn nhầm nội dung KB fixture (Q-3g-8) -------------------------------------------------


@pytest.mark.asyncio
async def test_g26_output_guard_passes_every_fixture_chunk() -> None:
    guard = OutputGuard.from_config(CONFIG, [])
    chunks = await fixture_chunks()
    blocked = []
    for cid, (doc, c) in chunks.items():
        ref = chunk_ref(doc, c, 0.9)
        for text in (render_answer(c.content, None, [ref]), render_answer("Tóm tắt.", c.content.split("\n"), [ref]),
                     c.text):  # fmt: skip
            if (kind := guard.violation(text)) is not None:
                blocked.append((cid, kind))
    facts = (FIXTURE_KB / "kb-facts.md").read_text(encoding="utf-8")
    if (kind := guard.violation(facts)) is not None:
        blocked.append(("kb-facts.md", kind))
    assert blocked == []


# ---- g25 (phần B10): goto dùng hằng chữ --------------------------------------------------------------------------------


def test_g25_b10_gotos_use_literal_step_event_reason() -> None:
    tree = ast.parse(Path(b10_route.__file__).read_text(encoding="utf-8"))
    gotos = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "goto"]
    assert len(gotos) >= 12
    for call in gotos:
        kw = {k.arg: k.value for k in call.keywords}
        assert isinstance(kw["step"], ast.Constant) and kw["step"].value == "B10", call.lineno
        assert isinstance(kw["event"], ast.Constant), call.lineno
        if "escalation_reason_detail" in kw:
            assert isinstance(kw["escalation_reason_detail"], ast.Constant), call.lineno
