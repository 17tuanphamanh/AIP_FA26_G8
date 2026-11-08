"""R2 — đường TRUY VẤN kiểm cờ `truncated` của `/embed` như đường ingest, nhưng CHỈ GHI, không chặn.

Ingest (`pipeline.py`): embed báo một đoạn bị cắt (> 512 token, D-21) → ingest thất bại. Truy vấn trước đây bỏ qua cờ này
(`query_truncated` hiện có là cờ của RERANKER, câu bị cắt ở 128 token — 3-Q12, nghĩa khác). Nay: `RetrievalResult.embed_truncated`
(bool, mặc định False) = cờ của lần embed câu truy vấn, đi vào điểm log 3 của B8 (`embed_truncated`). Không đổi điểm, không đổi top-5,
không đổi D-23, không ném lỗi; `query_truncated` giữ nghĩa cũ.
"""

import pytest
from app.domain.states import S_RETRIEVING
from app.graph.nodes import b08_retrieve
from app.rag.models import RetrievalQuery, RetrievalResult, RetrievalSystemError
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.graph import MemoryAudit
from tests.fakes.rag import FakeRag, SpyPoint
from tests.unit.test_b08_retrieve import _chunk, _harness_with_rag, _state, run
from tests.unit.test_rag_retriever import _ctx, _payload, _retriever, _spy

QUERY = RetrievalQuery(text="vpn loi ket noi cong", intent="vpn")


def _spy_with_doc() -> object:
    return _spy(points=[SpyPoint("1", _payload("D1", 0, "vpn loi ket"), score=1.0)])


async def _retrieve(fake: FakeMlService, q: RetrievalQuery = QUERY) -> RetrievalResult:
    return await _retriever(_spy_with_doc(), fake.client()).retrieve(q, _ctx())


@pytest.mark.asyncio
async def test_flag_is_true_only_when_embed_reports_truncation() -> None:
    assert (await _retrieve(FakeMlService())).embed_truncated is False
    assert (await _retrieve(FakeMlService(truncate_embed=True))).embed_truncated is True


@pytest.mark.asyncio
async def test_flag_changes_nothing_else_about_the_result() -> None:
    """Không đổi điểm, top-5, cờ D-23, số lần thử lại, và `query_truncated` (cờ của reranker, nghĩa khác)."""
    plain = await _retrieve(FakeMlService())
    cut = await _retrieve(FakeMlService(truncate_embed=True))
    assert cut.embed_truncated is True
    assert cut.model_copy(update={"embed_truncated": False}) == plain
    assert cut.query_truncated is False and plain.query_truncated is False


@pytest.mark.asyncio
async def test_flag_does_not_block_search_or_rerank() -> None:
    plain_spy, cut_spy = _spy_with_doc(), _spy_with_doc()
    fake_plain, fake_cut = FakeMlService(), FakeMlService(truncate_embed=True)
    await _retriever(plain_spy, fake_plain.client()).retrieve(QUERY, _ctx())
    await _retriever(cut_spy, fake_cut.client()).retrieve(QUERY, _ctx())
    assert fake_cut.calls == fake_plain.calls and fake_cut.calls["embed"] == 1 and fake_cut.calls["rerank"] == 1


@pytest.mark.asyncio
async def test_flag_survives_the_d23_fallback_paths() -> None:
    """Lần 1 (lọc intent) rỗng → D-23 thử không lọc: cờ của lần embed (dùng chung cho cả hai lần tìm) vẫn đi theo kết quả."""
    spy = _spy(points=[SpyPoint("1", _payload("D1", 0, "vpn loi ket"), score=1.0)])
    res = await _retriever(spy, FakeMlService(truncate_embed=True).client()).retrieve(
        RetrievalQuery(text="vpn loi ket noi cong", intent="account"), _ctx()
    )  # fmt: skip
    assert res.fallback_tried is True and res.embed_truncated is True


def test_default_is_false_for_existing_constructors() -> None:
    res = RetrievalResult(chunks=[], top_score=0.0, kb_version="a" * 64, intent_filter_fallback=False, fallback_tried=False,
                          retries=0, query_truncated=False)  # fmt: skip
    assert res.embed_truncated is False


# ---- B8: ghi vào điểm log 3 (bool), không chặn ------------------------------------------------------------------------------


def _result(**over: object) -> RetrievalResult:
    base: dict[str, object] = {"chunks": [_chunk()], "top_score": 0.9, "kb_version": "a" * 64, "intent_filter_fallback": False,
                               "fallback_tried": False, "retries": 0, "query_truncated": False}  # fmt: skip
    return RetrievalResult(**{**base, **over})  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [True, False])
async def test_b08_audit_records_embed_truncated_bool_and_still_routes(flag: bool) -> None:
    h = _harness_with_rag(FakeRag(result=_result(embed_truncated=flag)))
    audit = MemoryAudit()
    with run(audit):
        out = await b08_retrieve.make(h.deps())(_state())
    assert (out["status"], out["next"]) == (S_RETRIEVING, "b10_route")  # không chặn
    assert out["retrieval_score"] == 0.9 and [c.doc_id for c in out["retrieved"]] == ["KB-VPN-001"]
    detail = audit.rows[0]["detail"]
    assert detail["embed_truncated"] is flag and detail["query_truncated"] is False  # hai cờ tách bạch


@pytest.mark.asyncio
async def test_b08_error_branch_has_no_embed_flag() -> None:
    h = _harness_with_rag(FakeRag())
    h.rag.error = RetrievalSystemError("embed", 2, kb_version="a" * 64)
    audit = MemoryAudit()
    with run(audit):
        await b08_retrieve.make(h.deps())(_state())
    assert audit.rows[0]["detail"]["embed_truncated"] is None
