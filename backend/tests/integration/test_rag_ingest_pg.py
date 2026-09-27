"""b11–b19, b31–b35 — `run_ingest` trên Qdrant + Postgres 16 thật, `FakeMlService` sau `MlClient` thật (thiết kế
Phase 3 mục 5.8, 5.11; PLAN-3b mục 7, 9.1). Mỗi test làm việc trên bản sao fixture trong `tmp_path` và bắt đầu từ Qdrant
trống, bảng kb_* trống (`clean_qdrant`)."""

import io
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from app.core.clock import FakeClock
from app.db.kb import KbRepo
from app.rag.ingest import cli
from app.rag.ingest.config import ALIAS, INGEST_LOCK_KEY
from app.rag.ingest.kbversion import pipeline_sha
from app.rag.ingest.pipeline import IngestDeps, IngestOptions, run_ingest
from app.rag.token_counter import MlTokenCounter
from app.rag.vector_store import PAYLOAD_INDEXES, QdrantIndex
from app.settings import Settings
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.kb import CONFIG_DIR, KB_TEST_NOW, copy_kb, set_version
from tests.integration.pg import PgUrls


@dataclass
class Result:
    code: int
    out: str
    err: str


class Env:
    """Deps thật (Qdrant, Postgres app_rw) + ml-service giả; mỗi lượt `run` có stdout/stderr riêng."""

    def __init__(self, qdrant: AsyncQdrantClient, repo: KbRepo, fake: FakeMlService) -> None:
        self.qdrant = qdrant
        self.index = QdrantIndex(qdrant)
        self.repo = repo
        self.fake = fake

    def deps(self, *, app_env: str = "test", config_dir: Path = CONFIG_DIR, fake: FakeMlService | None = None,
             repo: KbRepo | None = None) -> IngestDeps:  # fmt: skip
        ml = (fake or self.fake).client()
        return IngestDeps(
            index=self.index, ml=ml, counter=MlTokenCounter(ml), repo=repo or self.repo, clock=FakeClock(KB_TEST_NOW),
            app_env=app_env, retrieval_threshold=0.6, keep_old=2, config_dir=config_dir, out=io.StringIO(),
            err=io.StringIO(),
        )  # fmt: skip

    async def run(self, kb: Path, deps: IngestDeps | None = None, **opts: bool) -> Result:
        d = deps or self.deps()
        code = await run_ingest(IngestOptions(kb, **opts), d)
        return Result(code, d.out.getvalue(), d.err.getvalue())  # type: ignore[attr-defined]


@asynccontextmanager
async def _env(qdrant_url: str, pg: PgUrls, fake: FakeMlService | None = None) -> AsyncIterator[Env]:
    qdrant = AsyncQdrantClient(url=qdrant_url, timeout=60)
    engine = create_async_engine(pg.role("app_rw"), pool_size=2)
    try:
        yield Env(qdrant, KbRepo(engine), fake or FakeMlService())
    finally:
        await qdrant.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def env(clean_qdrant: str, migrated: PgUrls) -> AsyncIterator[Env]:
    async with _env(clean_qdrant, migrated) as e:
        yield e


def _scalar(rw: Engine, sql: str, **params: object) -> object:
    with rw.connect() as conn:
        return conn.execute(text(sql), params).scalar()


async def _current(env: Env) -> str | None:
    return await env.index.alias_target(ALIAS)


# ---- b11 --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b11_same_version_changed_content_stops(env: Env, rw: Engine, tmp_path: Path) -> None:
    v0 = "0" * 64
    with rw.begin() as conn:  # dòng cũ cùng (KB-VPN-003, 1) nhưng sha khác
        conn.execute(text("INSERT INTO kb_versions (kb_version, doc_count) VALUES (:v, 1)"), {"v": v0})
        conn.execute(text(
            "INSERT INTO kb_documents (doc_id, version, title, request_type, doc_type, updated_at, sensitivity, "
            "kb_version, content_sha256) VALUES ('KB-VPN-003', 1, 'cũ', 'vpn', 'troubleshooting', '2026-09-01', "
            "'internal', :v, :sha)"
        ), {"v": v0, "sha": "f" * 64})  # fmt: skip
    r = await env.run(copy_kb(tmp_path), allow_unevaluated=True)
    assert r.code == 1
    assert "KB-VPN-003 v1: nội dung đã đổi nhưng chưa tăng version" in r.err
    assert await env.index.list_kb_collections() == []
    assert await _current(env) is None


