"""`Retriever` trên Qdrant + Postgres thật, `FakeMlService` sau `MlClient` thật (thiết kế Phase 3 mục 6.6;
PLAN-3c mục 7 — c4, c6–c12, c14, c16). Số/câu dùng lại đúng mô phỏng S2 (PROGRESS, phương án A) — KHÔNG đoán
lại: c4 kiểm top-3 (không phải top-1, vì FakeMl hoà điểm giữa 3 tài liệu ở bậc rerank thật); c11 tái dùng câu
P006 (như c10) để chắc chắn D-23 chạy rồi mới hỏng ở rerank.

KB dùng để truy vấn (c4, c6, c7, c9, c10, c11) là `backend/tests/fixtures/kb` ingest THẬT qua `run_ingest`
(`with_eval=False` + `--allow-unevaluated`) — cổng kiểm không phải việc của file này (xem
`test_rag_ingest_pg.py`, c37); ở đây chỉ cần một collection thật đã gắn alias.
"""

from collections.abc import AsyncIterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.domain.ticket_state import ChunkRef
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b08_retrieve, b10_route
from app.rag.bm25 import load_lexicon, to_sparse, tokenize_vi
from app.rag.ingest.config import ALIAS
from app.rag.ingest.kbversion import pipeline_sha
from app.rag.models import ChunkPayload, RetrievalQuery, RetrievalSystemError
from app.rag.retriever import RagConfig, Retriever
from app.rag.vector_store import DENSE, SPARSE, VectorIndex
from app.settings import Settings, get_policy
from qdrant_client.models import PointStruct
from tests.fakes.executor import MemoryTxLog
from tests.fakes.fake_ml import embed_text
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.kb import CONFIG_DIR, KB_TEST_NOW, copy_kb
from tests.fakes.llm import make_gateway
from tests.fixtures.llm.vpn import vpn_scripts
from tests.integration.pg import PgUrls
from tests.integration.test_rag_ingest_pg import Env, _env

pytestmark = pytest.mark.asyncio

THRESHOLD = get_policy().constants.RETRIEVAL_THRESHOLD
P006 = "chứng chỉ vpn trên máy em hết hạn rồi, xin cấp lại thế nào"  # intent account → D-23
P007 = "tường lửa biên phải mở những cổng nào cho máy chủ vpn"  # role l1 mới thấy KB-VPN-007


def _ctx(role: str) -> RequesterContext:
    return RequesterContext(
        user_id="u1", role=role, department="it", manager_id=None, employment_status="active",
        tenure_days=10, is_privileged_account=False, captured_at=KB_TEST_NOW,
    )  # fmt: skip


def _cfg() -> RagConfig:
    return RagConfig.from_settings(Settings(_env_file=None))


async def _retriever(env: Env, *, index: VectorIndex | None = None, threshold: float = THRESHOLD) -> Retriever:
    lexicon = load_lexicon(CONFIG_DIR)
    return Retriever(
        index or env.index, env.fake.client(), _cfg(), threshold=threshold,
        pipeline_sha=pipeline_sha(CONFIG_DIR), lexicon=lexicon, clock=FakeClock(),
    )  # fmt: skip


# ---- KB fixture ingest thật (c4, c6, c7, c9, c10, c11) --------------------------------------------


@pytest_asyncio.fixture
async def env(clean_qdrant: str, migrated: PgUrls, tmp_path: Path) -> AsyncIterator[Env]:
    async with _env(clean_qdrant, migrated) as e:
        kb_dir = copy_kb(tmp_path, with_eval=False)  # không cổng kiểm — việc của test_rag_ingest_pg.py (c37)
        r = await e.run(kb_dir, allow_unevaluated=True)
        assert r.code == 0, r.err
        yield e


# ---- c4 ---------------------------------------------------------------------------------------------


async def test_c4_vpn_port_question_finds_kb_vpn_001_in_top3(env: Env) -> None:
    retriever = await _retriever(env)
    q = RetrievalQuery(text="VPN công ty dùng cổng nào?", intent="vpn")
    res = await retriever.retrieve(q, _ctx("employee"))
    assert res.top_score >= THRESHOLD
    assert "KB-VPN-001" in [c.doc_id for c in res.chunks[:3]]


# ---- c6 ---------------------------------------------------------------------------------------------


async def test_c6_restricted_doc_hidden_from_employee_visible_to_l1(env: Env) -> None:
    retriever = await _retriever(env)
    q = RetrievalQuery(text=P007, intent="vpn")
    emp = await retriever.retrieve(q, _ctx("employee"))
    assert "KB-VPN-007" not in [c.doc_id for c in emp.chunks]
    l1 = await retriever.retrieve(q, _ctx("l1"))
    assert "KB-VPN-007" in [c.doc_id for c in l1.chunks]


# ---- c7 ---------------------------------------------------------------------------------------------


