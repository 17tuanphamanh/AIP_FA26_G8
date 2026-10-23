"""N18 / G4 — `app.eval.calibrate.fit_fold` (P8 v1.4 §5.3): hiệu chỉnh + chọn ngưỡng + chọn biến thể theo TỪNG PHẦN.

Kỳ vọng chép từ P8 §5.3, §9 và 7 điểm duyệt ngày 22–23/10 (docstring `calibrate.py`), không suy từ code:
- điểm 2: chi phí kỳ vọng tính CẢ ca không đi lớp LLM; `kb_gap` hạ AUTO → HITL; `no_evidence` dùng `kb_gap` GỐC của ca;
- điểm 3: hoà chi phí → with_evidence > no_evidence > max;
- điểm 4: ngưỡng trên 1,01 = lớp LLM không bao giờ đưa ca sang L2; "không AUTO" = ngưỡng DƯỚI 0, không phải ngưỡng trên;
- điểm 5/6: dưới 10 ca L2 (trong ca đi lớp LLM) hoặc AUC L2 < 0,7 hoặc không tính được → ngưỡng trên 1,01;
- điểm 7: biến thể fit lỗi bị loại + log; cả ba lỗi → chưa hiệu chỉnh (D-38), ngưỡng trên đọc từ policy;
- G4: fit chỉ trên calibration (`LeakageError`), ma trận chi phí 10:1 khớp bảng 7.3.
Dữ liệu tổng hợp; số tính tay.
"""

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.eval import calibrate
from app.eval.calibrate import (
    AUC_L2_MIN,
    MIN_L2_CASES,
    VARIANT_ORDER,
    FoldCase,
    expected_cost_on,
    fit_fold,
    llm_route,
)
from app.risk.calibrator import Calibrator, CalibratorParams, FitInfo, LeakageError
from app.risk.decision_math import (
    DEFAULT_COST,
    T_HIGH_MAX,
    ThresholdChoice,
    ece,
    route_for,
    t_low_star,
)

NOW = datetime(2026, 10, 22, 3, 0, tzinfo=UTC)
REPO = Path(__file__).resolve().parents[4]
T_HIGH = 0.9  # ngưỡng trên "của policy" dùng trong test (số tổng hợp, không phải giá trị thật)


def identity_cal() -> Calibrator:
    """Platt a = 1, b = 0 → `transform(p) = p` (tính tay không cần fit)."""
    info = FitInfo(split="calibration", n=10, n_pos=5, n_families=5, data_sha256="0" * 64)
    return Calibrator(CalibratorParams(version="platt-20261022-0123abcd", method="platt", a=1.0, b=0.0, fitted_on=info, created_at=NOW))


def fc(sid: str, gold: str, p: float | None = None, *, llm: bool = True, fixed: str | None = None, kb: bool = False,
       split: str = "calibration", probs: Mapping[str, float] | None = None) -> FoldCase:  # fmt: skip
    pr = dict(probs) if probs is not None else ({v: p for v in VARIANT_ORDER} if llm and p is not None else {})
    return FoldCase(sid, f"F-{sid}", split, gold, llm, fixed, pr, kb)  # type: ignore[arg-type]


# p đan xen giữa các lớp để Platt hữu hạn, a > 0 (không tách hoàn toàn)
AUTO_P = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.45, 0.55, 0.12, 0.18, 0.28]
HITL_P = [0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.45, 0.20, 0.62, 0.52, 0.58]
L2_P = [0.70, 0.75, 0.80, 0.85, 0.90, 0.92, 0.95, 0.78, 0.88, 0.97, 0.83, 0.60]


def llm_set(n_l2: int = 12, *, l2_p: list[float] | None = None) -> list[FoldCase]:
    cases = [fc(f"a{i}", "AUTO", p) for i, p in enumerate(AUTO_P)]
    cases += [fc(f"h{i}", "HITL", p) for i, p in enumerate(HITL_P)]
    cases += [fc(f"l{i}", "ESCALATE_L2", p) for i, p in enumerate((l2_p or L2_P)[:n_l2])]
    return cases


