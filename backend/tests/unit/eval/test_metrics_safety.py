"""S2 T29 — chỉ số an toàn và quyết định P8 §6.1 (`app.eval.metrics`). Chỉ dữ liệu tổng hợp; số tính tay khớp 1e-9.

Bộ H (10 lá tới M5, `[gold → pred]`), dùng chung cho FNR/FPR/ma trận/accuracy/macro-F1/chi phí:
    1  HITL → AUTO          (bỏ sót)
    2  HITL → HITL
    3  L2   → L2
    4  L2   → HITL
    5–8 AUTO → AUTO  (4 lá)
    9  AUTO → HITL          (escalate thừa)
    10 AUTO → L2            (escalate thừa)
Ma trận [gold][pred] (hàng gold, cột pred, thứ tự AUTO, HITL, L2):
    AUTO: 4 1 1 | HITL: 1 1 0 | L2: 0 1 1
"""

import itertools
import math
from typing import Any, Final

import pytest
from app.db.models import DECIDED_BY
from app.eval.metrics import (
    calibration_scores,
    decided_by_distribution,
    mean_route_cost,
    safety,
)
from app.eval.predictions import PredictionRecord
from app.risk.decision_math import DEFAULT_COST, clopper_pearson_upper

TOL = 1e-9
L2: Final = "ESCALATE_L2"
_ids = itertools.count()


def leaf(
    gold: str,
    pred: str | None,
    *,
    by: str | None = None,
    raw: float | None = None,
    cal: float | None = None,
    pm: str | None = None,
) -> PredictionRecord:
    """Lá tổng hợp. `pred=None` = không tới M5 → mọi trường rủi ro None. Tới M5 mà không ghi `by` → `rule`."""
    i = next(_ids)
    data: dict[str, Any] = {
        "run_id": "0123456789ab", "strategy": "hybrid", "split": "test",
        "scenario_id": f"S-{i}", "family": f"F-{i}", "ticket_id": f"T-{i}", "parent_ticket_id": None,
        "expected_route": gold, "route": pred,
        "decided_by": (by or "rule") if pred is not None else None,
        "raw_prob": raw, "calibrated_prob": cal, "p_method": pm,
        "final_state": "S_RESOLVED", "exit_code": None, "close_reason": "resolved_user_confirmed",
        "resolution_path": "auto", "has_approval": False, "clarification_turns": 0,
        "intent": "vpn", "gold_intent": "vpn", "doc_ids": None, "gold_doc_ids": (),
    }  # fmt: skip
    return PredictionRecord.model_validate(data)


def h_set() -> list[PredictionRecord]:
    return [
        leaf("HITL", "AUTO"), leaf("HITL", "HITL"), leaf(L2, L2), leaf(L2, "HITL"),
        *[leaf("AUTO", "AUTO") for _ in range(4)], leaf("AUTO", "HITL"), leaf("AUTO", L2),
    ]  # fmt: skip


def close(a: float | None, b: float) -> bool:
    return a is not None and math.isclose(a, b, rel_tol=0, abs_tol=TOL)


# ---- FNR / FPR ------------------------------------------------------------------------------------------------------


def test_fnr_hand() -> None:
    # Cần người (gold ≠ AUTO) = lá 1–4 → n = 4; trong đó pred = AUTO chỉ lá 1 → k = 1. FNR = 1/4 = 0,25.
    # Cận trên CP 95% một phía = BETA.INV(0,95; k+1; n−k) = BETA.INV(0,95; 2; 3) ≈ 0,751395374270.
    s = safety(h_set())
    assert (s.fnr.k, s.fnr.n) == (1, 4)
    assert close(s.fnr.value, 0.25)
    assert s.fnr_upper95 == clopper_pearson_upper(1, 4)
    assert close(s.fnr_upper95, 0.751395374270)


def test_fnr_excludes_route_none() -> None:
    # Thêm 2 lá KHÔNG tới M5 (gold HITL, gold AUTO; route None) → ngoài mẫu số §6.1 (P8:342). FNR vẫn 1/4, FPR vẫn 2/6,
    # n_m5 vẫn 10.
    s = safety([*h_set(), leaf("HITL", None), leaf("AUTO", None)])
    assert s.n_m5 == 10
    assert (s.fnr.k, s.fnr.n) == (1, 4)
    assert (s.fpr.k, s.fpr.n) == (2, 6)


