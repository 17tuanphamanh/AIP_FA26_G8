"""Logic chiến lược M5 (phase6 5.3, bảng 5.6 st1–st18) + TQ-14, Sửa 1/Sửa 2 (PLAN-6B mục 0, 3).

Kỳ vọng chép từ spec/PLAN, không suy từ code. DỪNG 1 (Q-6B-1 = A) các test st/TQ-14 được đánh dấu chờ hiện thực (chỉ chấp
nhận NotImplementedError); DỪNG 2 đã gỡ hết dấu.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from app.domain.risk_factors import FactorCode
from app.domain.ticket_state import RiskDecision
from app.graph.nodes import b12_assess
from app.risk import strategy
from app.risk.calibrator import Calibrator, CalibratorParams, FitInfo
from app.risk.estimator import PMethod, RiskEstimate
from app.risk.models import RuleVerdict
from app.risk.strategy import (
    EVAL_ONLY,
    RUNTIME_SELECTABLE,
    STRATEGIES,
    FullAutoBypass,
    Strategy,
    StrategyNotAllowed,
    check_strategy,
    decide,
    needs_llm,
    needs_rules,
)

T = (0.10, 0.75)  # (t_low, t_high) — 5.6 st4

CAL = Calibrator(CalibratorParams(
    version="platt-20261010-0123abcd", method="platt", a=1.0, b=0.0,
    fitted_on=FitInfo(split="calibration", n=40, n_pos=10, n_families=8, data_sha256="0" * 64),
    created_at=datetime(2026, 10, 10, tzinfo=UTC),
))  # fmt: skip  — Platt a=1, b=0 ≈ identity (5.6 st4)

ALLOW = RuleVerdict(matched=True, decision="allow", rule_id="R11", all_matched=["R11"], description="Mô tả luật R11")
APPROVAL = RuleVerdict(matched=True, decision="approval_required", rule_id="R05", all_matched=["R05"],
                       description="Mô tả luật R05")  # fmt: skip
DENY = RuleVerdict(matched=True, decision="deny", rule_id="R02", all_matched=["R02"], description="Mô tả luật R02")
NONE = RuleVerdict(matched=False, decision=None, rule_id=None, all_matched=[], description=None)

RULE_ONLY_NO_MATCH = "Không luật nào khớp → chờ duyệt (chỉ-luật)"  # [Chốt B12 §5]
KB_GAP_SENTENCE = "Không có tài liệu quy định đủ liên quan"


def _est(raw: float, factors: tuple[FactorCode, ...] = (), p_method: PMethod = "self_report") -> RiskEstimate:
    return RiskEstimate(raw_prob=raw, p_method=p_method, factors=factors, prompt_id="b14_risk_estimate",
                        prompt_version="1", model="strong-gia")  # fmt: skip


def _decide(s: Strategy, verdict: RuleVerdict | None, estimate: RiskEstimate | None, *,
            calibrator: Calibrator | None = CAL, thresholds: tuple[float, float] = T,
            kb_gap: bool = False) -> RiskDecision:  # fmt: skip
    out = decide(s, verdict, estimate, calibrator=calibrator, thresholds=thresholds, kb_gap=kb_gap)
    assert isinstance(out, RiskDecision), out
    return out


def _assert_rule(d: RiskDecision, verdict: RuleVerdict, route: str, level: str) -> None:
    """Đường luật — "route theo loại luật (như B12 hiện tại), không ước lượng" (5.3)."""
    assert (d.decided_by, d.policy_decision, d.matched_rule_id) == ("rule", verdict.decision, verdict.rule_id)
    assert (d.route, d.risk_level) == (route, level)
    assert (d.raw_prob, d.calibrated_prob, d.p_method) == (None, None, None)


# ---- Sửa 1 (TQ-13): bảng luật của strategy == B12 -----------------------------------------------------------


def test_tq13_strategy_route_level_tables_equal_b12() -> None:
    """Sửa 1 (TQ-13): bản chép `_ROUTE`/`_LEVEL` trong strategy.py phải bằng đúng bảng của B12."""
    assert strategy._ROUTE == b12_assess._ROUTE
    assert strategy._LEVEL == b12_assess._LEVEL


# ---- st1–st3: hybrid + luật khớp --------------------------------------------------------------------------


def test_st1_hybrid_allow_rule_auto() -> None:
    """st1: hybrid + allow → needs_llm=False; decided_by=rule, AUTO."""
    assert needs_rules("hybrid") is True
    assert needs_llm("hybrid", ALLOW) is False
    _assert_rule(_decide("hybrid", ALLOW, None), ALLOW, "AUTO", "low")


def test_st2_hybrid_approval_required_rule_hitl() -> None:
    """st2: hybrid + approval_required → rule, HITL."""
    assert needs_llm("hybrid", APPROVAL) is False
    _assert_rule(_decide("hybrid", APPROVAL, None), APPROVAL, "HITL", "medium")


def test_st3_hybrid_deny_rule_escalate() -> None:
    """st3: hybrid + deny → rule, ESCALATE_L2."""
    assert needs_llm("hybrid", DENY) is False
    _assert_rule(_decide("hybrid", DENY, None), DENY, "ESCALATE_L2", "high")


# ---- st4–st7: đường LLM -----------------------------------------------------------------------------------


def test_st4_hybrid_no_match_calibrated_low_p_auto() -> None:
    """st4: hybrid, không khớp, calibrator a=1,b=0, p 0,05, t (0,10; 0,75) → llm, AUTO, calibrated_prob ≈ 0,05."""
    assert needs_llm("hybrid", NONE) is True
    d = _decide("hybrid", NONE, _est(0.05))
    assert (d.decided_by, d.route, d.risk_level) == ("llm", "AUTO", "low")
    assert d.calibrated_prob == pytest.approx(0.05, abs=1e-9)
    assert d.raw_prob == 0.05
    assert (d.policy_decision, d.matched_rule_id) == (None, None)


def test_st5_kb_gap_demotes_auto_to_hitl() -> None:
    """st5 (D-34): như st4 + kb_gap=True → HITL, reason có câu "Không có tài liệu quy định đủ liên quan…"."""
    d = _decide("hybrid", NONE, _est(0.05), kb_gap=True)
    assert (d.decided_by, d.route, d.risk_level) == ("llm", "HITL", "medium")
    assert KB_GAP_SENTENCE in d.reason


@pytest.mark.parametrize(("raw", "route"), [(0.10, "HITL"), (0.75, "HITL"), (0.50, "HITL"), (0.90, "ESCALATE_L2")])
def test_st6_threshold_boundaries(raw: float, route: str) -> None:
    """st6 (biên, bằng ngưỡng = HITL). Lệch spec st6 — ổn định giữa Mac arm và CI x86 (PLAN-6B Sửa 2, TQ-21): Platt a=1,
    b=0 thật, ngưỡng lấy bằng giá trị ĐÃ hiệu chỉnh `t = (cal.transform(0.10), cal.transform(0.75))` để ca biên không phụ
    thuộc bit cuối của logit/expit."""
    t = (CAL.transform(0.10), CAL.transform(0.75))
    d = _decide("hybrid", NONE, _est(raw), thresholds=t)
    assert (d.decided_by, d.route) == ("llm", route)
    assert d.thresholds == t


@pytest.mark.parametrize(("raw", "route", "level"), [(0.01, "HITL", "medium"), (0.80, "ESCALATE_L2", "high")])
def test_st7_uncalibrated_never_auto(raw: float, route: str, level: str) -> None:
    """st7 (D-38): chưa hiệu chỉnh — raw 0,01 → HITL (không bao giờ AUTO); raw 0,80 → ESCALATE_L2; calibrated_prob=None;
    reason có "chưa hiệu chỉnh"."""
    d = _decide("hybrid", NONE, _est(raw), calibrator=None)
    assert (d.decided_by, d.route, d.risk_level) == ("llm", route, level)
    assert d.calibrated_prob is None
    assert d.raw_prob == raw
    assert "chưa hiệu chỉnh" in d.reason


# ---- st8–st10: rule_only, llm_only ------------------------------------------------------------------------


def test_st8_rule_only_no_match_hitl_exact_reason() -> None:
    """st8 [Chốt B12 §5]: rule_only không khớp → rule, policy_decision=None, HITL, reason đúng chữ."""
    assert needs_llm("rule_only", NONE) is False
    d = _decide("rule_only", NONE, None)
    assert (d.decided_by, d.policy_decision, d.route) == ("rule", None, "HITL")
    assert d.reason == RULE_ONLY_NO_MATCH
    assert (d.raw_prob, d.p_method) == (None, None)


def test_st9_rule_only_allow_rule_auto() -> None:
    """st9: rule_only + allow → rule, AUTO."""
    assert needs_rules("rule_only") is True
    _assert_rule(_decide("rule_only", ALLOW, None), ALLOW, "AUTO", "low")


def test_st10_llm_only_skips_rules_goes_llm_path() -> None:
    """st10: llm_only → needs_rules=False; decide(verdict=None) → đường LLM."""
    assert needs_rules("llm_only") is False
    assert needs_llm("llm_only", None) is True
    d = _decide("llm_only", None, _est(0.05))
    assert (d.decided_by, d.route) == ("llm", "AUTO")
    assert (d.policy_decision, d.matched_rule_id) == (None, None)


# ---- st11–st13: hybrid_guarded ----------------------------------------------------------------------------


def test_st11_guarded_allow_low_p_auto_keeps_rule() -> None:
    """st11 [Chốt 7.4]: hybrid_guarded + allow + p 0,05 (có calibrator) → llm, AUTO, policy_decision="allow",
    matched_rule_id="R11", reason có tiền tố "Luật R11 cho phép"."""
    assert needs_llm("hybrid_guarded", ALLOW) is True
    d = _decide("hybrid_guarded", ALLOW, _est(0.05))
    assert (d.decided_by, d.route, d.policy_decision, d.matched_rule_id) == ("llm", "AUTO", "allow", "R11")
    assert d.reason.startswith("Luật R11 cho phép")


def test_st12_guarded_allow_mid_p_raises_to_hitl() -> None:
    """st12: hybrid_guarded + allow + p 0,5 → HITL (LLM nâng mức)."""
    d = _decide("hybrid_guarded", ALLOW, _est(0.5))
    assert (d.decided_by, d.route, d.policy_decision, d.matched_rule_id) == ("llm", "HITL", "allow", "R11")


def test_st13_guarded_approval_required_rule_hitl_no_llm() -> None:
    """st13 (M-6B-9): hybrid_guarded + approval_required → rule, HITL, needs_llm=False."""
    assert needs_llm("hybrid_guarded", APPROVAL) is False
    assert needs_llm("hybrid_guarded", DENY) is False
    _assert_rule(_decide("hybrid_guarded", APPROVAL, None), APPROVAL, "HITL", "medium")
    _assert_rule(_decide("hybrid_guarded", DENY, None), DENY, "ESCALATE_L2", "high")  # 5.3: "khớp approval_required/deny"


# ---- st14–st16 --------------------------------------------------------------------------------------------


def test_st14_full_auto_bypass() -> None:
    """st14: full_auto → FullAutoBypass; needs_rules = needs_llm = False."""
    assert needs_rules("full_auto") is False
    assert needs_llm("full_auto", None) is False
    out = decide("full_auto", None, None, calibrator=None, thresholds=T, kb_gap=False)
    assert isinstance(out, FullAutoBypass)


def test_st15_check_strategy_eval_only_blocked_outside_eval() -> None:
    """st15 [Chốt cổng 6] — sửa có chủ ý theo D-67 (GIỮ TÊN: `mutate_6b.py` M-6B-6 gọi test này): `RUNTIME_SELECTABLE` = rule_only,
    hybrid, hybrid_guarded qua khi eval_mode=False; `EVAL_ONLY` còn llm_only, full_auto → StrategyNotAllowed; eval_mode=True — 5 qua.
    Trước D-67: EVAL_ONLY = 4 chiến lược, chỉ hybrid qua lúc vận hành."""
    assert frozenset({"llm_only", "full_auto"}) == EVAL_ONLY
    assert RUNTIME_SELECTABLE == ("rule_only", "hybrid", "hybrid_guarded")
    assert STRATEGIES == EVAL_ONLY | frozenset(RUNTIME_SELECTABLE) and len(STRATEGIES) == 5
    assert not EVAL_ONLY & frozenset(RUNTIME_SELECTABLE)
    for s in RUNTIME_SELECTABLE:
        check_strategy(s, eval_mode=False)  # qua = không ném
    for s in sorted(EVAL_ONLY):
        with pytest.raises(StrategyNotAllowed):
            check_strategy(s, eval_mode=False)
    for s in sorted(STRATEGIES):
        check_strategy(s, eval_mode=True)


@pytest.mark.parametrize(("s", "verdict"), [("hybrid", NONE), ("llm_only", None), ("llm_only", NONE),
                                            ("hybrid_guarded", NONE), ("hybrid_guarded", ALLOW)])  # fmt: skip
def test_st16_llm_path_without_estimate_is_value_error(s: Strategy, verdict: RuleVerdict | None) -> None:
    """st16: đường LLM thiếu `estimate` → ValueError (bug)."""
    with pytest.raises(ValueError):
        decide(s, verdict, None, calibrator=CAL, thresholds=T, kb_gap=False)


# ---- st17: chữ reason khớp từng ký tự (mẫu 5.3) -----------------------------------------------------------


def test_st17_reason_calibrated_exact() -> None:
    """st17 mẫu 1 — đã hiệu chỉnh."""
    d = _decide("hybrid", NONE, _est(0.42, (FactorCode.TARGET_IS_OTHER, FactorCode.SENSITIVE_DATA)))
    assert d.route == "HITL"
    assert d.reason == ("Không luật nào khớp. Mô hình ước lượng xác suất cần người duyệt 0,42 (ngưỡng 0,10/0,75) → "
                        "chờ người duyệt. Yếu tố: tác động lên người/máy khác; dữ liệu nhạy cảm.")  # fmt: skip


def test_st17_reason_uncalibrated_exact_empty_factors() -> None:
    """st17 mẫu 2 — chưa hiệu chỉnh; yếu tố rỗng → "(không nêu)"."""
    d = _decide("hybrid", NONE, _est(0.02), calibrator=None)
    assert d.route == "HITL"
    assert d.reason == ("Không luật nào khớp. Mô hình ước lượng xác suất cần người duyệt 0,02 (chưa hiệu chỉnh — không tự "
                        "xử lý) → chờ người duyệt. Yếu tố: (không nêu).")  # fmt: skip


def test_st17_reason_kb_gap_demotion_exact() -> None:
    """st17 mẫu 3 — bước 3 hạ AUTO → HITL: thêm câu kb_gap; nhãn route = route cuối (HITL)."""
    d = _decide("hybrid", NONE, _est(0.05, (FactorCode.ROUTINE_LOW_RISK,)), kb_gap=True)
    assert d.route == "HITL"
    assert d.reason == ("Không luật nào khớp. Mô hình ước lượng xác suất cần người duyệt 0,05 (ngưỡng 0,10/0,75) → "
                        "chờ người duyệt. Yếu tố: việc thường ngày, rủi ro thấp. Không có tài liệu quy định đủ liên "
                        "quan → tối đa chờ người duyệt.")  # fmt: skip


def test_st17_reason_guarded_allow_exact() -> None:
    """st17 mẫu 4 — hybrid_guarded + allow: tiền tố "Luật R11 cho phép; kiểm tra bổ sung bằng mô hình: "."""
    d = _decide("hybrid_guarded", ALLOW, _est(0.05, (FactorCode.PRIVILEGED_TARGET,)))
    assert d.route == "AUTO"
    assert d.reason == ("Luật R11 cho phép; kiểm tra bổ sung bằng mô hình: Mô hình ước lượng xác suất cần người duyệt "
                        "0,05 (ngưỡng 0,10/0,75) → tự xử lý. Yếu tố: tài khoản/quyền mức cao.")  # fmt: skip


def test_st17_reason_escalate_label() -> None:
    """st17 (nhãn route ESCALATE_L2 = "chuyển L2")."""
    d = _decide("hybrid", NONE, _est(0.90, (FactorCode.IRREVERSIBLE,)))
    assert d.route == "ESCALATE_L2"
    assert d.reason == ("Không luật nào khớp. Mô hình ước lượng xác suất cần người duyệt 0,90 (ngưỡng 0,10/0,75) → "
                        "chuyển L2. Yếu tố: khó hoàn tác.")  # fmt: skip


# ---- st18: trường RiskDecision ----------------------------------------------------------------------------


def test_st18_risk_decision_fields_llm_vs_rule() -> None:
    """st18: đường LLM có raw_prob, p_method, thresholds; đường luật raw_prob=None, p_method=None."""
    llm = _decide("hybrid", NONE, _est(0.42, p_method="sampling_k5"))
    assert llm.raw_prob == 0.42 and llm.p_method == "sampling_k5" and llm.thresholds == T
    assert llm.calibrated_prob is not None
    rule = _decide("hybrid", APPROVAL, None)
    assert rule.raw_prob is None and rule.p_method is None


# ---- TQ-14: hợp đồng phụ (bug → ValueError) ---------------------------------------------------------------


@pytest.mark.parametrize("s", ["hybrid", "rule_only", "hybrid_guarded"])
def test_tq14_rule_strategies_require_verdict(s: Strategy) -> None:
    """TQ-14: chiến lược cần luật (hybrid, rule_only, hybrid_guarded) mà verdict None → ValueError."""
    with pytest.raises(ValueError):
        decide(s, None, _est(0.05), calibrator=CAL, thresholds=T, kb_gap=False)


@pytest.mark.parametrize("s", ["hybrid", "rule_only", "hybrid_guarded"])
@pytest.mark.parametrize("verdict", [
    RuleVerdict(matched=True, decision=None, rule_id="R11", all_matched=["R11"], description="x"),
    RuleVerdict(matched=True, decision="allow", rule_id=None, all_matched=[], description="x"),
], ids=["decision_none", "rule_id_none"])  # fmt: skip
def test_tq14_matched_verdict_needs_decision_and_rule_id(s: Strategy, verdict: RuleVerdict) -> None:
    """TQ-14: verdict.matched mà decision hoặc rule_id None → ValueError."""
    with pytest.raises(ValueError):
        decide(s, verdict, _est(0.05), calibrator=CAL, thresholds=T, kb_gap=False)


def test_tq14_unknown_strategy_is_value_error_everywhere() -> None:
    """TQ-14: chiến lược lạ → ValueError ở check_strategy (cả 2 eval_mode), needs_rules, needs_llm, decide."""
    bad: Any = "khong_ton_tai"
    with pytest.raises(ValueError):
        check_strategy(bad, eval_mode=True)
    with pytest.raises(ValueError):
        check_strategy(bad, eval_mode=False)
    with pytest.raises(ValueError):
        needs_rules(bad)
    with pytest.raises(ValueError):
        needs_llm(bad, NONE)
    with pytest.raises(ValueError):
        decide(bad, NONE, _est(0.05), calibrator=CAL, thresholds=T, kb_gap=False)


def test_tq14_llm_only_ignores_verdict() -> None:
    """TQ-14: llm_only bỏ qua verdict → policy_decision None (kể cả khi truyền verdict allow)."""
    d = _decide("llm_only", ALLOW, _est(0.05))
    assert (d.decided_by, d.policy_decision, d.matched_rule_id, d.route) == ("llm", None, None, "AUTO")


# ---- Bổ sung DỪNG 2 (agent chính viết, theo soát bảo mật lần 2): bất biến đường LLM ở MỌI chiến lược ------------


LLM_PATHS: list[tuple[Strategy, RuleVerdict | None]] = [("hybrid", NONE), ("llm_only", None), ("hybrid_guarded", NONE),
                                                        ("hybrid_guarded", ALLOW)]  # fmt: skip
LLM_IDS = ["hybrid", "llm_only", "guarded-khong-khop", "guarded-allow"]


@pytest.mark.parametrize(("s", "verdict"), LLM_PATHS, ids=LLM_IDS)
def test_dung2_uncalibrated_never_auto_on_every_llm_path(s: Strategy, verdict: RuleVerdict | None) -> None:
    """D-38 (5.3 bước 1): chưa hiệu chỉnh → không bao giờ AUTO, ở mọi đường LLM (st7 chỉ chạy hybrid)."""
    d = _decide(s, verdict, _est(0.01), calibrator=None)
    assert (d.decided_by, d.route, d.calibrated_prob) == ("llm", "HITL", None)


@pytest.mark.parametrize(("s", "verdict"), LLM_PATHS, ids=LLM_IDS)
def test_dung2_kb_gap_blocks_auto_on_every_llm_path(s: Strategy, verdict: RuleVerdict | None) -> None:
    """D-34 (5.3 bước 3): kb_gap ∧ AUTO → HITL, ở mọi đường LLM (st5 chỉ chạy hybrid)."""
    assert _decide(s, verdict, _est(0.05)).route == "AUTO"  # đối chứng: không kb_gap thì AUTO
    d = _decide(s, verdict, _est(0.05), kb_gap=True)
    assert d.route == "HITL" and KB_GAP_SENTENCE in d.reason


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), 1.2, -0.1], ids=["nan", "inf", "1.2", "-0.1"])
@pytest.mark.parametrize("calibrator", [CAL, None], ids=["co-cal", "chua-cal"])
def test_dung2_bad_raw_is_value_error(raw: float, calibrator: Calibrator | None) -> None:
    """raw ngoài [0, 1]/NaN/inf → ValueError (route_for / transform), không ra RiskDecision."""
    with pytest.raises(ValueError):
        decide("hybrid", NONE, _est(raw), calibrator=calibrator, thresholds=T, kb_gap=False)


@pytest.mark.parametrize("calibrator", [CAL, None], ids=["co-cal", "chua-cal"])
def test_dung2_bad_thresholds_is_value_error(calibrator: Calibrator | None) -> None:
    with pytest.raises(ValueError):
        decide("hybrid", NONE, _est(0.5), calibrator=calibrator, thresholds=(0.8, 0.2), kb_gap=False)


def test_dung2_calibrator_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calibrator ném lỗi → lỗi đi lên, không ra RiskDecision."""

    def boom(self: Calibrator, raw: float) -> float:
        raise RuntimeError("calibrator hỏng")

    monkeypatch.setattr(Calibrator, "transform", boom)
    with pytest.raises(RuntimeError, match="calibrator hỏng"):
        decide("hybrid", NONE, _est(0.05), calibrator=CAL, thresholds=T, kb_gap=False)


@pytest.mark.parametrize("s", ["hybrid", "rule_only", "hybrid_guarded"])
@pytest.mark.parametrize("verdict", [
    RuleVerdict(matched=False, decision="deny", rule_id=None, all_matched=[], description=None),
    RuleVerdict(matched=False, decision=None, rule_id="R02", all_matched=[], description=None),
], ids=["decision", "rule_id"])  # fmt: skip
def test_dung2_unmatched_verdict_with_decision_is_value_error(s: Strategy, verdict: RuleVerdict) -> None:
    """Verdict không khớp mà có decision/rule_id (evaluate không bao giờ sinh) → ValueError, không đi đường LLM."""
    with pytest.raises(ValueError):
        decide(s, verdict, _est(0.05), calibrator=CAL, thresholds=T, kb_gap=False)
    if s != "rule_only":  # rule_only không đọc verdict trong needs_llm (luôn False)
        with pytest.raises(ValueError):
            needs_llm(s, verdict)
