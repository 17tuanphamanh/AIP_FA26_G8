"""`Retriever` — truy hồi hybrid, phân biệt tuyệt đối E2/E3 (thiết kế Phase 3 mục 6.6; PLAN-3c mục 3.3, 7).

c4–c10, c12, c14, c16, c19 (cần Qdrant thật) ở `integration/test_rag_query_qdrant.py` (S10). File này: c3, c11(U),
c13, c15(retrieve), c17, c23–c27, c31 (SpyIndex/QdrantIndex thật tới cổng sai — không cần Docker).
"""

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from app.core.clock import FakeClock
from app.domain.context import RequesterContext, Role
from app.domain.ticket_state import ChunkRef
from app.ml import MlClient
from app.ml.ports import MlContractError
from app.rag.bm25 import load_lexicon, tokenize_vi
from app.rag.models import ChunkTruncatedError, RetrievalQuery, RetrievalSystemError
from app.rag.retriever import RagConfig, Retriever, rank_and_dedupe, to_ref
from app.rag.vector_store import CollectionNotFound, QdrantIndex, VectorStoreError
from app.settings import get_settings
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, Range
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.rag import SpyIndex, SpyPoint

PSHA = "p" * 64
KBV = "a" * 64
COLL = f"kb_{KBV}"
LEXICON = load_lexicon(get_settings().config_dir)
tokenize_vi("khởi động pyvi trước khi đo thời gian", lexicon=LEXICON)  # bm25.py: nạp model lần đầu ~0,8 s


def _cfg(**over: object) -> RagConfig:
    base: dict[str, object] = {
        "prefetch_k": 20, "rerank_k": 20, "top_n": 5, "intent_fallback": True, "neighbor_window": 1,
        "evidence_max_tokens": 4000, "deadline_s": 5.0,
    }  # fmt: skip
    base.update(over)
    return RagConfig(**base)  # type: ignore[arg-type]


def _conds(flt: Filter) -> list[FieldCondition]:
    """Điều kiện `must` của filter do `rag/filters.py` dựng — toàn `FieldCondition` (thu hẹp kiểu cho mypy)."""
    must = flt.must if isinstance(flt.must, list) else [flt.must]
    out = [c for c in must if isinstance(c, FieldCondition)]
    assert len(out) == len(must)
    return out


