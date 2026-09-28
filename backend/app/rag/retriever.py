"""`Retriever` — truy hồi hybrid có lọc quyền, phân biệt tuyệt đối E2/E3 (thiết kế Phase 3 mục 6.6, 3-Q6, 3-Q11,
3-Q14; PLAN-3c mục 3.3).

- **Một lời gọi Qdrant = `_call`**: bọc `VectorStoreTransient` thành `httpx.ConnectError` để `call_with_retry`
  (đã dùng cho tool đọc, 3-Q6) coi là lỗi tạm; `CollectionNotFound`/`VectorStoreError` khác đi thẳng (không phải
  lỗi httpx) — bên gọi (`retrieve`/`_search`, `rag/expand.py`) tự bắt rồi đổi thành `RetrievalSystemError`. Với
  `ml` KHÔNG bọc thêm — `MlClient` đã tự retry (3-Q6).
- **`stage`** của một lượt truy hồi là biến cục bộ (`_StageBox`), không lưu trên `self` — `Retriever` dùng CHUNG
  giữa nhiều lượt đồng thời (nhiều coroutine gọi cùng một instance).
- **Embed một lần mỗi lượt** (Q-3c-3): vector dense + sparse dùng lại cho cả lần 1 và lần chạy lại D-23.
- `rag/expand.py::expand` là thân của `Retriever.expand_for_answer` (tách file theo PLAN-3c mục 2) — nạp muộn để
  tránh vòng import module (`expand.py` nhập ngược `_Counter`/`_Transient`/`content_of` ở đây).
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.clock import Clock
from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef
from app.ml.ports import MlPort
from app.rag.bm25 import ViLexicon, to_sparse, tokenize_vi
from app.rag.filters import intent_filter, query_filter
from app.rag.ingest.config import ALIAS, COLLECTION_RE
from app.rag.models import (
    ChunkTruncatedError,
    EvidenceBlock,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSystemError,
    Stage,
)
from app.rag.vector_store import CollectionNotFound, VectorIndex, VectorStoreTransient
from app.settings import Settings
from app.tools.retry import call_with_retry

_COLLECTION_RE = re.compile(COLLECTION_RE)


@dataclass(frozen=True)
class RagConfig:
    prefetch_k: int
    rerank_k: int
    top_n: int
    intent_fallback: bool
    neighbor_window: int
    evidence_max_tokens: int
    deadline_s: float

    @classmethod
    def from_settings(cls, s: Settings) -> "RagConfig":
        """MỘT nguồn: `Settings` (mục 3.5) — không lặp hằng ở chỗ khác."""
        return cls(
            prefetch_k=s.rag_prefetch_k,
            rerank_k=s.rag_rerank_k,
            top_n=s.rag_top_n,
            intent_fallback=s.rag_intent_fallback,
            neighbor_window=s.rag_neighbor_window,
            evidence_max_tokens=s.rag_evidence_max_tokens,
            deadline_s=s.rag_deadline_s,
        )


@dataclass
class _Counter:
    """`retries` = tổng số lần THỬ LẠI (Q-3c-10): thành công → cộng `attempts`; lỗi → cộng `max(0, attempts-1)`
    (hết lượt vẫn tính là 1 lần thử, không phải lần thử lại)."""

    total: int = 0

    def add(self, attempt: int, *, failed: bool) -> None:
        self.total += attempt if not failed else max(0, attempt - 1)


class _Transient(Exception):
    """Lỗi Qdrant tạm thời hết retry (nội bộ `_call`) — bên gọi đổi thành `RetrievalSystemError`."""


class _StageBox:
    """Hộp chứa `stage` khả biến, truyền qua tham số — KHÔNG lưu trên `self` của `Retriever`."""

    __slots__ = ("value",)

    def __init__(self, value: Stage) -> None:
        self.value: Stage = value


async def _call(clock: Clock, retries: _Counter, fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    async def once() -> Any:
        try:
            return await fn(*args)
        except VectorStoreTransient as e:
            raise httpx.ConnectError(str(e)) from e  # cho call_with_retry thấy là lỗi tạm (tiền lệ Q-3a-3)

    data, err, attempt = await call_with_retry(once, clock=clock)
    retries.add(attempt, failed=err is not None)
    if err is not None:
        raise _Transient(err)
    return data


@dataclass
class _Partial:
    chunks: list[ChunkRef]
    top_score: float
    query_truncated: bool

    def finish(self, kb_version: str, *, fallback: bool, tried: bool, retries: int) -> RetrievalResult:
        return RetrievalResult(
            chunks=self.chunks,
            top_score=self.top_score,
            kb_version=kb_version,
            intent_filter_fallback=fallback,
            fallback_tried=tried,
            retries=retries,
            query_truncated=self.query_truncated,
        )


def content_of(payload: dict[str, Any]) -> str:
    """`text` bỏ tiền tố `f"{title} › {heading_path}\\n\\n"` — không khớp tiền tố → trả nguyên `text` (Q-3c-13)."""
    prefix = f"{payload['title']} › {payload['heading_path']}\n\n"
    text: str = payload["text"]
    return text.removeprefix(prefix) if text.startswith(prefix) else text


def to_ref(payload: dict[str, Any], score: float) -> ChunkRef:
    """Payload thiếu key → `KeyError` (lỗi hợp đồng, không lường trước) → E9."""
    return ChunkRef(
        chunk_id=payload["chunk_id"],
        doc_id=payload["doc_id"],
        version=payload["version"],
        seq=payload["seq"],
        title=payload["title"],
        heading_path=payload["heading_path"],
        score=score,
        excerpt=content_of(payload)[:600],
    )


def rank_and_dedupe(hits: list[Any], scores: list[float], top_n: int) -> list[ChunkRef]:
    """Sắp `(hit, score, rrf_idx)` theo `(-score, rrf_idx)` (hoà điểm → thứ hạng RRF); giữ chunk điểm cao nhất của
    mỗi `doc_id`; lấy `top_n` đầu."""
    ranked = sorted(zip(hits, scores, range(len(hits)), strict=True), key=lambda x: (-x[1], x[2]))
    out: list[ChunkRef] = []
    seen: set[str] = set()
    for hit, score, _ in ranked:
        payload = hit.payload or {}
        doc_id = payload["doc_id"]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append(to_ref(payload, score))
        if len(out) >= top_n:
            break
    return out


class Retriever:
    def __init__(
        self,
        index: VectorIndex,
        ml: MlPort,
        cfg: RagConfig,
        *,
        threshold: float,
        pipeline_sha: str,
        lexicon: ViLexicon,
        clock: Clock,
    ) -> None:
        self._index = index
        self._ml = ml
        self._cfg = cfg
        self._threshold = threshold
        self._pipeline_sha = pipeline_sha
        self._lexicon = lexicon
        self._clock = clock

    async def _call(self, fn: Callable[..., Awaitable[Any]], *args: Any, retries: _Counter) -> Any:
        return await _call(self._clock, retries, fn, *args)

    async def retrieve(
        self, q: RetrievalQuery, ctx: RequesterContext, *, collection: str | None = None
    ) -> RetrievalResult:
        retries = _Counter()
        stage = _StageBox("alias")
        kb_version: str | None = None
        try:
            async with asyncio.timeout(self._cfg.deadline_s):
                if collection is not None:
                    coll = collection
                else:
                    try:
                        coll = await self._call(self._index.alias_target, ALIAS, retries=retries)
                    except _Transient as e:
                        raise RetrievalSystemError("search", retries.total, detail=str(e)) from e
                    if coll is None:
                        raise RetrievalSystemError("alias", retries.total)
                if not _COLLECTION_RE.match(coll):
                    raise RetrievalSystemError("alias", retries.total)
                kb_version = coll.removeprefix("kb_")
                stage.value = "pipeline"
                try:
                    meta = await self._call(self._index.get_metadata, coll, retries=retries)
                except CollectionNotFound:
                    raise RetrievalSystemError("alias", retries.total, kb_version=kb_version) from None
                except _Transient as e:
                    raise RetrievalSystemError(
                        "search", retries.total, kb_version=kb_version, detail=str(e)
                    ) from e
                if meta.get("pipeline_sha") != self._pipeline_sha:
                    raise RetrievalSystemError("pipeline", retries.total, kb_version=kb_version)
                stage.value = "embed"
                dense, sparse = await self._embed(q, retries, kb_version)
                first = await self._search(
                    coll, q, ctx.role, use_intent=bool(q.intent), dense=dense, sparse=sparse,
                    retries=retries, kb_version=kb_version, stage=stage,
                )  # fmt: skip
                if first.top_score < self._threshold and q.intent and self._cfg.intent_fallback:  # D-23
                    alt = await self._search(
                        coll, q, ctx.role, use_intent=False, dense=dense, sparse=sparse,
                        retries=retries, kb_version=kb_version, stage=stage,
                    )  # fmt: skip
                    if alt.top_score >= self._threshold:
                        return alt.finish(kb_version, fallback=True, tried=True, retries=retries.total)
                    return first.finish(kb_version, fallback=False, tried=True, retries=retries.total)
                return first.finish(kb_version, fallback=False, tried=False, retries=retries.total)
        except TimeoutError:
            raise RetrievalSystemError(
                stage.value, retries.total, kb_version=kb_version, detail="deadline"
            ) from None

    async def _embed(self, q: RetrievalQuery, retries: _Counter, kb_version: str) -> tuple[list[float], Any]:
        emb = await self._ml.embed([q.text])
        retries.add(emb.attempts, failed=emb.error is not None)
        if emb.error is not None:
            raise RetrievalSystemError("embed", retries.total, kb_version=kb_version)
        assert emb.data is not None
        dense = emb.data.vectors[0]
        sparse = to_sparse(tokenize_vi(q.text, lexicon=self._lexicon))
        return dense, sparse

    async def _search(
        self,
        coll: str,
        q: RetrievalQuery,
        role: str,
        *,
        use_intent: bool,
        dense: list[float],
        sparse: Any,
        retries: _Counter,
        kb_version: str,
        stage: _StageBox,
    ) -> _Partial:
        stage.value = "search"
        extra = [intent_filter(q.intent)] if use_intent and q.intent is not None else []
        flt = query_filter(role, *extra)
        try:
            hits = await self._call(
                self._index.hybrid_query, coll, dense, sparse, flt, self._cfg.prefetch_k, self._cfg.rerank_k,
                retries=retries,
            )  # fmt: skip
        except CollectionNotFound:
            raise RetrievalSystemError("alias", retries.total, kb_version=kb_version) from None
        except _Transient as e:
            raise RetrievalSystemError("search", retries.total, kb_version=kb_version, detail=str(e)) from e
        if not hits:  # RỖNG ≠ LỖI → không gọi rerank, B9 xử lý E3
            return _Partial(chunks=[], top_score=0.0, query_truncated=False)
        stage.value = "rerank"
        rr = await self._ml.rerank(q.text, [(hit.payload or {})["text"] for hit in hits])
        retries.add(rr.attempts, failed=rr.error is not None)
        if rr.error is not None:
            raise RetrievalSystemError("rerank", retries.total, kb_version=kb_version)
        assert rr.data is not None
        if any(rr.data.truncated):  # đoạn tài liệu bị cắt = vi phạm D-21 → E9
            raise ChunkTruncatedError(f"rerank cắt đoạn tài liệu ở {coll}")
        if len(rr.data.scores) != len(hits):  # hợp đồng
            raise ValueError(f"rerank trả {len(rr.data.scores)} điểm cho {len(hits)} đoạn")
        chunks = rank_and_dedupe(hits, rr.data.scores, self._cfg.top_n)
        top_score = chunks[0].score if chunks else 0.0
        return _Partial(chunks=chunks, top_score=top_score, query_truncated=rr.data.query_truncated)

    async def search_once(
        self, q: RetrievalQuery, ctx: RequesterContext, *, collection: str, use_intent: bool
    ) -> tuple[list[ChunkRef], float]:
        """Chỉ cho `eval_cli --sweep`: bước 2–4 của `retrieve` (không đọc alias; vẫn kiểm `pipeline_sha`) + một
        `_search`. Cùng lọc quyền."""
        retries = _Counter()
        kb_version = collection.removeprefix("kb_")
        meta = await self._call(self._index.get_metadata, collection, retries=retries)
        if meta.get("pipeline_sha") != self._pipeline_sha:
            raise RetrievalSystemError("pipeline", retries.total, kb_version=kb_version)
        dense, sparse = await self._embed(q, retries, kb_version)
        partial = await self._search(
            collection, q, ctx.role, use_intent=use_intent, dense=dense, sparse=sparse,
            retries=retries, kb_version=kb_version, stage=_StageBox("search"),
        )  # fmt: skip
        return partial.chunks, partial.top_score

    async def expand_for_answer(
        self, chunks: list[ChunkRef], ctx: RequesterContext, *, kb_version: str, max_tokens: int | None = None
    ) -> list[EvidenceBlock]:
        # Nạp muộn: tránh vòng import module (expand.py nhập ngược `_Counter`/`_Transient`/`content_of` từ đây).
        from app.rag.expand import expand

        return await expand(self, chunks, ctx, kb_version=kb_version, max_tokens=max_tokens)