def fit(train: list[FoldCase], **kw: object) -> calibrate.FoldFit:
    return fit_fold(train, now=NOW, policy_t_high=T_HIGH, **kw)  # type: ignore[arg-type]


# ---- điểm 2: chi phí kỳ vọng ------------------------------------------------------------------------------------------------


TH = (0.1, 0.8)


def six_cases() -> list[FoldCase]:
    return [
        fc("c1", "AUTO", 0.05), fc("c2", "HITL", 0.05), fc("c3", "HITL", 0.5), fc("c4", "ESCALATE_L2", 0.9),
        fc("c5", "AUTO", llm=False, fixed="HITL"), fc("c6", "ESCALATE_L2", llm=False, fixed="ESCALATE_L2"),
    ]  # fmt: skip


def test_p2_expected_cost_counts_fixed_route_cases_hand_computed() -> None:
    """AUTO→AUTO 0; HITL→AUTO 10; HITL→HITL 1; L2→L2 3; ca cố định: AUTO→HITL 1, L2→L2 3 ⇒ 18/6 = 3."""
    assert expected_cost_on(six_cases(), "with_evidence", identity_cal(), TH, T_HIGH) == pytest.approx(3.0, abs=1e-12)
    assert expected_cost_on(six_cases()[:4], "with_evidence", identity_cal(), TH, T_HIGH) == pytest.approx(14 / 4, abs=1e-12)


def test_p2_kb_gap_demotes_auto_to_hitl() -> None:
    cases = six_cases()
    cases[1] = fc("c2", "HITL", 0.05, kb=True)  # HITL→AUTO (10) trở thành HITL→HITL (1): (18 − 9)/6
    assert expected_cost_on(cases, "with_evidence", identity_cal(), TH, T_HIGH) == pytest.approx(1.5, abs=1e-12)
    assert llm_route(0.05, identity_cal(), TH, True, T_HIGH) == "HITL"
    assert llm_route(0.05, identity_cal(), TH, False, T_HIGH) == "AUTO"
    assert llm_route(0.9, identity_cal(), TH, True, T_HIGH) == "ESCALATE_L2"  # kb_gap chỉ hạ AUTO


def test_p2_no_evidence_uses_original_kb_gap_not_empty_evidence() -> None:
    """`kb_gap` là của ca (bằng chứng gốc): kb_gap = False thì `no_evidence` vẫn có thể AUTO; kb_gap = True thì mọi biến thể bị hạ."""
    probs = {"with_evidence": 0.5, "no_evidence": 0.05, "max": 0.5}
    free = [fc("x", "AUTO", probs=probs, kb=False)]
    gapped = [fc("x", "AUTO", probs=probs, kb=True)]
    assert expected_cost_on(free, "no_evidence", identity_cal(), TH, T_HIGH) == 0.0  # AUTO đúng gold AUTO
    assert expected_cost_on(gapped, "no_evidence", identity_cal(), TH, T_HIGH) == 1.0  # hạ HITL: AUTO→HITL = 1
    assert expected_cost_on(gapped, "with_evidence", identity_cal(), TH, T_HIGH) == 1.0  # p = 0,5 → HITL sẵn


def test_p2_fit_fold_scores_with_fixed_cases_included() -> None:
    llm_only = fit(llm_set())
    extra = llm_set() + [fc("r1", "AUTO", llm=False, fixed="HITL"), fc("r2", "HITL", llm=False, fixed="ESCALATE_L2")]
    with_fixed = fit(extra)
    n = len(llm_set())
    # hai ca cố định cộng 1 + 3 = 4 vào tổng chi phí; mẫu số tăng thêm 2
    assert with_fixed.trials[0].train_cost == pytest.approx((llm_only.trials[0].train_cost * n + 4) / (n + 2), abs=1e-9)  # type: ignore[operator]


