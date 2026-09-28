"""`expand_for_answer` / `trim_to_budget` (thiết kế Phase 3 mục 6.7, D-24; PLAN-3c mục 3.4, 7).

c8 (lọc quyền trên dữ liệu thật, Qdrant) ở `integration/test_b08_pg.py` (S10). File này: phần `expand` của c26
(`scroll_window` → `CollectionNotFound`/`VectorStoreError`) và c28 (`trim_to_budget` thuần)."""

from datetime import UTC, datetime

import pytest
from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef
from app.rag.expand import trim_to_budget
from app.rag.models import EvidenceBlock, RetrievalSystemError
from app.rag.retriever import RagConfig, Retriever
from app.rag.vector_store import CollectionNotFound, VectorStoreError
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.rag import SpyIndex

PSHA = "p" * 64
KBV = "a" * 64
COLL = f"kb_{KBV}"


def _ctx() -> RequesterContext:
    return RequesterContext(
        user_id="u1", role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=10, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def _retriever(index: SpyIndex) -> Retriever:
    from app.rag.bm25 import load_lexicon
    from app.settings import get_settings

    cfg = RagConfig(prefetch_k=20, rerank_k=20, top_n=5, intent_fallback=True, neighbor_window=1,
                    evidence_max_tokens=4000, deadline_s=5.0)  # fmt: skip
    return Retriever(index, FakeMlService().client(), cfg, threshold=0.6, pipeline_sha=PSHA,
                     lexicon=load_lexicon(get_settings().config_dir), clock=FakeClock())  # fmt: skip


def _ref(doc_id: str = "D1", seq: int = 0, score: float = 0.9) -> ChunkRef:
    return ChunkRef(chunk_id=f"{doc_id}#v1#{seq}", doc_id=doc_id, version=1, seq=seq, title="T",
                    heading_path="H", score=score, excerpt="x")  # fmt: skip


# ---- c26 (phần expand): CollectionNotFound → RSE("expand"); VectorStoreError khác → nổi lên nguyên ----


@pytest.mark.asyncio
async def test_c26_collection_not_found_during_expand_gives_expand_stage() -> None:
    spy = SpyIndex()
    spy.add_collection(COLL, metadata={"pipeline_sha": PSHA})
    spy.fail_next("scroll_window", CollectionNotFound("dọn giữa chừng"))
    r = _retriever(spy)
    with pytest.raises(RetrievalSystemError) as err:
        await r.expand_for_answer([_ref()], _ctx(), kb_version=KBV)
    assert err.value.stage == "expand"


@pytest.mark.asyncio
async def test_c26_other_vector_store_error_propagates_unchanged_in_expand() -> None:
    spy = SpyIndex()
    spy.add_collection(COLL, metadata={"pipeline_sha": PSHA})
    spy.fail_next("scroll_window", VectorStoreError("400 bad request"))
    r = _retriever(spy)
    with pytest.raises(VectorStoreError) as err:
        await r.expand_for_answer([_ref()], _ctx(), kb_version=KBV)
    assert not isinstance(err.value, RetrievalSystemError)


# ---- trim_to_budget (c28, thuần) -------------------------------------------------------------------


def _block(tokens: int, score: float) -> EvidenceBlock:
    return EvidenceBlock(anchor_chunk_id="c", doc_id="D", title="T", heading_path="H", score=score,
                         text="x", tokens=tokens)  # fmt: skip


def test_c28_drops_last_block_first_until_within_budget() -> None:
    blocks = [_block(100, 0.9), _block(100, 0.7), _block(100, 0.5)]
    out = trim_to_budget(blocks, max_tokens=250)
    assert [b.score for b in out] == [0.9, 0.7]
    assert sum(b.tokens for b in out) <= 250


def test_c28_never_drops_the_first_block_even_over_budget() -> None:
    blocks = [_block(500, 0.9), _block(100, 0.7)]
    out = trim_to_budget(blocks, max_tokens=100)
    assert [b.score for b in out] == [0.9]


def test_c28_keeps_everything_when_already_under_budget() -> None:
    blocks = [_block(10, 0.9), _block(10, 0.8)]
    out = trim_to_budget(blocks, max_tokens=1000)
    assert out == blocks
