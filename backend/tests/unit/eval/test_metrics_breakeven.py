"""G1 — điểm hoà vốn r* giữa hai phương án (`app.eval.metrics.breakeven`, `manual_baseline`; chốt #32 18/10 câu 1, phương án A).
Chỉ dữ liệu tổng hợp; số tính tay khớp 1e-9 (đã kiểm độc lập bằng phân số).

C(r) = `cost_matrix_for_ratio(r)`: HITL→AUTO = r, L2→AUTO = 2r, ô khác cố định → chi phí/ticket = fixed + miss·r;
r* = (fixed_B − fixed_A) / (miss_A − miss_B) (đơn vị: lượt duyệt / một ca bỏ sót). Cùng 8 scenario (+1 lá route None):
    sid  gold  H (Hybrid)  R (Chỉ-luật)  M (Thủ công = manual_baseline: route ≠ None → HITL)
    1-3  AUTO  AUTO        1-2 AUTO, 3 HITL   HITL
    4    AUTO  HITL        HITL               HITL
    5    HITL  AUTO        HITL               HITL
    6    HITL  HITL        HITL               HITL
    7    L2    HITL        L2                 HITL
    8    L2    L2          L2                 HITL
    9    AUTO  None        None               None
H: fixed (0+0+0+1 + 0+1 + 6+3)/8 = 11/8, miss 1/8. M: fixed (4·1 + 2·1 + 2·6)/8 = 9/4, miss 0. R: fixed 10/8, miss 0.
    cặp     không trọng số          70/20/10                60/30/10               80/15/5
    H vs M  (18−11)/1 = 7           (1,5−0,725)/0,1 = 7,75  (1,5−0,75)/0,15 = 5    (1,25−0,5)/0,075 = 10
    H vs R  −1 → None "dominated"   (0,85−0,725)/0,1 = 1,25 (0,9−0,75)/0,15 = 1    (0,7−0,5)/0,075 = 8/3
    R vs M  None "equal_miss"       None                    None                   None
|fixed_A − fixed_B| ≤ FIXED_TOL = 1e-9 → tử số 0 → r* = 0 → None "dominated" (Q-G1-11); equal_miss xét trước (Q-G1-9).
"""

from dataclasses import FrozenInstanceError
from typing import Any, Final

import pytest
from app.eval.metrics import (
    BREAKEVEN_RATIOS,
    OPERATING_MIX,
    SENSITIVITY_MIXES,
    Breakeven,
    breakeven,
    manual_baseline,
    mean_route_cost,
)
from app.eval.predictions import PredictionRecord
from app.risk.decision_math import cost_matrix_for_ratio
from tests.unit.eval.contract_v11 import V11

TOL = 1e-9
L2: Final = "ESCALATE_L2"
GOLDS: Final = ("AUTO", "AUTO", "AUTO", "AUTO", "HITL", "HITL", L2, L2, "AUTO")
H_ROUTES: Final = ("AUTO", "AUTO", "AUTO", "HITL", "AUTO", "HITL", "HITL", L2, None)
R_ROUTES: Final = ("AUTO", "AUTO", "HITL", "HITL", "HITL", "HITL", L2, L2, None)
MIXES: Final = {"70/20/10": OPERATING_MIX, **SENSITIVITY_MIXES}


def leaf(sid: int, gold: str | None, route: str | None, *, strategy: str = "hybrid", split: str = "test") -> PredictionRecord:
    data: dict[str, Any] = {
        "run_id": "0123456789ab", "strategy": strategy, "split": split,
        "scenario_id": f"S-{sid}", "family": f"F-{sid}", "ticket_id": f"T-{strategy}-{sid}", "parent_ticket_id": None,
        "expected_route": gold, "route": route, "decided_by": "rule" if route is not None else None,
        "raw_prob": None, "calibrated_prob": None, "p_method": None,
        "final_state": "S_RESOLVED", "exit_code": None, "close_reason": None, "resolution_path": None,
        "has_approval": False, "clarification_turns": 0,
        "intent": "vpn", "gold_intent": "vpn", "doc_ids": None, "gold_doc_ids": (),
        **V11,
    }  # fmt: skip
    return PredictionRecord.model_validate(data)


def run(routes: tuple[str | None, ...], strategy: str = "hybrid", golds: tuple[str | None, ...] = GOLDS) -> list[PredictionRecord]:
    return [leaf(i, g, r, strategy=strategy) for i, (g, r) in enumerate(zip(golds, routes, strict=True), start=1)]


