"""Phase 4 S0 (Q-4-U A+, D-34; phase4 mục 4.0 + chốt MẪU A S0-A1…A5): B9 chỉ cho câu TRẢ LỜI, căn cứ của HÀNH ĐỘNG =
`procedure_doc` kiểm tất định ở B11 trên KB hiện hành, cờ `GROUNDING_GATE_ACTIONS` (ablation).

- B10 node (gateway THẬT + ScriptedLLM, `FakeRag`): s1–s5, s15 (+ đối chứng cờ), S0-P4 (lỗi LLM ở need_type → E2).
- B11 node (`FixtureRag` = `Retriever` THẬT trên `SpyIndex` chứa KB fixture — alias, `pipeline_sha`, `procedure_filter` thật):
  s12, s13, s14, M-S0-7 (quy trình `restricted` + nhân viên), S0-A3 (alias đổi giữa B8 và B11), hạn lượt ở kiểm quy trình.
- Graph `nodes="real"`: s2 tới B11 → B12 dù điểm thấp; s13 0 lời gọi ghi 0 phiếu; S0-A1 ghi chú bàn giao qua B20 thật.
- B12: s11 (`evidence_for_estimator` + estimator giả ghi nhận đầu vào).
- `Retriever.procedure_available` (SpyIndex): lọc quyền `base_filter`, alias hiện hành, mọi lỗi → stage `"procedure"`.
- s6: AST S0-P5. Wiring: `open_runtime` dựng `Retriever` THẬT và cờ đi từ `Settings`; `FakeRag` không có trong `app/`.
e2e s7–s10: `e2e/test_gate3_vpn.py` (s7 = h7, s10 = h2); Qdrant thật cho `procedure_available` + c5: `integration/test_b08_pg.py`.
"""

import ast
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.core.errors import LLMUnavailable
from app.core.turn_budget import TurnBudgetExceeded, TurnDeadline, bind_turn_deadline
from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.exit_codes import REASON_DETAILS
from app.domain.states import S_ASSESSING, S_CONFIRMING, S_ESCALATED, S_RETRIEVING
from app.domain.ticket_state import ChunkRef
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b10_route, b11_slots, b12_assess
from app.llm.providers.scripted import Script, Unavailable
from app.rag.ingest.config import ALIAS
from app.rag.models import EvidenceBlock, RetrievalResult, RetrievalSystemError
from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStoreTransient
from app.risk.estimator import PMethod, evidence_for_estimator
from app.risk.models import RiskContext
from app.settings import (
    Settings,
    get_action_metadata,
    get_escalation_templates,
    get_policy,
)
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, ad_user
from tests.fakes.kb_index import COLL, KBV, FixtureRag, fixture_rag
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts

APP = Path(__file__).resolve().parents[2] / "app"
THRESHOLD = get_policy().constants.RETRIEVAL_THRESHOLD
LOW = 0.047  # tc09 với reranker thật (phase3 11.10 #17)
QUESTION = "VPN công ty dùng cổng nào vậy anh?"
RENEW = "gia hạn VPN cho máy LAP-0342"
NEW_KBV = "d" * 64
BELOW = "Tài liệu KB gần nhất (điểm dưới ngưỡng, KHÔNG dùng làm căn cứ — có thể KB còn thiếu)"


# ---- dựng dữ liệu ---------------------------------------------------------------------------------------------------


def _ctx(user: str = "nv001", role: str = "employee") -> RequesterContext:
    return RequesterContext(
        user_id=user, role=role, department="it", manager_id=None, employment_status="active",  # type: ignore[arg-type]
        tenure_days=100, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def _ref(doc: str, seq: int, score: float) -> ChunkRef:
    return ChunkRef(chunk_id=f"{doc}#v1#{seq}", doc_id=doc, version=1, seq=seq, title=f"Tài liệu {doc}",
                    heading_path=f"Mục {seq}", score=score, excerpt="x")  # fmt: skip


def _block(c: ChunkRef) -> EvidenceBlock:
    return EvidenceBlock(anchor_chunk_id=c.chunk_id, doc_id=c.doc_id, title=c.title, heading_path=c.heading_path,
                         score=c.score, text="nội dung", tokens=50)  # fmt: skip


def _top(score: float) -> list[ChunkRef]:
    return [_ref("KB-VPN-005", 0, score), _ref("KB-VPN-001", 1, score - 0.01)]


@contextmanager
def _run(h: GraphHarness) -> Iterator[None]:
    with bind_run(RunContext(turn_id="T1", trace_id="0" * 32, audit=h.audit, effects=h.effects, spans=h.spans,
                             clock=h.clock, txlog=h.txlog)):  # fmt: skip
        yield


# ---- B10: s1–s5, s15, S0-P4 ------------------------------------------------------------------------------------------


def _b10(need: str, chunks: list[ChunkRef], score: float | None, *, flag: bool = False,
         **scripts: Script) -> tuple[GraphHarness, Gateway, dict[str, Any]]:  # fmt: skip
    clock = FakeClock()
    gw = make_gateway({**vpn_scripts(need=need), **scripts}, clock=clock)  # type: ignore[arg-type]
    h = GraphHarness(clock=clock, llm=gw.client, rag=FakeRag(evidence=[_block(c) for c in chunks]),
                     grounding_gate_actions=flag)  # fmt: skip
    state: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "redacted_request": QUESTION, "intent": "vpn",
        "retrieved": list(chunks), "kb_version": KBV, "requester_context": _ctx(), "slots": {}, "facts": {},
    }  # fmt: skip
    if score is not None:
        state["retrieval_score"] = score
    return h, gw, state


