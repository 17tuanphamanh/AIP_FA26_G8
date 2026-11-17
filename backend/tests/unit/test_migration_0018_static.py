"""Migration 0018 (D-99, 17/11) — kiểm TĨNH, không cần Docker. Bản Postgres thật: `integration/test_d99_luong_l2_pg.py` (CHECK, store),
`integration/test_migration.py` (models khớp migration, hạ về base rồi nâng lại)."""

import ast
from pathlib import Path

from tests.unit.test_migration_0016_static import _assigns

VERSIONS = Path(__file__).resolve().parents[3] / "backend" / "app" / "db" / "alembic" / "versions"
NEW_COLUMNS = ("assigned_at", "tier", "raised_at", "raised_by", "raise_target", "raise_note", "user_message")


def _migration() -> str:
    found = sorted(VERSIONS.glob("0018_*.py"))
    assert len(found) == 1, f"cần đúng một file 0018_*.py, thấy {[p.name for p in found]}"
    return found[0].read_text(encoding="utf-8")


def test_0018_noi_sau_0017_co_downgrade() -> None:
    src = _migration()
    names = _assigns(src)
    assert (names.get("revision"), names.get("down_revision")) == ("0018", "0017")
    funcs = {n.name for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
    assert {"upgrade", "downgrade"} <= funcs


def test_0018_them_dung_cot_va_check() -> None:
    src = _migration()
    for column in NEW_COLUMNS:
        assert f'"{column}"' in src
    for check in ("tier IN (2, 3)", "raise_target IN ('it_manager', 'vendor')", "BETWEEN 1 AND 500", "(tier = 3) = (raised_at"):
        assert check in src


def test_models_khop_0018() -> None:
    from app.db.models import Escalation
    from sqlalchemy import Table

    table: Table = Escalation.__table__  # type: ignore[assignment]
    assert set(NEW_COLUMNS) <= set(table.c.keys())
    assert table.c.tier.server_default is not None and not table.c.tier.nullable
    names = {c.name for c in table.constraints if c.name}
    for name in ("tier", "assigned_pair", "raise_target", "raise_note_len", "raised_iff_tier3", "user_message_len"):
        assert f"ck_escalations_{name}" in names
