"""`GET /api/dashboard/business`, `GET /api/dashboard/ai` — M9 A3 (kế hoạch M9 4.5, 5.1–5.3; duyệt plan A3 ở #10).

Thứ tự kiểm: 401 → quyền (403 + `permission_denied`) → 422 kiểu tham số (FastAPI gom, ném SAU dependency quyền) → 422
`resolve_window` (gọi ở THÂN handler, sau quyền — không đặt trong dependency, kẻo không token/L2 với cửa sổ sai nhận 422
thay vì 401/403) → engine monitor (thiếu DSN → 503 `monitor_unavailable`, không rơi về `engines.main`).

- Quyền business: `dashboard:read:all` → `scope="all"`, đủ 10 khoá; `dashboard:read:own` (L1) → `scope="own"`, đúng
  `OWN_KEYS`, tính trên phiếu giao cho chính người trong token (không nhận người duyệt / phạm vi từ query). `require` chỉ nhận
  một quyền, `auth/deps.py` không thuộc M9 → `business_scope` dựa trên `require()` (chỉ cần đăng nhập) rồi tự kiểm, từ chối
  qua `deny(...)` (Q-M9-A3-7). AI: `require("dashboard:read:all")`.
- Một response = một giao dịch `REPEATABLE READ, READ ONLY` (`monitor.db.read_snapshot`, review PR #22).
- `metrics` là model Pydantic TƯỜNG MINH, mọi trường bắt buộc kiểu `T | None`, không default, `extra="forbid"` (Q-M9-A3-3):
  FastAPI lọc IM LẶNG khoá không có trong `response_model` — thêm chỉ số mà quên model thì response mất khoá không ai biết;
  ở đây dựng model lỗi to (test hai chiều tập trường = `BUSINESS_METRICS` / `OWN_KEYS` / `AI_METRICS`).
- `from`/`to` trả lại ở UTC.

Cửa sổ (`resolve_window`, Q-M9-A3-5): thiếu `to` → now (Clock của app); thiếu `from` → `to − 7 ngày`; `from < to`;
`to − from ≤ 90 ngày`; chặn biên `from ≥ 2000-01-01T00:00Z`, `to ≤ now + 1 ngày` — kiểm biên TRƯỚC khi tính mặc định
(`to` năm 0001 thì `to − 7 ngày` tràn; năm 9999 thì `day_starts` tràn → 500). Đổi về UTC có thể tràn (offset sát năm
1/9999) → 422.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.api.alerts import GET_ERRORS
from app.api.errors import InvalidRequest
from app.auth.deps import deny, require
from app.auth.models import Principal
from app.monitor.db import read_snapshot
from app.monitor.queries.ai import DayCost, ai_metrics
from app.monitor.queries.business import (
    E1Split,
    E3Cases,
    RuleCount,
    WeightedRate,
    business_metrics,
)

router = APIRouter()

WINDOW_LO = datetime(2000, 1, 1, tzinfo=UTC)
WINDOW_AHEAD = timedelta(days=1)
WINDOW_DEFAULT = timedelta(days=7)
WINDOW_MAX = timedelta(days=90)
FROM, TO = "query.from", "query.to"

type Scope = Literal["all", "own"]


def _bounded_utc(field: str, value: datetime | None, lo: datetime, hi: datetime) -> datetime | None:
    """Giá trị người gửi → UTC, trong `[lo, hi]`; tràn khi đổi múi giờ hoặc ngoài biên → `InvalidRequest([field])`."""
    if value is None:
        return None
    try:
        utc = value.astimezone(UTC)
    except OverflowError:
        raise InvalidRequest([field]) from None
    if not lo <= utc <= hi:
        raise InvalidRequest([field])
    return utc


def resolve_window(frm: datetime | None, to: datetime | None, now: datetime) -> tuple[datetime, datetime]:
    """Cửa sổ `[from, to)` kiểu UTC; sai → `InvalidRequest(fields)` (422). Hàm thuần — `now` do route truyền (Clock)."""
    now = now.astimezone(UTC)
    lo, hi = WINDOW_LO, now + WINDOW_AHEAD
    given_from, given_to = _bounded_utc(FROM, frm, lo, hi), _bounded_utc(TO, to, lo, hi)
    end = given_to or now
    start = given_from or end - WINDOW_DEFAULT
    if start < lo:
        raise InvalidRequest([FROM])
    if start >= end or end - start > WINDOW_MAX:
        raise InvalidRequest([FROM, TO])
    return start, end


def window(
    frm: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to: Annotated[AwareDatetime | None, Query()] = None,
) -> tuple[datetime | None, datetime | None]:
    """Chỉ khai kiểu (có múi giờ); mọi kiểm giá trị ở `resolve_window`, gọi trong thân handler sau quyền."""
    return frm, to


async def business_scope(request: Request, p: Annotated[Principal, Depends(require())]) -> tuple[Scope, Principal]:
    if p.has("dashboard:read:all"):
        return "all", p
    if p.has("dashboard:read:own"):
        return "own", p
    await deny(request, p, "dashboard:read:own")
    raise HTTPException(403, "forbidden")


class _Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BusinessAllMetrics(_Metrics):
    automation_rate: float | None
    escalation_rate_raw: float | None
    escalation_rate_weighted: WeightedRate | None
    deflection_rate: float | None
    approval_expired_count: int | None
    decided_by_distribution: dict[str, int] | None
    top_matched_rules: list[RuleCount] | None
    override_count: int | None
    e1_split: E1Split | None
    e3_cases: E3Cases | None


class BusinessOwnMetrics(_Metrics):
    approval_expired_count: int | None
    decided_by_distribution: dict[str, int] | None
    top_matched_rules: list[RuleCount] | None


class AiMetrics(_Metrics):
    tokens_per_ticket: float | None
    cost_per_day: list[DayCost] | None
    latency_p95_by_step: dict[str, float] | None
    cache_hit_rate: float | None
    json_invalid_first_try_rate: float | None
    fallback_rate: float | None
    e2_llm_count: int | None
    e9_count: int | None
    b2_llm_rate: float | None
    intent_filter_fallback_rate: float | None
    b3_llm_rate: float | None
    intent_model_version: str | None
    multi_intent_first_stop_to_reply_s: float | None
    multi_intent_messages_per_turn: float | None


class _Dashboard(BaseModel):
    frm: datetime = Field(alias="from")
    to: datetime
    unavailable: list[str]


class BusinessAll(_Dashboard):
    scope: Literal["all"]
    metrics: BusinessAllMetrics


class BusinessOwn(_Dashboard):
    scope: Literal["own"]
    metrics: BusinessOwnMetrics


class AiDashboard(_Dashboard):
    metrics: AiMetrics


BusinessDashboard = Annotated[BusinessAll | BusinessOwn, Field(discriminator="scope")]


def _now(request: Request) -> datetime:
    now: datetime = request.app.state.m9_clock.now()
    return now


@router.get("/api/dashboard/business", response_model=BusinessDashboard, responses=GET_ERRORS)
async def dashboard_business(
    request: Request,
    scope: Annotated[tuple[Scope, Principal], Depends(business_scope)],
    raw: Annotated[tuple[datetime | None, datetime | None], Depends(window)],
) -> Any:
    kind, p = scope
    frm, to = resolve_window(*raw, now=_now(request))
    async with read_snapshot(request.app.state.engines) as conn:
        got = await business_metrics(conn, frm, to, approver_id=None if kind == "all" else p.user_id)
    body = {"from": frm, "to": to, "unavailable": list(got.unavailable), "scope": kind}
    if kind == "all":
        return BusinessAll.model_validate({**body, "metrics": BusinessAllMetrics(**got.values)})
    return BusinessOwn.model_validate({**body, "metrics": BusinessOwnMetrics(**got.values)})


@router.get("/api/dashboard/ai", response_model=AiDashboard, responses=GET_ERRORS)
async def dashboard_ai(
    request: Request,
    _: Annotated[Principal, Depends(require("dashboard:read:all"))],
    raw: Annotated[tuple[datetime | None, datetime | None], Depends(window)],
) -> AiDashboard:
    frm, to = resolve_window(*raw, now=_now(request))
    async with read_snapshot(request.app.state.engines) as conn:
        got = await ai_metrics(conn, frm, to)
    return AiDashboard.model_validate(
        {"from": frm, "to": to, "unavailable": list(got.unavailable), "metrics": AiMetrics(**got.values)}
    )