def test_fnr_zero_of_60() -> None:
    # 60 lá HITL → HITL: k = 0, n = 60 → FNR = 0. Cận trên (k = 0) = 1 − 0,05^(1/60) ≈ 0,048702913310 (P8 §9: ≈ 0,049).
    s = safety([leaf("HITL", "HITL") for _ in range(60)])
    assert (s.fnr.k, s.fnr.n) == (0, 60)
    assert s.fnr.value == 0.0
    assert close(s.fnr_upper95, 1 - 0.05 ** (1 / 60))
    assert s.fnr_upper95 is not None and abs(s.fnr_upper95 - 0.049) < 1e-3


def test_fnr_no_need_human_is_none() -> None:
    # Mọi gold = AUTO → mẫu số FNR = 0 → FNR None, cận None (không trả 0 giả). FPR = 1/3 (lá 2 AUTO → HITL).
    s = safety([leaf("AUTO", "AUTO"), leaf("AUTO", "HITL"), leaf("AUTO", "AUTO")])
    assert (s.fnr.k, s.fnr.n) == (0, 0)
    assert s.fnr.value is None
    assert s.fnr_upper95 is None
    assert close(s.fpr.value, 1 / 3)


def test_fpr_hand() -> None:
    # gold = AUTO: lá 5–10 → n = 6; pred ≠ AUTO: lá 9 (HITL), 10 (L2) → k = 2. FPR = 2/6 = 0,333333333333.
    s = safety(h_set())
    assert (s.fpr.k, s.fpr.n) == (2, 6)
    assert close(s.fpr.value, 1 / 3)


def test_fpr_no_auto_gold_is_none() -> None:
    # Không lá gold = AUTO → FPR None.
    s = safety([leaf("HITL", "HITL"), leaf(L2, "AUTO")])
    assert (s.fpr.k, s.fpr.n) == (0, 0)
    assert s.fpr.value is None


# ---- ma trận, accuracy, macro-F1 ------------------------------------------------------------------------------------


def test_confusion_orientation() -> None:
    # [gold][pred]: AUTO→L2 = 1 (lá 10) nhưng L2→AUTO = 0; L2→HITL = 1 (lá 4) nhưng HITL→L2 = 0.
    c = safety(h_set()).confusion
    assert {g: dict(row) for g, row in c.items()} == {
        "AUTO": {"AUTO": 4, "HITL": 1, L2: 1},
        "HITL": {"AUTO": 1, "HITL": 1, L2: 0},
        L2: {"AUTO": 0, "HITL": 1, L2: 1},
    }
    assert c["AUTO"][L2] == 1 and c[L2]["AUTO"] == 0


def test_accuracy_hand() -> None:
    # Đường chéo 4 + 1 + 1 = 6 trên 10 → 0,6.
    s = safety(h_set())
    assert (s.accuracy.k, s.accuracy.n) == (6, 10)
    assert close(s.accuracy.value, 0.6)


def test_macro_f1_hand() -> None:
    # F1 lớp = 2·TP / (#pred lớp + #gold lớp) (= 2PR/(P+R)).
    #   AUTO: TP 4, pred 4+1+0 = 5, gold 6 → 8/11 ≈ 0,727272727273
    #   HITL: TP 1, pred 1+1+1 = 3, gold 2 → 2/5 = 0,4
    #   L2  : TP 1, pred 1+0+1 = 2, gold 2 → 2/4 = 0,5
    # macro = (8/11 + 0,4 + 0,5)/3 = 179/330 ≈ 0,542424242424
    s = safety(h_set())
    assert close(s.f1_by_class["AUTO"], 8 / 11)
    assert close(s.f1_by_class["HITL"], 0.4)
    assert close(s.f1_by_class[L2], 0.5)
    assert close(s.macro_f1, 179 / 330)


def test_macro_f1_absent_class() -> None:
    # Không lá nào có gold L2 hay pred L2 → lớp L2 bị LOẠI khỏi trung bình (không tính 0).
    #   AUTO→AUTO ×2, HITL→HITL, HITL→AUTO
    #   AUTO: TP 2, pred 3, gold 2 → 4/5 = 0,8;  HITL: TP 1, pred 1, gold 2 → 2/3
    # macro = (0,8 + 2/3)/2 = 11/15 ≈ 0,733333333333 (nếu gộp L2 = 0 → 0,488888888889: sai)
    s = safety([leaf("AUTO", "AUTO"), leaf("AUTO", "AUTO"), leaf("HITL", "HITL"), leaf("HITL", "AUTO")])
    assert s.f1_by_class[L2] is None
    assert close(s.macro_f1, 11 / 15)


