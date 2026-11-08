"""B8 — node THẬT (Phase 3 chặng 3c, thiết kế mục 6.8; Phase 4 S0-P1). Node giả (Phase 2, `FAKE_SCENARIO`):
`graph/nodes/fake/b08_retrieve.py` (giữ nhánh B9 cũ cho gate2).

- Chỉ bắt `RetrievalSystemError` (E2 `rag_system_error`). **Không** `except Exception` — `MlContractError`,
  `ChunkTruncatedError`, `VectorStoreError`, `KeyError` (payload thiếu key) nổi lên boundary → E9.
- **S0-P1 (Q-4-U A+, D-34):** B8 KHÔNG còn nhánh B9. RAG không lỗi (kể cả rỗng, điểm thấp) → luôn `b10_route` với
  `retrieved`/`retrieval_score`/`kb_version`; điểm log 3 thêm `above_threshold`. Cổng độ liên quan (B9) chỉ áp cho câu TRẢ LỜI
  và chạy ở `b10_route` SAU `b10_need_type` (step `B9`, event `no_evidence`, E3 `no_grounding` — y hệt nhánh cũ). Chunk dưới
  ngưỡng nằm trong state nhưng không bao giờ là căn cứ: B10 chặn trả lời, B12 chỉ đưa estimator qua `evidence_for_estimator`.
- `RETRIEVAL_THRESHOLD` đọc từ `deps.constants` (không đọc file trong node). `retrieved` là `list[ChunkRef]`
  (không `model_dump`) — `RetrievalResult` của `rag` chỉ là giá trị trả về, KHÔNG vào state.
- R2: điểm log 3 thêm `embed_truncated` (bool — cờ `truncated` của embed câu truy vấn, như ingest kiểm; CHỈ GHI, không chặn, không đổi
  điểm/top-5). `query_truncated` vẫn là cờ của reranker (câu bị cắt ở 128 token).
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


def point3(q: RetrievalQuery, *, result: RetrievalResult | None = None, threshold: float | None = None,
           error: RetrievalSystemError | None = None) -> dict[str, Any]:  # fmt: skip
    """Điểm log 3 (mục 3.6) — `query` là `redacted_request` đã che (+ `error_code`), không phải câu gốc;
    `detail`/`error.detail` không chứa câu truy vấn. `above_threshold` (S0-P1): có chunk và `top_score` ≥ ngưỡng."""
    return {
        "query": q.text[:500],
        "query_truncated": result.query_truncated if result else None,
        "embed_truncated": result.embed_truncated if result else None,  # R2: cờ embed câu truy vấn (chỉ ghi)
        "top_score": result.top_score if result else None,
        "above_threshold": (bool(result.chunks) and result.top_score >= threshold)
        if result is not None and threshold is not None else None,
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
        return await goto(  # S0-P1: không còn nhánh B9 ở đây — B10 áp ngưỡng sau khi biết need_type
            state, S_RETRIEVING, next_node="b10_route", step="B8", event="retrieved",
            retrieved=res.chunks, retrieval_score=res.top_score, kb_version=res.kb_version,
            intent_filter_fallback=res.intent_filter_fallback, tool_retry_count=res.retries,
            audit_detail=point3(q, result=res, threshold=deps.constants.RETRIEVAL_THRESHOLD),
        )  # fmt: skip

    return b08_retrieve
