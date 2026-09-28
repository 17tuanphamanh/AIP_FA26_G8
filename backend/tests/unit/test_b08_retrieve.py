"""Node B8–B9 thật (Phase 3 chặng 3c, thiết kế mục 6.8) — kiểm cơ chế node (goto, audit, exit_code, không
`except Exception`) với `FakeRag`. Chất lượng truy hồi thật: `test_rag_retriever.py` (S5), tích hợp Qdrant
thật `integration/test_b08_pg.py` (S10, c5, c19)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.domain.ticket_state import ChunkRef
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b08_retrieve
from app.rag.models import RetrievalSystemError
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.rag import FakeRag

pytestmark = pytest.mark.asyncio


@contextmanager
def run(audit: MemoryAudit) -> Iterator[RunContext]:
    ctx = RunContext(turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(),
                     spans=MemorySpans(), clock=FakeClock())  # fmt: skip
    with bind_run(ctx):
        yield ctx


def _ctx() -> RequesterContext:
    return RequesterContext(
        user_id="u1", role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=10, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def _state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "redacted_request": "vpn lỗi 809",
        "intent": "vpn", "slots": {}, "requester_context": _ctx(),
    }
    base.update(over)
    return base


def _chunk() -> ChunkRef:
    return ChunkRef(chunk_id="KB-VPN-001#v1#0", doc_id="KB-VPN-001", version=1, seq=0, title="T",
                    heading_path="H", score=0.9, excerpt="dùng cổng 809")  # fmt: skip


def _harness_with_rag(rag: FakeRag) -> GraphHarness:
    h = GraphHarness()
    h.rag = rag
    return h


# ---- c15 (node): top_score đúng bằng ngưỡng → vẫn qua B10 (không phải "<") ------------------------


async def test_c15_node_top_score_equal_threshold_routes_to_b10() -> None:
    h = _harness_with_rag(FakeRag())
    threshold = h.deps().constants.RETRIEVAL_THRESHOLD
    from app.rag.models import RetrievalResult

    h.rag.result = RetrievalResult(
        chunks=[_chunk()], top_score=threshold, kb_version="a" * 64, intent_filter_fallback=False,
        fallback_tried=False, retries=0, query_truncated=False,
    )  # fmt: skip
    deps = h.deps()
    audit = MemoryAudit()
    with run(audit):
        out = await b08_retrieve.make(deps)(_state())
    assert (out["status"], out["next"]) == (S_RETRIEVING, "b10_route")
    assert [c.chunk_id for c in out["retrieved"]] == ["KB-VPN-001#v1#0"]
    assert audit.events("t1") == [("B8", "retrieved")]
    assert len(h.rag.retrieve_calls) == 1  # node thật gọi rag, không đọc deps.scenario


async def test_node_empty_chunks_gives_e3_even_with_high_top_score() -> None:
    """`not res.chunks` là điều kiện riêng — top_score cao mà rỗng chunk vẫn phải E3 (không có gì để trả)."""
    from app.rag.models import RetrievalResult

    h = _harness_with_rag(FakeRag(result=RetrievalResult(
        chunks=[], top_score=0.99, kb_version="a" * 64, intent_filter_fallback=False,
        fallback_tried=False, retries=0, query_truncated=False,
    )))  # fmt: skip
    deps = h.deps()
    audit = MemoryAudit()
    with run(audit):
        out = await b08_retrieve.make(deps)(_state())
    assert (out["status"], out["exit_code"]) == (S_ESCALATED, "E3")
    assert audit.events("t1") == [("B9", "no_evidence")]


async def test_node_chunks_below_threshold_gives_e3() -> None:
    """S14: nhánh E3 thứ hai — CÓ chunk nhưng top_score < ngưỡng (khác nhánh rỗng ở test trên)."""
    from app.rag.models import RetrievalResult

    h = _harness_with_rag(FakeRag())
    threshold = h.deps().constants.RETRIEVAL_THRESHOLD
    h.rag.result = RetrievalResult(
        chunks=[_chunk()], top_score=threshold - 0.01, kb_version="a" * 64, intent_filter_fallback=False,
        fallback_tried=True, retries=0, query_truncated=False,
    )  # fmt: skip
    audit = MemoryAudit()
    with run(audit):
        out = await b08_retrieve.make(h.deps())(_state())
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E3", "no_grounding")
    assert audit.events("t1") == [("B9", "no_evidence")]


async def test_point3_query_comes_from_redacted_request_only() -> None:
    """Điểm log 3 (spec 3.6) và câu gửi RAG lấy từ `state["redacted_request"]` — không từ bất kỳ khoá nào khác
    (khoá mồi `raw_request` chứa PII không được lọt vào audit lẫn truy vấn)."""
    from app.rag.models import RetrievalResult

    h = _harness_with_rag(FakeRag(result=RetrievalResult(
        chunks=[_chunk()], top_score=0.9, kb_version="a" * 64, intent_filter_fallback=False,
        fallback_tried=False, retries=0, query_truncated=False,
    )))  # fmt: skip
    pii = "an.nv@congty.vn 0912345678"
    audit = MemoryAudit()
    with run(audit):
        await b08_retrieve.make(h.deps())(
            _state(redacted_request="vpn lỗi 809 của <EMAIL> <PHONE>", raw_request=f"vpn lỗi 809 của {pii}")
        )
    [row] = audit.rows
    assert row["detail"]["query"] == "vpn lỗi 809 của <EMAIL> <PHONE>"
    assert h.rag.retrieve_calls[0][0].text == "vpn lỗi 809 của <EMAIL> <PHONE>"
    assert "an.nv@congty.vn" not in str(row) and "0912345678" not in str(row)


# ---- c18: RetrievalSystemError → đúng 1 dòng audit điểm 3, state đúng, exit_code E2 ---------------


async def test_c18_retrieval_system_error_gives_single_e2_audit_row() -> None:
    err = RetrievalSystemError("search", 2, kb_version=None, detail="ConnectError: mất kết nối")
    h = _harness_with_rag(FakeRag(error=err))
    deps = h.deps()
    audit = MemoryAudit()
    with run(audit):
        out = await b08_retrieve.make(deps)(_state())
    assert (out["status"], out["exit_code"]) == (S_ESCALATED, "E2")
    assert (out["retrieval_error"], out["tool_retry_count"]) == ("search", 2)
    assert out["escalation_reason_detail"] == "rag_system_error"
    assert out["kb_version"] is None
    [row] = audit.rows
    assert (row["step"], row["event"]) == ("B8", "retrieval_error")
    assert row["detail"]["error_stage"] == "search"
    assert row["detail"]["retrieval_error"] == "ConnectError: mất kết nối"
    assert row["detail"]["query"] == "vpn lỗi 809"  # điểm log 3: query = redacted_request đã che (không phải lỗi)
    assert "vpn lỗi 809" not in row["detail"]["retrieval_error"]  # detail lỗi KHÔNG được chứa câu truy vấn


async def test_node_does_not_catch_exceptions_other_than_retrieval_system_error() -> None:
    """Node KHÔNG `except Exception` — lỗi khác (vd hợp đồng ml) phải nổi thẳng lên (boundary → E9)."""

    class _Boom(FakeRag):
        async def retrieve(self, *a: Any, **kw: Any) -> Any:  # type: ignore[override]
            raise ValueError("lỗi không lường trước")

    h = _harness_with_rag(_Boom())
    deps = h.deps()
    audit = MemoryAudit()
    with run(audit), pytest.raises(ValueError, match="lỗi không lường trước"):
        await b08_retrieve.make(deps)(_state())
    assert audit.rows == []