# ---- b12, b13 -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b12_first_ingest_unevaluated(env: Env, rw: Engine, tmp_path: Path) -> None:
    r = await env.run(copy_kb(tmp_path, with_eval=False), allow_unevaluated=True)
    assert r.code == 0, r.err
    name = await _current(env)
    assert name is not None and name.startswith("kb_") and f"kb_version={name[3:]}" in r.out
    n_chunks = int(_scalar(rw, "SELECT chunk_count FROM kb_versions WHERE kb_version = :v", v=name[3:]))  # type: ignore[arg-type]
    assert await env.index.count(name) == n_chunks > 0
    assert f"số đoạn: {n_chunks}" in r.out and "truncated=0" in r.out
    assert await env.index.payload_index_fields(name) == set(PAYLOAD_INDEXES)
    no_002 = Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value="KB-VPN-002"))])
    assert (await env.qdrant.count(name, count_filter=no_002, exact=True)).count == 0
    meta = await env.index.get_metadata(name)
    assert meta["pipeline_sha"] == pipeline_sha(CONFIG_DIR) and meta["eval_status"] == "unevaluated"
    with rw.connect() as conn:
        row = conn.execute(text("SELECT eval_status, is_current, doc_count, recall_at5 FROM kb_versions")).one()
        docs = dict(conn.execute(text("SELECT doc_id, kb_version FROM kb_documents")).all())
        owners = set(conn.execute(text("SELECT owner FROM kb_documents")).scalars())
    assert tuple(row) == ("unevaluated", True, 5, None)
    assert len(docs) == 6 and docs["KB-VPN-002"] is None and docs["KB-VPN-001"] == name[3:]
    assert owners == {None}
    assert "owner it_mgr01 chưa có trong bảng users" in r.err


@pytest.mark.asyncio
async def test_b13_rerun_unchanged(env: Env, tmp_path: Path) -> None:
    kb = copy_kb(tmp_path, with_eval=False)
    assert (await env.run(kb, allow_unevaluated=True)).code == 0
    before = await env.index.list_kb_collections()
    embeds = env.fake.calls["embed"]
    r = await env.run(kb, allow_unevaluated=True)
    assert r.code == 0 and "KB không đổi" in r.out
    assert await env.index.list_kb_collections() == before
    assert env.fake.calls["embed"] == embeds


# ---- b14 ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b14_three_bumps_keep_two_old(env: Env, tmp_path: Path) -> None:
    kb = copy_kb(tmp_path, with_eval=False)
    assert (await env.run(kb, allow_unevaluated=True)).code == 0
    seen = [await _current(env)]
    for version in (2, 3, 4):
        set_version(kb, "KB-VPN-001", version)
        r = await env.run(kb, allow_unevaluated=True)
        assert r.code == 0, r.err
        seen.append(await _current(env))
    assert len(set(seen)) == 4  # mỗi lần alias đổi
    assert await env.index.list_kb_collections() == sorted(seen[1:])  # đích alias + đúng 2 bản trước
    assert seen[0] is not None and seen[0] in r.out  # dòng "dọn: đã xoá kb_<bản đầu>"


# ---- b15, b16 -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b15_no_eval_no_flag_keeps_alias(env: Env, tmp_path: Path) -> None:
    kb = copy_kb(tmp_path, with_eval=False)
    r = await env.run(kb)
    assert r.code == 1 and "nhánh a" in r.err
    assert await _current(env) is None
    # ca có alias cũ
    assert (await env.run(kb, allow_unevaluated=True)).code == 0
    old = await _current(env)
    set_version(kb, "KB-VPN-001", 2)
    r = await env.run(kb)
    assert r.code == 1
    assert await _current(env) == old