async def test_c7_account_intent_fallback_still_hides_restricted_from_employee(env: Env) -> None:
    retriever = await _retriever(env)
    q = RetrievalQuery(text=P007, intent="account")
    res = await retriever.retrieve(q, _ctx("employee"))
    assert res.fallback_tried is True
    assert "KB-VPN-007" not in [c.doc_id for c in res.chunks]


# ---- c9 (như c6/c7 nhưng l1 + intent account: quyền cao hơn vẫn thấy dù qua D-23) ------------------


async def test_c9_account_intent_l1_still_sees_restricted(env: Env) -> None:
    retriever = await _retriever(env)
    q = RetrievalQuery(text=P007, intent="account")
    res = await retriever.retrieve(q, _ctx("l1"))
    assert "KB-VPN-007" in [c.doc_id for c in res.chunks]


# ---- c10 --------------------------------------------------------------------------------------------


async def test_c10_p006_account_intent_fallback_recovers_result(env: Env) -> None:
    retriever = await _retriever(env)
    q = RetrievalQuery(text=P006, intent="account")
    res = await retriever.retrieve(q, _ctx("employee"))
    assert res.chunks
    assert res.intent_filter_fallback is True
    assert res.fallback_tried is True


# ---- c11 (Q): lần 1 (account) rỗng — không tốn lượt rerank; D-23 mới gọi rerank rồi hết lượt --------


async def test_c11_rerank_exhausted_after_intent_fallback_raises(env: Env) -> None:
    retriever = await _retriever(env)
    env.fake.fail_next("rerank", "http_500", 3)
    q = RetrievalQuery(text=P006, intent="account")
    with pytest.raises(RetrievalSystemError) as exc:
        await retriever.retrieve(q, _ctx("employee"))
    assert exc.value.stage == "rerank"


# ---- c12: chưa có alias --------------------------------------------------------------------------


async def test_c12_no_alias_raises_stage_alias_no_ml_calls(clean_qdrant: str, migrated: PgUrls) -> None:
    async with _env(clean_qdrant, migrated) as env:
        retriever = await _retriever(env)
        q = RetrievalQuery(text="vpn lỗi 809", intent="vpn")
        with pytest.raises(RetrievalSystemError) as exc:
            await retriever.retrieve(q, _ctx("employee"))
        assert exc.value.stage == "alias"
        assert sum(env.fake.calls.values()) == 0


# ---- c14: alias trỏ collection rỗng ----------------------------------------------------------------


@contextmanager
def _run_ctx(audit: MemoryAudit) -> Any:
    ctx = RunContext(
        turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
        clock=FakeClock(), txlog=MemoryTxLog(),
    )  # fmt: skip
    with bind_run(ctx):
        yield ctx


def _state(ctx: RequesterContext, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "redacted_request": "vpn lỗi 809",
        "intent": "vpn", "slots": {}, "requester_context": ctx,
    }  # fmt: skip
    base.update(over)
    return base


async def _run_node(retriever: Retriever, ctx: RequesterContext) -> tuple[dict[str, Any], MemoryAudit]:
    """Phase 4 S0-P1/P2: B8 không còn nhánh B9 — chạy B8 → B10 (preset `b10_need_type=info`); B9 nằm trong `b10_route`."""
    h = GraphHarness(llm=make_gateway({"b10_need_type": vpn_scripts(need="info")["b10_need_type"]}).client)
    h.rag = retriever  # type: ignore[assignment]
    deps = h.deps()
    audit = MemoryAudit()
    with _run_ctx(audit):
        state = _state(ctx)
        out = await b08_retrieve.make(deps)(state)
        assert (out["status"], out["next"]) == (S_RETRIEVING, "b10_route")
        return await b10_route.make(deps)({**state, **out}), audit


async def test_c14_empty_collection_gives_e3_no_rerank_call(clean_qdrant: str, migrated: PgUrls) -> None:
    async with _env(clean_qdrant, migrated) as env:
        psha = pipeline_sha(CONFIG_DIR)
        v = "0" * 64
        name = f"kb_{v}"
        await env.index.create(name, {"kb_version": v, "pipeline_sha": psha})
        await env.index.switch_alias(ALIAS, name, had_alias=False)
        retriever = await _retriever(env)
        q = RetrievalQuery(text="vpn lỗi 809", intent="vpn")
        res = await retriever.retrieve(q, _ctx("employee"))
        assert res.chunks == [] and res.top_score == 0.0
        assert env.fake.calls["rerank"] == 0
        out, audit = await _run_node(retriever, _ctx("employee"))
        assert (out["status"], out["exit_code"]) == (S_ESCALATED, "E3")
        assert audit.events("t1") == [("B8", "retrieved"), ("B9", "no_evidence")]


# ---- c16: alias đổi NGAY TRONG hybrid_query đầu tiên — ghim kb_version của lượt đang chạy ----------