def _ctx(role: Role = "employee") -> RequesterContext:
    return RequesterContext(
        user_id="u1", role=role, department="it", manager_id=None, employment_status="active",
        tenure_days=10, is_privileged_account=False, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def _retriever(index: object, ml: object, *, cfg: RagConfig | None = None, threshold: float = 0.6,
              pipeline_sha: str = PSHA, clock: FakeClock | None = None) -> Retriever:  # fmt: skip
    return Retriever(index, ml, cfg or _cfg(), threshold=threshold, pipeline_sha=pipeline_sha,  # type: ignore[arg-type]
                     lexicon=LEXICON, clock=clock or FakeClock())  # fmt: skip


def _payload(doc_id: str, seq: int, text: str, **over: object) -> dict[str, object]:
    base = {
        "doc_id": doc_id, "chunk_id": f"{doc_id}#v1#{seq}", "version": 1, "seq": seq, "title": "T",
        "heading_path": "H", "text": f"T › H\n\n{text}", "enabled": True, "sensitivity": "public",
        "request_type": "vpn", "token_count": len(text.split()),
    }  # fmt: skip
    base.update(over)
    return base


def _spy(*, pipeline_sha: str = PSHA, points: list[SpyPoint] | None = None) -> SpyIndex:
    spy = SpyIndex()
    spy.add_collection(COLL, metadata={"pipeline_sha": pipeline_sha})
    if points:
        spy.add_points(COLL, points)
    spy.set_alias("kb_current", COLL)
    return spy


# ---- c3: rank_and_dedupe (thuần) ------------------------------------------------------------------


class _Hit:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload


def test_c3_rank_and_dedupe_keeps_highest_score_per_doc() -> None:
    hits = [_Hit(_payload("D1", 0, "a")), _Hit(_payload("D1", 1, "b")), _Hit(_payload("D2", 0, "c"))]
    out = rank_and_dedupe(hits, [0.3, 0.9, 0.5], top_n=5)
    assert [(c.doc_id, c.seq) for c in out] == [("D1", 1), ("D2", 0)]


def test_c3_tie_breaks_by_rrf_index_order() -> None:
    hits = [_Hit(_payload("D1", 0, "a")), _Hit(_payload("D2", 0, "b"))]
    out = rank_and_dedupe(hits, [0.5, 0.5], top_n=5)
    assert [c.doc_id for c in out] == ["D1", "D2"]  # hoà điểm → giữ thứ hạng RRF (thứ tự hits)


def test_c3_respects_top_n() -> None:
    hits = [_Hit(_payload(f"D{i}", 0, "x")) for i in range(8)]
    out = rank_and_dedupe(hits, [float(8 - i) for i in range(8)], top_n=5)
    assert len(out) == 5
    assert [c.doc_id for c in out] == ["D0", "D1", "D2", "D3", "D4"]


def test_c3_excerpt_has_no_prefix_and_is_capped() -> None:
    ref = to_ref(_payload("D1", 0, "x" * 700), score=0.5)
    assert not ref.excerpt.startswith("T › H")
    assert len(ref.excerpt) == 600


# ---- c13: Qdrant không tới được (cổng sai) — E2 stage=alias, 0 lời gọi ml -------------------------
# Lỗi tạm khi đọc alias → alias (phase4:739, ĐP 24/10); phase3:1089 vẫn đúng cho lỗi bước search.


@pytest.mark.asyncio
async def test_c13_unreachable_qdrant_gives_alias_stage_with_two_retries() -> None:
    client = AsyncQdrantClient(url="http://127.0.0.1:1", check_compatibility=False, timeout=1)
    fake = FakeMlService()
    r = _retriever(QdrantIndex(client), fake.client(), clock=FakeClock())
    try:
        with pytest.raises(RetrievalSystemError) as err:
            await r.retrieve(RetrievalQuery(text="vpn lỗi", intent="vpn"), _ctx())
        assert err.value.stage == "alias"
        assert err.value.retries == 2
        assert sum(fake.calls.values()) == 0
    finally:
        await client.close()


# ---- c15: top_score đúng bằng ngưỡng → không chạy D-23 ---------------------------------------------


@pytest.mark.asyncio
async def test_c15_top_score_equal_threshold_skips_d23() -> None:
    # FakeMl rerank = |giao âm tiết| / |âm tiết câu|; câu 5 âm tiết ("vpn loi ket noi cong"), đoạn chứa đúng 3
    # ("vpn loi ket", + "t"/"h" của tiền tố title › heading_path không đếm vào câu) → 3/5 = 0,6 = T.
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "vpn loi ket"), score=1.0)])
    fake = FakeMlService()
    r = _retriever(spy, fake.client())
    res = await r.retrieve(RetrievalQuery(text="vpn loi ket noi cong", intent="vpn"), _ctx())
    assert res.top_score == pytest.approx(0.6)
    assert (res.fallback_tried, res.intent_filter_fallback) == (False, False)


# ---- c11(U): lần 1 rỗng (intent account) → D-23 → rerank lỗi → E2 stage=rerank --------------------


@pytest.mark.asyncio
async def test_c11_first_search_empty_then_fallback_rerank_fails() -> None:
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "dùng cổng 809"))])  # request_type=vpn ≠ account
    fake = FakeMlService().fail_next("rerank", "http_500", 3)
    r = _retriever(spy, fake.client())
    with pytest.raises(RetrievalSystemError) as err:
        await r.retrieve(RetrievalQuery(text="dùng cổng 809", intent="account"), _ctx())
    assert err.value.stage == "rerank"
    assert fake.calls["embed"] == 1  # Q-3c-3: embed một lần, dùng lại cho D-23
    assert fake.calls["rerank"] == 3  # hết lượt của MlClient (không lặp thêm ở retriever)


