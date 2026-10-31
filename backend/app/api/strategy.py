"""Chiến lược M5 lúc vận hành (D-67) — ba route quản lý + chụp chiến lược lên ticket mới.

`GET /api/admin/strategy` (quyền `policy:read`) → trạng thái PHẲNG: chiến lược hiện hành, `selectable`, `llm_calibrated`
(= `m5.calibrator_version` khác null), `eval_mode`, và dòng đổi gần nhất (`changed_by/at`, `reason`; chưa có dòng → `hybrid` + 3 trường
null). `PUT` (quyền `policy:edit` + đăng nhập lại ≤ `reauth_minutes`, như đường ghi đè): thứ tự lỗi 401 → 403 `forbidden` → 403
`reauth_required` → 422 `{"error":"invalid_request","fields":["strategy"|"reason"]}` → 409 `same_as_current` → privacy guard (503) → ghi.
`reason` 10–500 ký tự SAU khi cắt khoảng trắng, đi qua privacy guard (bảng chỉ ghi thêm — chữ đã ghi không xoá được). Ghi MỘT
transaction: dòng `m5_strategy_changes` + `security_events` `policy_saved` với `detail = {kind: "m5_strategy", from, to}`.
`GET …/history?limit=` (1–200, mặc định 50): mới nhất trước; `strategy_from` = dòng liền trước (dòng đầu → `hybrid`).

`snapshot_for_new_ticket` (gọi ở `POST /api/tickets`): EVAL_MODE → chiến lược từ env (`Settings.strategy`), BỎ QUA DB, `source='eval'`;
còn lại → dòng mới nhất của `m5_strategy_changes` (ngoài `RUNTIME_SELECTABLE` — không được xảy ra — thì `hybrid` + log cảnh báo; đọc DB
lỗi → 503 `strategy_unavailable`, không tạo ticket — khuôn `checkpoint_unavailable` của `GET /api/tickets/{id}`);
`source='sim'` CHỈ khi request có header `X-Sim-Run` VÀ `APP_ENV` ∈ {dev, test} (ngoài dev/test bỏ qua header), còn lại `'real'`.
"""

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator

from app.api.alerts import ErrorDetail
from app.api.desk import SECRET_EVENT, Desk, get_desk, parse_body, redact, route_of
from app.api.errors import InvalidRequest, PrivacyGuardUnavailable
from app.auth.deps import require
from app.auth.models import Principal
from app.db.m5_strategy import DEFAULT_STRATEGY, SameStrategy, StrategyChange
from app.risk.strategy import RUNTIME_SELECTABLE
from app.settings import DEV_FAKE_ENVS, Settings, get_policy

log = logging.getLogger(__name__)
router = APIRouter()

SIM_HEADER = "X-Sim-Run"
REASON_MIN, REASON_MAX = 10, 500
HISTORY_DEFAULT, HISTORY_MAX = 50, 200
ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}, 409: {"model": ErrorDetail}, 503: {"model": ErrorDetail},
}  # fmt: skip


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategyState(_Strict):
    strategy: str  # một trong `selectable`
    selectable: list[str]
    llm_calibrated: bool
    eval_mode: bool
    changed_by: str | None
    changed_at: datetime | None
    reason: str | None


class HistoryItem(_Strict):
    changed_at: datetime
    changed_by: str
    strategy_from: str
    strategy_to: str
    reason: str


class StrategyHistory(_Strict):
    items: list[HistoryItem]
    truncated: bool


class StrategyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: str
    reason: str

    @field_validator("strategy")
    @classmethod
    def _selectable(cls, value: str) -> str:
        if value not in RUNTIME_SELECTABLE:
            raise ValueError("strategy")
        return value

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = value.strip()
        if not REASON_MIN <= len(value) <= REASON_MAX:
            raise ValueError("reason")
        return value


