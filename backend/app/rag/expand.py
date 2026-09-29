"""`expand_for_answer` [D-24 + 3-Q5, 3-Q14] — ghép chunk liền kề (`neighbor_window`) quanh mỗi chunk trúng để trả
lời có đủ ngữ cảnh, CÙNG collection với lượt truy hồi vừa xong (không đọc lại alias — 3-Q14: tránh đọc bản KB khác
giữa `retrieve` và `expand`, xem c16).

Thân của `Retriever.expand_for_answer` (PLAN-3c mục 2 tách file) — nhận thẳng instance `Retriever` để dùng lại
`_call`/`RagConfig`/`clock` của nó (một nơi retry Qdrant duy nhất), không lặp logic. Import `_Counter`, `_Transient`,
`content_of` ngược từ `retriever.py`; module đó chỉ nạp `expand` muộn (trong hàm), nên không vòng lúc nạp module.
"""

import asyncio
from typing import TYPE_CHECKING

from qdrant_client.models import FieldCondition, MatchValue, Range

from app.core.turn_budget import TurnBudgetExceeded, window
from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef
from app.rag.filters import query_filter
from app.rag.models import EvidenceBlock, RetrievalSystemError
from app.rag.retriever import _Counter, _Transient, content_of
from app.rag.vector_store import CollectionNotFound

if TYPE_CHECKING:
    from app.rag.retriever import Retriever


async def expand(
    retriever: "Retriever",
    chunks: list[ChunkRef],
    ctx: RequesterContext,
    *,
    kb_version: str,
    max_tokens: int | None = None,
) -> list[EvidenceBlock]:
    coll = f"kb_{kb_version}"
    cfg = retriever._cfg
    retries = _Counter()
    limit_s, turn_bound = window(cfg.deadline_s, retriever._clock, what="rag:expand")  # 9.0
    try:
        async with asyncio.timeout(limit_s):
            blocks: list[EvidenceBlock] = []
            for c in chunks:  # giữ thứ tự đầu vào = thứ tự điểm giảm dần
                w = cfg.neighbor_window
                flt = query_filter(
                    ctx.role,
                    FieldCondition(key="doc_id", match=MatchValue(value=c.doc_id)),
                    FieldCondition(key="seq", range=Range(gte=c.seq - w, lte=c.seq + w)),
                )
                try:
                    pts = await retriever._call(
                        retriever._index.scroll_window, coll, flt, 2 * w + 1, retries=retries
                    )
                except CollectionNotFound:
                    raise RetrievalSystemError("expand", retries.total, kb_version=kb_version) from None
                except _Transient as e:
                    raise RetrievalSystemError(
                        "expand", retries.total, kb_version=kb_version, detail=str(e)
                    ) from e
                pts = sorted(pts, key=lambda p: (p.payload or {})["seq"])
                blocks.append(
                    EvidenceBlock(
                        anchor_chunk_id=c.chunk_id,
                        doc_id=c.doc_id,
                        title=c.title,
                        heading_path=c.heading_path,
                        score=c.score,
                        text="\n\n".join(content_of(p.payload or {}) for p in pts),
                        tokens=sum((p.payload or {})["token_count"] for p in pts),
                    )
                )
            return trim_to_budget(blocks, max_tokens or cfg.evidence_max_tokens)
    except TimeoutError:
        if turn_bound:  # hết khung vì hạn cả lượt (9.0), không phải vì expand chậm quá rag_deadline_s
            raise TurnBudgetExceeded("rag:expand") from None
        raise RetrievalSystemError("expand", retries.total, kb_version=kb_version, detail="deadline") from None


def trim_to_budget(blocks: list[EvidenceBlock], max_tokens: int) -> list[EvidenceBlock]:
    """Bỏ khối CUỐI (điểm thấp nhất) trước, tới khi tổng `tokens` ≤ `max_tokens`; không bao giờ bỏ khối đầu
    (kể cả khi riêng nó đã vượt ngân sách)."""
    out = list(blocks)
    while len(out) > 1 and sum(b.tokens for b in out) > max_tokens:
        out.pop()
    return out
