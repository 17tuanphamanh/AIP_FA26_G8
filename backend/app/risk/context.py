"""build_ctx — ngữ cảnh cho luật M5 (B12 §2, phase3 11.3; PLAN-3h P2, P3).

CHỈ đọc 3 khoá state: `intended_action`, `requester_context`, `ctx_flags` (+ `now` do node lấy từ Clock của lượt) —
KHÔNG `redacted_request`, `conversation`, `slots` (test AST h21). Đọc slot thay vì `action.facts` là lỗ G-01 (M-3h-8).

`target_is_other` (P3, tự quyết 2 PLAN-3h): TRUE nếu cờ B6 `ctx_flags.target_is_other` khác False, HOẶC `requested_for` ≠ người
gửi, HOẶC `action.facts.device_owner_is_requester` không phải `True` (thiếu cũng tính TRUE — phân vân thì coi là "người
khác"). Cờ B6 chỉ làm chặt thêm. Công thức sở hữu máy là của VPN Phase 3 — Phase 5 xét lại theo intent.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.policy import BusinessHours, within_business_hours
from app.risk.models import RiskContext


def build_ctx(state: Mapping[str, Any], now: datetime, hours: BusinessHours) -> RiskContext:
    action = Action.model_validate(state["intended_action"])
    requester = RequesterContext.model_validate(state["requester_context"])
    flags = state.get("ctx_flags") or {}
    target_is_other = (
        flags.get("target_is_other", False) is not False
        or action.requested_for != requester.user_id
        or action.facts.get("device_owner_is_requester") is not True
    )  # fmt: skip
    return RiskContext(
        requester=requester, facts=dict(action.facts), now=now,
        within_business_hours=within_business_hours(now, hours), target_is_other=target_is_other,
    )  # fmt: skip
