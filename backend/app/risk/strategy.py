"""Chiến lược quyết định của M5 (phase6 5.3, P10) — hàm thuần: từ (kết quả luật, ước lượng B14, calibrator, ngưỡng, chiến
lược) ra `RiskDecision`. Chỉ `hybrid` chạy khi vận hành; 4 chiến lược còn lại chỉ để so sánh ở chế độ đánh giá
(`check_strategy`, cổng 6). Nguồn `Strategy` do 6C quyết (Settings).
"""

from dataclasses import dataclass
from typing import Literal

from app.domain.ticket_state import RiskDecision
from app.risk.calibrator import Calibrator
from app.risk.estimator import RiskEstimate
from app.risk.models import RuleVerdict

type Strategy = Literal["hybrid", "rule_only", "llm_only", "full_auto", "hybrid_guarded"]
STRATEGIES: frozenset[Strategy] = frozenset({"hybrid", "rule_only", "llm_only", "full_auto", "hybrid_guarded"})
EVAL_ONLY: frozenset[Strategy] = frozenset({"rule_only", "llm_only", "full_auto", "hybrid_guarded"})

# Đường luật — CHÉP từ `graph/nodes/b12_assess.py` (strategy không import graph); test so khớp hai bảng. 6C: B12 dùng strategy.
_ROUTE: dict[str, Literal["AUTO", "HITL", "ESCALATE_L2"]] = {
    "allow": "AUTO", "approval_required": "HITL", "deny": "ESCALATE_L2",
}  # fmt: skip
_LEVEL: dict[str, Literal["low", "medium", "high"]] = {"allow": "low", "approval_required": "medium", "deny": "high"}


class StrategyNotAllowed(RuntimeError):
    """Chiến lược chỉ-để-so-sánh được chọn khi không ở chế độ đánh giá [Chốt cổng 6]."""


@dataclass(frozen=True)
class FullAutoBypass:
    """Tín hiệu: B12 bỏ qua M5 (`full_auto`, Q-6-8 — biểu diễn chốt ở 6C)."""


def check_strategy(strategy: Strategy, *, eval_mode: bool) -> None:
    raise NotImplementedError


def needs_rules(strategy: Strategy) -> bool:
    raise NotImplementedError


def needs_llm(strategy: Strategy, verdict: RuleVerdict | None) -> bool:
    raise NotImplementedError


def decide(
    strategy: Strategy,
    verdict: RuleVerdict | None,
    estimate: RiskEstimate | None,
    *,
    calibrator: Calibrator | None,
    thresholds: tuple[float, float],
    kb_gap: bool,
) -> RiskDecision | FullAutoBypass:
    raise NotImplementedError
