"""6A — `app.risk.decision_math` (phase6 4.2, 4.5, 4.6). dm1–dm8 = 8 test cổng 6; dm9–dm12 bổ sung.

Mọi con số CHÉP từ spec 4.5–4.6 (bộ H tính tay, CP, ECE/Brier/AUC), không tính lại bằng code đang test. Bộ H: 10 ca,
DEFAULT_COST; (0,10; 0,75) → 1,3; (0,25; 0,75) → 2,2; quét lưới → (0,09; 0,60), 80 cặp hoà (t_low 0,09…0,12).
Cảnh báo = lỗi (P8: test chạy với cảnh báo là lỗi cho module mới).
"""

import math
import time
from types import MappingProxyType
from typing import Any

import numpy as np
import pytest
from app.risk.decision_math import (
    DEFAULT_COST,
    ROUTES,
    CostMatrix,
    ThresholdChoice,
    auc,
    brier,
    clopper_pearson_upper,
    cost_matrix_for_ratio,
    ece,
    expected_cost,
    route_for,
    select_thresholds,
    sensitivity,
    t_low_star,
)
from hypothesis import given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.filterwarnings("error")

# ---- Bộ H (spec 4.5) -----------------------------------------------------------------------------------------------

H_P = [0.02, 0.05, 0.08, 0.12, 0.30, 0.45, 0.60, 0.80, 0.90, 0.97]
H_GOLD = ["AUTO", "AUTO", "AUTO", "HITL", "AUTO", "HITL", "HITL", "ESCALATE_L2", "HITL", "ESCALATE_L2"]
H_ROUTE_010_075 = ["AUTO", "AUTO", "AUTO", "HITL", "HITL", "HITL", "HITL", "ESCALATE_L2", "ESCALATE_L2", "ESCALATE_L2"]
GRID = [i / 100 for i in range(101)]


# ---- dm1 -------------------------------------------------------------------------------------------------------------


def test_dm1_t_low_star() -> None:
    assert t_low_star(DEFAULT_COST) == pytest.approx(0.1, abs=1e-12)
    assert t_low_star() == pytest.approx(0.1, abs=1e-12)
    for ratio, expect in ((5, 0.2), (10, 0.1), (20, 0.05)):
        assert t_low_star(cost_matrix_for_ratio(ratio)) == pytest.approx(expect, abs=1e-12)
    assert cost_matrix_for_ratio(10) == DEFAULT_COST


def test_dm1_cost_matrix_for_ratio_cells() -> None:
    """HITL→AUTO = ratio, L2→AUTO = 2·ratio; các ô khác như DEFAULT_COST (spec 4.2)."""
    for ratio in (5, 10, 20):
        m = cost_matrix_for_ratio(ratio).costs
        for gold in ROUTES:
            for pred in ROUTES:
                expect = {("HITL", "AUTO"): ratio, ("ESCALATE_L2", "AUTO"): 2 * ratio}.get(
                    (gold, pred), DEFAULT_COST.costs[gold][pred]
                )
                assert m[gold][pred] == expect, (ratio, gold, pred)
    for bad in (0, -1, math.nan, math.inf):
        with pytest.raises(ValueError, match="ratio"):
            cost_matrix_for_ratio(bad)


def test_dm1_default_cost_table() -> None:
    expect = {
        "AUTO": {"AUTO": 0, "HITL": 1, "ESCALATE_L2": 3},
        "HITL": {"AUTO": 10, "HITL": 1, "ESCALATE_L2": 3},
        "ESCALATE_L2": {"AUTO": 20, "HITL": 6, "ESCALATE_L2": 3},
    }
    assert {g: dict(row) for g, row in DEFAULT_COST.costs.items()} == expect
    assert DEFAULT_COST.model_dump() == {"costs": expect}