def effective(current: StrategyChange | None) -> str:
    """Chiến lược hiện hành: chưa có dòng → `hybrid`; giá trị ngoài `RUNTIME_SELECTABLE` (không được xảy ra) → `hybrid` + cảnh báo."""
    if current is None:
        return DEFAULT_STRATEGY
    if current.strategy not in RUNTIME_SELECTABLE:
        log.warning("m5_strategy_changes: giá trị %r ngoài RUNTIME_SELECTABLE — dùng %s", current.strategy, DEFAULT_STRATEGY)
        return DEFAULT_STRATEGY
    return current.strategy


def _state(settings: Settings, current: StrategyChange | None) -> StrategyState:
    return StrategyState(
        strategy=effective(current), selectable=list(RUNTIME_SELECTABLE),
        llm_calibrated=get_policy().m5.calibrator_version is not None, eval_mode=settings.eval_mode,
        changed_by=current.changed_by if current else None, changed_at=current.changed_at if current else None,
        reason=current.reason if current else None,
    )  # fmt: skip


async def snapshot_for_new_ticket(request: Request, desk: Desk) -> tuple[str, str]:
    """(strategy, source) chụp lên ticket gốc lúc tạo. Ticket con kế thừa từ cha ở `db/tickets.create_child`."""
    settings: Settings = request.app.state.settings
    if settings.eval_mode:  # env thắng, bỏ qua DB
        return settings.strategy, "eval"
    try:
        current = await desk.strategy.current()
    except Exception:  # khuôn `checkpoint_unavailable` (api/tickets.py): không đoán chiến lược khi DB lỗi, không tạo ticket
        log.exception("đọc chiến lược M5 hiện hành lỗi — không tạo ticket")
        raise HTTPException(503, "strategy_unavailable") from None
    strategy = effective(current)
    sim = SIM_HEADER in request.headers and settings.app_env in DEV_FAKE_ENVS
    return strategy, "sim" if sim else "real"


@router.get("/api/admin/strategy", response_model=StrategyState, responses=ERRORS)
async def get_strategy(
    request: Request,
    _: Annotated[Principal, Depends(require("policy:read"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> StrategyState:
    return _state(request.app.state.settings, await desk.strategy.current())


@router.put("/api/admin/strategy", response_model=StrategyState, responses=ERRORS)
async def put_strategy(
    request: Request,
    p: Annotated[Principal, Depends(require("policy:edit", recent_login=True))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> StrategyState:
    body = await parse_body(request, StrategyIn)
    if body.strategy == effective(await desk.strategy.current()):
        raise HTTPException(409, "same_as_current")
    redacted = await redact(desk, request, body.reason)
    if redacted.secrets_found:
        try:
            await desk.security.record(
                SECRET_EVENT, user_id=p.user_id, route=route_of(request), detail={"count": redacted.secrets_found}
            )
        except Exception as exc:  # noqa: BLE001 — ghi sự kiện lỗi → 503, không ghi đổi chiến lược (khuôn desk.record_redacted)
            log.error("ghi %s lỗi: route=%s loại=%s", SECRET_EVENT, route_of(request), type(exc).__name__)
            raise PrivacyGuardUnavailable from None
    reason = redacted.text.strip()
    if len(reason) < REASON_MIN:  # che xong còn quá ngắn
        raise InvalidRequest(["reason"])
    try:
        change = await desk.strategy.append(body.strategy, changed_by=p.user_id, reason=reason, at=desk.clock.now())
    except SameStrategy:  # hai PUT đồng thời — người sau thấy chiến lược đã đổi
        raise HTTPException(409, "same_as_current") from None
    return _state(request.app.state.settings, change)


@router.get("/api/admin/strategy/history", response_model=StrategyHistory, responses=ERRORS)
async def strategy_history(
    _: Annotated[Principal, Depends(require("policy:read"))],
    desk: Annotated[Desk, Depends(get_desk)],
    limit: Annotated[int, Query(ge=1, le=HISTORY_MAX)] = HISTORY_DEFAULT,
) -> StrategyHistory:
    changes, truncated = await desk.strategy.history(limit)
    items = [
        HistoryItem(changed_at=c.changed_at, changed_by=c.changed_by, strategy_from=c.strategy_from, strategy_to=c.strategy,
                    reason=c.reason)
        for c in changes
    ]  # fmt: skip
    return StrategyHistory(items=items, truncated=truncated)
