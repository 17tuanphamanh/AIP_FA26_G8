"""models.py khớp app.domain và khớp phần grant của migration — không cần DB."""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
from app.db.models import Base
from app.domain.exit_codes import BlockReason, CloseReason, ExitCode
from app.domain.states import ALL_STATES
from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, Table

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "app/db/alembic/versions/0001_init_22_bang_role_trigger.py"
)


MIGRATION_0010 = MIGRATION.parent / "0010_rate_limits.py"  # gói 2b (D-54 a) — bảng thứ 23 `rate_hits`


def _migration(path: Path = MIGRATION) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"migration_{path.name[:4]}", path)
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


def test_23_tables() -> None:
    """Gói 2b (PLAN-2B1 G8 #1, Q-2B1-6; đặc tả 4.8 "bảng thứ 23"): 22 bảng gốc + `rate_hits` (migration 0010)."""
    assert len(Base.metadata.tables) == 23
    assert "rate_hits" in Base.metadata.tables


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
    """Gói 2b (PLAN-2B1 G8 #2): quyền `app_rw` = CRUD + append-only của `0001` HỢP `RW_TABLES` của `0010` (`rate_hits`)."""
    m, m10 = _migration(), _migration(MIGRATION_0010)
    assert tuple(m10.RW_TABLES) == ("rate_hits",)
    assert set(m.RW_CRUD_TABLES) | set(m.APPEND_ONLY) | set(m10.RW_TABLES) == set(Base.metadata.tables)
    assert not set(m.RW_CRUD_TABLES) & set(m.APPEND_ONLY)
    assert not (set(m.RW_CRUD_TABLES) | set(m.APPEND_ONLY)) & set(m10.RW_TABLES)  # rate_hits không phải bảng của 0001
    assert "rate_hits" not in m.MONITOR_TABLES  # 4.8: không cấp app_monitor
    assert set(m.MONITOR_TABLES) <= set(Base.metadata.tables)
    assert len(m.EXIT_CODE_PRIORITY) == len(ExitCode)


def test_kb_eval_statuses_match_migration_0006() -> None:
    from app.db.models import KB_EVAL_STATUSES

    assert KB_EVAL_STATUSES == ("evaluated", "unevaluated")
    assert _check("kb_versions", "eval_status") == "eval_status IN ('evaluated', 'unevaluated')"
    source = (MIGRATION.parent / "0006_kb_content_hash.py").read_text(encoding="utf-8")
    assert "\"eval_status IN ('evaluated', 'unevaluated')\"" in source


def test_side_effect_kinds_match_migration_0007() -> None:
    from app.db.models import SIDE_EFFECT_KINDS

    assert SIDE_EFFECT_KINDS[-1] == "security_event" and len(SIDE_EFFECT_KINDS) == 9
    source = (MIGRATION.parent / "0007_side_effects_security_event.py").read_text(encoding="utf-8")
    assert 'NEW_KINDS = ("security_event",)' in source
    for kind in SIDE_EFFECT_KINDS[:-1]:
        assert f'"{kind}"' in source  # OLD_KINDS tĩnh đủ 8 giá trị cũ
    assert _check("side_effects", "kind") == "kind IN (" + ", ".join(f"'{k}'" for k in SIDE_EFFECT_KINDS) + ")"


# ---- Gói 2b — chống spam (D-54 a; đặc tả 4.8, 4.10 "Dữ liệu"; PLAN-2B1 U19) ------------------------------------------------------


