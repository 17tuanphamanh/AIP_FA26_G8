"""RQ2 — ECE 10 ngăn đều, ECE 5 ngăn cùng số mẫu, Brier so số tính tay (1e-9); độ phân giải; bootstrap cùng seed → cùng KTC."""

import pytest
from app.eval.rq2.metrics import (
    N_BOOT,
    Point,
    bootstrap,
    brier_score,
    ece_equal_mass,
    ece_uniform,
    reliability_bins,
    resolution,
)
from app.eval.stats import SEED

TOL = 1e-9
# p, y — tính tay ở docstring từng test
DATA = [(0.05, False), (0.15, False), (0.12, True), (0.55, True), (0.58, False), (0.95, True)]
PTS = [Point(f"t{i}", f"H{i % 3}", p, y) for i, (p, y) in enumerate(DATA)]


def test_ece10_by_hand() -> None:
    """ngăn 0: |0,05−0| = 0,05; ngăn 1 (0,15; 0,12): |0,27−1| = 0,73; ngăn 5 (0,55; 0,58): |1,13−1| = 0,13; ngăn 9: |0,95−1| = 0,05.
    Σ = 0,96 → /6 = 0,16."""
    assert ece_uniform(PTS) == pytest.approx(0.16, abs=TOL)


def test_ece5_equal_mass_by_hand() -> None:
    """N = 6, 5 ngăn → cỡ 2,1,1,1,1 theo p tăng: (0,05;0,12 | y 0,1) → |0,17−1| = 0,83; (0,15|0) 0,15; (0,55|1) 0,45; (0,58|0) 0,58;
    (0,95|1) 0,05. Σ = 2,06 → /6."""
    assert ece_equal_mass(PTS) == pytest.approx(2.06 / 6, abs=TOL)


def test_ece5_ties_split_deterministically() -> None:
    """10 lá cùng p = 0,2, 4 lá y = 1 (t0..t3): sắp (p, ticket_id) → ngăn {t0,t1},{t2,t3},{t4,t5},… :
    |0,4−2| + |0,4−2| + 3·|0,4−0| = 1,6 + 1,6 + 1,2 = 4,4 → /10 = 0,44. ECE 10 ngăn đều: một ngăn, |2−4|/10 = 0,2."""
    pts = [Point(f"t{i}", "H", 0.2, i < 4) for i in range(10)]
    assert ece_equal_mass(list(reversed(pts))) == pytest.approx(0.44, abs=TOL)
    assert ece_uniform(pts) == pytest.approx(0.2, abs=TOL)


def test_brier_by_hand() -> None:
    """0,0025 + 0,0225 + 0,7744 + 0,2025 + 0,3364 + 0,0025 = 1,3408 → /6."""
    assert brier_score(PTS) == pytest.approx(1.3408 / 6, abs=TOL)


def test_ece5_fewer_points_than_bins() -> None:
    """N = 2 < 5: ngăn rỗng bị bỏ → mỗi lá một ngăn: (|0,3−1| + |0,9−0|)/2 = 0,8."""
    assert ece_equal_mass([Point("a", "H", 0.3, True), Point("b", "H", 0.9, False)]) == pytest.approx(0.8, abs=TOL)


def test_resolution_levels_and_top2() -> None:
    r = resolution([0.0, 0.2, 0.2, 0.2, 1.0, 1.0, 0.4, 0.6, 0.8, 0.2])
    assert r.n == 10 and r.n_levels == 6 and r.top2_share == pytest.approx(0.6, abs=TOL)


def test_reliability_bins_match_ece_bins() -> None:
    bins = reliability_bins(PTS)
    assert [b.n for b in bins] == [1, 2, 0, 0, 0, 2, 0, 0, 0, 1]
    assert bins[1].mean_p == pytest.approx(0.135, abs=TOL) and bins[1].frac_pos == pytest.approx(0.5, abs=TOL)
    assert sum(b.n * abs((b.mean_p or 0) - (b.frac_pos or 0)) for b in bins) / len(PTS) == pytest.approx(ece_uniform(PTS), abs=TOL)


def test_bootstrap_same_seed_same_ci() -> None:
    pts = [Point(f"t{i}", f"H{i % 7}", (i * 37 % 100) / 100, i % 3 == 0) for i in range(60)]
    a = bootstrap(pts, ece_equal_mass)
    b = bootstrap(list(reversed(pts)), ece_equal_mass)  # thứ tự đầu vào không đổi kết quả (stats sắp họ + ticket_id)
    assert (a.lo, a.hi, a.point) == (b.lo, b.hi, b.point)
    assert a.n_boot == N_BOOT == 1000 and a.seed == SEED == 20260925 and a.n_families == 7
    c = bootstrap(pts, ece_equal_mass, seed=SEED + 1)
    assert (c.lo, c.hi) != (a.lo, a.hi)
    assert a.lo is not None and a.hi is not None and a.lo <= a.point <= a.hi  # type: ignore[operator]
