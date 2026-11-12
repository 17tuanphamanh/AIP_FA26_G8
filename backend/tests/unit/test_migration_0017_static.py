"""Migration 0017 (E12 — soát 20 agent 12/11: agent 20 V21, agent 14/15 V14) — kiểm TĨNH, không cần Docker. Bản Postgres thật:
`integration/test_migration_0017.py`.

- `ix_llm_calls_span_id` ON llm_calls(span_id): tab "So sánh 30 ngày" nối `llm_calls` theo `span_id` — 10k ca mất 11,5 s khi quét tuần tự.
- `approvals` không xoá được bằng `app_rw` (REVOKE DELETE): phiếu duyệt là bằng chứng ai đã duyệt; code không bao giờ xoá phiếu.
"""

import ast
import re
from pathlib import Path

from tests.unit.test_migration_0016_static import _assigns

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "backend" / "app"
VERSIONS = APP / "db" / "alembic" / "versions"


def _migration() -> str:
    found = sorted(VERSIONS.glob("0017_*.py"))
    assert len(found) == 1, f"cần đúng một file 0017_*.py, thấy {[p.name for p in found]}"
    return found[0].read_text(encoding="utf-8")


def test_0017_noi_sau_0016_co_downgrade() -> None:
    src = _migration()
    names = _assigns(src)
    assert (names.get("revision"), names.get("down_revision")) == ("0017", "0016")
    funcs = {n.name for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
    assert {"upgrade", "downgrade"} <= funcs


def test_0017_khai_chi_muc_va_revoke() -> None:
    src = _migration()
    assert "ix_llm_calls_span_id" in src
    assert re.search(r"REVOKE DELETE ON approvals FROM app_rw", src)
    assert re.search(r"GRANT DELETE ON approvals TO app_rw", src)  # downgrade trả quyền của 0001


def test_models_khop_0017() -> None:
    from app.db.models import LlmCall
    from sqlalchemy import Table

    table: Table = LlmCall.__table__  # type: ignore[assignment]
    [ix] = [i for i in table.indexes if i.name == "ix_llm_calls_span_id"]
    assert [c.name for c in ix.columns] == ["span_id"]


def test_code_khong_xoa_phieu_duyet() -> None:
    sql = re.compile(r"\b(DELETE\s+FROM|TRUNCATE)\s+approvals\b", re.IGNORECASE)
    orm = re.compile(r"delete\(\s*(Approval|approvals)\b")
    offenders = [str(p.relative_to(REPO)) for p in APP.rglob("*.py") if "alembic" not in p.parts
                 and (sql.search(t := p.read_text(encoding="utf-8")) or orm.search(t))]  # fmt: skip
    assert offenders == []
