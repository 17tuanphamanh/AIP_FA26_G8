"""`FakeRag` (bản giả `RagPort`, dùng ở node `b08_retrieve` test — S6) và `SpyIndex` (`VectorIndex` giả trong tiến
trình, dùng ở test `Retriever` — S5).

`SpyIndex` KHÔNG mô phỏng dense/sparse fusion thật (RRF) — điểm mỗi `SpyPoint` do test tự gán, `hybrid_query` chỉ
lọc theo `Filter` (đúng ngữ nghĩa `MatchValue`/`MatchAny`/`Range`, đủ cho `base_filter`/`intent_filter`/`expand`)
rồi sắp theo điểm giảm dần. Dùng khi test chỉ cần kiểm CƠ CHẾ của `Retriever` (retry, deadline, ghim collection,
lọc quyền đúng field) — chất lượng xếp hạng thật kiểm ở test tích hợp trên Qdrant thật (c4–c10, S10).
"""

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef
from app.rag.models import (
    EvidenceBlock,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSystemError,
)
from app.rag.vector_store import CollectionNotFound
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    Record,
    ScoredPoint,
)

# ---- FakeRag (RagPort) --------------------------------------------------------------------------


@dataclass
class FakeRag:
    result: RetrievalResult | None = None
    error: RetrievalSystemError | None = None
    evidence: list[EvidenceBlock] = field(default_factory=list)
    retrieve_calls: list[tuple[RetrievalQuery, RequesterContext]] = field(default_factory=list)
    expand_calls: list[tuple[list[ChunkRef], RequesterContext]] = field(default_factory=list)

    async def retrieve(
        self, q: RetrievalQuery, ctx: RequesterContext, *, collection: str | None = None
    ) -> RetrievalResult:
        self.retrieve_calls.append((q, ctx))
        if self.error is not None:
            raise self.error
        assert self.result is not None, "FakeRag.result chưa gán"
        return self.result

    async def expand_for_answer(
        self, chunks: list[ChunkRef], ctx: RequesterContext, *, kb_version: str, max_tokens: int | None = None
    ) -> list[EvidenceBlock]:
        self.expand_calls.append((chunks, ctx))
        return self.evidence


# ---- SpyIndex (VectorIndex) ----------------------------------------------------------------------


@dataclass
class SpyPoint:
    id: str
    payload: dict[str, Any]
    score: float = 0.0


@dataclass
class _Coll:
    points: list[SpyPoint] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _condition_matches(payload: dict[str, Any], cond: FieldCondition) -> bool:
    val = payload.get(cond.key)
    if cond.match is not None:
        m = cond.match
        if isinstance(m, MatchValue) and val != m.value:
            return False
        if isinstance(m, MatchAny) and val not in m.any:
            return False
    if cond.range is not None:
        r = cond.range
        if r.gte is not None and not (val is not None and val >= r.gte):
            return False
        if r.lte is not None and not (val is not None and val <= r.lte):
            return False
    return True


def _flt_matches(payload: dict[str, Any], flt: Filter) -> bool:
    return all(_condition_matches(payload, c) for c in (flt.must or []) if isinstance(c, FieldCondition))


class SpyIndex:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.filters: list[Filter] = []
        self._collections: dict[str, _Coll] = {}
        self._alias: dict[str, str] = {}
        self._faults: dict[str, list[Exception]] = {}
        self._delays: dict[str, list[float]] = {}

    # ---- cấu hình test (đồng bộ) ----

    def add_collection(self, name: str, *, metadata: dict[str, Any] | None = None) -> None:
        self._collections[name] = _Coll(metadata=dict(metadata or {}))

    def add_points(self, name: str, points: list[SpyPoint]) -> None:
        self._collections.setdefault(name, _Coll()).points.extend(points)

    def set_alias(self, alias: str, target: str | None) -> None:
        if target is None:
            self._alias.pop(alias, None)
        else:
            self._alias[alias] = target

    def fail_next(self, method: str, exc: Exception, times: int = 1) -> "SpyIndex":
        self._faults.setdefault(method, []).extend([exc] * times)
        return self

    def delay_next(self, method: str, seconds: float, times: int = 1) -> "SpyIndex":
        self._delays.setdefault(method, []).extend([seconds] * times)
        return self

    async def _hook(self, method: str) -> None:
        self.calls[method] += 1
        delays = self._delays.get(method)
        if delays:
            await asyncio.sleep(delays.pop(0))
        faults = self._faults.get(method)
        if faults:
            raise faults.pop(0)

    def _coll(self, name: str) -> _Coll:
        coll = self._collections.get(name)
        if coll is None:
            raise CollectionNotFound(f"SpyIndex: khong co collection {name}")
        return coll

    # ---- VectorIndex ----

    async def alias_target(self, alias: str) -> str | None:
        await self._hook("alias_target")
        return self._alias.get(alias)

    async def list_kb_collections(self) -> list[str]:
        await self._hook("list_kb_collections")
        return sorted(self._collections)

    async def exists(self, name: str) -> bool:
        await self._hook("exists")
        return name in self._collections

    async def create(self, name: str, metadata: dict[str, Any]) -> None:
        await self._hook("create")
        self._collections[name] = _Coll(metadata=dict(metadata))

    async def drop(self, name: str) -> None:
        await self._hook("drop")
        self._collections.pop(name, None)

    async def upsert(self, name: str, points: list[Any]) -> None:
        raise NotImplementedError("SpyIndex: dùng add_points(), không dùng upsert() kiểu Qdrant thật")

    async def count(self, name: str) -> int:
        await self._hook("count")
        return len(self._coll(name).points)

    async def get_metadata(self, name: str) -> dict[str, Any]:
        await self._hook("get_metadata")
        return dict(self._coll(name).metadata)

    async def set_metadata(self, name: str, metadata: dict[str, Any]) -> None:
        await self._hook("set_metadata")
        self._coll(name).metadata.update(metadata)

    async def switch_alias(self, alias: str, target: str, *, had_alias: bool) -> None:
        await self._hook("switch_alias")
        self._alias[alias] = target

    async def snapshot(self, name: str) -> str:
        raise NotImplementedError("SpyIndex: không mô phỏng snapshot")

    async def payload_index_fields(self, name: str) -> set[str]:
        await self._hook("payload_index_fields")
        return set()

    async def hybrid_query(
        self, name: str, dense: list[float], sparse: Any, flt: Filter, prefetch_k: int, limit: int
    ) -> list[ScoredPoint]:
        await self._hook("hybrid_query")
        self.filters.append(flt)
        pts = [p for p in self._coll(name).points if _flt_matches(p.payload, flt)]
        pts.sort(key=lambda p: -p.score)
        return [ScoredPoint(id=p.id, version=0, score=p.score, payload=p.payload) for p in pts[:limit]]

    async def scroll_window(self, name: str, flt: Filter, limit: int) -> list[Record]:
        await self._hook("scroll_window")
        self.filters.append(flt)
        pts = [p for p in self._coll(name).points if _flt_matches(p.payload, flt)]
        return [Record(id=p.id, payload=p.payload) for p in pts[:limit]]
