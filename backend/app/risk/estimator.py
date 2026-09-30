"""Lớp 2 của M5 (B14 — ước lượng xác suất cần người duyệt). Phase 3: `DisabledEstimator` (3-Q30, phase3 11.3) — mọi ca
không luật nào khớp đi E5 `llm_layer_disabled`, KHÔNG tự làm. Estimator thật (LLM strong `b14_risk_estimate`) ở Phase 6.

Input của estimator (mọi phase): `Action` + `RiskContext` + trích đoạn KB — KHÔNG câu người dùng (B12 §5.1).

Phase 4 S0-P9 (Q-4-U A+, D-34): B12 đưa trích đoạn KB cho estimator CHỈ qua `evidence_for_estimator` — đoạn dưới ngưỡng
truy hồi không bao giờ tới B14 (chúng không phải căn cứ). Ràng buộc cho Phase 6: không luật nào khớp + `kb_gap` → route tối
đa HITL, không AUTO.
"""

from collections.abc import Sequence
from typing import Literal, Protocol

from app.core.errors import LLMUnavailable
from app.domain.action import Action
from app.domain.ticket_state import ChunkRef
from app.risk.models import RiskContext

type PMethod = Literal["self_report", "sampling_k5"]


def evidence_for_estimator(chunks: Sequence[ChunkRef], score: float | None, threshold: float) -> list[ChunkRef]:
    """S0-P9 — hàm thuần: `chunks` khi `score` ≥ `threshold` (bằng ngưỡng là đạt, như B9), không thì `[]`. Thiếu `score`
    (None) hoặc NaN → `[]` (fail-closed; `not score >= threshold` thay cho `score < threshold` — NaN so sánh luôn False)."""
    if score is None or not score >= threshold:
        return []
    return list(chunks)


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
