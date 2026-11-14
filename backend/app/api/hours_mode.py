"""Giả lập giờ hành chính cho demo (D-97, TA chốt 14/11) — hai route.

`GET /api/hours-mode` (MỌI người đã đăng nhập — giao diện hiện dải báo "đang giả lập" cho mọi vai trò) → `{mode, modes, changed_by,
changed_at, eval_mode}`. `PUT /api/admin/hours-mode` (quyền `policy:edit` + đăng nhập lại ≤ `reauth_minutes`, như đổi chiến lược M5):
thứ tự lỗi 401 → 403 `forbidden` → 403 `reauth_required` → 422 `{"error":"invalid_request","fields":["mode"]}` → 409
`same_as_current` → ghi. Ghi = MỘT dòng `security_events` `policy_saved` `{kind: "hours_mode", from, to}` (`db/hours_mode`), nên
màn Cảnh báo có dòng "lưu chính sách" và nhật ký biết ai bật, lúc nào. EVAL_MODE: graph bỏ qua chế độ này (số đo theo giờ thật);
`eval_mode` trả ra để giao diện nói rõ. Không đổi đồng hồ hệ thống — chỉ fact `time.within_business_hours` của luật (R18).
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator

from app.api.alerts import ErrorDetail
from app.api.desk import Desk, HoursModeStore, get_desk, parse_body
from app.auth.deps import require
from app.auth.models import Principal
from app.db.hours_mode import HOURS_MODES, HoursMode, HoursModeState, SameHoursMode
from app.settings import Settings

router = APIRouter()

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}, 409: {"model": ErrorDetail}, 503: {"model": ErrorDetail},
}  # fmt: skip


class HoursModeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: HoursMode
    modes: list[str]
    changed_by: str | None
    changed_at: datetime | None
    eval_mode: bool


class HoursModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str

    @field_validator("mode")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in HOURS_MODES:
            raise ValueError("mode")
        return value


def _store(desk: Desk) -> HoursModeStore:
    if desk.hours is None:  # runtime dựng thiếu store — không đoán chế độ
        raise HTTPException(503, "runtime_unavailable")
    return desk.hours


def _view(request: Request, state: HoursModeState) -> HoursModeView:
    settings: Settings = request.app.state.settings
    return HoursModeView(
        mode=state.mode, modes=list(HOURS_MODES), changed_by=state.changed_by, changed_at=state.changed_at,
        eval_mode=settings.eval_mode,
    )  # fmt: skip


@router.get("/api/hours-mode", response_model=HoursModeView, responses=ERRORS)
async def get_hours_mode(
    request: Request,
    _: Annotated[Principal, Depends(require())],
    desk: Annotated[Desk, Depends(get_desk)],
) -> HoursModeView:
    return _view(request, await _store(desk).current())


@router.put("/api/admin/hours-mode", response_model=HoursModeView, responses=ERRORS)
async def put_hours_mode(
    request: Request,
    p: Annotated[Principal, Depends(require("policy:edit", recent_login=True))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> HoursModeView:
    body = await parse_body(request, HoursModeIn)
    store = _store(desk)
    try:
        state = await store.set_mode(body.mode, changed_by=p.user_id, at=desk.clock.now())  # type: ignore[arg-type]
    except SameHoursMode:
        raise HTTPException(409, "same_as_current") from None
    return _view(request, state)
