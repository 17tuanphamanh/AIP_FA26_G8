"""Chiến lược quyết định của M5 (phase6 5.3, P10) — hàm thuần: từ (kết quả luật, ước lượng B14, calibrator, ngưỡng, chiến
lược) ra `RiskDecision`. Chỉ `hybrid` chạy khi vận hành; 4 chiến lược còn lại chỉ để so sánh ở chế độ đánh giá
(`check_strategy`, cổng 6). Nguồn `Strategy` do 6C quyết (Settings).
"""

from dataclasses import dataclass
from typing import Literal

from app.domain.ticket_state import RiskDecision
from app.risk.calibrator import Calibrator
from app.risk.decision_math import Route, route_for
from app.risk.estimator import RiskEstimate
from app.risk.factors import FACTOR_LABELS
from app.risk.models import RuleVerdict

type Strategy = Literal["hybrid", "rule_only", "llm_only", "full_auto", "hybrid_guarded"]
STRATEGIES: frozenset[Strategy] = frozenset({"hybrid", "rule_only", "llm_only", "full_auto", "hybrid_guarded"})
EVAL_ONLY: frozenset[Strategy] = frozenset({"rule_only", "llm_only", "full_auto", "hybrid_guarded"})

# Đường luật — CHÉP từ `graph/nodes/b12_assess.py` (strategy không import graph); test so khớp hai bảng. 6C: B12 dùng strategy.
_ROUTE: dict[str, Literal["AUTO", "HITL", "ESCALATE_L2"]] = {
    "allow": "AUTO", "approval_required": "HITL", "deny": "ESCALATE_L2",
}  # fmt: skip
_LEVEL: dict[str, Literal["low", "medium", "high"]] = {"allow": "low", "approval_required": "medium", "deny": "high"}
_LLM_LEVEL: dict[Route, Literal["low", "medium", "high"]] = {"AUTO": "low", "HITL": "medium", "ESCALATE_L2": "high"}
_ROUTE_LABEL: dict[Route, str] = {"AUTO": "tự xử lý", "HITL": "chờ người duyệt", "ESCALATE_L2": "chuyển L2"}
_RULES_NEEDED: frozenset[Strategy] = frozenset({"hybrid", "rule_only", "hybrid_guarded"})
RULE_ONLY_NO_MATCH = "Không luật nào khớp → chờ duyệt (chỉ-luật)"  # [Chốt B12 §5]
_NO_RULE = "Không luật nào khớp. "
_KB_GAP = " Không có tài liệu quy định đủ liên quan → tối đa chờ người duyệt."


class StrategyNotAllowed(RuntimeError):
    """Chiến lược chỉ-để-so-sánh được chọn khi không ở chế độ đánh giá [Chốt cổng 6]."""


@dataclass(frozen=True)
class FullAutoBypass:
    """Tín hiệu: B12 bỏ qua M5 (`full_auto`, Q-6-8 — biểu diễn chốt ở 6C)."""


def _known(strategy: Strategy) -> None:
    if strategy not in STRATEGIES:
        raise ValueError("strategy: chiến lược lạ")


def check_strategy(strategy: Strategy, *, eval_mode: bool) -> None:
    """Chiến lược thuộc `EVAL_ONLY` khi không ở chế độ đánh giá → `StrategyNotAllowed` (6C gọi lúc khởi động)."""
    _known(strategy)
    if strategy in EVAL_ONLY and not eval_mode:
        raise StrategyNotAllowed(f"chiến lược {strategy!r} chỉ dùng ở chế độ đánh giá (EVAL_MODE)")


def needs_rules(strategy: Strategy) -> bool:
    _known(strategy)
    return strategy in _RULES_NEEDED


def _verdict(strategy: Strategy, verdict: RuleVerdict | None) -> RuleVerdict:
    """Chiến lược cần luật mà không có kết quả luật, hoặc `matched` lệch `decision`/`rule_id` → bug (TQ-14)."""
    if verdict is None:
        raise ValueError(f"verdict: chiến lược {strategy!r} cần kết quả luật")
    if verdict.matched and (verdict.decision is None or verdict.rule_id is None):
        raise ValueError("verdict: khớp luật nhưng thiếu decision hoặc rule_id")
    if not verdict.matched and (verdict.decision is not None or verdict.rule_id is not None):
        raise ValueError("verdict: không khớp luật nhưng có decision hoặc rule_id")  # soát bảo mật DỪNG 2: luật deny không lọt đường LLM
    return verdict