def h_set() -> list[PredictionRecord]:
    return run(H_ROUTES)


def r_set() -> list[PredictionRecord]:
    return run(R_ROUTES, "rule_only")


def close(a: float | None, b: float) -> bool:
    return a is not None and abs(a - b) <= TOL


# ---- Thủ công giải tích ---------------------------------------------------------------------------------------------------


def test_manual_baseline() -> None:
    h = h_set()
    m = manual_baseline(h)
    assert len(m) == len(h)
    assert [r.route for r in m] == ["HITL"] * 8 + [None]  # lá có hành động (route ≠ None) → HITL; route None giữ None
    assert {r.strategy for r in m} == {"manual"}
    for a, b in zip(h, m, strict=True):
        assert (a.scenario_id, a.family, a.expected_route, a.split) == (b.scenario_id, b.family, b.expected_route, b.split)
    assert tuple(r.route for r in h) == H_ROUTES  # đầu vào không đổi


# ---- bảng tính tay ----------------------------------------------------------------------------------------------------------


def test_breakeven_vs_manual_hand() -> None:
    b = breakeven(h_set(), manual_baseline(h_set()))
    assert (b.reason, b.mix, b.n, b.n_excluded_a, b.n_excluded_b, b.missing_groups) == ("ok", None, 8, 0, 0, ())
    assert close(b.fixed_a, 11 / 8) and close(b.miss_a, 1 / 8)
    assert close(b.fixed_b, 9 / 4) and close(b.miss_b, 0.0)
    assert close(b.r_star, 7.0)


def test_breakeven_cost_equal_at_rstar() -> None:
    # Đường độc lập: ở r*, chi phí §6.1 (mean_route_cost với C(r*)) của hai phương án bằng nhau = 18/8.
    h, m = h_set(), manual_baseline(h_set())
    r = breakeven(h, m).r_star
    assert r is not None
    cm = cost_matrix_for_ratio(r)
    assert close(mean_route_cost(h, cm).value, 2.25)
    assert close(mean_route_cost(m, cm).value, 2.25)


def test_breakeven_weighted_hand() -> None:
    h, m = h_set(), manual_baseline(h_set())
    for name, expected in {"70/20/10": 7.75, "60/30/10": 5.0, "80/15/5": 10.0}.items():
        b = breakeven(h, m, MIXES[name])
        assert b.reason == "ok", name
        assert close(b.r_star, expected), (name, b.r_star)
        assert b.mix is not None and dict(b.mix) == dict(MIXES[name])
    w = breakeven(h, m, OPERATING_MIX)
    assert close(w.fixed_a, 0.725) and close(w.miss_a, 0.1) and close(w.fixed_b, 1.5) and close(w.miss_b, 0.0)


def test_breakeven_dominated() -> None:
    # Không trọng số: r* = (10 − 11)/1 = −1 ≤ 0 → H đắt hơn R với mọi r > 0 → None, "dominated" (G1-Q2).
    b = breakeven(h_set(), r_set())
    assert (b.r_star, b.reason) == (None, "dominated")
    assert b.fixed_a is not None and b.fixed_b is not None and b.fixed_a > b.fixed_b
    assert b.miss_a is not None and b.miss_b is not None and b.miss_a > b.miss_b
    # Có trọng số: R duyệt thừa nửa nhóm routine (nặng 0,7) → đổi dấu.
    for name, expected in {"70/20/10": 1.25, "60/30/10": 1.0, "80/15/5": 8 / 3}.items():
        w = breakeven(h_set(), r_set(), MIXES[name])
        assert w.reason == "ok" and close(w.r_star, expected), (name, w.r_star)


def test_breakeven_rstar_zero_is_dominated() -> None:
    # fixed bằng nhau, miss khác → r* = 0 → không có r > 0 nào hoà → "dominated". Saving vẫn tính: ½ − (r + 1)/2 = −r/2.
    a = [leaf(1, "HITL", "AUTO"), leaf(2, "AUTO", "HITL")]  # fixed (0 + 1)/2, miss 1/2
    b = [leaf(1, "HITL", "HITL"), leaf(2, "AUTO", "AUTO")]  # fixed (1 + 0)/2, miss 0
    t = breakeven(a, b)
    assert (t.r_star, t.reason) == (None, "dominated")
    assert dict(t.saving) == pytest.approx({5.0: -2.5, 10.0: -5.0, 20.0: -10.0}, abs=TOL)