def test_dm1_cost_matrix_frozen_deep() -> None:
    """Q-6A-2 = A: DEFAULT_COST dùng chung (M5, T27, T29) — không sửa được ô nào."""
    with pytest.raises(TypeError):
        DEFAULT_COST.costs["HITL"]["AUTO"] = 0  # type: ignore[index]
    with pytest.raises(TypeError):
        DEFAULT_COST.costs["HITL"] = {}  # type: ignore[index]
    assert isinstance(DEFAULT_COST.costs, MappingProxyType)
    assert DEFAULT_COST.costs["HITL"]["AUTO"] == 10


@pytest.mark.parametrize(
    "costs",
    [
        {"AUTO": {"AUTO": 0, "HITL": 1}, "HITL": {"AUTO": 10, "HITL": 1, "ESCALATE_L2": 3},
         "ESCALATE_L2": {"AUTO": 20, "HITL": 6, "ESCALATE_L2": 3}},  # thiếu ô
        {"AUTO": {"AUTO": 0, "HITL": 1, "ESCALATE_L2": 3}, "HITL": {"AUTO": 10, "HITL": 1, "ESCALATE_L2": 3}},  # thiếu hàng
        {"AUTO": {"AUTO": 0, "HITL": -1, "ESCALATE_L2": 3}, "HITL": {"AUTO": 10, "HITL": 1, "ESCALATE_L2": 3},
         "ESCALATE_L2": {"AUTO": 20, "HITL": 6, "ESCALATE_L2": 3}},  # âm
        {"AUTO": {"AUTO": 0, "HITL": math.inf, "ESCALATE_L2": 3}, "HITL": {"AUTO": 10, "HITL": 1, "ESCALATE_L2": 3},
         "ESCALATE_L2": {"AUTO": 20, "HITL": 6, "ESCALATE_L2": 3}},  # inf
        {"AUTO": {"AUTO": 0, "HITL": 1, "ESCALATE_L2": 3}, "HITL": {"AUTO": 10, "HITL": 1, "ESCALATE_L2": 3},
         "ESCALATE_L2": {"AUTO": 20, "HITL": 6, "ESCALATE_L2": 3}, "L2": {"AUTO": 1, "HITL": 1, "ESCALATE_L2": 1}},
    ],
    ids=["thieu-o", "thieu-hang", "am", "inf", "khoa-la"],
)  # fmt: skip
def test_dm1_cost_matrix_invalid(costs: Any) -> None:
    with pytest.raises(ValueError):
        CostMatrix(costs=costs)


def test_dm1_t_low_star_zero_miss_cost() -> None:
    rows = {g: dict(r) for g, r in DEFAULT_COST.costs.items()}
    rows["HITL"]["AUTO"] = 0
    with pytest.raises(ValueError):
        t_low_star(CostMatrix(costs=rows))


# ---- dm2 -------------------------------------------------------------------------------------------------------------


def test_dm2_route_for_boundaries() -> None:
    assert route_for(0.0999, 0.10, 0.75) == "AUTO"
    assert route_for(0.10, 0.10, 0.75) == "HITL"
    assert route_for(0.75, 0.10, 0.75) == "HITL"
    assert route_for(0.7501, 0.10, 0.75) == "ESCALATE_L2"
    assert route_for(0.0, 0.0, 0.75) == "HITL"
    assert route_for(1.0, 0.10, 1.01) == "HITL"
    with pytest.raises(ValueError):
        route_for(0.5, 0.8, 0.3)


@pytest.mark.parametrize(
    ("p", "t_low", "t_high"),
    [(0.5, -0.01, 0.75), (0.5, 0.1, 1.02), (math.nan, 0.1, 0.75), (1.2, 0.1, 0.75), (-0.1, 0.1, 0.75),
     (0.5, math.nan, 0.75), (0.5, 0.1, math.nan), (math.inf, 0.1, 0.75)],
)  # fmt: skip
def test_dm2_route_for_invalid(p: float, t_low: float, t_high: float) -> None:
    with pytest.raises(ValueError):
        route_for(p, t_low, t_high)


# ---- dm3 -------------------------------------------------------------------------------------------------------------


