"""G5 — cận dưới và khoảng hai phía Clopper–Pearson (`app.eval.stats`). Số tính tay khớp 1e-9; cận trên là của `decision_math`.

Ca biên dạng đóng: k = 0 → cận dưới 0; k = n → cận dưới = (1 − conf)^(1/n), cận trên = 1; k = 1 → 1 − (1 − lo)^n = 1 − conf.
"""

from math import comb
from typing import Any

import pytest
from app.eval.stats import clopper_pearson_lower, clopper_pearson_two_sided
from app.risk.decision_math import clopper_pearson_upper

TOL = 1e-9


def close(a: float, b: float) -> bool:
    return abs(a - b) <= TOL


def at_least(k: int, n: int, p: float) -> float:
    """P(X ≥ k), X ~ Binomial(n, p) — đường độc lập với beta.ppf."""
    return sum(comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(k, n + 1))


def test_cp_lower_hand() -> None:
    assert clopper_pearson_lower(0, 5) == 0.0
    assert clopper_pearson_lower(0, 1, 0.975) == 0.0
    assert close(clopper_pearson_lower(5, 5, 0.975), 0.025 ** (1 / 5))
    assert close(clopper_pearson_lower(1, 1, 0.975), 0.025)
    assert close(clopper_pearson_lower(1, 5, 0.975), 1 - 0.975 ** (1 / 5))
    assert close(clopper_pearson_lower(3, 3), 0.05 ** (1 / 3))  # conf mặc định 0,95


def test_cp_lower_binomial() -> None:
    for k, n, conf in ((2, 4, 0.975), (3, 10, 0.95), (7, 9, 0.9)):
        lo = clopper_pearson_lower(k, n, conf)
        assert close(at_least(k, n, lo), 1 - conf), (k, n, conf)


def test_cp_lower_duality() -> None:
    # beta.ppf(1 − c, k, n−k+1) = 1 − beta.ppf(c, n−k+1, k) → cận dưới của k = 1 − cận trên của n − k
    for k, n, conf in ((2, 7, 0.9), (3, 10, 0.975), (1, 2, 0.95)):
        assert close(clopper_pearson_lower(k, n, conf), 1 - clopper_pearson_upper(n - k, n, conf)), (k, n, conf)


def test_cp_two_sided_hand() -> None:
    lo, hi = clopper_pearson_two_sided(0, 5)
    assert lo == 0.0 and close(hi, 1 - 0.025 ** (1 / 5))
    lo, hi = clopper_pearson_two_sided(5, 5)
    assert close(lo, 0.025 ** (1 / 5)) and hi == 1.0
    lo, hi = clopper_pearson_two_sided(2, 4, 0.9)  # mỗi phía 5%
    assert close(lo, clopper_pearson_lower(2, 4, 0.95)) and close(hi, clopper_pearson_upper(2, 4, 0.95))
    assert close(at_least(2, 4, lo), 0.05) and close(1 - at_least(3, 4, hi), 0.05)
    lo, hi = clopper_pearson_two_sided(1, 5)
    assert close(lo, 1 - 0.975 ** (1 / 5)) and close(hi, clopper_pearson_upper(1, 5, 0.975)) and lo < 1 / 5 < hi


@pytest.mark.parametrize(
    ("k", "n", "conf"),
    [(0, 0, 0.95), (-1, 5, 0.95), (6, 5, 0.95), (True, 5, 0.95), (1.5, 5, 0.95), (1, 5, 0.0), (1, 5, 1.0), (1, 5, float("nan"))],
)
def test_cp_lower_rejects(k: Any, n: Any, conf: Any) -> None:
    with pytest.raises(ValueError):
        clopper_pearson_lower(k, n, conf)


@pytest.mark.parametrize("level", [0.0, 1.0, -0.5, float("nan"), True])
def test_cp_two_sided_rejects_level(level: Any) -> None:
    with pytest.raises(ValueError, match="level"):
        clopper_pearson_two_sided(1, 5, level)