# ---- c17: embed lỗi 2 lần rồi thành công → đúng 1 lời gọi ml.embed (không 9) ----------------------


@pytest.mark.asyncio
async def test_c17_embed_retries_inside_single_ml_call() -> None:
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "vpn lỗi 809"))])
    fake = FakeMlService().fail_next("embed", "http_500", 2)
    r = _retriever(spy, fake.client())
    res = await r.retrieve(RetrievalQuery(text="vpn lỗi 809", intent="vpn"), _ctx())
    assert fake.calls["embed"] == 3  # 2 lỗi + 1 thành công, MỘT lời gọi retrieve()
    assert res.retries == 2  # Q-3c-10: lỗi → max(0, attempts-1); Qdrant retries = 0 (SpyIndex không lỗi)


# ---- S14: ml-service hết lượt / timeout → RetrievalSystemError (E2), KHÔNG thành kết quả rỗng (E3) ---


@pytest.mark.asyncio
async def test_embed_exhausted_raises_embed_stage_not_empty_result() -> None:
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "vpn lỗi 809"))])
    fake = FakeMlService().fail_next("embed", "http_500", 3)
    r = _retriever(spy, fake.client())
    with pytest.raises(RetrievalSystemError) as err:
        await r.retrieve(RetrievalQuery(text="vpn lỗi 809", intent="vpn"), _ctx())
    assert err.value.stage == "embed"
    assert spy.calls["hybrid_query"] == 0  # không truy vấn Qdrant khi chưa có vector


@pytest.mark.asyncio
async def test_rerank_timeout_raises_rerank_stage_not_empty_result() -> None:
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "vpn lỗi 809"))])
    fake = FakeMlService().fail_next("rerank", "timeout", 3)
    r = _retriever(spy, fake.client())
    with pytest.raises(RetrievalSystemError) as err:
        await r.retrieve(RetrievalQuery(text="vpn lỗi 809", intent="vpn"), _ctx())
    assert err.value.stage == "rerank"
    assert fake.calls["rerank"] == 3


# ---- c23: pipeline_sha lệch → E2 stage=pipeline, 0 lời gọi ml (Q-3c-2) ----------------------------


@pytest.mark.asyncio
async def test_c23_pipeline_sha_mismatch_before_any_ml_call() -> None:
    spy = _spy(pipeline_sha="lệch" * 16)
    fake = FakeMlService()
    r = _retriever(spy, fake.client())
    with pytest.raises(RetrievalSystemError) as err:
        await r.retrieve(RetrievalQuery(text="x", intent="vpn"), _ctx())
    assert err.value.stage == "pipeline"
    assert sum(fake.calls.values()) == 0


# ---- c24: lỗi hợp đồng ml (401) nổi lên nguyên, KHÔNG phải RetrievalSystemError -------------------


@pytest.mark.asyncio
async def test_c24_ml_contract_error_is_not_wrapped() -> None:
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "vpn"))])
    fake = FakeMlService()
    http = httpx.AsyncClient(transport=fake.transport, base_url="http://ml-fake:8200")
    ml = MlClient(http, "token-sai", clock=FakeClock())
    r = _retriever(spy, ml)
    with pytest.raises(MlContractError):
        await r.retrieve(RetrievalQuery(text="x", intent="vpn"), _ctx())


# ---- c25: reranker báo cắt đoạn → ChunkTruncatedError (E9, không phải RetrievalSystemError) -------


@pytest.mark.asyncio
async def test_c25_reranker_truncated_chunk_raises_contract_error() -> None:
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "vpn cổng 809"))])
    fake = FakeMlService(truncate_all=True)
    r = _retriever(spy, fake.client())
    with pytest.raises(ChunkTruncatedError):
        await r.retrieve(RetrievalQuery(text="vpn cổng 809", intent="vpn"), _ctx())


# ---- c26: phân loại lỗi Qdrant ở tầng Retriever ----------------------------------------------------


