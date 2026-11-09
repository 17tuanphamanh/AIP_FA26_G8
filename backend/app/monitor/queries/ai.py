"""Chỉ số dashboard AI/LLMOps (kế hoạch M9 5.2; hợp đồng mục 3 — `b2_llm_rate`, `b3_llm_rate` cho luật 12, 13).

- Chỉ đọc qua `AsyncConnection` của engine `app_monitor`. MỌI chỉ số đi qua `v_leaf` (D-30, Q-M9-A2-3): lời gọi LLM
  nối `llm_calls.span_id → spans.turn_id → turns.ticket_id → v_leaf`; span node qua `turns → v_leaf`; `audit_logs`,
  `escalations` join `v_leaf`. Ticket cha (từ Phase 5 mang lời gọi B2/B3 của câu nhiều ý) không được tính.
- Cửa sổ `[frm, to)` theo `created_at` của lá; riêng `cost_per_day` theo `llm_calls.created_at` (ngày phát sinh chi).
  `frm`/`to` naive, hoặc `frm >= to` → `ValueError`.
- `final_state IS NOT NULL` chỉ áp cho `tokens_per_ticket` (chỉ số theo ticket). Chỉ số theo lời gọi / dòng audit /
  span không lọc (Q-M9-A2-7): mỗi dòng đã có kết quả lúc ghi; lọc thì luật 12/13 "trong ngày" bỏ sót lá đang chạy.
- Tỉ lệ có mẫu số 0 → `None`. Nguồn pending → `null` + tên trong `unavailable` (không trả 0).
- F12: `multi_intent_first_stop_to_reply_s` đọc `v_child_notices` (0011) + `v_leaf` (cửa sổ theo con); còn
  `multi_intent_messages_per_turn` pending (`d30_parent_turns`).
- JSON `detail` so sánh dạng chữ (`->> ... = 'true'`), không ép kiểu: dòng ghi lệch kiểu không làm hỏng cả truy vấn.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.monitor.metrics import E2_LLM_REASONS, is_pending
from app.monitor.queries.common import (
    DONE,
    LEAF_WINDOW,
    ratio,
    scalar_row,
    window_params,
)
from app.monitor.views import V_CHILD_NOTICES, V_LEAF
from app.monitor.window import VN_TZ, day_start

AI_METRICS: tuple[str, ...] = (
    "tokens_per_ticket", "cost_per_day", "latency_p95_by_step", "cache_hit_rate", "json_invalid_first_try_rate",
    "fallback_rate", "e2_llm_count", "e9_count", "b2_llm_rate", "intent_filter_fallback_rate", "b3_llm_rate",
    "intent_model_version", "multi_intent_first_stop_to_reply_s", "multi_intent_messages_per_turn",
)  # fmt: skip
P95 = 0.95
# Cộng 36 giờ vào 00:00 của một ngày luôn rơi vào ngày KẾ (ngày dài 23–25 giờ khi có DST) → `day_start` ra mốc kế.
_NEXT_DAY = timedelta(hours=36)

# Mảnh SQL điểm log (Q-M9-A2-5): ca `guard_unavailable` (L3 lưng chừng/lỗi rồi L4 LLM lỗi) đã xuống L4 → tính vào
# cả tử và mẫu; `turn_budget_exceeded` ở B2 không có `screening` → ngoài cả hai.
_B2_LAYER = "a.detail->'screening'->>'layer_decided'"
_B2_NUM = f"({_B2_LAYER} = 'llm' OR a.event = 'guard_unavailable')"
_B2_DEN = f"({_B2_LAYER} IS NOT NULL OR a.event = 'guard_unavailable')"
_B3_STEPS = "a.step IN ('B3', 'B4')"  # ca E1 ghi điểm log 1 ở step B4 (graph/nodes/b03_classify.py)


@dataclass(frozen=True)
class DayCost:
    day_start: datetime  # 00:00 giờ VN của ngày (window.day_start), kiểu UTC
    cost_usd: float


@dataclass(frozen=True)
class AiMetrics:
    values: Mapping[str, Any]  # đủ AI_METRICS
    unavailable: tuple[str, ...]


def _leaf_calls() -> str:
    """FROM/JOIN lời gọi LLM của ticket lá (alias `c` llm_calls, `s` spans, `u` turns, `t` v_leaf)."""
    return (
        "FROM llm_calls c JOIN spans s ON s.span_id = c.span_id JOIN turns u ON u.turn_id = s.turn_id "
        f"JOIN {V_LEAF} t ON t.ticket_id = u.ticket_id"
    )


def day_starts(frm: datetime, to: datetime, tz: ZoneInfo = VN_TZ) -> list[datetime]:
    """Mốc 00:00 (theo `tz`, kiểu UTC) của mọi ngày giao với `[frm, to)`; ngày đầu là ngày chứa `frm`."""
    window_params(frm, to)
    days = [day_start(frm, tz)]
    while (nxt := day_start(days[-1] + _NEXT_DAY, tz)) < to:
        days.append(nxt)
    return days


async def tokens_per_ticket(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """Σ(tokens_in + tokens_out) / #lá đã kết thúc có ≥ 1 lời gọi LLM (token NULL = 0)."""
    row = await scalar_row(conn, (
        "SELECT count(DISTINCT t.ticket_id), "
        "COALESCE(sum(COALESCE(c.tokens_in, 0) + COALESCE(c.tokens_out, 0)), 0) "
        f"{_leaf_calls()} WHERE {LEAF_WINDOW} AND {DONE}"
    ), window_params(frm, to))  # fmt: skip
    leaves, tokens = int(row[0]), int(row[1])
    return None if leaves == 0 else tokens / leaves


