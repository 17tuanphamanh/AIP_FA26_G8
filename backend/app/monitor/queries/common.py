"""Phần dùng chung của truy vấn M9 (`business.py`, `ai.py`): kiểm cửa sổ, tỉ lệ, mảnh SQL cửa sổ lá.

- Cửa sổ `[frm, to)`: `frm`/`to` naive, hoặc `frm >= to` → `ValueError` (trước khi chạm DB).
- Tỉ lệ có mẫu số 0 → `None`, không bao giờ 0 (kế hoạch M9 4.3).
- `LEAF_WINDOW`/`DONE` viết cho alias `t` của `v_leaf`.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

LEAF_WINDOW = "t.created_at >= :frm AND t.created_at < :to"
DONE = "t.final_state IS NOT NULL"  # mẫu số tỉ lệ theo kết cục ticket: chỉ lá đã kết thúc (quy ước 5.1(a))


def window_params(frm: datetime, to: datetime) -> dict[str, Any]:
    for ts in (frm, to):
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("cần datetime có múi giờ")
    if frm >= to:
        raise ValueError("cửa sổ rỗng: frm phải < to")
    return {"frm": frm, "to": to}


def ratio(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


async def scalar_row(conn: AsyncConnection, sql: str, params: dict[str, Any]) -> Any:
    return (await conn.execute(text(sql), params)).one()