@pytest.mark.asyncio
async def test_c26_collection_not_found_in_search_gives_alias_stage() -> None:
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "vpn"))])
    spy.fail_next("hybrid_query", CollectionNotFound("collection đã bị dọn"))
    fake = FakeMlService()
    r = _retriever(spy, fake.client())
    with pytest.raises(RetrievalSystemError) as err:
        await r.retrieve(RetrievalQuery(text="x", intent="vpn"), _ctx())
    assert err.value.stage == "alias"


@pytest.mark.asyncio
async def test_c26_other_vector_store_error_propagates_unchanged() -> None:
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "vpn"))])
    spy.fail_next("hybrid_query", VectorStoreError("400 bad request: bộ lọc sai"))
    fake = FakeMlService()
    r = _retriever(spy, fake.client())
    with pytest.raises(VectorStoreError, match="400 bad request") as err:
        await r.retrieve(RetrievalQuery(text="x", intent="vpn"), _ctx())
    assert not isinstance(err.value, RetrievalSystemError)


# ---- c27: mọi Filter gửi đi luôn có enabled + sensitivity; lần 1 có request_type, D-23 thì không ---


@pytest.mark.asyncio
async def test_c27_every_filter_has_enabled_and_sensitivity_and_intent_only_on_first_try() -> None:
    # Điểm request_type=account: lần 1 (intent vpn) không thấy → D-23 (không intent) mới thấy nhưng điểm thấp.
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "abc", request_type="account"), score=0.0)])
    fake = FakeMlService()
    r = _retriever(spy, fake.client())
    res = await r.retrieve(RetrievalQuery(text="hỏi về vpn", intent="vpn"), _ctx())
    assert res.fallback_tried is True
    assert len(spy.filters) == 2
    for flt in spy.filters:
        by_key = {c.key: c.match for c in _conds(flt)}
        enabled, sensitivity = by_key["enabled"], by_key["sensitivity"]
        assert isinstance(enabled, MatchValue) and isinstance(sensitivity, MatchAny)
        assert enabled.value is True
        assert set(sensitivity.any) == {"public", "internal"}
    assert "request_type" in {c.key for c in _conds(spy.filters[0])}
    assert "request_type" not in {c.key for c in _conds(spy.filters[1])}


@pytest.mark.asyncio
async def test_c27_expand_filter_uses_role_sensitivity_and_doc_scope() -> None:
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "abc"))])
    fake = FakeMlService()
    r = _retriever(spy, fake.client())
    ref = ChunkRef(chunk_id="D1#v1#0", doc_id="D1", version=1, seq=0, title="T", heading_path="H",
                   score=0.9, excerpt="abc")  # fmt: skip
    await r.expand_for_answer([ref], _ctx("l1"), kb_version=KBV)
    by_key = {c.key: c for c in _conds(spy.filters[-1])}
    sensitivity, doc_id, seq = by_key["sensitivity"].match, by_key["doc_id"].match, by_key["seq"].range
    assert isinstance(sensitivity, MatchAny) and isinstance(doc_id, MatchValue) and isinstance(seq, Range)
    assert set(sensitivity.any) == {"public", "internal", "restricted"}
    assert doc_id.value == "D1"
    assert (seq.gte, seq.lte) == (-1, 1)


# ---- c31: hết hạn (deadline) giữa lượt Qdrant → E2 stage=search, detail=deadline ------------------


@pytest.mark.asyncio
async def test_c31_deadline_during_hybrid_query_gives_search_stage() -> None:
    spy = _spy()
    spy.delay_next("hybrid_query", 1.0)
    fake = FakeMlService()
    r = _retriever(spy, fake.client(), cfg=_cfg(deadline_s=0.05))
    t0 = asyncio.get_event_loop().time()
    with pytest.raises(RetrievalSystemError) as err:
        await r.retrieve(RetrievalQuery(text="x", intent=None), _ctx())
    assert err.value.stage == "search"
    assert err.value.detail == "deadline"
    assert err.value.retries == 0
    assert asyncio.get_event_loop().time() - t0 < 0.5  # không chờ hết 1 s thật của delay_next
