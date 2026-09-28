"""models.py khớp app.domain và khớp phần grant của migration — không cần DB."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from app.db.models import Base
from app.domain.exit_codes import BlockReason, CloseReason, ExitCode
from app.domain.states import ALL_STATES
from sqlalchemy import CheckConstraint, Table

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "app/db/alembic/versions/0001_init_22_bang_role_trigger.py"
)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0001", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check(table: str, column: str) -> str:
    t: Table = Base.metadata.tables[table]
    for c in t.constraints:
        if isinstance(c, CheckConstraint) and str(c.name).endswith(f"_{column}"):
            return str(c.sqltext)
    raise AssertionError(f"không có CHECK cho {table}.{column}")


def test_22_tables() -> None:
    assert len(Base.metadata.tables) == 22


@pytest.mark.parametrize("table", ["tickets", "audit_logs"])
def test_codes_come_from_domain(table: str) -> None:
    for code in ExitCode:
        assert f"'{code.value}'" in _check(table, "exit_code")
    for reason in CloseReason:
        assert f"'{reason.value}'" in _check(table, "close_reason")
    for block in BlockReason:
        assert f"'{block.value}'" in _check(table, "block_reason")
    assert _check(table, "final_state").count("'S_") == 4


def test_audit_status_columns_cover_14_states() -> None:
    for column in ("from_status", "to_status"):
        text = _check("audit_logs", column)
        assert text.count("'S_") == 14
        assert all(f"'{s}'" in text for s in ALL_STATES)


def test_no_password_column_anywhere() -> None:
    for table in Base.metadata.tables.values():
        assert not [c.name for c in table.columns if "password" in c.name], table.name


def test_tickets_store_redacted_request_only() -> None:
    cols = set(Base.metadata.tables["tickets"].columns.keys())
    assert "redacted_request" in cols and "raw_request" not in cols  # D-07 (A1)
    assert len(cols) == 21  # 20 cột nguồn + is_parent (A2)


def test_migration_grants_cover_every_table() -> None:
    m = _migration()
    assert set(m.RW_CRUD_TABLES) | set(m.APPEND_ONLY) == set(Base.metadata.tables)
    assert not set(m.RW_CRUD_TABLES) & set(m.APPEND_ONLY)
    assert set(m.MONITOR_TABLES) <= set(Base.metadata.tables)
    assert len(m.EXIT_CODE_PRIORITY) == len(ExitCode)


def test_kb_eval_statuses_match_migration_0006() -> None:
    from app.db.models import KB_EVAL_STATUSES

    assert KB_EVAL_STATUSES == ("evaluated", "unevaluated")
    assert _check("kb_versions", "eval_status") == "eval_status IN ('evaluated', 'unevaluated')"
    source = (MIGRATION.parent / "0006_kb_content_hash.py").read_text(encoding="utf-8")
    assert "\"eval_status IN ('evaluated', 'unevaluated')\"" in source