async def _b10_run(h: GraphHarness, state: dict[str, Any]) -> dict[str, Any]:
    with _run(h):
        return await b10_route.make(h.deps())(state)  # type: ignore[no-any-return]


def _calls(gw: Gateway, prompt: str) -> int:
    return len(gw.llm.calls_for(prompt))


@pytest.mark.asyncio
async def test_s1_info_below_threshold_e3_at_b9_without_expand_or_answer() -> None:
    h, gw, state = _b10("info", _top(THRESHOLD - 0.01), THRESHOLD - 0.01)
    out = await _b10_run(h, state)
    assert (out["status"], out["next"], out["exit_code"], out["escalation_reason_detail"]) == (
        S_ESCALATED, "b20_audit", "E3", "no_grounding",
    )  # fmt: skip
    assert out["need_type"] == "info"
    assert h.audit.events("t1") == [("B9", "no_evidence")]  # CÙNG step/event với nhánh B9 cũ ở B8 (B20, M9 không đổi)
    [row] = h.audit.rows
    assert row["detail"]["grounding"] == {"top_score": THRESHOLD - 0.01, "above_threshold": False, "kb_gap": True}
    assert row["kb_version"] == KBV  # cột audit như dòng B9 cũ ở B8 (soát NGHI-5)
    assert (_calls(gw, "b10_need_type"), _calls(gw, "b10_answer")) == (1, 0)
    assert h.rag.expand_calls == [] and h.notifier.sent == []


@pytest.mark.asyncio
async def test_s4_info_no_chunks_e3_without_expand() -> None:
    h, gw, state = _b10("info", [], 0.0)
    out = await _b10_run(h, state)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "no_grounding")
    assert h.audit.events("t1") == [("B9", "no_evidence")]
    assert h.rag.expand_calls == [] and _calls(gw, "b10_answer") == 0


@pytest.mark.asyncio
async def test_s4b_info_high_score_but_no_chunks_is_e3() -> None:
    """`not chunks` là điều kiện riêng (như nhánh B9 cũ): top_score cao mà rỗng chunk vẫn E3."""
    h, _, state = _b10("info", [], 0.99)
    out = await _b10_run(h, state)
    assert (out["exit_code"], h.audit.events("t1")) == ("E3", [("B9", "no_evidence")])


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [None, float("nan")], ids=["thieu", "nan"])
async def test_s1b_info_missing_or_nan_score_is_below_threshold_fail_closed(score: float | None) -> None:
    h, _, state = _b10("info", _top(0.9), score)
    out = await _b10_run(h, state)
    assert (out["exit_code"], h.audit.events("t1")) == ("E3", [("B9", "no_evidence")])


@pytest.mark.asyncio
async def test_s5_info_score_equal_threshold_answers() -> None:
    h, gw, state = _b10("info", _top(THRESHOLD), THRESHOLD)
    out = await _b10_run(h, state)
    assert (out["status"], out["next"]) == (S_CONFIRMING, "confirm_wait")
    assert (_calls(gw, "b10_answer"), len(h.rag.expand_calls)) == (1, 1)
    [row] = h.audit.of("t1", "deflected_info_only")
    assert row["detail"]["grounding"] == {"top_score": THRESHOLD, "above_threshold": True, "kb_gap": False}


@pytest.mark.parametrize(("chunks", "score"), [(_top(LOW), LOW), ([], 0.0)], ids=["s2-diem-thap", "s3-khong-chunk"])
@pytest.mark.asyncio
async def test_s2_s3_action_goes_to_b11_regardless_of_score(chunks: list[ChunkRef], score: float) -> None:
    h, gw, state = _b10("action", chunks, score)
    out = await _b10_run(h, state)
    assert (out["status"], out["next"], out["need_type"]) == (S_RETRIEVING, "b11_slots", "action")
    assert "exit_code" not in out
    [row] = h.audit.rows
    assert (row["step"], row["event"]) == ("B10", "needs_action")
    assert row["detail"]["grounding"] == {"top_score": score, "above_threshold": False, "kb_gap": True}
    assert h.rag.expand_calls == [] and _calls(gw, "b10_answer") == 0