async def cost_per_day(
    conn: AsyncConnection, frm: datetime, to: datetime, *, tz: ZoneInfo = VN_TZ
) -> tuple[DayCost, ...]:
    """Σ `cost_usd` theo ngày `tz` (Q-M9-2) của lời gọi có `llm_calls.created_at` trong `[frm, to)`; ngày không có lời
    gọi → 0.0 (đã đo, không chi). Ngày đầu/cuối bị cắt theo `frm`/`to`.
    Là chi phí của ticket lá (qua `v_leaf`), khác tổng chi toàn bảng `llm_calls` mà luật 14 đọc; hai số lệch nhau từ
    Phase 5 (Q-M9-A2-3)."""
    params = window_params(frm, to)
    starts = day_starts(frm, to, tz)
    params |= {"starts": starts, "ends": [*starts[1:], day_start(starts[-1] + _NEXT_DAY, tz)]}
    rows = (await conn.execute(text(
        "SELECT b.d, COALESCE(sum(x.cost_usd), 0) "
        "FROM unnest(CAST(:starts AS timestamptz[]), CAST(:ends AS timestamptz[])) AS b(d, e) "
        f"LEFT JOIN (SELECT c.created_at, c.cost_usd {_leaf_calls()} "
        "WHERE c.created_at >= :frm AND c.created_at < :to) x ON x.created_at >= b.d AND x.created_at < b.e "
        "GROUP BY b.d ORDER BY b.d"
    ), params)).all()  # fmt: skip
    return tuple(DayCost(day_start=d.astimezone(UTC), cost_usd=float(cost)) for d, cost in rows)


async def latency_p95_by_step(conn: AsyncConnection, frm: datetime, to: datetime) -> dict[str, float]:
    """p95 (`percentile_cont`, nội suy) `duration_ms` của span node theo `name` (`node:<tên node>`), mọi `status`
    (span lỗi/interrupted vẫn là độ trễ thật). Không có span → `{}`."""
    rows = (await conn.execute(text(
        f"SELECT s.name, percentile_cont({P95}) WITHIN GROUP (ORDER BY s.duration_ms) "
        f"FROM spans s JOIN turns u ON u.turn_id = s.turn_id JOIN {V_LEAF} t ON t.ticket_id = u.ticket_id "
        f"WHERE {LEAF_WINDOW} AND s.span_type = 'node' AND s.duration_ms IS NOT NULL GROUP BY s.name ORDER BY s.name"
    ), window_params(frm, to))).all()  # fmt: skip
    return {name: float(p95) for name, p95 in rows}


async def _call_rate(conn: AsyncConnection, frm: datetime, to: datetime, *, num: str, den: str) -> float | None:
    row = await scalar_row(conn, (
        f"SELECT count(*) FILTER (WHERE {den}), count(*) FILTER (WHERE {num}) {_leaf_calls()} WHERE {LEAF_WINDOW}"
    ), window_params(frm, to))  # fmt: skip
    return ratio(row[1], row[0])