def test_dm3_expected_cost_set_h() -> None:
    assert [route_for(p, 0.10, 0.75) for p in H_P] == H_ROUTE_010_075  # cột "route ở (0,10; 0,75)" bảng 4.5
    assert expected_cost(H_P, H_GOLD, 0.10, 0.75) == pytest.approx(1.3, abs=1e-12)
    assert expected_cost(H_P, H_GOLD, 0.25, 0.75) == pytest.approx(2.2, abs=1e-12)
    assert expected_cost(np.array(H_P), np.array(H_GOLD), 0.10, 0.75, DEFAULT_COST) == pytest.approx(1.3, abs=1e-12)


# ---- dm4 -------------------------------------------------------------------------------------------------------------


def test_dm4_select_thresholds() -> None:
    choice = select_thresholds(H_P, H_GOLD)
    assert isinstance(choice, ThresholdChoice)
    assert (choice.t_low, choice.t_high) == (0.09, 0.60)
    assert choice.expected_cost == pytest.approx(1.3, abs=1e-12)


def test_dm4_sensitivity() -> None:
    out = sensitivity(H_P, H_GOLD)
    assert set(out) == {5, 10, 20}
    for ratio, expect in ((5, 0.2), (10, 0.1), (20, 0.05)):
        star, choice = out[ratio]
        assert star == pytest.approx(expect, abs=1e-12)
        assert isinstance(choice, ThresholdChoice)
        assert choice == select_thresholds(H_P, H_GOLD, cost_matrix_for_ratio(ratio))


# ---- dm5 -------------------------------------------------------------------------------------------------------------


def test_dm5_clopper_pearson() -> None:
    assert clopper_pearson_upper(0, 60) == pytest.approx(0.04870291331, abs=1e-9)
    assert clopper_pearson_upper(0, 60) == pytest.approx(1 - 0.05 ** (1 / 60), abs=1e-9)
    assert clopper_pearson_upper(1, 20) == pytest.approx(0.21610616421, abs=1e-9)
    assert clopper_pearson_upper(2, 60) == pytest.approx(0.10123589492, abs=1e-9)
    assert clopper_pearson_upper(60, 60) == 1.0
    with pytest.raises(ValueError):
        clopper_pearson_upper(0, 0)
    with pytest.raises(ValueError):
        clopper_pearson_upper(21, 20)


@pytest.mark.parametrize(("k", "n", "conf"), [(-1, 10, 0.95), (1, 10, 0.0), (1, 10, 1.0), (1, 10, math.nan),
                                              (1.0, 10, 0.95), (1, 10.0, 0.95), (True, 10, 0.95)])  # fmt: skip
def test_dm5_clopper_pearson_invalid(k: Any, n: Any, conf: float) -> None:
    with pytest.raises(ValueError):
        clopper_pearson_upper(k, n, conf)


# ---- dm6, dm7, dm8 -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("probs", "labels", "expect"),
    [([0.05, 0.15, 0.15, 0.95], [0, 0, 1, 1], 0.2),
     ([0.0, 0.1, 0.1, 0.95, 1.0], [0, 0, 1, 1, 1], 0.17),
     ([0.7 - 0.4, 0.35], [1, 0], 0.175)],
    ids=["bon-diem", "nam-diem", "bien-0.7-0.4"],
)  # fmt: skip
def test_dm6_ece(probs: list[float], labels: list[int], expect: float) -> None:
    assert ece(probs, labels) == pytest.approx(expect, abs=1e-12)
    assert ece(np.array(probs), np.array(labels, dtype=bool)) == pytest.approx(expect, abs=1e-12)


@pytest.mark.parametrize(
    ("probs", "labels", "expect"),
    [([0.05, 0.15, 0.15, 0.95], [0, 0, 1, 1], 0.1875), ([0.0, 0.1, 0.1, 0.95, 1.0], [0, 0, 1, 1, 1], 0.1645)],
    ids=["bon-diem", "nam-diem"],
)  # fmt: skip
def test_dm7_brier(probs: list[float], labels: list[int], expect: float) -> None:
    assert brier(probs, labels) == pytest.approx(expect, abs=1e-12)
    assert brier(probs, [bool(v) for v in labels]) == pytest.approx(expect, abs=1e-12)


