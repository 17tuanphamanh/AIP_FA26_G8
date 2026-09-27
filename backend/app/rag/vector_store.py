"""Port `VectorIndex` + `QdrantIndex` (thiết kế Phase 3 mục 5.7; PLAN-3b mục 4.7).

- Collection `kb_<64 hex>`: vector dense 1024 chiều cosine + sparse `bm25` (IDF), 6 payload index.
- Đổi alias NGUYÊN TỬ: đúng MỘT lời gọi `update_collection_aliases([DeleteAlias?, CreateAlias])` — không bao giờ
  xoá rồi tạo bằng hai lệnh (khe giữa hai lệnh là lúc không có KB nào). M-3b-5 kiểm bằng review + test spy.
- Không retry (ingest chạy tay): lỗi Qdrant đổi thành `VectorStoreError` kèm thao tác, pipeline in rồi trả mã 1/2.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import httpx
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from qdrant_client.models import (
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    Distance,
    Filter,
    Modifier,
    PayloadSchemaType,
    PointStruct,
    ScoredPoint,
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


@contextmanager
def _qdrant(op: str) -> Iterator[None]:
    try:
        yield
    except (UnexpectedResponse, ResponseHandlingException, httpx.HTTPError) as e:
        raise VectorStoreError(f"Qdrant {op}: {type(e).__name__}: {e}") from e


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
    async def query_dense(self, name: str, vector: list[float], flt: Filter, limit: int) -> list[ScoredPoint]: ...


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

    async def query_dense(self, name: str, vector: list[float], flt: Filter, limit: int) -> list[ScoredPoint]:
        with _qdrant(f"query {name}"):
            result = await self._client.query_points(
                name, query=vector, using=DENSE, query_filter=flt, limit=limit, with_payload=True
            )
        return list(result.points)
