"""KB fixture (`tests/fixtures/kb`) đã chunk, cho test B10 (PLAN-3g S4): TC04/TC05 (g5, g6), g26 (output guard không chặn nhầm
chunk KB).

- `fixture_chunks()`: mọi tài liệu fixture (kể cả `enabled=false`) chunk bằng chunker THẬT + `WordCounter` (không cần
  tokenizer thật — ranh giới chunk khác chút so với bge-m3, không sao: test kiểm cơ chế, không kiểm chất lượng truy hồi).
- `FixtureRag` (`RagPort`): `retrieve` trả top-N cố định (test chọn `chunk_id`); `expand_for_answer` là
  `Retriever.expand_for_answer` THẬT trên `SpyIndex` chứa mọi chunk với payload như ingest (lọc quyền `base_filter` thật,
  cửa sổ ±`RAG_NEIGHBOR_WINDOW`). `procedure_available` (Phase 4 S0-P10) cũng là `Retriever` THẬT: alias `kb_current` →
  `COLL` (đổi được bằng `index.set_alias`), `procedure_filter` thật — KB-VPN-002 `enabled=false`, KB-VPN-007 `restricted`.
"""

from dataclasses import dataclass, field

from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef
from app.rag.bm25 import load_lexicon
from app.rag.ingest.chunker import chunk_doc
from app.rag.ingest.config import ALIAS
from app.rag.ingest.loader import load_kb
from app.rag.models import (
    Chunk,
    Doc,
    EvidenceBlock,
    ProcedureCheck,
    RetrievalQuery,
    RetrievalResult,
)
from app.rag.retriever import RagConfig, Retriever
from app.settings import get_settings
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.kb import FIXTURE_KB, KB_TEST_NOW
from tests.fakes.rag import SpyIndex, SpyPoint
from tests.fakes.token_counter import WordCounter

KBV = "b" * 64  # kb_version giả của collection fixture
COLL = f"kb_{KBV}"


async def fixture_chunks() -> dict[str, tuple[Doc, Chunk]]:
    docs, issues = load_kb(FIXTURE_KB, FakeClock(KB_TEST_NOW))
    assert issues == [], issues
    out: dict[str, tuple[Doc, Chunk]] = {}
    for doc in docs:
        for c in await chunk_doc(doc, WordCounter()):
            out[c.chunk_id] = (doc, c)
    assert len(out) >= 20  # 3.9: danh sách quét không rỗng
    return out


def chunk_ref(doc: Doc, c: Chunk, score: float) -> ChunkRef:
    return ChunkRef(chunk_id=c.chunk_id, doc_id=doc.fm.doc_id, version=doc.fm.version, seq=c.seq, title=doc.fm.title,
                    heading_path=c.heading_path, score=score, excerpt=c.content[:600])  # fmt: skip


def _payload(doc: Doc, c: Chunk) -> dict[str, object]:
    fm = doc.fm  # như `rag/ingest/pipeline._payload`
    return {"chunk_id": c.chunk_id, "doc_id": fm.doc_id, "version": fm.version, "seq": c.seq, "title": fm.title,
            "heading_path": c.heading_path, "request_type": fm.request_type, "doc_type": fm.doc_type,
            "sensitivity": fm.sensitivity, "enabled": fm.enabled, "distractor": fm.distractor, "text": c.text,
            "token_count": c.text_tokens, "kb_version": KBV, "owner": fm.owner}  # fmt: skip


@dataclass
class FixtureRag:
    top: list[ChunkRef]
    retriever: Retriever
    index: SpyIndex
    expand_calls: list[list[ChunkRef]] = field(default_factory=list)

    async def retrieve(
        self, q: RetrievalQuery, ctx: RequesterContext, *, collection: str | None = None
    ) -> RetrievalResult:
        return RetrievalResult(chunks=self.top, top_score=self.top[0].score, kb_version=KBV,
                               intent_filter_fallback=False, fallback_tried=False, retries=0,
                               query_truncated=False)  # fmt: skip

    async def expand_for_answer(
        self, chunks: list[ChunkRef], ctx: RequesterContext, *, kb_version: str, max_tokens: int | None = None
    ) -> list[EvidenceBlock]:
        self.expand_calls.append(list(chunks))
        return await self.retriever.expand_for_answer(chunks, ctx, kb_version=kb_version, max_tokens=max_tokens)

    async def procedure_available(self, doc_id: str, ctx: RequesterContext) -> ProcedureCheck:
        return await self.retriever.procedure_available(doc_id, ctx)


async def fixture_rag(top_ids: list[str], clock: FakeClock, *, evidence_max_tokens: int = 4000) -> FixtureRag:
    """`top_ids` theo thứ tự điểm giảm dần (0,95; 0,90; …)."""
    chunks = await fixture_chunks()
    index = SpyIndex()
    index.add_collection(COLL, metadata={"pipeline_sha": "p" * 64})
    index.add_points(COLL, [SpyPoint(id=cid, payload=_payload(d, c)) for cid, (d, c) in chunks.items()])
    index.set_alias(ALIAS, COLL)  # procedure_available đọc alias hiện hành (S0-A3)
    cfg = RagConfig(prefetch_k=20, rerank_k=20, top_n=5, intent_fallback=True, neighbor_window=1,
                    evidence_max_tokens=evidence_max_tokens, deadline_s=50.0)  # fmt: skip
    retriever = Retriever(index, FakeMlService().client(clock), cfg, threshold=0.6, pipeline_sha="p" * 64,
                          lexicon=load_lexicon(get_settings().config_dir), clock=clock)  # fmt: skip
    top = [chunk_ref(*chunks[cid], score=0.95 - 0.05 * i) for i, cid in enumerate(top_ids)]
    return FixtureRag(top, retriever, index)