def test_dm8_auc() -> None:
    assert auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]) == pytest.approx(0.75, abs=1e-12)
    assert auc([0.5, 0.5, 0.2, 0.9], [1, 0, 0, 1]) == pytest.approx(0.875, abs=1e-12)
    with pytest.raises(ValueError):
        auc([0.1, 0.4, 0.35], [1, 1, 1])
    with pytest.raises(ValueError):
        auc([0.1, 0.4, 0.35], [0, 0, 0])


# ---- dm9 -------------------------------------------------------------------------------------------------------------


def test_dm9_t_low_near_star_on_calibrated_synthetic() -> None:
    n = 20_000
    rng = np.random.default_rng(20260925)
    p = rng.uniform(0, 1, n)
    golds = ["HITL" if u < q else "AUTO" for u, q in zip(rng.uniform(0, 1, n), p, strict=True)]
    start = time.perf_counter()
    choice = select_thresholds(p, golds)
    elapsed = time.perf_counter() - start
    assert 0.08 <= choice.t_low <= 0.12
    assert elapsed < 5.0


# ---- dm10 (P3) -------------------------------------------------------------------------------------------------------

NAN, INF = math.nan, math.inf


@pytest.mark.parametrize(
    ("call", "param", "absent"),
    [
        (lambda: ece([0.1, NAN], [0, 1]), "probs", ["nan"]),
        (lambda: brier([0.1, INF], [0, 1]), "probs", ["inf"]),
        (lambda: ece([0.1, 1.2], [0, 1]), "probs", ["1.2"]),
        (lambda: brier([0.1, -0.3], [0, 1]), "probs", ["0.3"]),
        (lambda: brier([0.1, 0.2, 0.3], [0, 1]), "labels", []),
        (lambda: ece([], []), "probs", []),
        (lambda: auc([0.1, NAN], [0, 1]), "scores", ["nan"]),
        (lambda: auc([0.1, INF], [0, 1]), "scores", ["inf"]),
        (lambda: auc([0.1, 0.2], [0, 1, 1]), "labels", []),
        (lambda: brier([0.1, 0.2], [0, 2]), "labels", ["2"]),
        (lambda: ece([0.1, 0.2], [0, 2]), "labels", ["2"]),
        (lambda: auc([0.1, 0.2], [0, 2]), "labels", ["2"]),
        (lambda: brier([0.1, 0.2], [0.0, 1.0]), "labels", []),  # type: ignore[list-item]  # Q-6A-1 = A: nhãn float → lỗi
        (lambda: brier([0.1, 0.2], np.array([0.0, 1.0])), "labels", []),
        (lambda: brier([0.1, 0.2], ["0", "1"]), "labels", []),  # type: ignore[list-item]
        (lambda: brier([[0.1, 0.2]], [[0, 1]]), "probs", []),  # type: ignore[list-item]
        (lambda: brier([True, False], [0, 1]), "probs", []),
        (lambda: expected_cost([0.1, NAN], ["AUTO", "HITL"], 0.1, 0.75), "probs", ["nan"]),
        (lambda: expected_cost([0.1, 1.2], ["AUTO", "HITL"], 0.1, 0.75), "probs", ["1.2"]),
        (lambda: expected_cost([0.1, 0.2], ["AUTO"], 0.1, 0.75), "golds", []),
        (lambda: expected_cost([], [], 0.1, 0.75), "probs", []),
        (lambda: expected_cost([0.1, 0.2], ["AUTO", "L2"], 0.1, 0.75), "golds", ["L2"]),
        (lambda: expected_cost([0.1, 0.2], ["AUTO", "HITL"], 0.8, 0.3), "t_low", []),
        (lambda: select_thresholds([0.1, NAN], ["AUTO", "HITL"]), "probs", ["nan"]),
        (lambda: select_thresholds([0.1, 0.2], ["AUTO", "L2"]), "golds", ["L2"]),
        (lambda: select_thresholds([0.1, 0.2], ["AUTO"]), "golds", []),
        (lambda: select_thresholds([], []), "probs", []),
        (lambda: sensitivity([0.1, 0.2], ["AUTO", "HITL"], ()), "ratios", []),
        (lambda: ece([0.1, 0.2], [0, 1], n_bins=0), "n_bins", []),
    ],
)  # fmt: skip
def test_dm10_input_validation(call: Any, param: str, absent: list[str]) -> None:
    with pytest.raises(ValueError) as info:
        call()
    msg = str(info.value)
    assert param in msg
    for value in absent:
        assert value not in msg.lower(), (value, msg)