@pytest.mark.asyncio
async def test_b16_prod_rejects_flag(env: Env, tmp_path: Path) -> None:
    fake = FakeMlService()
    r = await env.run(copy_kb(tmp_path), env.deps(app_env="prod", fake=fake), allow_unevaluated=True)
    assert r.code == 1 and "bước 0" in r.err
    assert not fake.calls
    assert await env.index.list_kb_collections() == []


# ---- b17 ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b17_gate_c_recall_drop(env: Env, tmp_path: Path) -> None:
    kb = copy_kb(tmp_path)
    first = await env.run(kb)
    assert first.code == 0, first.err
    assert "nhánh b" in first.out and "Recall@5 1.000" in first.out and "trả lời bừa 0.000" in first.out
    old = await _current(env)
    set_version(kb, "KB-VPN-004", 2, enabled=False)  # tắt 004 (đổi enabled phải tăng version — Q-3b-2)
    r = await env.run(kb)
    assert r.code == 1 and "nhánh c" in r.err
    assert "Recall@5 0.875" in r.out and "(đổi -0.125)" in r.out
    assert await _current(env) == old
    assert len(await env.index.list_kb_collections()) == 2  # collection mới giữ lại để xem


# ---- b18 ------------------------------------------------------------------------------------------


class _DiesOnce(KbRepo):
    def __init__(self, inner: KbRepo) -> None:
        self.__dict__.update(inner.__dict__)
        self.died = False

    async def write_version(self, *args: object, **kwargs: object) -> None:
        if not self.died:
            self.died = True
            raise RuntimeError("chết giả")
        await super().write_version(*args, **kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_b18_crash_between_alias_and_db(env: Env, rw: Engine, tmp_path: Path) -> None:
    kb = copy_kb(tmp_path)
    with pytest.raises(RuntimeError, match="chết giả") as e:
        await env.run(kb, env.deps(repo=_DiesOnce(env.repo)))
    assert "ingest: lỗi ở bước 12" in e.value.__notes__
    name = await _current(env)
    assert name is not None
    assert _scalar(rw, "SELECT count(*) FROM kb_versions") == 0
    r = await env.run(kb)
    assert r.code == 0 and "đã ghi bù" in r.out
    assert _scalar(rw, "SELECT count(*) FROM kb_versions WHERE is_current") == 1
    meta = await env.index.get_metadata(name)
    with rw.connect() as conn:
        row = conn.execute(text("SELECT kb_version, recall_at5, false_grounding_rate, chunk_count FROM kb_versions")).one()
    assert tuple(row) == (name[3:], meta["recall_at5"], meta["false_grounding_rate"], meta["chunk_count"])
    assert _scalar(rw, "SELECT count(*) FROM kb_documents") == 6


# ---- b19 ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b19_truncate_all_stops_at_step7(env: Env, tmp_path: Path) -> None:
    r = await env.run(copy_kb(tmp_path), env.deps(fake=FakeMlService(truncate_all=True)))
    assert r.code == 1 and "bước 7" in r.err and "truncated" in r.err
    assert await env.index.list_kb_collections() == []


# ---- b31–b35 --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b31_dry_run_writes_nothing(env: Env, rw: Engine, tmp_path: Path) -> None:
    other = rw.connect()
    try:  # dry-run không lấy khoá: khoá đang bị giữ mà vẫn chạy được
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": INGEST_LOCK_KEY})
        r = await env.run(copy_kb(tmp_path), dry_run=True)
    finally:
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": INGEST_LOCK_KEY})
        other.close()
    assert r.code == 0, r.err
    assert "số đoạn: " in r.out and "dry-run" in r.out
    assert await env.index.list_kb_collections() == []
    assert _scalar(rw, "SELECT count(*) FROM kb_versions") == 0
    assert _scalar(rw, "SELECT count(*) FROM kb_documents") == 0


@pytest.mark.asyncio
async def test_b32_pipeline_sha_changed(env: Env, tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, cfg)
    kb = copy_kb(tmp_path)
    assert (await env.run(kb, env.deps(config_dir=cfg))).code == 0
    with (cfg / "vi_stopwords.txt").open("a", encoding="utf-8") as f:
        f.write("thêm\n")
    r = await env.run(kb, env.deps(config_dir=cfg))
    assert r.code == 1 and "cấu hình ingest đã đổi" in r.err


@pytest.mark.asyncio
async def test_b33_concurrent_ingest_locked(env: Env, rw: Engine, tmp_path: Path) -> None:
    other = rw.connect()
    try:
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": INGEST_LOCK_KEY})
        r = await env.run(copy_kb(tmp_path))
    finally:
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": INGEST_LOCK_KEY})
        other.close()
    assert r.code == 1 and "đang có lượt ingest khác" in r.err
    assert await env.index.list_kb_collections() == []


@pytest.mark.asyncio
async def test_b34_known_owner_written(env: Env, rw: Engine, tmp_path: Path) -> None:
    with rw.begin() as conn:
        conn.execute(text("INSERT INTO users (user_id, username, role) VALUES ('it_mgr01', 'it_mgr01', 'manager') "
                          "ON CONFLICT DO NOTHING"))  # fmt: skip
    try:
        r = await env.run(copy_kb(tmp_path))
        assert r.code == 0, r.err
        with rw.connect() as conn:
            assert set(conn.execute(text("SELECT owner FROM kb_documents")).scalars()) == {"it_mgr01"}
        assert "owner" not in r.err
    finally:  # DB dùng chung cả phiên: các test khác cần users không có it_mgr01
        with rw.begin() as conn:
            conn.execute(text("DELETE FROM kb_documents"))
            conn.execute(text("DELETE FROM users WHERE user_id = 'it_mgr01'"))


@pytest.mark.asyncio
async def test_b35_kb_version_comes_back(env: Env, rw: Engine, tmp_path: Path) -> None:
    kb = copy_kb(tmp_path, with_eval=False)
    original = (kb / "vpn" / "KB-VPN-004.md").read_text(encoding="utf-8")
    assert (await env.run(kb, allow_unevaluated=True)).code == 0
    first = await _current(env)
    assert first is not None
    created = _scalar(rw, "SELECT created_at FROM kb_versions WHERE kb_version = :v", v=first[3:])
    set_version(kb, "KB-VPN-004", 2, enabled=False)
    assert (await env.run(kb, allow_unevaluated=True)).code == 0
    (kb / "vpn" / "KB-VPN-004.md").write_text(original, encoding="utf-8")  # bật lại đúng bản v1
    r = await env.run(kb, allow_unevaluated=True)
    assert r.code == 0, r.err
    assert await _current(env) == first
    assert _scalar(rw, "SELECT count(*) FROM kb_versions WHERE is_current") == 1
    assert _scalar(rw, "SELECT kb_version FROM kb_versions WHERE is_current") == first[3:]
    assert _scalar(rw, "SELECT created_at FROM kb_versions WHERE kb_version = :v", v=first[3:]) == created


# ---- CLI ------------------------------------------------------------------------------------------


def test_cli_exit_codes(clean_qdrant: str, migrated: PgUrls, tmp_path: Path) -> None:
    kb = copy_kb(tmp_path, with_eval=False)

    def factory(app_env: str) -> cli.DepsFactory:
        @asynccontextmanager
        async def build(_: Settings) -> AsyncIterator[IngestDeps]:
            async with _env(clean_qdrant, migrated) as e:
                yield e.deps(app_env=app_env)

        return build

    assert cli.main(["--kb-dir", str(kb), "--dry-run"], deps_factory=factory("test")) == 0
    assert cli.main(["--kb-dir", str(kb), "--allow-unevaluated"], deps_factory=factory("prod")) == 1
    assert cli.main(["--kb-dir", str(kb)], deps_factory=factory("test")) == 1  # nhánh a không cờ
    assert cli.main(["--kb-dir", str(kb), "--allow-unevaluated"], deps_factory=factory("test")) == 0
