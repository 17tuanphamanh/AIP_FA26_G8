"""Migration 0006 (thiết kế Phase 3 mục 5.10, Q-3b-5): CHECK `eval_status`, index duy nhất một bản hiện hành,
hạ về 0005 rồi nâng lại. Mỗi test một database riêng (`fresh_database`) — không đụng DB chung của phiên."""

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError
from tests.integration.pg import PgUrls, alembic_config, fresh_database

V1, V2 = "a" * 64, "b" * 64


def _insert(rw: Engine, version: str, *, is_current: bool, eval_status: str | None = None) -> None:
    cols = "kb_version, doc_count, is_current" + (", eval_status" if eval_status is not None else "")
    vals = ":v, 1, :c" + (", :s" if eval_status is not None else "")
    with rw.begin() as conn:
        conn.execute(text(f"INSERT INTO kb_versions ({cols}) VALUES ({vals})"),
                     {"v": version, "c": is_current, "s": eval_status})  # fmt: skip


def test_0006_eval_status_check(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        rw = create_engine(db.role("app_rw"))
        try:
            with pytest.raises(IntegrityError, match="ck_kb_versions_eval_status"):
                _insert(rw, V1, is_current=False, eval_status="foo")
            _insert(rw, V1, is_current=False)
            _insert(rw, V2, is_current=False, eval_status="unevaluated")
            with rw.connect() as conn:
                rows = dict(conn.execute(text("SELECT kb_version, eval_status FROM kb_versions")).all())
            assert rows == {V1: "evaluated", V2: "unevaluated"}
        finally:
            rw.dispose()


def test_0006_single_current(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        rw = create_engine(db.role("app_rw"))
        try:
            _insert(rw, V1, is_current=False)
            _insert(rw, V2, is_current=False)  # hai dòng false: được
            with rw.begin() as conn:
                conn.execute(text("UPDATE kb_versions SET is_current = true WHERE kb_version = :v"), {"v": V1})
            with pytest.raises(IntegrityError, match="ux_kb_versions_current"), rw.begin() as conn:
                conn.execute(text("UPDATE kb_versions SET is_current = true WHERE kb_version = :v"), {"v": V2})
        finally:
            rw.dispose()


def _columns(conn_engine: Engine) -> set[tuple[str, str]]:
    with conn_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name IN ('kb_versions', 'kb_documents')"
        )).all()  # fmt: skip
    return {(t, c) for t, c in rows}


def _index_exists(conn_engine: Engine) -> bool:
    with conn_engine.connect() as conn:
        return bool(conn.execute(text(
            "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'ux_kb_versions_current'"
        )).scalar_one())  # fmt: skip


def test_0006_down_up(pg: PgUrls) -> None:
    new_cols = {("kb_documents", "content_sha256"), ("kb_versions", "chunk_count"), ("kb_versions", "eval_status")}
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        command.upgrade(cfg, "head")
        owner = create_engine(db.role("app_migrate"))
        try:
            assert new_cols <= _columns(owner) and _index_exists(owner)
            command.downgrade(cfg, "0005")
            assert not new_cols & _columns(owner)
            assert not _index_exists(owner)
            command.upgrade(cfg, "head")
            assert new_cols <= _columns(owner) and _index_exists(owner)
        finally:
            owner.dispose()