@pytest.mark.asyncio
async def test_s15_flag_on_action_below_threshold_e3_like_3h() -> None:
    h, _, state = _b10("action", _top(LOW), LOW, flag=True)
    out = await _b10_run(h, state)
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"], out["need_type"]) == (
        S_ESCALATED, "E3", "no_grounding", "action",
    )  # fmt: skip
    assert h.audit.events("t1") == [("B9", "no_evidence")]
    assert h.audit.rows[0]["kb_version"] == KBV


@pytest.mark.asyncio
async def test_s15_flag_on_action_above_threshold_still_b11() -> None:
    """Đối chứng cờ (M-S0-8 đảo nghĩa): cờ bật mà điểm đạt → vẫn B11; cờ tắt + điểm thấp → B11 (s2)."""
    h, _, state = _b10("action", _top(THRESHOLD), THRESHOLD, flag=True)
    out = await _b10_run(h, state)
    assert out["next"] == "b11_slots" and "exit_code" not in out


@pytest.mark.asyncio
async def test_s15_flag_comes_from_settings_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).grounding_gate_actions is False  # type: ignore[call-arg]
    monkeypatch.setenv("GROUNDING_GATE_ACTIONS", "true")
    assert Settings(_env_file=None).grounding_gate_actions is True  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_s0p4_llm_error_at_need_type_with_low_score_is_e2_not_e3() -> None:
    """S0-P4: need_type chạy TRƯỚC kiểm ngưỡng → lỗi LLM ở đó là E2 kể cả khi điểm thấp (trước S0: E3 ở B8)."""
    h, _, state = _b10("info", _top(LOW), LOW, b10_need_type=lambda _: Unavailable())
    out = await _b10_run(h, state)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E2", "llm_unavailable")
    assert h.audit.events("t1") == [("B10", "llm_unavailable")]


# ---- B11: s12–s14, M-S0-7, S0-A3 -------------------------------------------------------------------------------------

B6_LAP0342 = {"device_count": 1, "has_registered_device": True, "device_registered": True,
              "device_owner_is_requester": True, "cert_status": "expired", "cert_days_to_expiry": -3,
              "last_connection_ok": False}  # fmt: skip


def _b11_state(ctx: RequesterContext | None = None, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "intent": "vpn",
        "slots": {"device_id": "LAP-0342", "action": "renew_vpn_cert"}, "facts": dict(B6_LAP0342),
        "requester_context": ctx or _ctx(), "redacted_request": RENEW, "clarification_turns": 0,
        "retrieved": _top(LOW), "retrieval_score": LOW, "kb_version": KBV,
    }  # fmt: skip
    base.update(over)
    return base


async def _b11(rag: Any, state: dict[str, Any] | None = None, *, clock: FakeClock | None = None,
               **deps_over: Any) -> tuple[dict[str, Any], GraphHarness]:  # fmt: skip
    clock = clock or FakeClock()
    h = GraphHarness(clock=clock, llm=make_gateway(vpn_scripts(), clock=clock).client, rag=rag)  # type: ignore[arg-type]
    deps = h.deps()
    for k, v in deps_over.items():
        setattr(deps, k, v)
    with _run(h):
        out = await b11_slots.make(deps)(state or _b11_state())
    return out, h


async def _frag(clock: FakeClock | None = None) -> FixtureRag:
    return await fixture_rag([], clock or FakeClock())


@pytest.mark.asyncio
async def test_s12_procedure_in_current_kb_reaches_b12_and_audits_doc() -> None:
    rag = await _frag()
    out, h = await _b11(rag)
    assert (out["status"], out["next"]) == (S_ASSESSING, "b12_assess")
    [row] = h.audit.rows
    assert (row["event"], row["detail"]["procedure_doc"], row["detail"]["procedure_kb_version"]) == (
        "action_built", "KB-VPN-004", KBV,
    )  # fmt: skip
    flt = rag.index.filters[-1]  # procedure_filter: base_filter (enabled + độ nhạy) + doc_id
    keys = {c.key for c in flt.must}  # type: ignore[union-attr]
    assert keys == {"enabled", "sensitivity", "doc_id"}


