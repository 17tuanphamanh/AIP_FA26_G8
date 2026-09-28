"""Port `VectorIndex` + `QdrantIndex` (thiết kế Phase 3 mục 5.7, 6.2 [3c]; PLAN-3b mục 4.7, PLAN-3c mục 3.2).

- Collection `kb_<64 hex>`: vector dense 1024 chiều cosine + sparse `bm25` (IDF), 6 payload index.
- Đổi alias NGUYÊN TỬ: đúng MỘT lời gọi `update_collection_aliases([DeleteAlias?, CreateAlias])` — không bao giờ
  xoá rồi tạo bằng hai lệnh (khe giữa hai lệnh là lúc không có KB nào). M-3b-5 kiểm bằng review + test spy.
- Ingest (3b) không retry (chạy tay): lỗi Qdrant đổi thành `VectorStoreError` kèm thao tác, pipeline in rồi trả mã
  1/2. Truy hồi (3c, `Retriever._call`) CÓ retry ở tầng trên — `_classify` phân biệt lỗi tạm thời
  (`VectorStoreTransient`, retry được) với 404 (`CollectionNotFound`, không retry — collection bị dọn) và lỗi hợp
  đồng khác (`VectorStoreError` gốc, nổi lên thành E9). Bản thân `vector_store` KHÔNG retry, không tự dựng `Filter`
  (chỉ nhận từ bên gọi, `rag/filters.py`).
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import httpx
from qdrant_client import AsyncQdrantClient
from qdrant_client.common.client_exceptions import ResourceExhaustedResponse
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from qdrant_client.models import (
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    Distance,
    Filter,
    Fusion,
    FusionQuery,
    Modifier,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    Record,
    ScoredPoint,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from app.rag.ingest.config import COLLECTION_RE, DENSE_DIM

DENSE = "dense"
SPARSE = "bm25"
PAYLOAD_INDEXES: dict[str, PayloadSchemaType] = {
    "request_type": PayloadSchemaType.KEYWORD,
    "sensitivity": PayloadSchemaType.KEYWORD,
    "doc_id": PayloadSchemaType.KEYWORD,
    "doc_type": PayloadSchemaType.KEYWORD,
    "enabled": PayloadSchemaType.BOOL,
    "seq": PayloadSchemaType.INTEGER,
}
_COLLECTION = re.compile(COLLECTION_RE)


class VectorStoreError(Exception):
    """Qdrant lỗi (mạng, HTTP, phản hồi hỏng) — lỗi dự kiến của ingest, không phải bug."""


class VectorStoreTransient(VectorStoreError):
    """Lỗi tạm thời (transport, timeout, 5xx, 429) — `Retriever._call` (3c) coi là retry được."""


class CollectionNotFound(VectorStoreError):
    """HTTP 404 — collection không tồn tại (bị dọn giữa chừng) — KHÔNG retry."""


def _classify(op: str, e: Exception) -> VectorStoreError:
    msg = f"Qdrant {op}: {type(e).__name__}: {e}"
    if isinstance(e, ResponseHandlingException) and isinstance(e.source, httpx.TransportError):
        return VectorStoreTransient(msg)
    if isinstance(e, ResourceExhaustedResponse):
        return VectorStoreTransient(msg)
    if isinstance(e, UnexpectedResponse):
        if e.status_code == 404:
            return CollectionNotFound(msg)
        if e.status_code is not None and (e.status_code >= 500 or e.status_code == 429):
            return VectorStoreTransient(msg)
        return VectorStoreError(msg)
    if isinstance(e, httpx.TransportError):
        return VectorStoreTransient(msg)
    return VectorStoreError(msg)


@contextmanager
def _qdrant(op: str) -> Iterator[None]:
    try:
        yield
    except (UnexpectedResponse, ResponseHandlingException, ResourceExhaustedResponse, httpx.HTTPError) as e:
        raise _classify(op, e) from e


class VectorIndex(Protocol):
    async def alias_target(self, alias: str) -> str | None: ...
    async def list_kb_collections(self) -> list[str]: ...
    async def exists(self, name: str) -> bool: ...
    async def create(self, name: str, metadata: dict[str, Any]) -> None: ...
    async def drop(self, name: str) -> None: ...
    async def upsert(self, name: str, points: list[PointStruct]) -> None: ...
    async def count(self, name: str) -> int: ...
    async def get_metadata(self, name: str) -> dict[str, Any]: ...
    async def set_metadata(self, name: str, metadata: dict[str, Any]) -> None: ...
    async def switch_alias(self, alias: str, target: str, *, had_alias: bool) -> None: ...
    async def snapshot(self, name: str) -> str: ...
    async def payload_index_fields(self, name: str) -> set[str]: ...
    async def hybrid_query(
        self, name: str, dense: list[float], sparse: SparseVector, flt: Filter, prefetch_k: int, limit: int
    ) -> list[ScoredPoint]: ...
    async def scroll_window(self, name: str, flt: Filter, limit: int) -> list[Record]: ...


class QdrantIndex:
    def __init__(self, client: AsyncQdrantClient) -> None:
        self._client = client  # người dựng tự đóng

    async def alias_target(self, alias: str) -> str | None:
        with _qdrant("get_aliases"):
            aliases = (await self._client.get_aliases()).aliases
        return next((a.collection_name for a in aliases if a.alias_name == alias), None)

    async def list_kb_collections(self) -> list[str]:
        with _qdrant("get_collections"):
            collections = (await self._client.get_collections()).collections
        return sorted(c.name for c in collections if _COLLECTION.match(c.name))

    async def exists(self, name: str) -> bool:
        with _qdrant("collection_exists"):
            return await self._client.collection_exists(name)

    async def create(self, name: str, metadata: dict[str, Any]) -> None:
        with _qdrant(f"create {name}"):
            await self._client.create_collection(
                name,
                vectors_config={DENSE: VectorParams(size=DENSE_DIM, distance=Distance.COSINE)},
                sparse_vectors_config={SPARSE: SparseVectorParams(modifier=Modifier.IDF)},
                metadata=metadata,
            )
            for field, schema in PAYLOAD_INDEXES.items():
                await self._client.create_payload_index(name, field, field_schema=schema, wait=True)

    async def drop(self, name: str) -> None:
        with _qdrant(f"drop {name}"):
            for snap in await self._client.list_snapshots(name):
                await self._client.delete_snapshot(name, snap.name, wait=True)
            await self._client.delete_collection(name)

    async def upsert(self, name: str, points: list[PointStruct]) -> None:
        with _qdrant(f"upsert {name}"):
            await self._client.upsert(name, points=points, wait=True)

    async def count(self, name: str) -> int:
        with _qdrant(f"count {name}"):
            return (await self._client.count(name, exact=True)).count

    async def get_metadata(self, name: str) -> dict[str, Any]:
        with _qdrant(f"get_collection {name}"):
            info = await self._client.get_collection(name)
        return dict(info.config.metadata or {})

    async def set_metadata(self, name: str, metadata: dict[str, Any]) -> None:
        merged = {**await self.get_metadata(name), **metadata}
        with _qdrant(f"update_collection {name}"):
            await self._client.update_collection(name, metadata=merged)

    async def switch_alias(self, alias: str, target: str, *, had_alias: bool) -> None:
        ops: list[DeleteAliasOperation | CreateAliasOperation] = []
        if had_alias:
            ops.append(DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias)))
        ops.append(CreateAliasOperation(create_alias=CreateAlias(collection_name=target, alias_name=alias)))
        with _qdrant(f"đổi alias {alias} → {target}"):
            await self._client.update_collection_aliases(change_aliases_operations=ops)  # MỘT lệnh, nguyên tử

    async def snapshot(self, name: str) -> str:
        with _qdrant(f"snapshot {name}"):
            snap = await self._client.create_snapshot(name, wait=True)
        if snap is None:
            raise VectorStoreError(f"Qdrant snapshot {name}: không trả mô tả snapshot")
        return snap.name

    async def payload_index_fields(self, name: str) -> set[str]:
        with _qdrant(f"get_collection {name}"):
            info = await self._client.get_collection(name)
        return set(info.payload_schema or {})

    async def hybrid_query(
        self, name: str, dense: list[float], sparse: SparseVector, flt: Filter, prefetch_k: int, limit: int
    ) -> list[ScoredPoint]:
        with _qdrant(f"query {name}"):
            result = await self._client.query_points(
                name,
                prefetch=[
                    Prefetch(query=dense, using=DENSE, limit=prefetch_k, filter=flt),
                    Prefetch(query=sparse, using=SPARSE, limit=prefetch_k, filter=flt),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=limit,
                with_payload=True,
            )
        return list(result.points)

    async def scroll_window(self, name: str, flt: Filter, limit: int) -> list[Record]:
        with _qdrant(f"scroll {name}"):
            points, _ = await self._client.scroll(
                name, scroll_filter=flt, limit=limit, with_payload=True, with_vectors=False
            )
        return list(points)
