"""`graph/tracing.trace_parent` — nguồn trace graph tiêm vào LLM gateway (PLAN-3d Q-3d-2), và `NodeDeps.llm` (S5)."""

from typing import Any

import pytest
from app.core.clock import FakeClock
from app.graph.context import RunContext, bind_run
from app.graph.tracing import trace_parent, traced
from app.llm.ports import TraceParent
from app.llm.schemas import NeedTypeOut
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.llm import make_gateway
from tests.fakes.scripted_llm import Reply, ScriptExhausted


def _ctx(spans: MemorySpans) -> RunContext:
    return RunContext(turn_id="T1", trace_id="a" * 32, audit=MemoryAudit(), effects=MemoryEffects(), spans=spans,
                      clock=FakeClock(), txlog=MemoryTxLog())  # fmt: skip


def test_outside_graph_turn_is_none() -> None:
    assert trace_parent() is None


@pytest.mark.asyncio
async def test_inside_traced_node_gives_turn_trace_and_node_span() -> None:
    spans = MemorySpans()
    gw = make_gateway({"b10_need_type": [Reply({"type": "info", "confidence": 0.5})]}, trace=trace_parent)
    seen: list[TraceParent | None] = []

    async def node(state: Any) -> dict[str, Any]:
        seen.append(trace_parent())
        await gw.client.complete("fast", "b10_need_type", {"text": "x", "evidence_titles": []}, NeedTypeOut)
        return {}

    with bind_run(_ctx(spans)):
        assert trace_parent() == TraceParent("T1", "a" * 32, None)  # trong lượt, ngoài node: chưa có span cha
        await traced("b10_route", node)({})
    (node_span,) = spans.spans
    assert seen == [TraceParent("T1", "a" * 32, node_span.span_id)]
    (llm_span,) = gw.store.spans
    assert (llm_span.turn_id, llm_span.trace_id, llm_span.parent_span_id) == ("T1", "a" * 32, node_span.span_id)


@pytest.mark.asyncio
async def test_graph_harness_default_llm_is_real_gateway_without_scripts() -> None:
    deps = GraphHarness().deps()
    with pytest.raises(ScriptExhausted):  # node gọi LLM mà test chưa cấp kịch bản → E9 (không trả mặc định)
        await deps.llm.complete("fast", "b10_need_type", {"text": "x", "evidence_titles": []}, NeedTypeOut)
