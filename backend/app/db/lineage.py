"""`lineage` (P7; HD17.1 [Chốt 17.1]; phase3 mục 10.3; chốt Q-3g-3 3g) — prompt/model/`kb_version` nào sinh ra một quyết
định hay câu trả lời (B10 ở 3g; B12 ở 3h).

- Ghi **cùng transaction với dòng audit của `goto`** (`AuditWriter.record(row, lineage=…)`), không transaction riêng:
  audit của bước và lineage của nó cùng có hoặc cùng không.
- **Idempotent** bằng `INSERT … SELECT … WHERE NOT EXISTS (ticket_id, turn_id, step, prompt_id)` — chạy lại node trong cùng
  lượt không ghi dòng thứ hai. Không cần khoá duy nhất (không migration): hai lượt cùng ticket không chạy song song
  (khoá ticket D-19).
- `commit_sha = NULL` ở Phase 3 (chưa có nguồn — "Việc treo": `GIT_SHA` lúc build image, trước mốc G).
- Không chứa văn bản người dùng/LLM: chỉ định danh, phiên bản, tên model.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Table, and_, exists, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import Lineage

_TABLE: Table = Lineage.__table__  # type: ignore[assignment]
LINEAGE_COLUMNS = frozenset(c.name for c in _TABLE.columns) - {"lineage_id"}
LINEAGE_KEY = ("ticket_id", "turn_id", "step", "prompt_id")


def check_lineage_row(row: Mapping[str, Any]) -> None:
    """Dùng chung cho writer thật và bản giả: cột lạ hoặc thiếu khoá → lỗi lập trình (E9)."""
    unknown = set(row) - LINEAGE_COLUMNS
    if unknown:
        raise ValueError(f"lineage: cột lạ {sorted(unknown)}")
    if not row.get("ticket_id") or not row.get("turn_id") or not row.get("step") or not row.get("created_at"):
        raise ValueError("lineage: thiếu ticket_id/turn_id/step/created_at")


async def insert_once(conn: AsyncConnection, row: Mapping[str, Any]) -> None:
    check_lineage_row(row)
    names = sorted(row)
    same = and_(*(_TABLE.c[k].is_not_distinct_from(literal(row.get(k), _TABLE.c[k].type)) for k in LINEAGE_KEY))
    values = select(*(literal(row[k], _TABLE.c[k].type) for k in names)).where(~exists().where(same))
    await conn.execute(insert(_TABLE).from_select(names, values))