@pytest.mark.asyncio
async def test_s13_procedure_doc_disabled_in_kb_e3_no_procedure() -> None:
    rag = await _frag()
    assert rag.index.edit_doc(COLL, "KB-VPN-004", enabled=False) > 0
    out, h = await _b11(rag)
    assert (out["status"], out["next"], out["exit_code"], out["escalation_reason_detail"]) == (
        S_ESCALATED, "b20_audit", "E3", "no_procedure",
    )  # fmt: skip
    assert out["intended_action"].type == "renew_vpn_cert"  # L2 thấy hành động dự kiến trong ghi chú bàn giao
    [row] = h.audit.rows
    assert (row["step"], row["event"], row["detail"]["procedure_doc"]) == ("B11", "no_procedure", "KB-VPN-004")
    assert "no_procedure" in REASON_DETAILS


@pytest.mark.asyncio
async def test_m_s0_7_restricted_procedure_employee_e3_l1_passes() -> None:
    """M-S0-7: `procedure_available` phải lọc theo quyền người gửi (`base_filter`) — tài liệu quy trình `restricted` (KB-VPN-007):
    nhân viên → E3 `no_procedure`; L1 (được xem restricted) → qua. Cùng tài liệu, chỉ khác vai trò."""
    meta = dict(get_action_metadata().root["vpn"])
    meta["renew_vpn_cert"] = meta["renew_vpn_cert"].model_copy(update={"procedure_doc": "KB-VPN-007"})
    override: dict[str, Any] = {"action_metadata": {"vpn": meta}}
    out, _ = await _b11(await _frag(), **override)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "no_procedure")
    out, _ = await _b11(await _frag(), _b11_state(_ctx(role="l1")), **override)
    assert out["status"] == S_ASSESSING


@pytest.mark.parametrize("fault", ["qdrant", "alias", "pipeline"])
@pytest.mark.asyncio
async def test_s14_procedure_check_system_error_is_e2_not_e3(fault: str) -> None:
    clock = FakeClock()
    rag = await _frag(clock)
    if fault == "qdrant":
        rag.index.fail_next("scroll_window", VectorStoreTransient("mất kết nối"), times=10)
    elif fault == "alias":
        rag.index.set_alias(ALIAS, None)
    else:
        await rag.index.set_metadata(COLL, {"pipeline_sha": "khac"})
    out, h = await _b11(rag, clock=clock)
    assert (out["exit_code"], out["escalation_reason_detail"], out["retrieval_error"]) == (
        "E2", "rag_system_error", "procedure",
    )  # fmt: skip
    [row] = h.audit.rows
    assert (row["step"], row["event"], row["detail"]["rag_error"]) == ("B11", "rag_system_error", "procedure")


@pytest.mark.asyncio
async def test_s0a3_alias_switched_to_kb_without_procedure_after_b8_is_e3() -> None:
    """Chốt S0-A3: B11 đọc alias HIỆN HÀNH, không dùng `kb_version` ghim ở B8. Ingest mới (alias → collection không còn
    KB-VPN-004) giữa B8 và B11 → E3 `no_procedure`, audit `procedure_kb_version` = bản mới."""
    rag = await _frag()
    rag.index.copy_collection(COLL, f"kb_{NEW_KBV}", drop_doc="KB-VPN-004")
    rag.index.set_alias(ALIAS, f"kb_{NEW_KBV}")
    out, h = await _b11(rag, _b11_state(kb_version=KBV))  # B8 đã ghim bản cũ (có KB-VPN-004)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E3", "no_procedure")
    assert h.audit.rows[0]["detail"]["procedure_kb_version"] == NEW_KBV


@pytest.mark.asyncio
async def test_s0a3_pinned_b8_collection_gone_but_current_alias_has_procedure_passes() -> None:
    """Chiều ngược: bản ghim ở B8 đã bị dọn (hỏi lại lâu, nhiều lần ingest) — B11 không đụng tới nó, alias hiện hành có
    KB-VPN-004 → đi tiếp (không E2 như phương án cũ)."""
    rag = await _frag()
    out, h = await _b11(rag, _b11_state(kb_version="e" * 64))
    assert out["status"] == S_ASSESSING
    assert h.audit.rows[0]["detail"]["procedure_kb_version"] == KBV


@pytest.mark.asyncio
async def test_procedure_check_respects_turn_budget() -> None:
    """Hết hạn cả lượt trong lúc kiểm quy trình → E2 `turn_budget_exceeded` (9.0), không E3/không cho qua."""
    clock = FakeClock()
    rag = await _frag(clock)
    rag.index.delay_next("scroll_window", 1.0)  # giây THẬT (asyncio.timeout) — lâu hơn phần còn lại 0,2 s
    with bind_turn_deadline(TurnDeadline(clock.now() + timedelta(seconds=2.2), 2.0)):
        out, _ = await _b11(rag, clock=clock)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E2", "turn_budget_exceeded")