# ---- điểm 3: hoà chi phí ------------------------------------------------------------------------------------------------


def test_p3_tie_goes_to_with_evidence_then_no_evidence_then_max() -> None:
    f = fit(llm_set())
    costs = {t.variant: t.train_cost for t in f.trials}
    assert len(set(costs.values())) == 1  # ba biến thể trùng p → trùng chi phí
    assert f.variant == "with_evidence"
    # with_evidence xấu hơn (4 ca AUTO bị đẩy lên p cao), no_evidence = max tốt như nhau → no_evidence thắng max
    train = []
    for c in llm_set():
        bad = {"a0": 0.95, "a1": 0.93, "a2": 0.91, "a3": 0.90}.get(c.scenario_id)
        pe = c.probs["with_evidence"] if bad is None else bad
        train.append(fc(c.scenario_id, c.gold, probs={"with_evidence": pe, "no_evidence": c.probs["max"], "max": c.probs["max"]}))
    g = fit(train)
    by = {t.variant: t for t in g.trials if t.status == "ok"}
    assert by["no_evidence"].train_cost == by["max"].train_cost
    assert by["with_evidence"].train_cost > by["no_evidence"].train_cost  # type: ignore[operator]
    assert g.variant == "no_evidence"


def test_p3_variant_order_constant() -> None:
    assert VARIANT_ORDER == ("with_evidence", "no_evidence", "max")


# ---- điểm 4: ngưỡng trên 1,01 và "không AUTO" -------------------------------------------------------------------------------


def test_p4_upper_1_01_means_llm_never_escalates_to_l2() -> None:
    f = fit(llm_set(n_l2=MIN_L2_CASES - 1))
    assert f.upper_disabled == "too_few_l2" and f.thresholds[1] == T_HIGH_MAX == 1.01
    assert f.calibrator is not None
    for p in (0.0, 0.5, 0.99, 1.0):
        assert llm_route(p, f.calibrator, f.thresholds, False, T_HIGH) != "ESCALATE_L2"
    assert route_for(1.0, 0.5, T_HIGH_MAX) == "HITL"  # hành vi decision_math không đổi
    assert not hasattr(ThresholdChoice, "with_upper")  # không thêm with_upper/tham số


def test_p4_uncalibrated_never_auto_because_lower_threshold_is_zero() -> None:
    f = fit([fc(f"a{i}", "AUTO", 0.1) for i in range(5)])  # < 10 mẫu: cả ba biến thể fit lỗi
    assert f.mode == "uncalibrated" and f.calibrator is None
    assert f.thresholds[0] == 0.0  # "không AUTO" = ngưỡng dưới 0
    # ngưỡng trên rộng nhất có thể (1,0): nếu AUTO bị chặn thì chỉ có thể do ngưỡng dưới
    wide = (0.0, 1.0)
    assert llm_route(0.0, None, wide, False, 1.0) == "HITL"
    assert llm_route(0.0, None, f.thresholds, False, T_HIGH) == "HITL"
    assert llm_route(T_HIGH + 0.01, None, f.thresholds, False, T_HIGH) == "ESCALATE_L2"  # raw > ngưỡng trên của policy
    assert llm_route(T_HIGH, None, f.thresholds, False, T_HIGH) == "HITL"  # bằng ngưỡng = HITL


def test_p4_decision_math_comments_fixed_behaviour_unchanged() -> None:
    src = (REPO / "backend/app/risk/decision_math.py").read_text(encoding="utf-8")
    assert "mọi ca LLM đi L2" not in src and "bỏ đường LLM → L2, P8" not in src
    assert src.count("không bao giờ đưa ca sang L2") == 2  # dòng T_HIGH_MAX và docstring route_for
    assert T_HIGH_MAX == 1.01 and route_for(1.0, 0.0, T_HIGH_MAX) == "HITL" and route_for(0.0, 0.1, 0.8) == "AUTO"


