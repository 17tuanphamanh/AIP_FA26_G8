"""Estimator giả của B14 (phase6 5.1 P1) — trả một `RiskEstimate` cố định hoặc ném một lỗi cố định; ghi lại mọi đầu vào
(`Action`, `RiskContext`, trích đoạn) để test kiểm B12 đưa gì cho estimator. Thoả `app.risk.estimator.RiskEstimator`."""

from collections.abc import Sequence

from app.domain.action import Action
from app.domain.ticket_state import ChunkRef
from app.risk.estimator import RiskEstimate
from app.risk.models import RiskContext


class FakeRiskEstimator:
    def __init__(self, result: RiskEstimate | BaseException) -> None:
        self._result = result
        self.calls: list[tuple[Action, RiskContext, list[ChunkRef]]] = []

    async def estimate(self, action: Action, ctx: RiskContext, retrieved: Sequence[ChunkRef]) -> RiskEstimate:
        self.calls.append((action, ctx, list(retrieved)))
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result
