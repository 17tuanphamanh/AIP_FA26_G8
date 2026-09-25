"""Migration 0001 trên Postgres 16 thật, chạy bằng app_migrate: lên/xuống sạch, đủ 22 bảng,
view, trigger, role; models và migration không lệch nhau (P7 mục 5 tiêu chí 1)."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.db.models import Base
from sqlalchemy import Connection, create_engine, text
from tests.integration.pg import PgUrls, alembic_config

EXPECTED_TABLES = {
    # 17 bảng gốc (claude/thiet-ke-database.md)
    "users", "sessions", "policy_versions", "policy_rules", "kb_versions", "kb_documents",
    "tickets", "approvals", "transaction_log", "exit_code_priority", "escalations",
    "audit_logs", "lineage", "turns", "spans", "llm_calls", "alerts",
    # 5 bảng mới (P7)
    "security_events", "llm_cache", "wait_deadlines", "side_effects", "child_notices",
}  # fmt: skip


def _tables(conn: Connection) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "AND table_name <> 'alembic_version'"
        )
    )
    return {r[0] for r in rows}


def _scalar(conn: Connection, sql: str) -> object:
    return conn.execute(text(sql)).scalar()


def test_upgrade_creates_exactly_22_tables(migrated: PgUrls) -> None:
    engine = create_engine(migrated.role("app_migrate"))
    with engine.connect() as conn:
        assert _tables(conn) == EXPECTED_TABLES
        assert len(EXPECTED_TABLES) == 22
        assert _scalar(conn, "SELECT to_regclass('public.auth_failures')") == "auth_failures"
        owners = conn.execute(
            text("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
        assert set(owners) == {"app_migrate"}
        triggers = conn.execute(
            text(
                "SELECT event_object_table, trigger_name FROM information_schema.triggers "
                "WHERE trigger_schema = 'public'"
            )
        ).all()
        assert {t for t, _ in triggers} == {"audit_logs", "security_events"}
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


def test_models_match_migration(migrated: PgUrls) -> None:
    engine = create_engine(migrated.role("app_migrate"))
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_downgrade_is_clean_then_upgrade_again(migrated: PgUrls) -> None:
    cfg = alembic_config(migrated)
    engine = create_engine(migrated.role("app_migrate"))
    try:
        command.downgrade(cfg, "base")
        with engine.connect() as conn:
            assert _tables(conn) == set()
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