# ---- Retriever.procedure_available (SpyIndex) ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "role", "ok"),
    [("KB-VPN-004", "employee", True), ("KB-VPN-001", "employee", True), ("KB-VPN-002", "employee", False),
     ("KB-VPN-002", "l1", False), ("KB-VPN-007", "employee", False), ("KB-VPN-007", "l1", True),
     ("KB-VPN-009", "manager", False)],
    ids=["co", "public", "tat-employee", "tat-l1", "restricted-employee", "restricted-l1", "khong-co"],
)  # fmt: skip
@pytest.mark.asyncio
async def test_retriever_procedure_available_filters_like_retrieve(doc: str, role: str, ok: bool) -> None:
    rag = await _frag()
    check = await rag.retriever.procedure_available(doc, _ctx(role=role))
    assert (check.available, check.kb_version) == (ok, KBV)
    assert rag.index.calls["alias_target"] == 1 and rag.index.calls["get_metadata"] == 1  # đường của retrieve
    assert rag.index.calls["scroll_window"] == 1


@pytest.mark.asyncio
async def test_retriever_procedure_errors_carry_stage_procedure() -> None:
    rag = await _frag()
    rag.index.set_alias(ALIAS, None)
    with pytest.raises(RetrievalSystemError) as e:
        await rag.retriever.procedure_available("KB-VPN-004", _ctx())
    assert (e.value.stage, e.value.detail) == ("procedure", "alias")
    rag.index.set_alias(ALIAS, "kb_" + "f" * 64)  # alias trỏ collection không tồn tại
    with pytest.raises(RetrievalSystemError) as e:
        await rag.retriever.procedure_available("KB-VPN-004", _ctx())
    assert e.value.stage == "procedure"


@pytest.mark.asyncio
async def test_retriever_procedure_turn_budget_exhausted_raises() -> None:
    clock = FakeClock()
    rag = await _frag(clock)
    with bind_turn_deadline(TurnDeadline(clock.now() + timedelta(seconds=2.0), 2.0)), \
            pytest.raises(TurnBudgetExceeded):  # fmt: skip
        await rag.retriever.procedure_available("KB-VPN-004", _ctx())


# ---- Graph nodes="real": s2 tới B12, s13 0 ghi 0 phiếu, S0-A1 qua B20 ---------------------------------------------------


def _low_rag(score: float = LOW, **kw: Any) -> FakeRag:
    chunks = _top(score)
    return FakeRag(result=RetrievalResult(chunks=chunks, top_score=score, kb_version=KBV, intent_filter_fallback=False,
                                          fallback_tried=True, retries=0, query_truncated=False), **kw)  # fmt: skip


async def _graph(rag: FakeRag, text: str, *, need: str = "action", **scripts: Script) -> tuple[GraphHarness, dict[str, Any]]:
    clock = FakeClock()
    gw = make_gateway({**vpn_scripts(need=need), **scripts}, clock=clock)  # type: ignore[arg-type]
    h = GraphHarness(clock=clock, nodes="real", llm=gw.client, rag=rag, ad=FakeAd(ad_user("nv001")))
    h.identity.add_session("s-nv001", "nv001", expires_at=clock.now() + timedelta(days=365))
    h.tickets.register("t1", clock.now(), requester_id="nv001")
    values = (await h.runner.submit("t1", session_id="s-nv001", redacted_request=text)).values
    return h, values  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_s2_graph_low_score_action_reaches_b12_not_b9() -> None:
    h, v = await _graph(_low_rag(), RENEW)
    events = h.audit.events("t1")
    assert ("B9", "no_evidence") not in events
    assert ("B10", "needs_action") in events and ("B11", "action_built") in events
    assert any(step == "B13/B14" for step, _ in events)  # tới M5 (luật quyết), không dừng ở B9
    [b8] = h.audit.of("t1", "retrieved")
    assert b8["detail"]["above_threshold"] is False
    assert v["intended_action"].type == "renew_vpn_cert"


@pytest.mark.asyncio
async def test_s13_graph_no_procedure_zero_writes_zero_approvals_handoff() -> None:
    h, v = await _graph(_low_rag(procedures=set()), RENEW)
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E3", "no_procedure")
    assert h.executor.calls["t1"] == 0 and h.deadlines.approvals == {}
    [esc] = h.escalations.of("t1")
    assert (esc["exit_code"], esc["reason_detail"]) == ("E3", "no_procedure")
    done = esc["handoff_note"]["done_so_far"]
    assert "Hành động dự kiến: renew_vpn_cert → device:LAP-0342." in done
    assert BELOW in done  # S0-A1: điểm truy hồi 0,047 < ngưỡng
    [msg] = [m for m in v["conversation"] if m.get("kind") == "escalation"]
    assert msg["text"] == get_escalation_templates().of("E3").user_message  # mẫu tin E3 không đổi