# Một lá mỗi nhóm. A: fixed 0,7·1 + 0,2·1 + 0,1·0, miss 0,1·2; B: fixed 0,2·3 + 0,1·3, miss 0. Hai fixed bằng nhau về toán (0,9).
FIXED_EQ_A: Final = (("AUTO", "HITL"), ("HITL", "HITL"), (L2, "AUTO"))
FIXED_EQ_B: Final = (("AUTO", "AUTO"), ("HITL", L2), (L2, L2))


def fixed_eq_pair() -> tuple[list[PredictionRecord], list[PredictionRecord]]:
    def build(cells: tuple[tuple[str, str], ...]) -> list[PredictionRecord]:
        return [leaf(i, g, p) for i, (g, p) in enumerate(cells, start=1)]

    return build(FIXED_EQ_A), build(FIXED_EQ_B)


def test_breakeven_fixed_tol_float_noise() -> None:
    # 70/20/10: fixed_A = 0.8999999999999999, fixed_B = 0.9000000000000001 (cộng dồn số thực) → không có dung sai thì
    # r* = 2,2e-16/0,2 ≈ 1e-15 "ok"; có dung sai → tử số 0 → "dominated" (Q-G1-11). Saving = 0,9 − (0,9 + 0,2r) = −0,2r.
    a, b = fixed_eq_pair()
    t = breakeven(a, b, OPERATING_MIX)
    assert t.fixed_a is not None and t.fixed_b is not None and t.fixed_a != t.fixed_b
    assert close(t.fixed_a, 0.9) and close(t.fixed_b, 0.9) and close(t.miss_a, 0.2) and close(t.miss_b, 0.0)
    assert (t.r_star, t.reason) == (None, "dominated")
    assert dict(t.saving) == pytest.approx({5.0: -1.0, 10.0: -2.0, 20.0: -4.0}, abs=TOL)


def eps_mix(eps: float) -> dict[str, float]:
    # fixed_A = 0,9 − ε, fixed_B = 0,9 + 3ε → tử số 4ε; miss_A = 0,2 + 2ε, miss_B = 0.
    return {"routine": 0.7 - eps, "approval": 0.2, "sensitive": 0.1 + eps}


@pytest.mark.parametrize("eps", [2.5e-13, 2e-10])  # tử số 1e-12, 8e-10 ≤ 1e-9
def test_breakeven_fixed_tol_within(eps: float) -> None:
    a, b = fixed_eq_pair()
    t = breakeven(a, b, eps_mix(eps))
    assert t.fixed_a is not None and t.fixed_b is not None and close(t.fixed_b - t.fixed_a, 4 * eps)
    assert (t.r_star, t.reason) == (None, "dominated")


def test_breakeven_fixed_tol_outside() -> None:
    # ε = 5e-10 → tử số 2e-9 > 1e-9 → giữ tử số: r* = 2e-9 / (0,2 + 1e-9) ≈ 1e-8, "ok".
    a, b = fixed_eq_pair()
    t = breakeven(a, b, eps_mix(5e-10))
    assert t.reason == "ok"
    assert t.r_star == pytest.approx(2e-9 / (0.2 + 1e-9), rel=1e-6)


def test_breakeven_equal_miss_before_fixed_tol() -> None:
    # fixed ½ = ½ VÀ miss 0 = 0 → "equal_miss" (xét trước dung sai fixed — Q-G1-9); saving 0 ở mọi r.
    a = [leaf(1, "AUTO", "HITL"), leaf(2, "AUTO", "AUTO")]
    b = [leaf(1, "AUTO", "AUTO"), leaf(2, "AUTO", "HITL")]
    t = breakeven(a, b)
    assert (t.r_star, t.reason) == (None, "equal_miss")
    assert close(t.fixed_a, 0.5) and close(t.fixed_b, 0.5)
    assert all(close(v, 0.0) for v in t.saving.values())


def test_breakeven_equal_miss() -> None:
    # R và M đều không bỏ sót (miss 0 = 0) → không có điểm hoà vốn (chốt 1: b_A = b_B → None); M − R = 1 lượt duyệt/ticket ở mọi r.
    r = r_set()
    b = breakeven(r, manual_baseline(r))
    assert (b.r_star, b.reason) == (None, "equal_miss")
    assert all(close(v, 1.0) for v in b.saving.values())
    w = breakeven(r, manual_baseline(r), OPERATING_MIX)
    assert (w.r_star, w.reason) == (None, "equal_miss")
    assert all(close(v, 0.65) for v in w.saving.values())  # 1,5 − 0,85


