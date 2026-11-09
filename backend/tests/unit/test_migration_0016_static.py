"""Migration 0016 (bn-a, 08/11; dời từ 0015 sang 0016 ngày 09/11 — số 0015 thuộc lô Q1 `it_help`) — kiểm TĨNH chạy được không cần Docker (test viết trước, DỪNG 1). Bản Postgres thật:
`integration/test_migration_0016.py`, `integration/test_txlog_pg.py` (TA chạy).

- File `0016_*.py` nối sau `0015` (lô Q1 `it_help`), có `downgrade`; khai đủ S1/S2/S4/A4.
- `models.py` khớp: `users.mfa_last_step` BigInteger NULL; chỉ mục từng phần `ix_approvals_pending_deadline`.
- Xác nhận code (S1, S2) — test canh, XANH sẵn trên d9b356e, giữ xanh sau 0016:
  - `transaction_log`: chỉ `executor/txlog.SqlTxLog._insert` ghi, và chỉ INSERT — không `update(`/`delete(`/SQL UPDATE/DELETE nào trên bảng.
  - `tickets.final_state`: chỉ `db/tickets.SqlTicketStore.finalize_once` ghi (UPDATE … WHERE final_state IS NULL).
"""

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "backend" / "app"
VERSIONS = APP / "db" / "alembic" / "versions"

CHO_0016 = pytest.mark.xfail(strict=True, reason="CHỜ migration 0016 — gỡ cờ khi hiện thực")


def _migration() -> tuple[Path, str]:
    found = sorted(VERSIONS.glob("0016_*.py"))
    assert len(found) == 1, f"cần đúng một file 0016_*.py, thấy {[p.name for p in found]}"
    return found[0], found[0].read_text(encoding="utf-8")


def _assigns(source: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign | ast.Assign):
            target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
            if isinstance(target, ast.Name) and node.value is not None:
                try:
                    out[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return out


@CHO_0016


def test_0016_chains_after_0015_and_has_downgrade() -> None:
    _, src = _migration()
    names = _assigns(src)
    assert (names.get("revision"), names.get("down_revision")) == ("0016", "0015")
    funcs = {n.name for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
    assert {"upgrade", "downgrade"} <= funcs


@CHO_0016


def test_0016_declares_s1_s2_s4_a4() -> None:
    _, src = _migration()
    assert re.search(r"REVOKE UPDATE, DELETE, TRUNCATE ON transaction_log FROM app_rw", src)
    assert "transaction_log_append_only" in src and "transaction_log_no_truncate" in src
    assert "tickets_final_state_once" in src
    assert "ix_approvals_pending_deadline" in src and "status = 'pending'" in src
    assert "mfa_last_step" in src


@CHO_0016


def test_models_match_0016() -> None:
    from app.db.models import Approval, User
    from sqlalchemy import BigInteger, Table

    users: Table = User.__table__  # type: ignore[assignment]
    approvals: Table = Approval.__table__  # type: ignore[assignment]
    col = users.c["mfa_last_step"]
    assert isinstance(col.type, BigInteger) and col.nullable
    [ix] = [i for i in approvals.indexes if i.name == "ix_approvals_pending_deadline"]
    assert [c.name for c in ix.columns] == ["deadline"]
    assert "pending" in str(ix.dialect_options["postgresql"]["where"])


# ---- test canh (xanh sẵn): xác nhận đường ghi --------------------------------------------------------------------------------------


def _py_files() -> list[Path]:
    return [p for p in APP.rglob("*.py") if "alembic" not in p.parts]


def test_s1_transaction_log_only_inserted_by_txlog() -> None:
    sql_mut = re.compile(r"\b(UPDATE|DELETE\s+FROM|TRUNCATE)\s+transaction_log\b", re.IGNORECASE)
    offenders = [str(p.relative_to(REPO)) for p in _py_files() if sql_mut.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
    users = [p for p in _py_files() if "TransactionLogEntry" in p.read_text(encoding="utf-8")]
    assert sorted(p.name for p in users) == ["models.py", "txlog.py"]
    txlog = (APP / "executor" / "txlog.py").read_text(encoding="utf-8")
    assert "insert(_TABLE)" in txlog and not re.search(r"\b(update|delete)\(_TABLE\)", txlog)


def test_s2_final_state_written_only_by_finalize_once() -> None:
    """Mọi `update(_TICKETS)…values(` có `final_state` / SQL `SET final_state` trong app — chỉ ở `finalize_once`."""
    hits: list[str] = []
    for p in _py_files():
        src = p.read_text(encoding="utf-8")
        if re.search(r"SET\s+final_state", src, re.IGNORECASE):
            hits.append(f"{p.name}:sql")
        tree = ast.parse(src)
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            body = ast.unparse(fn)
            if re.search(r"update\(_TICKETS\)|_TICKETS\.update\(\)", body) and ("_FINAL_COLUMNS" in body or "final_state=" in body):
                hits.append(f"{p.name}:{fn.name}")
    assert hits == ["tickets.py:finalize_once"]