# ---- điểm 5: thiếu L2 / AUC ------------------------------------------------------------------------------------------------


def test_p5_enough_l2_and_high_auc_keeps_selected_upper() -> None:
    f = fit(llm_set(n_l2=12))
    assert f.upper_disabled is None
    assert f.thresholds[1] <= 1.0 and f.trials[0].auc_l2 is not None and f.trials[0].auc_l2 >= AUC_L2_MIN


def test_p5_low_auc_forces_upper() -> None:
    # AUTO thấp, L2 ở giữa, HITL cao: Platt (nhãn "cần người") vẫn a > 0, nhưng p không tách L2 khỏi phần còn lại (AUC = 0,5)
    train = [fc(f"a{i}", "AUTO", 0.02 + 0.015 * i) for i in range(12)]
    train += [fc(f"h{i}", "HITL", 0.55 + 0.035 * i) for i in range(12)]
    train += [fc(f"l{i}", "ESCALATE_L2", 0.25 + 0.017 * i) for i in range(12)]
    f = fit(train)
    assert f.mode == "calibrated"
    assert f.upper_disabled == "auc_below_min" and f.thresholds[1] == T_HIGH_MAX
    assert f.trials[0].auc_l2 is not None and f.trials[0].auc_l2 < AUC_L2_MIN


def test_p5_auc_exactly_at_minimum_is_not_disabled() -> None:
    """10 ca L2, 10 ca khác: 7 ca L2 ở trên, 3 ca L2 ở dưới → 70/100 cặp đúng thứ tự → AUC = 0,7 đúng (so `<`, không `<=`)."""
    low = [0.02, 0.03, 0.04]
    mid = [fc(f"a{i}", "AUTO", p) for i, p in enumerate([0.10, 0.20, 0.30, 0.40, 0.50])]
    mid += [fc(f"h{i}", "HITL", p) for i, p in enumerate([0.35, 0.45, 0.55, 0.60, 0.65])]
    high = [0.70, 0.75, 0.80, 0.85, 0.90, 0.92, 0.95]
    train = mid + [fc(f"l{i}", "ESCALATE_L2", p) for i, p in enumerate(low + high)]
    f = fit(train)
    assert f.mode == "calibrated" and f.trials[0].auc_l2 == 0.7
    assert f.upper_disabled is None


def test_p5_auc_undefined_forces_upper() -> None:
    """10 ca L2 chỉ có with_evidence (G10 bỏ hai biến thể kia) → ngoài tập so sánh; trong tập so sánh không có ca L2 → AUC không tính."""
    train = [fc(c.scenario_id, c.gold, c.probs["with_evidence"]) for c in llm_set(n_l2=0)]
    train += [fc(f"l{i}", "ESCALATE_L2", probs={"with_evidence": p}) for i, p in enumerate(L2_P[:10])]
    f = fit(train)
    assert f.n_l2 == 10 and f.n_incomplete == 10
    assert f.upper_disabled == "auc_undefined" and f.thresholds[1] == T_HIGH_MAX


def test_p5_one_class_fit_error_drops_variant() -> None:
    f = fit([fc(f"h{i}", "HITL", 0.1 + 0.05 * i) for i in range(12)])  # chỉ lớp "cần người"
    assert f.mode == "uncalibrated"
    assert all(t.status == "dropped" and t.reason for t in f.trials)


# ---- điểm 6: "thiếu ca L2" đếm trên ca đi lớp LLM ---------------------------------------------------------------------------


def test_p6_boundary_nine_vs_ten_l2_cases_among_llm_cases() -> None:
    nine, ten = fit(llm_set(n_l2=9)), fit(llm_set(n_l2=10))
    assert (nine.n_l2, ten.n_l2) == (9, 10)
    assert nine.upper_disabled == "too_few_l2" and ten.upper_disabled is None