def _point(
    text: str, *, doc_id: str, seq: int, kb_version: str, lexicon: Any, sensitivity: str = "public",
) -> PointStruct:  # fmt: skip
    payload = ChunkPayload(
        chunk_id=f"{doc_id}#v1#{seq}", doc_id=doc_id, version=1, seq=seq, title="T", heading_path="H",
        request_type="vpn", doc_type="faq", sensitivity=sensitivity, enabled=True, distractor=False,
        text=text, token_count=10, kb_version=kb_version, owner="u1",
    )  # fmt: skip
    return PointStruct(
        id=str(uuid4()),
        vector={DENSE: embed_text(text), SPARSE: to_sparse(tokenize_vi(text, lexicon=lexicon))},
        payload=payload.model_dump(),
    )


class _AliasSwitcher:
    """Bọc `VectorIndex` thật (không phải `tests.fakes.rag.SpyIndex` — đó là bản giả toàn bộ, ở đây cần Qdrant
    THẬT phía sau): mọi phương thức khác uỷ quyền nguyên qua `__getattr__`; `hybrid_query` đổi alias sang
    `target` làm tác dụng phụ NGAY LẦN GỌI ĐẦU (mô phỏng một lượt ingest khác đổi alias giữa chừng — c16,
    3-Q14) rồi mới thực hiện truy vấn thật (vẫn trên `name` mà `Retriever` đã ghim từ đầu — không đọc lại)."""

    def __init__(self, inner: VectorIndex, alias: str, target: str) -> None:
        self._inner = inner
        self._alias = alias
        self._target = target
        self._switched = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def hybrid_query(self, *args: Any, **kwargs: Any) -> Any:
        if not self._switched:
            self._switched = True
            await self._inner.switch_alias(self._alias, self._target, had_alias=True)  # type: ignore[attr-defined]
        return await self._inner.hybrid_query(*args, **kwargs)  # type: ignore[attr-defined]


async def test_c16_alias_switch_mid_query_pins_old_kb_version(clean_qdrant: str, migrated: PgUrls) -> None:
    async with _env(clean_qdrant, migrated) as env:
        psha = pipeline_sha(CONFIG_DIR)
        old_v, new_v = "1" * 64, "2" * 64
        old_name, new_name = f"kb_{old_v}", f"kb_{new_v}"
        lexicon = load_lexicon(CONFIG_DIR)
        for name, v, mark in ((old_name, old_v, "OLD_MARK"), (new_name, new_v, "NEW_MARK")):
            await env.index.create(name, {"kb_version": v, "pipeline_sha": psha})
            pt = _point(f"vpn loi 809 {mark}", doc_id="KB-VPN-001", seq=0, kb_version=v, lexicon=lexicon)
            await env.index.upsert(name, [pt])
        await env.index.switch_alias(ALIAS, old_name, had_alias=False)
        wrapped = _AliasSwitcher(env.index, ALIAS, new_name)
        retriever = await _retriever(env, index=wrapped)
        q = RetrievalQuery(text="vpn loi 809", intent=None)
        res = await retriever.retrieve(q, _ctx("employee"))
        assert res.kb_version == old_v
        assert res.chunks and "OLD_MARK" in res.chunks[0].excerpt
        evidence = await retriever.expand_for_answer(res.chunks, _ctx("employee"), kb_version=res.kb_version)
        assert evidence and "OLD_MARK" in evidence[0].text and "NEW_MARK" not in evidence[0].text


# ---- c8: expand_for_answer tôn trọng lọc quyền TRONG cửa sổ láng giềng -----------------------------


async def test_c8_expand_respects_permission_within_neighbor_window(clean_qdrant: str, migrated: PgUrls) -> None:
    async with _env(clean_qdrant, migrated) as env:
        psha = pipeline_sha(CONFIG_DIR)
        v = "3" * 64
        name = f"kb_{v}"
        lexicon = load_lexicon(CONFIG_DIR)
        await env.index.create(name, {"kb_version": v, "pipeline_sha": psha})
        pts = [
            _point("noi dung MARK0", doc_id="KB-VPN-001", seq=0, kb_version=v, lexicon=lexicon, sensitivity="restricted"),
            _point("noi dung MARK1", doc_id="KB-VPN-001", seq=1, kb_version=v, lexicon=lexicon, sensitivity="public"),
            _point("noi dung MARK2", doc_id="KB-VPN-001", seq=2, kb_version=v, lexicon=lexicon, sensitivity="restricted"),
        ]  # fmt: skip
        await env.index.upsert(name, pts)
        retriever = await _retriever(env)
        anchor = ChunkRef(
            chunk_id="KB-VPN-001#v1#1", doc_id="KB-VPN-001", version=1, seq=1, title="T", heading_path="H",
            score=1.0, excerpt="noi dung MARK1",
        )  # fmt: skip
        emp = await retriever.expand_for_answer([anchor], _ctx("employee"), kb_version=v)
        assert "MARK1" in emp[0].text and "MARK0" not in emp[0].text and "MARK2" not in emp[0].text
        l1 = await retriever.expand_for_answer([anchor], _ctx("l1"), kb_version=v)
        assert all(mark in l1[0].text for mark in ("MARK0", "MARK1", "MARK2"))