async def cache_hit_rate(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """#lời gọi `cache_hit` / #lời gọi."""
    return await _call_rate(conn, frm, to, num="c.cache_hit", den="TRUE")


async def json_invalid_first_try_rate(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """#lời gọi `json_valid_first_try = false` / #lời gọi có giá trị khác NULL. NULL (provider lỗi trước khi có phản
    hồi) không phải "JSON lỗi" → ngoài cả tử lẫn mẫu."""
    return await _call_rate(
        conn, frm, to, num="c.json_valid_first_try = false", den="c.json_valid_first_try IS NOT NULL"
    )


async def fallback_rate(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """#lời gọi `used_fallback` / #lời gọi."""
    return await _call_rate(conn, frm, to, num="c.used_fallback", den="TRUE")


async def e2_llm_count(conn: AsyncConnection, frm: datetime, to: datetime) -> int:
    """#lá `exit_code = 'E2'` có dòng escalation E2 mới nhất mang `reason_detail` thuộc `E2_LLM_REASONS`."""
    params = {**window_params(frm, to), "reasons": list(E2_LLM_REASONS)}
    row = await scalar_row(conn, (
        f"SELECT count(*) FROM {V_LEAF} t WHERE {LEAF_WINDOW} AND t.exit_code = 'E2' AND "
        "(SELECT e.reason_detail FROM escalations e WHERE e.ticket_id = t.ticket_id AND e.exit_code = 'E2' "
        "ORDER BY e.created_at DESC, e.escalation_id DESC LIMIT 1) = ANY(CAST(:reasons AS text[]))"
    ), params)  # fmt: skip
    return int(row[0])


async def e9_count(conn: AsyncConnection, frm: datetime, to: datetime) -> int:
    """#lá `exit_code = 'E9'`."""
    row = await scalar_row(
        conn, f"SELECT count(*) FROM {V_LEAF} t WHERE {LEAF_WINDOW} AND t.exit_code = 'E9'", window_params(frm, to)
    )
    return int(row[0])


async def _audit_rate(
    conn: AsyncConnection, frm: datetime, to: datetime, *, steps: str, num: str, den: str
) -> float | None:
    row = await scalar_row(conn, (
        f"SELECT count(*) FILTER (WHERE {den}), count(*) FILTER (WHERE {num}) "
        f"FROM audit_logs a JOIN {V_LEAF} t ON t.ticket_id = a.ticket_id WHERE {LEAF_WINDOW} AND {steps}"
    ), window_params(frm, to))  # fmt: skip
    return ratio(row[1], row[0])


async def b2_llm_rate(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """Luật 12. Dòng step B2 xuống L4: `detail.screening.layer_decided = 'llm'` hoặc event `guard_unavailable` / dòng
    B2 có `layer_decided` hoặc `guard_unavailable` (Q-M9-A2-5)."""
    return await _audit_rate(conn, frm, to, steps="a.step = 'B2'", num=_B2_NUM, den=_B2_DEN)


async def intent_filter_fallback_rate(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """Dòng step B8 có `detail.intent_filter_fallback = true` / dòng B8 có giá trị `true` hoặc `false`. NULL (ca
    `retrieval_error`) và giá trị lệch kiểu nằm ngoài cả tử lẫn mẫu (Q-A2)."""
    return await _audit_rate(
        conn, frm, to, steps="a.step = 'B8'", num="a.detail->>'intent_filter_fallback' = 'true'",
        den="a.detail->>'intent_filter_fallback' IN ('true', 'false')",
    )  # fmt: skip


async def b3_llm_rate(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """Luật 13. Dòng điểm log 1 (step B3 và B4) có `detail.layer = 'llm'` / dòng có `detail.layer` khác NULL. Phase 3–4
    ≈ 1,0 (mọi câu xuống LLM) — đúng thực tế."""
    return await _audit_rate(
        conn, frm, to, steps=_B3_STEPS, num="a.detail->>'layer' = 'llm'", den="a.detail->>'layer' IS NOT NULL"
    )


async def intent_model_version(conn: AsyncConnection, frm: datetime, to: datetime) -> str | None:
    """`detail.model_version` của dòng B3/B4 mới nhất có giá trị; không có (ml-service `model_missing`) → None — chỉ số
    vẫn ready, không vào `unavailable` (Q-M9-A2-1)."""
    result = await conn.execute(text(
        f"SELECT a.detail->>'model_version' FROM audit_logs a JOIN {V_LEAF} t ON t.ticket_id = a.ticket_id "
        f"WHERE {LEAF_WINDOW} AND {_B3_STEPS} AND a.detail->>'model_version' IS NOT NULL "
        "ORDER BY a.created_at DESC, a.log_id DESC LIMIT 1"
    ), window_params(frm, to))  # fmt: skip
    value: str | None = result.scalar_one_or_none()
    return value


async def multi_intent_first_stop_to_reply_s(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """Câu nhiều ý (P9 §5.2, D-31; F12 #45): trung vị (`percentile_cont(0.5)`, nội suy) theo ticket CHA của số giây từ khi con
    đầu tiên dừng tới khi cha gửi tin — CHỈ vòng đầu. Nguồn `v_child_notices` (0011: notice của con là lá, không `body`).
    - Cha vào cửa sổ ⇔ `min(created_at)` của các con (`v_leaf.parent_ticket_id`) ∈ `[frm, to)` — không đọc ticket cha (D-30).
    - Vòng đầu = `min(delivered_round)` trên notice ĐÃ gửi; giá trị = `min(delivered_at) − min(created_at)` của notice thuộc
      vòng đó (notice chưa gửi hoặc gửi ở vòng sau không tính, kể cả khi tạo sớm hơn).
    - Cha chưa gửi vòng nào → không tính; không còn cha nào → None."""
    row = await scalar_row(conn, (
        f"WITH par AS (SELECT t.parent_ticket_id AS p FROM {V_LEAF} t WHERE t.parent_ticket_id IS NOT NULL "
        "GROUP BY t.parent_ticket_id HAVING min(t.created_at) >= :frm AND min(t.created_at) < :to), "
        f"r1 AS (SELECT n.parent_ticket_id AS p, min(n.delivered_round) AS r FROM {V_CHILD_NOTICES} n "
        "JOIN par ON par.p = n.parent_ticket_id WHERE n.delivered_round IS NOT NULL GROUP BY n.parent_ticket_id), "
        "per AS (SELECT CAST(extract(epoch FROM min(n.delivered_at) - min(n.created_at)) AS double precision) AS s "
        f"FROM {V_CHILD_NOTICES} n JOIN r1 ON r1.p = n.parent_ticket_id AND n.delivered_round = r1.r "
        "GROUP BY n.parent_ticket_id) "
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY per.s) FROM per"
    ), window_params(frm, to))  # fmt: skip
    return None if row[0] is None else float(row[0])


# Khóa → truy vấn `(conn, frm, to)`. None = chưa có nguồn: khóa đó PHẢI pending trong METRIC_SOURCES (test ghim).
QUERIES: Mapping[str, Callable[..., Awaitable[Any]] | None] = {
    "tokens_per_ticket": tokens_per_ticket,
    "cost_per_day": cost_per_day,
    "latency_p95_by_step": latency_p95_by_step,
    "cache_hit_rate": cache_hit_rate,
    "json_invalid_first_try_rate": json_invalid_first_try_rate,
    "fallback_rate": fallback_rate,
    "e2_llm_count": e2_llm_count,
    "e9_count": e9_count,
    "b2_llm_rate": b2_llm_rate,
    "intent_filter_fallback_rate": intent_filter_fallback_rate,
    "b3_llm_rate": b3_llm_rate,
    "intent_model_version": intent_model_version,
    "multi_intent_first_stop_to_reply_s": multi_intent_first_stop_to_reply_s,  # F12 (D-31)
    "multi_intent_messages_per_turn": None,  # D-31: cần lượt của ticket cha (D-30) — pending `d30_parent_turns`
}


async def ai_metrics(conn: AsyncConnection, frm: datetime, to: datetime) -> AiMetrics:
    """Gom chỉ số cho `/api/dashboard/ai` (chỉ `dashboard:read:all`): đủ `AI_METRICS`; pending → None + `unavailable`."""
    window_params(frm, to)
    values: dict[str, Any] = {}
    unavailable: list[str] = []
    for key in AI_METRICS:
        query = QUERIES[key]
        if is_pending(key):
            values[key] = None
            unavailable.append(key)
        elif query is None:
            raise RuntimeError(f"{key}: METRIC_SOURCES ghi ready nhưng chưa có truy vấn")
        else:
            values[key] = await query(conn, frm, to)
    return AiMetrics(values=values, unavailable=tuple(unavailable))