def test_macro_f1_zero_division() -> None:
    # P hoặc R = 0/0 → F1 lớp = 0 (vẫn vào trung bình).  AUTO→AUTO, L2→HITL
    #   AUTO: TP 1, pred 1, gold 1 → 1
    #   HITL: pred 1, gold 0 → R = 0/0 → 0
    #   L2  : pred 0, gold 1 → P = 0/0 → 0
    # macro = (1 + 0 + 0)/3 = 1/3
    s = safety([leaf("AUTO", "AUTO"), leaf(L2, "HITL")])
    assert s.f1_by_class["HITL"] == 0.0 and s.f1_by_class[L2] == 0.0
    assert close(s.macro_f1, 1 / 3)


def test_single_record() -> None:
    # 1 lá AUTO → AUTO: FNR None (n = 0), FPR 0/1 = 0, accuracy 1/1, chỉ lớp AUTO có mặt → macro-F1 = 1, chi phí 0.
    s = safety([leaf("AUTO", "AUTO")])
    assert s.fnr.value is None and s.fnr_upper95 is None
    assert (s.fpr.k, s.fpr.n) == (0, 1) and s.fpr.value == 0.0
    assert s.accuracy.value == 1.0
    assert s.macro_f1 == 1.0
    assert s.cost.value == 0.0


def test_safety_no_m5_all_none() -> None:
    # Có lá nhưng không lá nào tới M5 → mọi tỉ lệ None, macro-F1 None, ma trận toàn 0, n_m5 = 0.
    s = safety([leaf("HITL", None), leaf("AUTO", None)])
    assert s.n_m5 == 0
    assert s.fnr.value is None and s.fpr.value is None and s.accuracy.value is None
    assert s.fnr_upper95 is None and s.macro_f1 is None and s.cost.value is None
    assert all(v == 0 for row in s.confusion.values() for v in row.values())


# ---- chi phí kỳ vọng --------------------------------------------------------------------------------------------------


def test_mean_route_cost_hand() -> None:
    # COST[gold][pred] (bảng 7.3): lá 1 HITL→AUTO 10; 2 HITL→HITL 1; 3 L2→L2 3; 4 L2→HITL 6; 5–8 AUTO→AUTO 0;
    # 9 AUTO→HITL 1; 10 AUTO→L2 3. Tổng = 24, n = 10 → 2,4.
    m = mean_route_cost(h_set())
    assert (m.total, m.n) == (24.0, 10)
    assert close(m.value, 2.4)
    assert safety(h_set()).cost == m


def test_mean_route_cost_asymmetric() -> None:
    # Một lá HITL → AUTO: COST[HITL][AUTO] = 10 (đọc ngược COST[AUTO][HITL] = 1 là sai).
    assert mean_route_cost([leaf("HITL", "AUTO")]).value == 10.0
    assert mean_route_cost([leaf("AUTO", "HITL")]).value == 1.0


def test_mean_route_cost_excludes_route_none() -> None:
    m = mean_route_cost([leaf("HITL", "AUTO"), leaf("HITL", None)])
    assert (m.total, m.n) == (10.0, 1)
    assert mean_route_cost([leaf("HITL", None)]).value is None


def test_mean_route_cost_uses_given_matrix() -> None:
    assert mean_route_cost([leaf("HITL", "AUTO")], DEFAULT_COST).value == 10.0
    from app.risk.decision_math import cost_matrix_for_ratio

    assert mean_route_cost([leaf("HITL", "AUTO")], cost_matrix_for_ratio(20)).value == 20.0


# ---- ECE / Brier ----------------------------------------------------------------------------------------------------


def calib_set() -> list[PredictionRecord]:
    """4 ca LLM (self_report) + 1 ca luật có p (phải bị lọc) + 1 ca LLM không có p + 1 lá không tới M5.
        ca   gold  y   raw   cal
        a    AUTO  0   0,15  0,05
        b    HITL  1   0,35  0,55
        c    L2    1   0,65  0,75
        d    HITL  1   0,85  0,95
        e    AUTO  0   0,95  0,95   decided_by = rule → loại
        f    AUTO  0   —     —      LLM nhưng p None → loại
    """
    sr = "self_report"
    return [
        leaf("AUTO", "AUTO", by="llm", raw=0.15, cal=0.05, pm=sr),
        leaf("HITL", "HITL", by="llm", raw=0.35, cal=0.55, pm=sr),
        leaf(L2, "HITL", by="llm", raw=0.65, cal=0.75, pm=sr),
        leaf("HITL", L2, by="llm", raw=0.85, cal=0.95, pm=sr),
        leaf("AUTO", "AUTO", by="rule", raw=0.95, cal=0.95, pm=sr),
        leaf("AUTO", "HITL", by="llm"),
        leaf("HITL", None),
    ]  # fmt: skip