def test_breakeven_l2_miss_counts_double() -> None:
    # Bộ E: L2→AUTO = 2r → miss_a = 2/2 = 1; fixed_b = (6 + 1)/2 = 3,5 → r* = 3,5 (nếu tính trọng 1 → 7).
    a = [leaf(1, L2, "AUTO"), leaf(2, "AUTO", "AUTO")]
    b = breakeven(a, manual_baseline(a))
    assert close(b.miss_a, 1.0) and close(b.fixed_a, 0.0) and close(b.fixed_b, 3.5)
    assert close(b.r_star, 3.5)


@pytest.mark.parametrize(
    ("gold", "pred", "fixed", "miss"),
    [("HITL", "AUTO", 0.0, 1.0), (L2, "AUTO", 0.0, 2.0), (L2, "HITL", 6.0, 0.0), ("AUTO", L2, 3.0, 0.0),
     ("AUTO", "AUTO", 0.0, 0.0), ("HITL", "HITL", 1.0, 0.0)],
)  # fmt: skip
def test_breakeven_cells_from_cost_matrix(gold: str, pred: str, fixed: float, miss: float) -> None:
    # Hệ số từng ô lấy từ cost_matrix_for_ratio: C(r)[g][p] = fixed + miss·r.
    a = [leaf(1, gold, pred)]
    b = breakeven(a, a)
    assert close(b.fixed_a, fixed) and close(b.miss_a, miss)
    assert b.reason == "equal_miss"


# ---- tiết kiệm / ticket -----------------------------------------------------------------------------------------------------


def test_breakeven_savings_hand() -> None:
    # saving[r] = cost_B(r) − cost_A(r) (G1-Q5: dương = A rẻ hơn), lượt duyệt/ticket.
    assert BREAKEVEN_RATIOS == (5.0, 10.0, 20.0)
    h, m, r = h_set(), manual_baseline(h_set()), r_set()
    hm, hr = breakeven(h, m).saving, breakeven(h, r).saving
    assert set(hm) == set(hr) == {5.0, 10.0, 20.0}
    for ratio, e_hm, e_hr in ((5.0, 0.25, -0.75), (10.0, -0.375, -1.375), (20.0, -1.625, -2.625)):
        assert close(hm[ratio], e_hm) and close(hr[ratio], e_hr), ratio
        cm = cost_matrix_for_ratio(ratio)
        h_cost = mean_route_cost(h, cm).value
        assert h_cost is not None
        assert close(hm[ratio], (mean_route_cost(m, cm).value or 0.0) - h_cost)
    assert dict(breakeven(h, m, ratios=(7,)).saving) == pytest.approx({7.0: 0.0}, abs=TOL)


def test_breakeven_savings_affine() -> None:
    h = h_set()
    for other in (manual_baseline(h), r_set()):
        for mix in (None, *MIXES.values()):
            b = breakeven(h, other, mix)
            assert b.fixed_a is not None and b.miss_a is not None and b.fixed_b is not None and b.miss_b is not None
            for ratio, s in b.saving.items():
                assert close(s, (b.fixed_b + b.miss_b * ratio) - (b.fixed_a + b.miss_a * ratio)), (mix, ratio)


def test_breakeven_antisymmetric() -> None:
    a = run(("AUTO", "AUTO", "AUTO", "HITL", "AUTO", None, "HITL", L2, None))
    b = r_set()
    ab, ba = breakeven(a, b, OPERATING_MIX), breakeven(b, a, OPERATING_MIX)
    assert ab.r_star is not None and close(ba.r_star, ab.r_star)
    assert all(close(ba.saving[k], -v) for k, v in ab.saving.items() if v is not None)
    assert (ab.n_excluded_a, ab.n_excluded_b) == (ba.n_excluded_b, ba.n_excluded_a) == (0, 1)


# ---- phần giao, rỗng, chưa nhãn, nhóm thiếu ----------------------------------------------------------------------------------


