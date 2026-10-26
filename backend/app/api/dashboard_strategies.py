"""`GET /api/dashboard/strategies` — so sánh phương án M5 (D-60 P2; hình dạng BE chốt 26/10).

Quyền `dashboard:read:all` (như `/api/dashboard/ai`). Thứ tự lỗi: 401 → 403 → 422 (`source` ngoài `real|sim` — KHÔNG có `all` —, kiểu
`from`/`to`; FastAPI gom sau dependency quyền) → 422 `resolve_window` (thân handler) → 503 `monitor_unavailable` (engine monitor).
Cửa sổ: `resolve_window` của `api/dashboard.py` (mặc định 7 ngày, tối đa 90). Một response = một giao dịch READ ONLY.

Thân: `{source, from, to, strategies, intent_mix: {<chiến lược>: {<intent>: n}}, metrics: [{key, kind, unit?, values: {<chiến lược>:
ô | null}}], unavailable}` — `strategies` = `risk.strategy.RUNTIME_SELECTABLE` (đúng thứ tự); 17 khoá `metrics` đúng thứ tự
`monitor.queries.strategies.STRATEGY_METRICS`. Ô tỉ lệ `{num, den}`; ô giá trị `{value}` hoặc `{value, n}` (khoá "kèm n"). Chiến lược 0
lá → null. Không có "điểm tổng". Định nghĩa từng ô: docstring `monitor/queries/strategies.py`.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.alerts import GET_ERRORS
from app.api.dashboard import resolve_window, window
from app.auth.deps import require
from app.auth.models import Principal
from app.monitor.db import read_snapshot
from app.monitor.queries.strategies import strategy_comparison
from app.risk.strategy import RUNTIME_SELECTABLE

router = APIRouter()

type Source = Literal["real", "sim"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RatioCell(_Strict):
    num: int
    den: int


class ValueCell(_Strict):
    value: int | float | None


class ValueNCell(_Strict):
    value: int | float | None
    n: int


class RatioMetric(_Strict):
    key: str
    kind: Literal["ratio"]
    values: dict[str, RatioCell | None]


class ValueMetric(_Strict):
    key: str
    kind: Literal["value"]
    unit: Literal["count", "s", "min", "usd"]
    values: dict[str, ValueNCell | ValueCell | None]


class StrategyDashboard(_Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: Source
    frm: datetime = Field(alias="from")
    to: datetime
    strategies: list[str]
    intent_mix: dict[str, dict[str, int]]
    metrics: list[RatioMetric | ValueMetric]
    unavailable: list[str]


@router.get("/api/dashboard/strategies", response_model=StrategyDashboard, responses=GET_ERRORS)
async def dashboard_strategies(
    request: Request,
    _: Annotated[Principal, Depends(require("dashboard:read:all"))],
    raw: Annotated[tuple[datetime | None, datetime | None], Depends(window)],
    source: Annotated[Source, Query()] = "real",
) -> StrategyDashboard:
    now: datetime = request.app.state.m9_clock.now()
    frm, to = resolve_window(*raw, now=now)
    strategies = list(RUNTIME_SELECTABLE)
    async with read_snapshot(request.app.state.engines) as conn:
        got = await strategy_comparison(conn, frm, to, source=source, strategies=strategies)
    metrics: list[RatioMetric | ValueMetric] = []
    for spec, values in got.metrics:
        if spec.kind == "ratio":
            metrics.append(RatioMetric.model_validate({"key": spec.key, "kind": "ratio", "values": values}))
        else:
            metrics.append(ValueMetric.model_validate({"key": spec.key, "kind": "value", "unit": spec.unit, "values": values}))
    return StrategyDashboard.model_validate({
        "source": source, "from": frm, "to": to, "strategies": strategies, "intent_mix": got.intent_mix, "metrics": metrics,
        "unavailable": list(got.unavailable),
    })  # fmt: skip
