"""Số liệu dùng LLM cho `GET /api/admin/llm-status` (I1) — một SELECT chỉ đọc trên `llm_calls`.

- Chạy trên connection của engine `app_monitor` (`read_snapshot`: READ ONLY). `llm_calls ⋈ spans ⋈ turns` không làm rơi
  dòng nào: `llm_calls.span_id`, `spans.turn_id` NOT NULL FK → `spent_usd` khớp `SUM(llm_calls.cost_usd)` mà trần chi
  (`llm/spend.py`) đọc. Khác `monitor.queries.ai`: không qua `v_leaf` — đây là TỔNG chi toàn bảng, không phải chi của ticket lá.
- `tickets` = số ticket CÓ ≥ 1 lời gọi (kể cả cache hit, chi phí 0); `cost_usd` NULL = 0.
- `calls_since` đếm `created_at >= since` (nơi gọi truyền `now − 24 giờ`).
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class LlmUsage:
    spent_usd: float
    calls_total: int
    calls_since: int
    tickets: int


async def llm_usage(conn: AsyncConnection, since: datetime) -> LlmUsage:
    if since.tzinfo is None:
        raise ValueError("since phải có múi giờ")
    row = (await conn.execute(text(
        "SELECT COALESCE(sum(c.cost_usd), 0), count(*), count(*) FILTER (WHERE c.created_at >= :since), "
        "count(DISTINCT u.ticket_id) "
        "FROM llm_calls c JOIN spans s ON s.span_id = c.span_id JOIN turns u ON u.turn_id = s.turn_id"
    ), {"since": since})).one()  # fmt: skip
    return LlmUsage(spent_usd=float(row[0]), calls_total=int(row[1]), calls_since=int(row[2]), tickets=int(row[3]))