@pytest.mark.asyncio
async def test_q4a1_no_procedure_after_grounded_retrieval_handoff_says_not_grounds() -> None:
    """Q-4a-1: B8 đã tra được KB-VPN-004 ĐẠT ngưỡng (0,9) nhưng KB hiện hành lúc B11 không có quy trình → E3 `no_procedure`;
    ghi chú bàn giao (B20 thật) vẫn in "tra được: KB-VPN-004" nên PHẢI có câu "không phải căn cứ, không làm tay theo tài liệu cũ"."""
    from app.audit.handoff import NO_PROCEDURE_NOTE

    chunk = _ref("KB-VPN-004", 0, 0.9)
    rag = FakeRag(result=RetrievalResult(chunks=[chunk], top_score=0.9, kb_version=KBV, intent_filter_fallback=False,
                                         fallback_tried=False, retries=0, query_truncated=False),
                  procedures=set())  # fmt: skip
    h, v = await _graph(rag, RENEW)
    assert (v["exit_code"], v["escalation_reason_detail"]) == ("E3", "no_procedure")
    note = h.escalations.of("t1")[0]["handoff_note"]
    assert "Tài liệu KB tra được: KB-VPN-004." in note["done_so_far"]
    assert NO_PROCEDURE_NOTE in note["why_escalated"]


@pytest.mark.asyncio
async def test_s0a1_b20_handoff_marks_below_threshold_docs() -> None:
    h, v = await _graph(_low_rag(), QUESTION, need="info")
    assert (v["exit_code"], v["escalation_reason_detail"]) == ("E3", "no_grounding")
    [esc] = h.escalations.of("t1")
    done = esc["handoff_note"]["done_so_far"]
    assert f"{BELOW}: KB-VPN-001, KB-VPN-005." in done and "Tài liệu KB tra được" not in done


@pytest.mark.asyncio
async def test_s0a1_b20_handoff_keeps_old_sentence_above_threshold() -> None:
    """Đạt ngưỡng mà vẫn E3 (B10 không có khối bằng chứng — `FakeRag.evidence` rỗng) → câu cũ "tra được"."""
    h, v = await _graph(_low_rag(0.9), QUESTION, need="info")
    assert (v["exit_code"], v["escalation_reason_detail"]) == ("E3", "no_grounding")
    assert ("B10", "no_evidence") in h.audit.events("t1")
    done = h.escalations.of("t1")[0]["handoff_note"]["done_so_far"]
    assert "Tài liệu KB tra được: KB-VPN-001, KB-VPN-005." in done and "dưới ngưỡng" not in done


# ---- B12: s11 ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "keep"),
    [(THRESHOLD - 0.01, False), (THRESHOLD, True), (THRESHOLD + 0.2, True), (None, False), (float("nan"), False)],
    ids=["duoi", "bang", "tren", "thieu", "nan"],
)
def test_s11_evidence_for_estimator(score: float | None, keep: bool) -> None:
    chunks = _top(0.5)
    assert evidence_for_estimator(chunks, score, THRESHOLD) == (chunks if keep else [])
    assert evidence_for_estimator([], score, THRESHOLD) == []


class RecordingEstimator:
    def __init__(self) -> None:
        self.seen: list[list[ChunkRef]] = []

    async def estimate(self, action: Action, ctx: RiskContext, retrieved: Sequence[ChunkRef]) -> tuple[float, PMethod]:
        self.seen.append(list(retrieved))
        raise LLMUnavailable("estimator giả — chỉ ghi nhận đầu vào")


@pytest.mark.parametrize(("score", "keep"), [(LOW, False), (THRESHOLD, True)], ids=["kb_gap", "dat-nguong"])
@pytest.mark.asyncio
async def test_s11_b12_passes_only_grounded_chunks_to_estimator(score: float, keep: bool) -> None:
    """Không luật nào khớp (máy người khác, trong giờ) → B14. Dưới ngưỡng (`kb_gap`) → estimator nhận `[]` (S0-P9)."""
    meta = get_action_metadata().root["vpn"]["renew_vpn_cert"]
    action = Action(
        type="renew_vpn_cert", target="device:LAP-0417", requested_for="nv001", scope=meta.scope,
        privilege_level=meta.privilege_level, reversible=meta.reversible, reversibility=meta.reversibility,
        data_sensitivity=meta.data_sensitivity, params={"device_id": "LAP-0417"},
        facts={"device_registered": True, "device_owner_is_requester": False, "cert_status": "expired",
               "cert_days_to_expiry": -3},
    )  # fmt: skip
    chunks = _top(score)
    state = {"ticket_id": "t1", "turn_id": "T1", "status": S_ASSESSING, "intent": "vpn", "reasoning_loops": 1,
             "requester_context": _ctx(), "intended_action": action, "ctx_flags": {"target_is_other": True},
             "retrieved": chunks, "retrieval_score": score, "kb_version": KBV}  # fmt: skip
    h = GraphHarness(clock=FakeClock(datetime(2026, 9, 29, 3, 0, tzinfo=UTC)), llm=make_gateway({}).client)
    deps = h.deps()
    spy = RecordingEstimator()
    deps.estimator = spy
    with _run(h):
        out = await b12_assess.make(deps)(state)
    assert out["escalation_reason_detail"] == "llm_layer_disabled"
    assert spy.seen == [chunks if keep else []]


