"""Lớp luật M5. Bất biến [Chốt]: evaluate chỉ nhận action và ctx — không bao giờ đọc câu
người dùng. Chữ ký được khóa bằng test; thân hàm làm ở B12 (Phase 3)."""

from app.domain.action import Action
from app.risk.models import RiskContext, RuleVerdict


def evaluate(action: Action, ctx: RiskContext) -> RuleVerdict:
    raise NotImplementedError("B12 — Phase 3")
