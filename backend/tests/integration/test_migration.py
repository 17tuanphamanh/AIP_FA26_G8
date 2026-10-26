"""Migration 0001 trên Postgres 16 thật, chạy bằng app_migrate: lên/xuống sạch, đủ 22 bảng,
view, trigger, role; models và migration không lệch nhau (P7 mục 5 tiêu chí 1).

Từ 0003 (Phase 2a) có thêm 4 bảng checkpoint LangGraph (`PostgresSaver.setup()`, P7 mục 3) — tính
riêng, không thuộc 22 bảng nghiệp vụ và không nằm trong models.py."""

from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.db.models import Base
from app.graph.checkpoint import CHECKPOINT_TABLES
from sqlalchemy import Connection, create_engine, text
from tests.integration.pg import PgUrls, alembic_config, fresh_database

EXPECTED_TABLES = {
    # 17 bảng gốc (claude/thiet-ke-database.md)
    "users", "sessions", "policy_versions", "policy_rules", "kb_versions", "kb_documents",
    "tickets", "approvals", "transaction_log", "exit_code_priority", "escalations",
    "audit_logs", "lineage", "turns", "spans", "llm_calls", "alerts",
    # 5 bảng mới (P7)
    "security_events", "llm_cache", "wait_deadlines", "side_effects", "child_notices",
    # bảng thứ 23 — migration 0010 (gói 2b, D-54 a, đặc tả 4.8): bộ đếm 429 của tin nhắn
    "rate_hits",
    # bảng thứ 24 — migration 0012 (notify-email): hàng đợi email
    "email_outbox",
    # bảng thứ 25 — migration 0013 (D-60): lịch sử đổi chiến lược M5 lúc vận hành (chỉ ghi thêm)
    "m5_strategy_changes",
}  # fmt: skip


def _all_tables(conn: Connection) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "AND table_name <> 'alembic_version'"
        )
    )
    return {r[0] for r in rows}


def _tables(conn: Connection) -> set[str]:
    """Bảng nghiệp vụ — bỏ 4 bảng checkpoint LangGraph."""
    return _all_tables(conn) - set(CHECKPOINT_TABLES)


def _scalar(conn: Connection, sql: str) -> object:
    return conn.execute(text(sql)).scalar()


def test_upgrade_creates_exactly_24_tables(migrated: PgUrls) -> None:
    """Gói 2b (PLAN-2B1 G8 #3, Q-2B1-6): 22 bảng gốc + `rate_hits` (0010) + `email_outbox` (0012, notify-email) + D-60
    `m5_strategy_changes` (0013) — giữ tên test."""
    engine = create_engine(migrated.role("app_migrate"))
    with engine.connect() as conn:
        assert _tables(conn) == EXPECTED_TABLES
        assert len(EXPECTED_TABLES) == 25
        assert _all_tables(conn) - EXPECTED_TABLES == set(CHECKPOINT_TABLES)  # migration 0003
        assert _scalar(conn, "SELECT to_regclass('public.auth_failures')") == "auth_failures"
        owners: Any = conn.execute(
            text("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
        assert set(owners) == {"app_migrate"}
        triggers = conn.execute(
            text(
                "SELECT event_object_table, trigger_name FROM information_schema.triggers "
                "WHERE trigger_schema = 'public'"
            )
        ).all()
        assert {t for t, _ in triggers} == {"audit_logs", "security_events", "m5_strategy_changes"}  # D-60: 0013
    engine.dispose()


def test_three_roles_exist_and_migrate_is_not_superuser(migrated: PgUrls) -> None:
    engine = create_engine(migrated.role("app_migrate"))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT rolname, rolsuper FROM pg_roles "
                "WHERE rolname IN ('app_migrate', 'app_rw', 'app_monitor')"
            )
        ).all()
    engine.dispose()
    assert {name for name, _ in rows} == {"app_migrate", "app_rw", "app_monitor"}
    assert all(not is_super for _, is_super in rows)


def _not_checkpoint(obj: object, name: str | None, type_: str, *_: object) -> bool:
    table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
    return table not in CHECKPOINT_TABLES


def test_models_match_migration(migrated: PgUrls) -> None:
    engine = create_engine(migrated.role("app_migrate"))
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"include_object": _not_checkpoint})
        diff = compare_metadata(ctx, Base.metadata)
    engine.dispose()
    assert diff == []


def test_downgrade_is_clean_then_upgrade_again(migrated: PgUrls) -> None:
    cfg = alembic_config(migrated)
    engine = create_engine(migrated.role("app_migrate"))
    try:
        command.downgrade(cfg, "base")
        with engine.connect() as conn:
            assert _all_tables(conn) == set()  # gồm cả 4 bảng checkpoint
            assert _scalar(conn, "SELECT to_regclass('public.auth_failures')") is None
            assert _scalar(conn, "SELECT count(*) FROM pg_proc WHERE proname = 'forbid_mutation'") == 0
            # downgrade không đụng role (role do script init quản lý)
            assert _scalar(conn, "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'app\\_%'") == 3
    finally:
        command.upgrade(cfg, "head")  # trả DB về head cho các test khác
    with engine.connect() as conn:
        assert _tables(conn) == EXPECTED_TABLES
        assert _scalar(conn, "SELECT count(*) FROM exit_code_priority") == 10
    engine.dispose()


def test_0003_checkpoint_tables_down_and_up(pg: PgUrls) -> None:
    """0003 hạ xuống bỏ đúng 4 bảng checkpoint; nâng lại chạy `setup()` từ đầu, grant lại app_rw.
    Gói 2b (PLAN-2B1 G8 #5): xuống `0002` thì `rate_hits` (0010) cũng không còn; notify-email: `email_outbox` (0012) cũng vậy; D-60:
    `m5_strategy_changes` (0013) cũng vậy."""
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0002")
        owner = create_engine(db.role("app_migrate"))
        try:
            with owner.connect() as conn:
                assert _all_tables(conn) == EXPECTED_TABLES - {"rate_hits", "email_outbox", "m5_strategy_changes"}  # D-60: 0013
            command.upgrade(cfg, "head")
            with owner.connect() as conn:
                assert _all_tables(conn) - EXPECTED_TABLES == set(CHECKPOINT_TABLES)
                grants = conn.execute(text(
                    "SELECT table_name, string_agg(privilege_type, ',' ORDER BY privilege_type) "
                    "FROM information_schema.role_table_grants WHERE grantee = 'app_rw' "
                    "AND table_name LIKE 'checkpoint%' GROUP BY table_name"
                )).all()  # fmt: skip
            assert {t: p for t, p in grants} == dict.fromkeys(
                CHECKPOINT_TABLES, "DELETE,INSERT,SELECT,UPDATE"
            )
        finally:
            owner.dispose()
