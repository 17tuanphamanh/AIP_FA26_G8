"""build_ctx — ngữ cảnh cho luật M5 (B12 §2, phase3 11.3; PLAN-3h P2, P3).

CHỈ đọc 3 khoá state: `intended_action`, `requester_context`, `ctx_flags` (+ `now` do node lấy từ Clock của lượt) —
KHÔNG `redacted_request`, `conversation`, `slots` (test AST h21). Đọc slot thay vì `action.facts` là lỗ G-01 (M-3h-8).

`target_is_other` (P3, tự quyết 2 PLAN-3h; Phase 5 T22a P5 — G5-1, D-41): TRUE nếu cờ B6 `ctx_flags.target_is_other` khác False,
HOẶC `requested_for` (người bị tác động, P4) ≠ người gửi, HOẶC — CHỈ khi đích là máy (`action.target` bắt đầu `device:`) —
`action.facts.device_owner_is_requester` không phải `True` (thiếu cũng tính TRUE — phân vân thì coi là "người khác"). Cờ B6 chỉ làm
chặt thêm. Vế chủ máy chỉ áp cho đích máy: tài khoản/thư mục (`user:`, `folder:`) không có chủ máy, áp vế đó cho mọi đích thì không
luật allow nào của account/access khớp được (R01, R02, R06, R10). VPN không đổi (mọi đích VPN là `device:`).

`hours_mode` (D-97, demo 14/11): chế độ giả lập giờ hành chính do Trưởng BP bật (`db/hours_mode`) — `outside` / `inside` ghi đè
ĐÚNG fact `within_business_hours` (False / True); `real` (mặc định) tính từ `now` như cũ. Không đổi `now`.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.policy import BusinessHours, within_business_hours
from app.risk.models import RiskContext


def build_ctx(state: Mapping[str, Any], now: datetime, hours: BusinessHours, *, hours_mode: str = "real") -> RiskContext:
    action = Action.model_validate(state["intended_action"])
    requester = RequesterContext.model_validate(state["requester_context"])
    flags = state.get("ctx_flags") or {}
    device_target = action.target.startswith("device:")
    target_is_other = (
        flags.get("target_is_other", False) is not False
        or action.requested_for != requester.user_id
        or (device_target and action.facts.get("device_owner_is_requester") is not True)
    )  # fmt: skip
    return RiskContext(
        requester=requester, facts=dict(action.facts), now=now,
        within_business_hours=_within(now, hours, hours_mode), target_is_other=target_is_other,
    )  # fmt: skip


def _within(now: datetime, hours: BusinessHours, hours_mode: str) -> bool:
    if hours_mode == "outside":
        return False
    if hours_mode == "inside":
        return True
    if hours_mode != "real":  # chế độ lạ = bug nơi gọi (db/hours_mode.as_mode đã lọc) → E9, không đoán
        raise ValueError(f"hours_mode lạ {hours_mode!r}")
    return within_business_hours(now, hours)
