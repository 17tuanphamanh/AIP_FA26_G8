"""Hợp đồng vào/ra của lớp luật M5 — B12-B14 mục 4.1 [Chốt]."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.context import RequesterContext


class RiskContext(BaseModel, frozen=True):
    requester: RequesterContext
    facts: dict[str, str | int | bool]  # từ diagnostics (qua Action.facts)
    now: datetime
    within_business_hours: bool
    target_is_other: bool


class RuleVerdict(BaseModel):
    matched: bool
    decision: Literal["allow", "approval_required", "deny"] | None
    rule_id: str | None
    all_matched: list[str]
    description: str | None
