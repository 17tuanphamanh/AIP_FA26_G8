"""Repository `kb_versions` / `kb_documents` cho RAG ingest (thiết kế Phase 3 mục 5.8 bước 4, 5, 12, 14;
PLAN-3b mục 4.9).

`write_version` — MỘT transaction, thứ tự bắt buộc (FK `kb_documents.kb_version` và index duy nhất
`ux_kb_versions_current` kiểm NGAY từng câu, không hoãn):
  1. tắt `is_current` của bản khác;
  2. upsert `kb_versions` với `is_current = true` (bản quay lại dùng lại dòng cũ, giữ `created_at` — Q-3b-15);
  3. upsert `kb_documents` (enabled → `kb_version = v`; disabled → NULL — Q-3b-2).
Khoá advisory cấp session (`try_lock`) chặn hai lượt ingest chạy cùng lúc (Q-3b-15).
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime

from sqlalchemy import ColumnElement, Table, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.models import KbDocument, KbVersion, User

_VERSIONS: Table = KbVersion.__table__  # type: ignore[assignment]
_DOCS: Table = KbDocument.__table__  # type: ignore[assignment]
_USERS: Table = User.__table__  # type: ignore[assignment]


@dataclass(frozen=True)
class KbVersionRow:
    kb_version: str
    created_at: datetime
    doc_count: int
    chunk_count: int | None
    recall_at5: float | None
    false_grounding_rate: float | None
    eval_status: str
    is_current: bool


@dataclass(frozen=True)
class DocRow:
    doc_id: str
    version: int
    title: str
    request_type: str
    doc_type: str
    owner: str | None  # NULL khi user chưa có trong `users` (3-Q40)
    updated_at: date
    sensitivity: str
    enabled: bool
    distractor: bool
    content_sha256: str
    kb_version: str | None


_VERSION_COLUMNS = tuple(KbVersionRow.__dataclass_fields__)


class KbRepo:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def doc_rows(self, keys: list[tuple[str, int]]) -> dict[tuple[str, int], str | None]:
        """sha đã ghi theo `(doc_id, version)` — chỉ các khoá có dòng."""
        if not keys:
            return {}
        stmt = select(_DOCS.c.doc_id, _DOCS.c.version, _DOCS.c.content_sha256).where(
            tuple_(_DOCS.c.doc_id, _DOCS.c.version).in_(keys)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return {(r.doc_id, r.version): r.content_sha256 for r in rows}

    async def _version(self, where: ColumnElement[bool]) -> KbVersionRow | None:
        stmt = select(*(_VERSIONS.c[c] for c in _VERSION_COLUMNS)).where(where)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return KbVersionRow(**row._mapping) if row else None

    async def current(self) -> KbVersionRow | None:
        return await self._version(_VERSIONS.c.is_current.is_(True))

    async def version_row(self, v: str) -> KbVersionRow | None:
        return await self._version(_VERSIONS.c.kb_version == v)

    async def known_users(self, ids: Iterable[str]) -> set[str]:
        wanted = sorted(set(ids))
        if not wanted:
            return set()
        async with self._engine.connect() as conn:
            rows = await conn.execute(select(_USERS.c.user_id).where(_USERS.c.user_id.in_(wanted)))
        return {r[0] for r in rows}

    async def created_order(self) -> dict[str, datetime]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(select(_VERSIONS.c.kb_version, _VERSIONS.c.created_at))
        return {r[0]: r[1] for r in rows}

    async def write_version(
        self, v: str, *, doc_count: int, chunk_count: int, recall: float | None, fg: float | None,
        eval_status: str, docs: list[DocRow],
    ) -> None:  # fmt: skip
        values = {
            "doc_count": doc_count, "chunk_count": chunk_count, "recall_at5": recall,
            "false_grounding_rate": fg, "eval_status": eval_status, "is_current": True,
        }  # fmt: skip
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_VERSIONS).where(_VERSIONS.c.is_current, _VERSIONS.c.kb_version != v).values(is_current=False)
            )
            ins = insert(_VERSIONS).values(kb_version=v, **values)
            await conn.execute(ins.on_conflict_do_update(index_elements=["kb_version"], set_=values))
            if docs:
                rows = [asdict(d) for d in docs]
                ins_docs = insert(_DOCS).values(rows)
                keep = {c: ins_docs.excluded[c] for c in rows[0] if c not in ("doc_id", "version")}
                await conn.execute(ins_docs.on_conflict_do_update(index_elements=["doc_id", "version"], set_=keep))

    async def try_lock(self, key: int) -> AsyncConnection | None:
        """Khoá advisory cấp session trên connection RIÊNG; không lấy được → None. Nhả bằng `release`."""
        conn = await self._engine.connect()
        try:
            got = bool((await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key})).scalar_one())
            await conn.commit()  # kết thúc transaction ngầm; khoá cấp session vẫn giữ
        except BaseException:
            await conn.close()
            raise
        if not got:
            await conn.close()
            return None
        return conn

    async def release(self, conn: AsyncConnection, key: int) -> None:
        try:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            await conn.commit()
        finally:
            await conn.close()
