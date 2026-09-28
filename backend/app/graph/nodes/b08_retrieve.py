"""B8–B9 — node THẬT (Phase 3 chặng 3c, thiết kế mục 6.8). Node giả (Phase 2, `FAKE_SCENARIO`):
`graph/nodes/fake/b08_retrieve.py`.

- Chỉ bắt `RetrievalSystemError` (E2). **Không** `except Exception` — `MlContractError`, `ChunkTruncatedError`,
  `VectorStoreError`, `KeyError` (payload thiếu key) nổi lên boundary → E9.
- Giữ tên event cũ (`retrieval_error`, `no_evidence`, `retrieved`) — audit Phase 2 và test B20 không đổi.
- `RETRIEVAL_THRESHOLD` đọc từ `deps.constants` (không đọc file trong node). `retrieved` là `list[ChunkRef]`
  (không `model_dump`) — `RetrievalResult` của `rag` chỉ là giá trị trả về, KHÔNG vào state.
- Node thật không gọi `deps.scenario`. Thông báo người dùng E2/E3 do B20 gửi (B8 không tự gửi).
"""

from typing import Any

from app.domain.exit_codes import ExitCode
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.rag.models import RetrievalQuery, RetrievalResult, RetrievalSystemError
from app.rag.query import build_query


def point3(q: RetrievalQuery, *, result: RetrievalResult | None = None,
          error: RetrievalSystemError | None = None) -> dict[str, Any]:  # fmt: skip
    """Điểm log 3 (mục 3.6) — `query` là `redacted_request` đã che (+ `error_code`), không phải câu gốc;
    `detail`/`error.detail` không chứa câu truy vấn."""
    return {
        "query": q.text[:500],
        "query_truncated": result.query_truncated if result else None,
        "top_score": result.top_score if result else None,
        "doc_ids": [c.doc_id for c in result.chunks] if result else [],
        "chunk_ids": [c.chunk_id for c in result.chunks] if result else [],
        "kb_version": result.kb_version if result else (error.kb_version if error else None),
        "intent_filter_fallback": result.intent_filter_fallback if result else None,
        "fallback_tried": result.fallback_tried if result else None,
        "retrieval_error": error.detail if error else None,
        "error_stage": error.stage if error else None,
        "tool_retry_count": result.retries if result else (error.retries if error else None),
    }


def make(deps: NodeDeps) -> NodeFn:
    async def b08_retrieve(state: Any) -> dict[str, Any]:
        q = build_query(
            state["redacted_request"], state.get("intent"), state.get("slots") or {},
            query_slots=deps.query_slots,
        )  # fmt: skip
        ctx = state["requester_context"]
        try:
            res = await deps.rag.retrieve(q, ctx)
        except RetrievalSystemError as e:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B8", event="retrieval_error",
                exit_code=ExitCode.E2.value, retrieval_error=e.stage, tool_retry_count=e.retries,
                kb_version=e.kb_version, escalation_reason_detail="rag_system_error",
                audit_detail=point3(q, error=e),
            )  # fmt: skip
        if not res.chunks or res.top_score < deps.constants.RETRIEVAL_THRESHOLD:  # B9
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B9", event="no_evidence",
                exit_code=ExitCode.E3.value, retrieval_score=res.top_score, kb_version=res.kb_version,
                tool_retry_count=res.retries, escalation_reason_detail="no_grounding",
                audit_detail=point3(q, result=res),
            )  # fmt: skip
        return await goto(
            state, S_RETRIEVING, next_node="b10_route", step="B8", event="retrieved",
            retrieved=res.chunks, retrieval_score=res.top_score, kb_version=res.kb_version,
            intent_filter_fallback=res.intent_filter_fallback, tool_retry_count=res.retries,
            audit_detail=point3(q, result=res),
        )  # fmt: skip

    return b08_retrieve