def test_p6_fixed_route_l2_cases_do_not_count() -> None:
    extra = [fc(f"r{i}", "ESCALATE_L2", llm=False, fixed="ESCALATE_L2") for i in range(20)]
    f = fit(llm_set(n_l2=9) + extra)
    assert f.n_l2 == 9 and f.upper_disabled == "too_few_l2"


def test_p6_threshold_is_the_named_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    assert MIN_L2_CASES == 10
    monkeypatch.setattr(calibrate, "MIN_L2_CASES", 3)
    assert fit(llm_set(n_l2=5)).upper_disabled is None  # 5 ≥ 3: hằng được đọc lúc gọi, không rải số 10


# ---- điểm 7: biến thể lỗi, chưa hiệu chỉnh ---------------------------------------------------------------------------------


def test_p7_failed_variant_is_dropped_and_logged_others_compete() -> None:
    train = [fc(c.scenario_id, c.gold, probs={"with_evidence": c.probs["with_evidence"], "no_evidence": 0.5,
                                              "max": c.probs["with_evidence"]}) for c in llm_set()]  # fmt: skip
    f = fit(train)
    by = {t.variant: t for t in f.trials}
    assert by["no_evidence"].status == "dropped" and by["no_evidence"].reason  # p hằng ⇒ a ≤ 0 / một lớp
    assert by["with_evidence"].status == by["max"].status == "ok"
    assert f.mode == "calibrated" and f.variant in ("with_evidence", "max")
    assert any("no_evidence" in line and "bị loại" in line for line in f.log)


def test_p7_all_variants_failing_means_uncalibrated_with_policy_threshold() -> None:
    f = fit([fc(f"a{i}", "AUTO", 0.1) for i in range(5)])
    assert f.mode == "uncalibrated" and f.variant is None and f.sensitivity is None
    assert f.thresholds == (0.0, T_HIGH)
    assert all(t.status == "dropped" for t in f.trials)
    assert any("CHƯA HIỆU CHỈNH" in line for line in f.log)


def test_p7_uncalibrated_threshold_comes_from_argument_not_a_constant() -> None:
    a = fit_fold([fc("a", "AUTO", 0.1)], now=NOW, policy_t_high=0.42)
    b = fit_fold([fc("a", "AUTO", 0.1)], now=NOW, policy_t_high=0.77)
    assert a.thresholds[1] == 0.42 and b.thresholds[1] == 0.77
    assert llm_route(0.6, None, a.thresholds, False, 0.42) == "ESCALATE_L2"
    assert llm_route(0.6, None, b.thresholds, False, 0.77) == "HITL"


# ---- LeakageError / G4 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mixed", ["llm", "fixed"])
def test_leakage_any_test_case_in_train_raises(mixed: str) -> None:
    extra = fc("t", "HITL", 0.5, split="test") if mixed == "llm" else fc("t", "AUTO", llm=False, fixed="AUTO", split="test")
    with pytest.raises(LeakageError):
        fit(llm_set() + [extra])


def test_g4_calibrator_per_fit_is_platt_fitted_on_calibration() -> None:
    f = fit(llm_set())
    assert f.calibrator is not None and f.calibrator.params.method == "platt"
    assert f.calibrator.params.fitted_on.split == "calibration"
    assert f.calibrator.params.a is not None and f.calibrator.params.a > 0


def test_g4_default_cost_matches_table_7_3_and_ratio_10_to_1() -> None:
    """Bảng 7.3 của `huong-dan` (Q9): hàng = đúng, cột = chọn; ô L2 → Chờ duyệt = 1 + 5 (duyệt theo phản xạ)."""
    spec = {
        "AUTO": {"AUTO": 0, "HITL": 1, "ESCALATE_L2": 3},
        "HITL": {"AUTO": 10, "HITL": 1, "ESCALATE_L2": 3},
        "ESCALATE_L2": {"AUTO": 20, "HITL": 1 + 5, "ESCALATE_L2": 3},
    }
    assert {g: dict(row) for g, row in DEFAULT_COST.costs.items()} == spec
    assert t_low_star(DEFAULT_COST) == pytest.approx(0.1, abs=1e-12)