# ---- s6: AST S0-P5 ------------------------------------------------------------------------------------------------------

KB_KEYS = frozenset({"retrieved", "retrieval_score"})
NO_KB_MODULES = [
    "graph/nodes/b11_slots.py", "risk/policy_engine.py", "risk/context.py", "domain/policy.py",
    "graph/nodes/b17_execute.py", *sorted(str(p.relative_to(APP)) for p in (APP / "executor").glob("*.py")),
]  # fmt: skip


def _kb_refs(tree: ast.AST) -> list[ast.AST]:
    return [n for n in ast.walk(tree)
            if (isinstance(n, ast.Constant) and n.value in KB_KEYS) or (isinstance(n, ast.Attribute) and n.attr in KB_KEYS)]  # fmt: skip


def test_s6_rule_layer_b11_b17_executor_never_read_retrieval() -> None:
    """S0-P5: KB (chunk truy hồi, điểm) không là đầu vào lớp luật, B11, B17, executor."""
    assert len(NO_KB_MODULES) >= 4
    for rel in NO_KB_MODULES:
        tree = ast.parse((APP / rel).read_text(encoding="utf-8"))
        assert _kb_refs(tree) == [], rel


def test_s6_b12_reads_retrieval_only_through_evidence_for_estimator() -> None:
    tree = ast.parse((APP / "graph/nodes/b12_assess.py").read_text(encoding="utf-8"))
    allowed = {id(n) for c in ast.walk(tree)
               if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "evidence_for_estimator"
               for arg in c.args for n in ast.walk(arg)}  # fmt: skip
    refs = _kb_refs(tree)
    assert refs, "B12 phải đọc retrieved qua evidence_for_estimator"
    assert all(id(n) in allowed for n in refs), [ast.unparse(n) for n in refs if id(n) not in allowed]


# ---- Wiring: Retriever THẬT, cờ từ Settings; FakeRag không vào app/ ------------------------------------------------------


@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.asyncio
async def test_wiring_open_runtime_uses_real_retriever_and_flag_from_settings(
    monkeypatch: pytest.MonkeyPatch, flag: bool
) -> None:
    from app.db.session import create_engines
    from app.graph import wiring
    from langgraph.checkpoint.memory import InMemorySaver
    from pydantic import SecretStr

    @asynccontextmanager
    async def memory_saver(*_: Any, **__: Any) -> AsyncIterator[InMemorySaver]:
        yield InMemorySaver()

    captured: list[Any] = []
    real_select = wiring.select_nodes

    def spy_select(settings: Settings, deps: Any) -> Any:
        captured.append(deps)
        return real_select(settings, deps)

    monkeypatch.setattr(wiring, "open_postgres_saver", memory_saver)
    monkeypatch.setattr(wiring, "select_nodes", spy_select)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, app_env="dev", llm_backend="scripted", ml_service_token=SecretStr("t" * 32),
        database_url="postgresql+psycopg://x@127.0.0.1:1/khong_co", grounding_gate_actions=flag,
    )
    engines = create_engines(settings)
    try:
        async with wiring.open_runtime(settings, engines, FakeClock(), can_execute=False):
            pass
    finally:
        await engines.dispose()
    [deps] = captured
    assert type(deps.rag) is Retriever and type(deps.rag).__module__ == "app.rag.retriever"
    assert deps.grounding_gate_actions is flag


def test_wiring_app_never_imports_test_fakes() -> None:
    """FakeRag (FakeMl, ScriptedLLM giả…) chỉ ở `tests/` — không module nào trong `app/` import `tests` hay nhắc `FakeRag`."""
    files = sorted(APP.rglob("*.py"))
    assert len(files) > 100
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not any(m == "tests" or m.startswith("tests.") for m in mods), path
        assert not any(isinstance(n, ast.Name) and n.id == "FakeRag" for n in ast.walk(tree)), path


# ---- make ingest: cảnh báo procedure_doc (S0-P10) — không chặn ----------------------------------------------------------


