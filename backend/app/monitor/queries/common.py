"""Phần dùng chung của truy vấn M9 (`business.py`, `ai.py`): kiểm cửa sổ, tỉ lệ, mảnh SQL cửa sổ lá.

- Cửa sổ `[frm, to)`: `frm`/`to` naive, hoặc `frm >= to` → `ValueError` (trước khi chạm DB).
- Tỉ lệ có mẫu số 0 → `None`, không bao giờ 0 (kế hoạch M9 4.3).
- `LEAF_WINDOW`/`DONE` viết cho alias `t` của `v_leaf`.
- B1 (12/11) — nguồn ticket của tab Nghiệp vụ/AI: `business.py`, `ai.py` ghép `LEAF_SOURCE` vào câu đọc `v_leaf` và lấy tham số
  qua `leaf_params`. Route dashboard đặt `only_sources(("real",))` (mặc định API) quanh `business_metrics`/`ai_metrics`. Nơi
  không đặt (luật cảnh báo, tab So sánh) → đủ `TICKET_SOURCES` = hành vi trước B1 (cột NOT NULL, CHECK ∈ `TICKET_SOURCES`).
  ContextVar thay vì thêm tham số: chữ ký `(conn, frm, to)` của hàm truy vấn bị ghim (hợp đồng mục 3; luật 1 gọi lại).
  `LEAF_WINDOW` KHÔNG đổi (luật drift so cùng chữ, tab So sánh lọc nguồn riêng).
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import TICKET_SOURCES

LEAF_WINDOW = "t.created_at >= :frm AND t.created_at < :to"
DONE = "t.final_state IS NOT NULL"  # mẫu số tỉ lệ theo kết cục ticket: chỉ lá đã kết thúc (quy ước 5.1(a))
LEAF_SOURCE = "t.source = ANY(CAST(:sources AS text[]))"  # B1: nguồn ticket lá (tham số `sources` của `leaf_params`)

_SOURCES: ContextVar[tuple[str, ...]] = ContextVar("monitor_leaf_sources", default=TICKET_SOURCES)


@contextmanager
def only_sources(sources: Sequence[str]) -> Iterator[None]:
    """Trong khối: câu Nghiệp vụ/AI chỉ đếm lá có `source` thuộc `sources`. Rỗng / nguồn lạ → `ValueError` (không âm thầm
    ra 0 ca). Ra khỏi khối (kể cả lỗi) → trả lại nguồn trước đó."""
    chosen = tuple(sources)
    if not chosen or not set(chosen) <= set(TICKET_SOURCES):
        raise ValueError(f"nguồn ticket không hợp lệ: {chosen!r}")
    token = _SOURCES.set(chosen)
    try:
        yield
    finally:
        _SOURCES.reset(token)


def current_sources() -> tuple[str, ...]:
    return _SOURCES.get()


def window_params(frm: datetime, to: datetime) -> dict[str, Any]:
    for ts in (frm, to):
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("cần datetime có múi giờ")
    if frm >= to:
        raise ValueError("cửa sổ rỗng: frm phải < to")
    return {"frm": frm, "to": to}


def leaf_params(frm: datetime, to: datetime) -> dict[str, Any]:
    """`window_params` + `sources` (nguồn đang đặt, mặc định đủ 3) — cho câu có `LEAF_SOURCE`."""
    return {**window_params(frm, to), "sources": list(_SOURCES.get())}


def ratio(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


async def scalar_row(conn: AsyncConnection, sql: str, params: dict[str, Any]) -> Any:
    return (await conn.execute(text(sql), params)).one()
