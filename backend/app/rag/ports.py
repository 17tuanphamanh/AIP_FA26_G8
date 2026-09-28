"""Port của RAG cho node `b08_retrieve` (thiết kế Phase 3 mục 6.2, 6.3). Bản thật: `rag.retriever.Retriever`
(S5), dựng ở `graph/wiring.py`. Bản giả test: `tests/fakes/rag.py::FakeRag` (S5)."""

from typing import Protocol

from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef
from app.rag.models import EvidenceBlock, RetrievalQuery, RetrievalResult


class RagPort(Protocol):
    async def retrieve(
        self, q: RetrievalQuery, ctx: RequesterContext, *, collection: str | None = None
    ) -> RetrievalResult: ...

    async def expand_for_answer(
        self, chunks: list[ChunkRef], ctx: RequesterContext, *, kb_version: str, max_tokens: int | None = None
    ) -> list[EvidenceBlock]: ...