def test_security_event_types_match_migration_0010() -> None:
    """U19: `rate_limited` là loại CUỐI của `SECURITY_EVENT_TYPES`; `0010` có `NEW_TYPES = ("rate_limited",)` và `OLD_TYPES` tĩnh đủ
    15 giá trị cũ (khuôn `0002`/`0007`); CHECK của model khớp."""
    from app.db.models import SECURITY_EVENT_TYPES

    assert SECURITY_EVENT_TYPES[-1] == "rate_limited" and len(SECURITY_EVENT_TYPES) == 16
    assert SECURITY_EVENT_TYPES[-2] == "mfa_reset"  # thêm ở cuối, sau loại của 0002
    source = MIGRATION_0010.read_text(encoding="utf-8")
    assert re.search(r'^NEW_TYPES(\s*:[^=\n]+)?\s*=\s*\("rate_limited",\)', source, re.MULTILINE)  # viết tĩnh
    for kind in SECURITY_EVENT_TYPES[:-1]:
        assert f'"{kind}"' in source  # OLD_TYPES viết tĩnh — migration không đổi theo models
    m10 = _migration(MIGRATION_0010)
    assert tuple(m10.OLD_TYPES) == SECURITY_EVENT_TYPES[:-1] and tuple(m10.NEW_TYPES) == ("rate_limited",)
    expected = "event_type IN (" + ", ".join(f"'{k}'" for k in SECURITY_EVENT_TYPES) + ")"
    assert _check("security_events", "event_type") == expected


def test_migration_0010_revision_and_leaf_columns() -> None:
    """U19 (+ 4.10 "Dữ liệu"): `0010` nối sau `0009`; cột `v_leaf` mới = 9 cột của `0008` (không sửa `0008`) + `requester_id` ở CUỐI."""
    m10 = _migration(MIGRATION_0010)
    m8 = _migration(MIGRATION.parent / "0008_monitor_views.py")
    assert (m10.revision, m10.down_revision) == ("0010", "0009")
    assert tuple(m10.LEAF_COLUMNS) == (*m8.LEAF_COLUMNS, "requester_id")
    assert len(m8.LEAF_COLUMNS) == 9 and "requester_id" not in m8.LEAF_COLUMNS
    assert "security_invoker = true" in MIGRATION_0010.read_text(encoding="utf-8")  # CREATE OR REPLACE thay mọi option


def test_rate_hits_model_columns_index_fk() -> None:
    """U19 (4.8): `rate_hits` = `hit_id` BIGINT tự tăng (khoá chính), `user_id` FK `users` NOT NULL, `created_at` timestamptz NOT NULL
    KHÔNG server_default (giờ lấy từ Clock của app); index (`user_id`, `created_at`); không chữ người dùng, không `ticket_id`."""
    t: Table = Base.metadata.tables["rate_hits"]
    assert list(t.columns.keys()) == ["hit_id", "user_id", "created_at"]
    hit, user, created = t.c.hit_id, t.c.user_id, t.c.created_at
    assert hit.primary_key and isinstance(hit.type, BigInteger) and hit.autoincrement in (True, "auto")
    assert [c.name for c in t.primary_key.columns] == ["hit_id"]
    assert isinstance(user.type, String) and user.type.length == 64 and not user.nullable
    assert {fk.target_fullname for fk in user.foreign_keys} == {"users.user_id"}
    assert isinstance(created.type, DateTime) and created.type.timezone and not created.nullable
    assert created.server_default is None and created.default is None
    indexes = {str(ix.name): [c.name for c in ix.columns] for ix in t.indexes}
    assert indexes == {"ix_rate_hits_user_created_at": ["user_id", "created_at"]}


def test_tickets_requester_created_at_index() -> None:
    """4.8 bộ A: index `tickets(requester_id, created_at)` của migration 0010."""
    t: Table = Base.metadata.tables["tickets"]
    indexes = {str(ix.name): [c.name for c in ix.columns] for ix in t.indexes}
    assert indexes["ix_tickets_requester_created_at"] == ["requester_id", "created_at"]
    assert len(t.columns) == 21  # không thêm cột vào tickets


def test_migration_0010_downgrade_views_equal_0008() -> None:
    """Downgrade của 0010 tạo lại 3 view từ SQL chép tĩnh — phải đúng từng chữ như `VIEWS` của 0008 (cùng tên, cùng thứ tự)."""
    m10 = _migration(MIGRATION_0010)
    m8 = _migration(MIGRATION.parent / "0008_monitor_views.py")
    assert tuple(m10.VIEWS_0008) == tuple(m8.VIEWS)