def test_ece_brier_llm_only() -> None:
    # raw: mỗi ca một bin (0,15→1, 0,35→3, 0,65→6, 0,85→8) → ECE = mean|p − y| = (0,15+0,65+0,35+0,15)/4 = 1,3/4 = 0,325.
    # Brier = (0,0225 + 0,4225 + 0,1225 + 0,0225)/4 = 0,59/4 = 0,1475.  (Gộp ca e: ECE 0,45, Brier 0,2985 — sai.)
    c = calibration_scores(calib_set(), "raw")
    assert c is not None
    assert c.n == 4 and c.p_method == "self_report"
    assert close(c.ece, 0.325)
    assert close(c.brier, 0.1475)


def test_raw_vs_calibrated() -> None:
    # calibrated: bin 0, 5, 7, 9 → ECE = (0,05+0,45+0,25+0,05)/4 = 0,8/4 = 0,2.
    # Brier = (0,0025 + 0,2025 + 0,0625 + 0,0025)/4 = 0,27/4 = 0,0675.
    c = calibration_scores(calib_set(), "calibrated")
    assert c is not None and c.n == 4
    assert close(c.ece, 0.2)
    assert close(c.brier, 0.0675)


def test_calibration_matches_decision_math() -> None:
    from app.risk.decision_math import brier, ece

    c = calibration_scores(calib_set(), "raw")
    assert c is not None
    assert c.ece == ece([0.15, 0.35, 0.65, 0.85], [0, 1, 1, 1])
    assert c.brier == brier([0.15, 0.35, 0.65, 0.85], [0, 1, 1, 1])


def test_mixed_p_method_rejected() -> None:
    rows = [leaf("AUTO", "AUTO", by="llm", raw=0.1, cal=0.1, pm="self_report"),
            leaf("HITL", "HITL", by="llm", raw=0.6, cal=0.6, pm="sampling_k5")]  # fmt: skip
    for which in ("raw", "calibrated"):
        with pytest.raises(ValueError, match="p_method"):
            calibration_scores(rows, which)  # type: ignore[arg-type]


def test_no_llm_cases_none() -> None:
    # Chỉ ca luật (vd `rule_only`) hoặc ca LLM không có p → None (không phải lỗi, không phải 0).
    assert calibration_scores([leaf("AUTO", "AUTO"), leaf("HITL", "HITL")], "raw") is None
    assert calibration_scores([leaf("AUTO", "HITL", by="llm")], "calibrated") is None
    assert calibration_scores([leaf("AUTO", None)], "raw") is None


def test_calibration_which_rejected() -> None:
    with pytest.raises(ValueError, match="which"):
        calibration_scores(calib_set(), "before")  # type: ignore[arg-type]


# ---- decided_by ---------------------------------------------------------------------------------------------------------


def test_decided_by_values_in_sync() -> None:
    """`DecidedByDistribution` có đúng một trường cho mỗi giá trị DB nhận."""
    assert DECIDED_BY == ("rule", "llm")


def test_decided_by_distribution_hand() -> None:
    # 5 lá tới M5: rule ×3, llm ×2 + 2 lá không tới M5 (ngoài mẫu số, P8:342) → rule 3/5 = 0,6; llm 2/5 = 0,4.
    rows = [*[leaf("AUTO", "AUTO") for _ in range(3)], leaf("HITL", "HITL", by="llm"), leaf("AUTO", "HITL", by="llm"),
            leaf("HITL", None), leaf("AUTO", None)]  # fmt: skip
    d = decided_by_distribution(rows)
    assert (d.rule.k, d.rule.n) == (3, 5) and close(d.rule.value, 0.6)
    assert (d.llm.k, d.llm.n) == (2, 5) and close(d.llm.value, 0.4)


def test_decided_by_no_m5_is_none() -> None:
    d = decided_by_distribution([leaf("AUTO", None)])
    assert d.rule.value is None and d.llm.value is None


# ---- rỗng ----------------------------------------------------------------------------------------------------------------


def test_empty_records_raises() -> None:
    with pytest.raises(ValueError, match="rỗng"):
        safety([])
    with pytest.raises(ValueError, match="rỗng"):
        mean_route_cost([])
    with pytest.raises(ValueError, match="rỗng"):
        calibration_scores([], "raw")
    with pytest.raises(ValueError, match="rỗng"):
        decided_by_distribution([])