def test_breakeven_intersection() -> None:
    # A không tới M5 ở sid 6 (gold HITL) mà B có route → lá đó ngoài phần giao (G1-Q3; P8 §5.4), n_excluded_b = 1.
    # Phần giao 7 lá: A fixed (1 + 0 + 9)/7, miss 1/7; M fixed (4 + 1 + 12)/7 → r* = 7.
    # (Không lấy phần giao: A 10/7, 1/7 trên 7 lá; M 18/8 trên 8 lá → r* = 5,75.)
    a = run(("AUTO", "AUTO", "AUTO", "HITL", "AUTO", None, "HITL", L2, None))
    b = breakeven(a, manual_baseline(h_set()))
    assert (b.n, b.n_excluded_a, b.n_excluded_b) == (7, 0, 1)
    assert close(b.fixed_a, 10 / 7) and close(b.miss_a, 1 / 7) and close(b.fixed_b, 17 / 7)
    assert close(b.r_star, 7.0)


def test_breakeven_no_common() -> None:
    a = [leaf(1, "AUTO", None), leaf(2, "HITL", None), leaf(3, L2, None)]
    for mix in (None, OPERATING_MIX):
        b = breakeven(a, manual_baseline(a), mix)
        assert (b.r_star, b.reason, b.n, b.fixed_a, b.miss_a) == (None, "no_common", 0, None, None)
        assert set(b.saving) == {5.0, 10.0, 20.0} and all(v is None for v in b.saving.values())


def test_breakeven_skips_unlabeled() -> None:
    golds = (*GOLDS, None, None)
    a = run((*H_ROUTES, "AUTO", "HITL"), golds=golds)
    b = breakeven(a, manual_baseline(a))
    assert (b.n, b.n_unlabeled, b.reason) == (8, 2, "ok")
    assert close(b.r_star, 7.0)
    assert breakeven(h_set(), manual_baseline(h_set())).n_unlabeled == 0


def test_breakeven_all_unlabeled() -> None:
    a = [leaf(1, None, "AUTO"), leaf(2, None, "HITL")]
    b = breakeven(a, manual_baseline(a))
    assert (b.r_star, b.reason, b.n, b.n_unlabeled) == (None, "no_common", 0, 2)


def test_breakeven_missing_group() -> None:
    # Bỏ lá gold L2: không trọng số H fixed 2/6, miss 1/6; M fixed 6/6 → r* = 4. Có mix → None, "missing_groups" (Q5).
    keep = [i for i, g in enumerate(GOLDS) if g != L2]
    h = [r for i, r in enumerate(h_set()) if i in keep]
    m = manual_baseline(h)
    assert close(breakeven(h, m).r_star, 4.0)
    w = breakeven(h, m, OPERATING_MIX)
    assert (w.r_star, w.reason, w.missing_groups) == (None, "missing_groups", ("sensitive",))
    assert all(v is None for v in w.saving.values())


# ---- kiểm đầu vào -----------------------------------------------------------------------------------------------------------


def test_breakeven_input_mismatch() -> None:
    h = h_set()
    with pytest.raises(ValueError, match="scenario_id") as e:
        breakeven(h, manual_baseline(h)[:-1])
    assert "S-9" not in str(e.value)
    with pytest.raises(ValueError, match="split"):
        breakeven(h, [r.model_copy(update={"split": "calibration"}) for r in manual_baseline(h)])
    other_gold = manual_baseline(h)
    other_gold[0] = other_gold[0].model_copy(update={"expected_route": "HITL"})
    with pytest.raises(ValueError, match="expected_route") as e:
        breakeven(h, other_gold)
    assert "S-1" not in str(e.value)


def test_breakeven_bad_args() -> None:
    h = h_set()
    with pytest.raises(ValueError, match="rỗng"):
        breakeven([], h)
    with pytest.raises(ValueError, match="rỗng"):
        breakeven(h, [])
    with pytest.raises(ValueError, match="mix"):
        breakeven(h, manual_baseline(h), {"routine": 0.5, "approval": 0.2, "sensitive": 0.1})
    for bad in ((0,), (-1,)):
        with pytest.raises(ValueError, match="ratio"):
            breakeven(h, manual_baseline(h), ratios=bad)


def test_breakeven_frozen() -> None:
    b = breakeven(h_set(), manual_baseline(h_set()))
    assert isinstance(b, Breakeven)
    with pytest.raises(FrozenInstanceError):
        b.r_star = 0.0  # type: ignore[misc]
    with pytest.raises(TypeError):
        b.saving[5.0] = 0.0  # type: ignore[index]