def needs_llm(strategy: Strategy, verdict: RuleVerdict | None) -> bool:
    """hybrid: không khớp · hybrid_guarded: không khớp HOẶC luật allow (LLM chỉ nâng mức) · llm_only: luôn · còn lại: không."""
    _known(strategy)
    if strategy == "llm_only":
        return True
    if strategy in ("rule_only", "full_auto"):
        return False
    v = _verdict(strategy, verdict)
    if strategy == "hybrid":
        return not v.matched
    return not v.matched or v.decision == "allow"


def _rule_decision(v: RuleVerdict) -> RiskDecision:
    assert v.decision is not None  # _verdict bảo đảm
    return RiskDecision(
        decided_by="rule", policy_decision=v.decision, matched_rule_id=v.rule_id, raw_prob=None, calibrated_prob=None,
        p_method=None, risk_level=_LEVEL[v.decision], route=_ROUTE[v.decision],
        reason=v.description or v.rule_id or "", thresholds=None,
    )  # fmt: skip


def _num(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _factors(estimate: RiskEstimate) -> str:
    return "; ".join(FACTOR_LABELS[f] for f in estimate.factors) or "(không nêu)"


def _llm_decision(
    estimate: RiskEstimate | None, *, calibrator: Calibrator | None, thresholds: tuple[float, float], kb_gap: bool,
    allow_rule: RuleVerdict | None,
) -> RiskDecision:  # fmt: skip
    """Đường LLM (5.3 bước 1–4). Chưa hiệu chỉnh → KHÔNG BAO GIỜ AUTO (D-38); kb_gap ∧ AUTO → HITL (D-34). Route qua
    `decision_math.route_for` (kiểm p ∈ [0,1], NaN, ngưỡng — một nguồn 6A)."""
    if estimate is None:
        raise ValueError("estimate: đường LLM cần ước lượng của B14")
    t_low, t_high = thresholds
    raw = estimate.raw_prob
    if calibrator is None:
        p: float | None = None
        route = route_for(raw, t_low, t_high)
        if route == "AUTO":
            route = "HITL"  # D-38: chưa hiệu chỉnh — raw > t_high → L2, còn lại HITL
        basis = f"{_num(raw)} (chưa hiệu chỉnh — không tự xử lý)"
    else:
        p = calibrator.transform(raw)
        route = route_for(p, t_low, t_high)
        basis = f"{_num(p)} (ngưỡng {_num(t_low)}/{_num(t_high)})"
    demoted = kb_gap and route == "AUTO"
    if demoted:
        route = "HITL"  # D-34
    body = (f"Mô hình ước lượng xác suất cần người duyệt {basis} → {_ROUTE_LABEL[route]}. Yếu tố: {_factors(estimate)}."
            + (_KB_GAP if demoted else ""))  # fmt: skip
    if allow_rule is not None:
        reason = f"Luật {allow_rule.rule_id} cho phép; kiểm tra bổ sung bằng mô hình: {body}"
    else:
        reason = _NO_RULE + body
    return RiskDecision(
        decided_by="llm", policy_decision="allow" if allow_rule is not None else None,
        matched_rule_id=allow_rule.rule_id if allow_rule is not None else None, raw_prob=raw, calibrated_prob=p,
        p_method=estimate.p_method, risk_level=_LLM_LEVEL[route], route=route, reason=reason,
        thresholds=(t_low, t_high),
    )  # fmt: skip


def decide(
    strategy: Strategy,
    verdict: RuleVerdict | None,
    estimate: RiskEstimate | None,
    *,
    calibrator: Calibrator | None,
    thresholds: tuple[float, float],
    kb_gap: bool,
) -> RiskDecision | FullAutoBypass:
    """Bảng quyết định 5.3."""
    _known(strategy)
    if strategy == "full_auto":
        return FullAutoBypass()
    if strategy == "llm_only":
        return _llm_decision(estimate, calibrator=calibrator, thresholds=thresholds, kb_gap=kb_gap, allow_rule=None)
    v = _verdict(strategy, verdict)
    if not v.matched:
        if strategy == "rule_only":
            return RiskDecision(
                decided_by="rule", policy_decision=None, matched_rule_id=None, raw_prob=None, calibrated_prob=None,
                p_method=None, risk_level=_LLM_LEVEL["HITL"], route="HITL", reason=RULE_ONLY_NO_MATCH, thresholds=None,
            )  # fmt: skip
        return _llm_decision(estimate, calibrator=calibrator, thresholds=thresholds, kb_gap=kb_gap, allow_rule=None)
    if strategy == "hybrid_guarded" and v.decision == "allow":
        # sàn AUTO — LLM chỉ nâng mức [Chốt 7.4]
        return _llm_decision(estimate, calibrator=calibrator, thresholds=thresholds, kb_gap=kb_gap, allow_rule=v)
    return _rule_decision(v)
