"""So sánh phương án M5 (D-60 P2) — `GET /api/dashboard/strategies`: 17 chỉ số theo chiến lược đã CHỤP trên ticket lá.

- Chỉ đọc qua `AsyncConnection` của engine `app_monitor`, qua `v_leaf` (cột `strategy`, `source` — migration 0013). Cửa sổ `[frm, to)`
  theo `created_at` của lá; CHỈ lá đã kết thúc (`final_state IS NOT NULL`) — khuôn `business.py`. Lọc `source` (real/sim) và
  `strategy = ANY(:strategies)` — ticket `strategy` NULL (trước D-60), `llm_only`, `full_auto` KHÔNG vào bảng. Danh sách chiến lược do
  route truyền (`risk.strategy.RUNTIME_SELECTABLE`; monitor không import `risk` — hợp đồng import 2).
- Trả SỐ ĐẾM kèm mẫu số (`{num, den}`) hoặc giá trị kèm `n` — không "điểm tổng". Chiến lược 0 lá → `None` ở mọi chỉ số (route trả null).
- Định nghĩa (mỗi lá một dòng `per`, rồi gộp theo chiến lược):
  * `auto_rate` — lá TỰ XỬ LÝ = ĐÚNG định nghĩa `business.automation_rate`: `S_RESOLVED` ∧ không dòng `approvals` ∧ không dòng
    `escalations` (gồm ca chỉ trả lời — deflected). Mẫu = số lá.
  * `hitl_rate`, `l2_rate` — `detail.route` của dòng `audit_logs` step `B13/B14` MỚI NHẤT của lá (`created_at`, `log_id` giảm dần;
    gồm cả `llm_layer_disabled` — route ESCALATE_L2) = `HITL` / `ESCALATE_L2`. Mẫu = số lá.
  * `confirmed_rate`, `no_response_rate`, `unresolved_rate` — lá có dòng B19 `user_confirmed` / `auto_closed_no_response_48h` /
    `user_reported_unresolved`; mẫu = số lá có ít nhất một trong 3 sự kiện.
  * `l1_reject_rate` — phiếu `rejected` / phiếu `approved + rejected` (đếm PHIẾU `approvals` của lá).
  * `quick_approve_rate` — phiếu `approved` có dòng audit B16 cùng ticket (`approval_result = 'approved'`, `created_at ≥` phiếu) mà
    `detail.decided_without_view = true` hoặc `detail.view_duration < REFLEX_SECONDS` (5 — khuôn luật 7 `monitor/rules.py`; ca "mơ hồ"
    của luật 7 KHÔNG tính) / phiếu `approved + rejected`.
  * `system_time_p50/p90` (giây) — trung vị / p90 (`percentile_cont`, nội suy) của Σ `spans.duration_ms` (`span_type = 'node'`,
    `status <> 'interrupted'`, qua `turns`) mỗi lá ÷ 1000; LOẠI lá không có span; `n` = số lá có span.
  * `human_wait_p50` (phút) — trung vị của Σ (`decided_at − created_at`) các phiếu `approved`/`rejected` mỗi lá ÷ 60; `n` = số lá có
    phiếu đã quyết; không có → `value` null.
  * `human_minutes_per_100` (phút) — 100 × Σ max(`detail.view_duration`, 0) của dòng B16 (`approval_result` approved/rejected) ÷ 60
    ÷ số lá; `n` = số lá.
  * `e5_recheck_failed` — số lá có `escalations` E5 `reason_detail = recheck_failed`; `overrides` — số dòng `audit_logs`
    `OVERRIDE/override_recorded` của lá; `rollbacks` — số lá có dòng B17 `rollback_status ∈ {undone, partial, undo_failed}`.
  * `llm_cost_per_ticket` (USD) — Σ `llm_calls.cost_usd` (NULL = 0; `llm_calls → spans → turns`) của lá ÷ số lá; `n` = số lá.
- JSON `detail` đọc dạng chữ; ép số chỉ khi `jsonb_typeof = 'number'` (trong CASE — dòng lệch kiểu không làm hỏng truy vấn).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.override import OVERRIDE_EVENT, OVERRIDE_STEP
from app.monitor.queries.common import DONE, LEAF_WINDOW, window_params
from app.monitor.rules import REFLEX_SECONDS
from app.monitor.views import V_LEAF

type Kind = Literal["ratio", "value"]
type Unit = Literal["count", "s", "min", "usd"]


@dataclass(frozen=True)
class MetricSpec:
    key: str
    kind: Kind
    unit: Unit | None = None  # chỉ `value`
    with_n: bool = False  # `value` kèm `n`


# 17 khoá, ĐÚNG thứ tự hợp đồng (BE chốt 26/10)
STRATEGY_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("tickets", "value", "count"),
    MetricSpec("auto_rate", "ratio"),
    MetricSpec("hitl_rate", "ratio"),
    MetricSpec("l2_rate", "ratio"),
    MetricSpec("confirmed_rate", "ratio"),
    MetricSpec("no_response_rate", "ratio"),
    MetricSpec("unresolved_rate", "ratio"),
    MetricSpec("l1_reject_rate", "ratio"),
    MetricSpec("quick_approve_rate", "ratio"),
    MetricSpec("system_time_p50", "value", "s", with_n=True),
    MetricSpec("system_time_p90", "value", "s", with_n=True),
    MetricSpec("human_wait_p50", "value", "min", with_n=True),
    MetricSpec("human_minutes_per_100", "value", "min", with_n=True),
    MetricSpec("e5_recheck_failed", "value", "count"),
    MetricSpec("overrides", "value", "count"),
    MetricSpec("rollbacks", "value", "count"),
    MetricSpec("llm_cost_per_ticket", "value", "usd", with_n=True),
)
ROLLBACK_DONE = ("undone", "partial", "undo_failed")  # B17 đã thử hoàn tác (khác `none_needed`, `not_attempted`)

_LEAF = (
    f"SELECT t.ticket_id, t.strategy, t.intent, t.final_state FROM {V_LEAF} t WHERE {LEAF_WINDOW} AND {DONE} "
    "AND t.source = :source AND t.strategy = ANY(CAST(:strategies AS text[]))"
)
_NUM = "jsonb_typeof(a.detail->'view_duration') = 'number'"
_PER = (
    "SELECT l.ticket_id, l.strategy, "
    "(l.final_state = 'S_RESOLVED' AND NOT EXISTS (SELECT 1 FROM approvals x WHERE x.ticket_id = l.ticket_id) "
    " AND NOT EXISTS (SELECT 1 FROM escalations x WHERE x.ticket_id = l.ticket_id)) AS auto, "
    "(SELECT a.detail->>'route' FROM audit_logs a WHERE a.ticket_id = l.ticket_id AND a.step = 'B13/B14' "
    " ORDER BY a.created_at DESC, a.log_id DESC LIMIT 1) AS route, "
    "EXISTS (SELECT 1 FROM audit_logs a WHERE a.ticket_id = l.ticket_id AND a.step = 'B19' AND a.event = 'user_confirmed') AS confirmed, "
    "EXISTS (SELECT 1 FROM audit_logs a WHERE a.ticket_id = l.ticket_id AND a.step = 'B19' "
    " AND a.event = 'auto_closed_no_response_48h') AS no_response, "
    "EXISTS (SELECT 1 FROM audit_logs a WHERE a.ticket_id = l.ticket_id AND a.step = 'B19' "
    " AND a.event = 'user_reported_unresolved') AS unresolved, "
    "(SELECT count(*) FROM approvals ap WHERE ap.ticket_id = l.ticket_id AND ap.status = 'approved') AS approved, "
    "(SELECT count(*) FROM approvals ap WHERE ap.ticket_id = l.ticket_id AND ap.status = 'rejected') AS rejected, "
    "(SELECT count(*) FROM approvals ap WHERE ap.ticket_id = l.ticket_id AND ap.status = 'approved' AND EXISTS ("
    "  SELECT 1 FROM audit_logs a WHERE a.ticket_id = ap.ticket_id AND a.step = 'B16' AND a.approval_result = 'approved' "
    "  AND a.created_at >= ap.created_at AND (a.detail->>'decided_without_view' = 'true' "
    f"  OR CASE WHEN {_NUM} THEN CAST(a.detail->>'view_duration' AS float8) < :reflex ELSE false END))) AS quick, "
    "(SELECT sum(s.duration_ms) FROM spans s JOIN turns u ON u.turn_id = s.turn_id WHERE u.ticket_id = l.ticket_id "
    " AND s.span_type = 'node' AND s.status <> 'interrupted') AS system_ms, "
    "(SELECT sum(EXTRACT(EPOCH FROM ap.decided_at - ap.created_at)) FROM approvals ap WHERE ap.ticket_id = l.ticket_id "
    " AND ap.status IN ('approved', 'rejected') AND ap.decided_at IS NOT NULL) AS human_wait_s, "
    f"(SELECT COALESCE(sum(CASE WHEN {_NUM} THEN GREATEST(CAST(a.detail->>'view_duration' AS float8), 0) ELSE 0 END), 0) "
    " FROM audit_logs a WHERE a.ticket_id = l.ticket_id AND a.step = 'B16' AND a.approval_result IN ('approved', 'rejected')) "
    " AS view_s, "
    "EXISTS (SELECT 1 FROM escalations e WHERE e.ticket_id = l.ticket_id AND e.exit_code = 'E5' "
    " AND e.reason_detail = 'recheck_failed') AS recheck, "
    "(SELECT count(*) FROM audit_logs a WHERE a.ticket_id = l.ticket_id AND a.step = :ostep AND a.event = :oevent) AS overrides, "
    "EXISTS (SELECT 1 FROM audit_logs a WHERE a.ticket_id = l.ticket_id AND a.step = 'B17' "
    " AND a.rollback_status = ANY(CAST(:rollback AS text[]))) AS rollback, "
    "(SELECT COALESCE(sum(c.cost_usd), 0) FROM llm_calls c JOIN spans s ON s.span_id = c.span_id JOIN turns u ON u.turn_id = s.turn_id "
    " WHERE u.ticket_id = l.ticket_id) AS cost "
    "FROM leaf l"
)
_AGG = (
    f"WITH leaf AS ({_LEAF}), per AS ({_PER}) SELECT strategy, count(*) AS n, count(*) FILTER (WHERE auto) AS auto, "
    "count(*) FILTER (WHERE route = 'HITL') AS hitl, count(*) FILTER (WHERE route = 'ESCALATE_L2') AS l2, "
    "count(*) FILTER (WHERE confirmed OR no_response OR unresolved) AS b19, count(*) FILTER (WHERE confirmed) AS confirmed, "
    "count(*) FILTER (WHERE no_response) AS no_response, count(*) FILTER (WHERE unresolved) AS unresolved, "
    "COALESCE(sum(approved), 0) AS approved, COALESCE(sum(rejected), 0) AS rejected, COALESCE(sum(quick), 0) AS quick, "
    "percentile_cont(0.5) WITHIN GROUP (ORDER BY system_ms) FILTER (WHERE system_ms IS NOT NULL) AS sys_p50, "
    "percentile_cont(0.9) WITHIN GROUP (ORDER BY system_ms) FILTER (WHERE system_ms IS NOT NULL) AS sys_p90, "
    "count(system_ms) AS sys_n, "
    "percentile_cont(0.5) WITHIN GROUP (ORDER BY human_wait_s) FILTER (WHERE human_wait_s IS NOT NULL) AS wait_p50, "
    "count(human_wait_s) AS wait_n, COALESCE(sum(view_s), 0) AS view_s, count(*) FILTER (WHERE recheck) AS recheck, "
    "COALESCE(sum(overrides), 0) AS overrides, count(*) FILTER (WHERE rollback) AS rollbacks, COALESCE(sum(cost), 0) AS cost "
    "FROM per GROUP BY strategy"
)
_INTENTS = f"WITH leaf AS ({_LEAF}) SELECT strategy, COALESCE(intent, 'none'), count(*) FROM leaf GROUP BY 1, 2 ORDER BY 1, 2"


@dataclass(frozen=True)
class StrategyComparison:
    intent_mix: Mapping[str, Mapping[str, int]]  # chiến lược 0 lá → {}
    metrics: tuple[tuple[MetricSpec, Mapping[str, Mapping[str, Any] | None]], ...]  # 17 khoá, đúng thứ tự
    unavailable: tuple[str, ...]


def _value(x: Any, scale: float = 1.0) -> float | None:
    return None if x is None else float(x) / scale


def cells(agg: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """THUẦN: một dòng gộp của MỘT chiến lược (n ≥ 1) → ô của 17 khoá. Tỉ lệ → `{num, den}` (mẫu 0 vẫn trả, FE quyết hiển thị)."""
    n = int(agg["n"])
    decided = int(agg["approved"]) + int(agg["rejected"])
    b19 = int(agg["b19"])
    return {
        "tickets": {"value": n},
        "auto_rate": {"num": int(agg["auto"]), "den": n},
        "hitl_rate": {"num": int(agg["hitl"]), "den": n},
        "l2_rate": {"num": int(agg["l2"]), "den": n},
        "confirmed_rate": {"num": int(agg["confirmed"]), "den": b19},
        "no_response_rate": {"num": int(agg["no_response"]), "den": b19},
        "unresolved_rate": {"num": int(agg["unresolved"]), "den": b19},
        "l1_reject_rate": {"num": int(agg["rejected"]), "den": decided},
        "quick_approve_rate": {"num": int(agg["quick"]), "den": decided},
        "system_time_p50": {"value": _value(agg["sys_p50"], 1000), "n": int(agg["sys_n"])},
        "system_time_p90": {"value": _value(agg["sys_p90"], 1000), "n": int(agg["sys_n"])},
        "human_wait_p50": {"value": _value(agg["wait_p50"], 60), "n": int(agg["wait_n"])},
        "human_minutes_per_100": {"value": 100 * float(agg["view_s"]) / 60 / n, "n": n},
        "e5_recheck_failed": {"value": int(agg["recheck"])},
        "overrides": {"value": int(agg["overrides"])},
        "rollbacks": {"value": int(agg["rollbacks"])},
        "llm_cost_per_ticket": {"value": float(agg["cost"]) / n, "n": n},
    }  # fmt: skip


def assemble(
    strategies: Sequence[str], aggs: Mapping[str, Mapping[str, Any]], intents: Mapping[str, Mapping[str, int]]
) -> StrategyComparison:
    """THUẦN: chiến lược không có dòng gộp (0 lá) → `None` ở mọi khoá, `intent_mix` = {}."""
    per = {s: cells(aggs[s]) if s in aggs else None for s in strategies}
    metrics = tuple(
        (spec, {s: None if cell is None else cell[spec.key] for s, cell in per.items()}) for spec in STRATEGY_METRICS
    )
    return StrategyComparison({s: dict(intents.get(s, {})) for s in strategies}, metrics, ())


async def strategy_comparison(
    conn: AsyncConnection, frm: datetime, to: datetime, *, source: str, strategies: Sequence[str]
) -> StrategyComparison:
    params = {**window_params(frm, to), "source": source, "strategies": list(strategies), "reflex": REFLEX_SECONDS,
              "ostep": OVERRIDE_STEP, "oevent": OVERRIDE_EVENT, "rollback": list(ROLLBACK_DONE)}  # fmt: skip
    rows = (await conn.execute(text(_AGG), params)).mappings().all()
    aggs = {str(r["strategy"]): dict(r) for r in rows}
    intents: dict[str, dict[str, int]] = {}
    for strategy, intent, count in (await conn.execute(text(_INTENTS), params)).all():
        intents.setdefault(str(strategy), {})[str(intent)] = int(count)
    return assemble(strategies, aggs, intents)
