"""Lớp 2 của M5 (B14 — ước lượng xác suất cần người duyệt). Phase 3: `DisabledEstimator` (3-Q30, phase3 11.3) — mọi ca
không luật nào khớp đi E5 `llm_layer_disabled`, KHÔNG tự làm. Estimator thật (LLM strong `b14_risk_estimate`) ở Phase 6.

Input của estimator (mọi phase): `Action` + `RiskContext` + trích đoạn KB — KHÔNG câu người dùng (B12 §5.1).
"""

from collections.abc import Sequence
from typing import Literal, Protocol

from app.core.errors import LLMUnavailable
from app.domain.action import Action
from app.domain.ticket_state import ChunkRef
from app.risk.models import RiskContext

type PMethod = Literal["self_report", "sampling_k5"]


class RiskEstimator(Protocol):
    async def estimate(
        self, action: Action, ctx: RiskContext, retrieved: Sequence[ChunkRef]
    ) -> tuple[float, PMethod]: ...


class DisabledEstimator:
    """Luôn ném `LLMUnavailable` → B12 nhánh sẵn có → `ESCALATE_L2` / E5 `llm_layer_disabled`. Trả `p=0` thay vì ném là
    lỗ tự làm (M-3h-9)."""

    async def estimate(
        self, action: Action, ctx: RiskContext, retrieved: Sequence[ChunkRef]
    ) -> tuple[float, PMethod]:
        raise LLMUnavailable("lớp LLM rủi ro (B14) chưa bật ở Phase 3 — 3-Q30")