def _fixture_docs() -> list[Any]:
    from app.rag.ingest.loader import load_kb
    from tests.fakes.kb import FIXTURE_KB, KB_TEST_NOW

    docs, issues = load_kb(FIXTURE_KB, FakeClock(KB_TEST_NOW))
    assert issues == []
    return docs


def test_ingest_procedure_warnings_repo_config_on_fixture_kb_is_clean() -> None:
    """Phase 5 T22a 4.7b: KB fixture chỉ có VPN → VPN sạch (0 dòng `vpn/`); 6 hành động khai báo (chưa bật) cảnh báo ĐÚNG 6 dòng,
    mỗi mã bảng 4.2 [Chốt 09/10] một dòng (hàm gộp theo `doc_id` — 6 hành động 6 mã khác nhau). KB thật có K2 → 0 dòng."""
    from app.rag.ingest.procedures import procedure_warnings

    lines = procedure_warnings(_fixture_docs(), get_action_metadata().root)
    assert not [line for line in lines if "vpn/" in line]
    expected = {
        "KB-ACC-001": "account/reset_password", "KB-ACC-002": "account/unlock_account",
        "KB-SW-001": "software/install_software", "KB-ACS-005": "access/view_permissions",
        "KB-ACS-001": "access/grant_permission", "KB-ACS-003": "access/extend_permission",
    }  # fmt: skip
    assert len(lines) == 6
    for doc_id, action in expected.items():
        assert [line for line in lines if f"procedure_doc {doc_id} ({action}) không có trong KB" in line], doc_id


def test_ingest_procedure_warnings_missing_disabled_restricted() -> None:
    from app.rag.ingest.procedures import procedure_warnings

    base = get_action_metadata().root["vpn"]
    meta = {"vpn": {"renew_vpn_cert": base["renew_vpn_cert"].model_copy(update={"procedure_doc": "KB-VPN-009"}),
                    "reissue_vpn_access": base["reissue_vpn_access"].model_copy(update={"procedure_doc": "KB-VPN-002"}),
                    "check_vpn_status": base["check_vpn_status"].model_copy(update={"procedure_doc": "KB-VPN-007"})}}  # fmt: skip
    lines = procedure_warnings(_fixture_docs(), meta)
    assert len(lines) == 3 and all(line.startswith("cảnh báo: procedure_doc KB-VPN-00") for line in lines)
    assert "KB-VPN-002 (vpn/reissue_vpn_access) enabled=false" in lines[0]
    assert "KB-VPN-007 (vpn/check_vpn_status) sensitivity=restricted" in lines[1]
    assert "KB-VPN-009 (vpn/renew_vpn_cert) không có trong KB" in lines[2]


@pytest.mark.asyncio
async def test_ingest_prints_procedure_warning_without_blocking(tmp_path: Path) -> None:
    """Cảnh báo in ra stderr ở bước 3 rồi ingest ĐI TIẾP (ở đây dừng ở bước 4 vì repo giả lỗi — không phải vì cảnh báo)."""
    import io
    import shutil
    from typing import cast

    from app.rag.ingest.pipeline import IngestDeps, IngestOptions, run_ingest
    from sqlalchemy.exc import OperationalError
    from tests.fakes.kb import CONFIG_DIR, FIXTURE_KB, KB_TEST_NOW

    cfg = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, cfg)
    meta = cfg / "action_metadata.yaml"
    meta.write_text(meta.read_text(encoding="utf-8").replace("procedure_doc: KB-VPN-001", "procedure_doc: KB-VPN-009"),
                    encoding="utf-8")  # fmt: skip

    class _Repo:
        async def doc_rows(self, keys: Any) -> Any:
            raise OperationalError("SELECT", {}, Exception("db giả tắt"))

    unused = cast(Any, None)
    out, err = io.StringIO(), io.StringIO()
    deps = IngestDeps(index=unused, ml=unused, counter=unused, repo=cast(Any, _Repo()), clock=FakeClock(KB_TEST_NOW),
                      app_env="test", retrieval_threshold=0.6, keep_old=2, config_dir=cfg, out=out, err=err,
                      rag=unused)  # fmt: skip
    assert await run_ingest(IngestOptions(FIXTURE_KB, dry_run=True), deps) == 1
    lines = err.getvalue().splitlines()
    # T22a 4.7b: thêm cảnh báo của 6 hành động mới (KB fixture chỉ VPN) → tìm dòng VPN-009, không ghim vị trí
    assert [line for line in lines if line.startswith("cảnh báo: procedure_doc KB-VPN-009 (vpn/check_vpn_status) không có trong KB")]
    assert "bước 4: đọc kb_documents lỗi" in err.getvalue()  # dừng vì repo giả, sau cảnh báo