def test_dm10_numpy_bool_and_int_labels_accepted() -> None:
    probs = np.array([0.05, 0.15, 0.15, 0.95])
    labels: Any
    for labels in (np.array([0, 0, 1, 1], dtype=np.int64), np.array([0, 0, 1, 1], dtype=np.uint8),
                   np.array([False, False, True, True]), [np.int64(0), np.int64(0), np.int64(1), np.int64(1)]):  # fmt: skip
        assert brier(probs, labels) == pytest.approx(0.1875, abs=1e-12)


# ---- dm11 (hypothesis) -----------------------------------------------------------------------------------------------

_P = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


@settings(derandomize=True, deadline=None)
@given(st.lists(st.tuples(_P, st.booleans()), min_size=1, max_size=60))
def test_dm11_ece_brier_in_unit_interval(rows: list[tuple[float, bool]]) -> None:
    probs, labels = [r[0] for r in rows], [r[1] for r in rows]
    assert 0.0 <= ece(probs, labels) <= 1.0
    assert 0.0 <= brier(probs, labels) <= 1.0


@settings(derandomize=True, deadline=None)
@given(st.integers(min_value=1, max_value=400).flatmap(lambda n: st.tuples(st.just(n), st.integers(0, n - 1))))
def test_dm11_clopper_pearson_monotone(nk: tuple[int, int]) -> None:
    n, k = nk
    lo, hi = clopper_pearson_upper(k, n), clopper_pearson_upper(k + 1, n)
    assert lo < hi
    assert lo >= k / n
    assert hi >= (k + 1) / n


_ORDER = {"AUTO": 0, "HITL": 1, "ESCALATE_L2": 2}


@settings(derandomize=True, deadline=None)
@given(_P, _P, _P, st.floats(min_value=0.0, max_value=1.01, allow_nan=False))
def test_dm11_route_for_monotone(p1: float, p2: float, a: float, b: float) -> None:
    lo, hi = sorted((p1, p2))
    t_low, t_high = sorted((a, b))
    assert _ORDER[route_for(lo, t_low, t_high)] <= _ORDER[route_for(hi, t_low, t_high)]


# ---- dm12 ------------------------------------------------------------------------------------------------------------


def test_dm12_ties() -> None:
    """Đúng 80 cặp tối ưu trên bộ H (đếm độc lập qua `expected_cost` trên cả lưới); chọn cặp nhỏ nhất theo (t_low, t_high);
    đảo thứ tự dữ liệu → không đổi."""
    costs = {(lo, hi): round(expected_cost(H_P, H_GOLD, lo, hi), 12) for lo in GRID for hi in GRID if hi >= lo}
    best = min(costs.values())
    ties = sorted(pair for pair, c in costs.items() if c == best)
    assert best == pytest.approx(1.3, abs=1e-12)
    assert len(ties) == 80
    assert {lo for lo, _ in ties} == {0.09, 0.10, 0.11, 0.12}
    assert ties[0] == (0.09, 0.60)
    expect = select_thresholds(H_P, H_GOLD)
    assert (expect.t_low, expect.t_high) == ties[0]
    order = np.random.default_rng(7).permutation(len(H_P))
    for perm in (list(reversed(range(len(H_P)))), [int(i) for i in order]):
        got = select_thresholds([H_P[i] for i in perm], [H_GOLD[i] for i in perm])
        assert got == expect
