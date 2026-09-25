"""Migration 0002 (P7 2.3 bản 1.5): nới CHECK `security_events.event_type` thêm mfa_enrolled,
mfa_reset; view `auth_failures` không đếm hai loại này; downgrade dừng rõ ràng khi đã có dòng."""

import pytest
from alembic import command
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError
from tests.integration.pg import PgUrls, alembic_config, fresh_database


def _event(conn: Connection, event_type: str, username: str = "quan.tm") -> None:
    conn.execute(
        text("INSERT INTO security_events (event_type, username_attempted) VALUES (:e, :u)"),
        {"e": event_type, "u": username},
    )


def _version(db: PgUrls) -> str:
    """Đọc bằng app_migrate: app_rw không có quyền trên alembic_version (đúng như thiết kế)."""
    engine = create_engine(db.role("app_migrate"))
    try:
        with engine.connect() as conn:
            return str(conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
    finally:
        engine.dispose()


def test_upgrade_accepts_mfa_types_and_view_excludes_them(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        command.upgrade(cfg, "head")
        rw = create_engine(db.role("app_rw"))
        try:
            assert _version(db) == "0002"
            with rw.begin() as conn:
                for e in ("mfa_enrolled", "mfa_reset", "login_failed", "mfa_failed"):
                    _event(conn, e)
            with rw.connect() as conn:
                types = conn.execute(
                    text("SELECT event_type FROM auth_failures ORDER BY event_id")
                ).scalars()
                assert list(types) == ["login_failed", "mfa_failed"]

            # đã có dòng mfa_* → downgrade dừng với thông báo rõ, DB giữ nguyên ở 0002
            with pytest.raises(RuntimeError, match="Không hạ được migration 0002.*2 dòng"):
                command.downgrade(cfg, "0001")
            assert _version(db) == "0002"
        finally:
            rw.dispose()


def test_downgrade_without_rows_restores_old_check_then_upgrade_again(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0001")
        rw = create_engine(db.role("app_rw"))
        try:
            assert _version(db) == "0001"
            with pytest.raises(DBAPIError, match="ck_security_events_event_type"), rw.begin() as conn:
                _event(conn, "mfa_enrolled")
            with rw.begin() as conn:
                _event(conn, "login_failed")  # loại cũ vẫn ghi được
            command.upgrade(cfg, "head")
            with rw.begin() as conn:
                _event(conn, "mfa_reset")
            assert _version(db) == "0002"
        finally:
            rw.dispose()


def test_unknown_event_type_still_rejected_after_0002(migrated: PgUrls) -> None:
    rw = create_engine(migrated.role("app_rw"))
    try:
        with pytest.raises(DBAPIError, match="ck_security_events_event_type"), rw.begin() as conn:
            _event(conn, "mfa_hacked")
    finally:
        rw.dispose()
