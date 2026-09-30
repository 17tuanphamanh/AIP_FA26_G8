"""Port của RAG cho node `b08_retrieve` (thiết kế Phase 3 mục 6.2, 6.3), `b10_route` (`expand_for_answer`) và `b11_slots`
(`procedure_available`, Phase 4 S0-P10). Bản thật: `rag.retriever.Retriever` (S5), dựng ở `graph/wiring.py`. Bản giả test:
`tests/fakes/rag.py::FakeRag` (S5) — chỉ nằm trong `tests/`."""

from typing import Protocol

from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef
from app.rag.models import (
    EvidenceBlock,
    ProcedureCheck,
    RetrievalQuery,
    RetrievalResult,
)


class RagPort(Protocol):
    async def retrieve(
        self, q: RetrievalQuery, ctx: RequesterContext, *, collection: str | None = None
    ) -> RetrievalResult: ...

    async def expand_for_answer(
        self, chunks: list[ChunkRef], ctx: RequesterContext, *, kb_version: str, max_tokens: int | None = None
    ) -> list[EvidenceBlock]: ...

    async def procedure_available(self, doc_id: str, ctx: RequesterContext) -> ProcedureCheck:
        """Tài liệu quy trình `doc_id` có trong KB HIỆN HÀNH (alias tại lúc gọi), enabled, `ctx.role` được xem. Lỗi hệ thống
        (alias, pipeline, Qdrant, hết `rag_deadline_s`) → `RetrievalSystemError` stage `"procedure"` (E2, không phải E3)."""
        ...