def test_g4_threshold_scan_on_calibrated_synthetic_data_gives_lower_threshold_near_one_tenth() -> None:
    """P8 §9: chọn ngưỡng trên dữ liệu tổng hợp đã hiệu chỉnh → ngưỡng dưới gần 1/10 (ma trận 10:1)."""
    train: list[FoldCase] = []
    for k in range(1, 50):
        p = k / 50
        positives = round(p * 50)
        for j in range(50):
            train.append(fc(f"k{k}-{j}", "HITL" if j < positives else "AUTO", p))
    f = fit(train)
    assert f.mode == "calibrated"
    assert 0.07 <= f.thresholds[0] <= 0.13 and f.t_low_star == pytest.approx(0.1, abs=1e-12)


def test_g4_platt_reduces_ece_on_skewed_synthetic_data() -> None:
    train: list[FoldCase] = []
    raws: list[float] = []
    ys: list[bool] = []
    for k in range(1, 50):
        true_p = k / 50
        raw = true_p**0.4  # xác suất thô lệch (quá tự tin)
        positives = round(true_p * 50)
        for j in range(50):
            gold = "HITL" if j < positives else "AUTO"
            train.append(fc(f"k{k}-{j}", gold, raw))
            raws.append(raw)
            ys.append(gold != "AUTO")
    f = fit(train)
    assert f.calibrator is not None
    after = ece([f.calibrator.transform(r) for r in raws], ys)
    assert after < ece(raws, ys) / 2


def test_sensitivity_5_10_20_and_theory_threshold_recorded() -> None:
    f = fit(llm_set())
    assert f.sensitivity is not None and set(f.sensitivity) == {"5", "10", "20"}
    assert f.sensitivity["10"]["t_low_star"] == pytest.approx(0.1, abs=1e-12)
    assert f.sensitivity["5"]["t_low_star"] == pytest.approx(0.2, abs=1e-12)
    assert f.sensitivity["20"]["t_low_star"] == pytest.approx(0.05, abs=1e-12)
    d = f.to_dict()
    assert d["thresholds"] == {"t_low": f.thresholds[0], "t_high": f.thresholds[1]}
    assert d["calibrator_version"] == (f.calibrator.params.version if f.calibrator else None)


def test_incomplete_cases_leave_comparison_but_stay_counted() -> None:
    train = llm_set() + [fc("m", "HITL", probs={"with_evidence": 0.5})]  # thiếu hai biến thể
    f = fit(train)
    assert f.n_incomplete == 1 and f.n_llm == len(llm_set()) + 1
    assert all(t.n_fit == len(llm_set()) for t in f.trials)


def test_fold_case_validation() -> None:
    with pytest.raises(ValueError):
        FoldCase("s", "F", "calibration", "AUTO", True, "AUTO", {}, False)  # llm=True mà có fixed_route
    with pytest.raises(ValueError):
        FoldCase("s", "F", "calibration", "AUTO", False, None, {}, False)  # llm=False mà không có route
    with pytest.raises(ValueError):
        FoldCase("s", "F", "calibration", "AUTO", True, None, {"max": 1.2}, False)  # p ngoài [0, 1]
    with pytest.raises(ValueError):
        expected_cost_on([], "max", None, TH, T_HIGH)


def test_module_has_no_hard_coded_policy_numbers() -> None:
    src = (REPO / "backend/app/eval/calibrate.py").read_text(encoding="utf-8")
    code = re.sub(r'""".*?"""', "", src, flags=re.DOTALL)
    assert "THRESHOLD_HIGH" not in code and "policy.json" not in code
